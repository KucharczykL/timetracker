"""One batch, run chunk by chunk in the background."""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import partial
from time import monotonic
from typing import Any, Literal, NotRequired, TypedDict

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django_q.tasks import async_task

from common.notices import ToastAction, ToastType, Undo
from games.bulk_actions import BulkAction, bulk_action
from games.bulk_parts import (
    BoundRow,
    BulkActionName,
    ChoiceValue,
    Refused,
    Resolution,
    RowOutcome,
)
from games.models import BulkBatch, UserLibrary
from games.writes.answers import CONFLICT_STATUS, CommandFailed

logger = logging.getLogger("games")

#: The rows one task acts on.
#: No transaction: each row commits on its own.
CHUNK_BUDGET = timedelta(seconds=3)

#: Starts a chunk gets; the next fails.
STARTS_ALLOWED = 2

#: How long an unseen end is shown.
ANNOUNCE_WINDOW = timedelta(days=1)

#: The log's words for a row unreached.
STOPPED_BY_HAND = "The batch was stopped before this row was reached."
ENDED_BY_A_DEFECT = "A problem on our side ended the batch before this row was reached."

#: The log's words for the row the defect was met on, which is not
#: unreached: an act whose run states two writes may have made the
#: first one. `playergame.remove` appends its event, then stamps.
MET_THE_DEFECT = (
    "A problem on our side was met on this row. An act that states two writes "
    "may have made the first, so read this row before acting on it again."
)

#: A toast's title for an act the table lost.
UNKNOWN_TITLE = "A bulk change"

type BatchToken = uuid.UUID


@dataclass(frozen=True, slots=True)
class Tally:
    """What the batch did, and what remains."""

    done: int = 0
    unchanged: int = 0
    lost: int = 0
    #: Refused on merits: not moved, not gone.
    refused: int = 0
    #: Each distinct reason once, in order.
    reasons: tuple[str, ...] = ()
    #: The denominator: what the confirmation resolved.
    total: int = 0
    #: Rows not reached yet.
    left: int = 0

    @classmethod
    def of(cls, batch: BulkBatch) -> Tally:
        return cls(
            done=batch.done,
            unchanged=batch.unchanged,
            lost=batch.lost,
            refused=batch.refused,
            reasons=tuple(batch.reasons),
            total=batch.total,
            left=max(batch.total - batch.position, 0),
        )

    def columns(self) -> dict[str, Any]:
        """The row's tally columns."""
        return {
            "done": self.done,
            "unchanged": self.unchanged,
            "lost": self.lost,
            "refused": self.refused,
            "reasons": list(self.reasons),
        }

    def left_alone(self, refused: Sequence[Refused]) -> Tally:
        """Count rows left alone, reasons once."""
        reasons = list(self.reasons)
        for entry in refused:
            if entry.sentence not in reasons:
                reasons.append(entry.sentence)
        lost = sum(1 for entry in refused if entry.lost)
        return replace(
            self,
            lost=self.lost + lost,
            refused=self.refused + len(refused) - lost,
            reasons=tuple(reasons),
        )

    def counted(self, outcome: RowOutcome) -> Tally:
        """Moved, or already in that state."""
        if outcome is RowOutcome.UNCHANGED:
            return replace(self, unchanged=self.unchanged + 1)
        return replace(self, done=self.done + 1)

    def sentence(self, *, ended: bool = False) -> str:
        """What the toast says."""
        parts = [f"{self.done} of {self.total} done"]
        if self.unchanged:
            parts.append(f"{self.unchanged} already done")
        if self.refused:
            parts.append(f"{self.refused} left as {_as_it_is(self.refused)}")
        if self.lost:
            parts.append(f"{self.lost} no longer there")
        if self.left:
            parts.append(f"{self.left} not reached" if ended else f"{self.left} left")
        return ", ".join(parts) + "."


def _as_it_is(count: int) -> str:
    """Singular or plural pronoun for a count."""
    return "it is" if count == 1 else "they are"


@dataclass(frozen=True, slots=True)
class BatchAct:
    """What one batch does to each of its rows."""

    #: The idempotency key's prefix, so an act and its undo
    #: never share a key space.
    name: str
    resolve: Callable[[UserLibrary, uuid.UUID], Resolution]
    #: Its own fact is bound; the row and the keys remain.
    run: BoundRow


def undo_name(action: BulkAction[Any]) -> str:
    """One spelling, for the key prefix and the log."""
    return f"{action.name}.undo"


def _forward(action: BulkAction[Any], choice: ChoiceValue | None) -> BatchAct:
    return BatchAct(
        name=action.name,
        resolve=lambda library, key: action.resolve(library, [key]),
        run=partial(action.run, choice=choice),
    )


def _taken_as_is(library: UserLibrary, key: uuid.UUID) -> Resolution:
    """An Undo's rows are read by the server."""
    return Resolution((key,), ())


def _backward(action: BulkAction[Any], undoes: uuid.UUID) -> BatchAct:
    return BatchAct(
        name=undo_name(action),
        resolve=_taken_as_is,
        run=partial(action.inverse, undoes=undoes),
    )


def batch_act(batch: BulkBatch) -> BatchAct | None:
    """The act a batch runs; None when gone."""
    declared = bulk_action(batch.action)
    if declared is None:
        return None
    if batch.undoes is not None:
        return _backward(declared, batch.undoes)
    return _forward(declared, batch.choice or None)


def log_left_alone(
    name: str,
    refused: Sequence[Refused],
    library_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> None:
    """The toast prints sentences; the log, keys."""
    for entry in refused:
        logger.info(
            "[bulk]: %s left row %s of library %s under %s: %s",
            name,
            entry.key,
            library_id,
            correlation_id,
            entry.sentence,
        )


def _log_unreached(
    name: str,
    keys: Sequence[str],
    batch: BulkBatch,
    sentence: str,
) -> None:
    log_left_alone(
        name,
        [Refused(key, sentence) for key in keys],
        batch.library_id,
        batch.token,
    )


# ── Starting ────────────────────────────────────────────────────────────────


def enqueue(batch_id: uuid.UUID, chunk: int) -> None:
    """Queue one chunk; tests replace it."""
    async_task("games.tasks.run_bulk_batch", str(batch_id), chunk)


def start_batch(
    library: UserLibrary,
    action: BulkActionName,
    *,
    token: BatchToken,
    keys: Sequence[uuid.UUID],
    tally: Tally,
    choice: ChoiceValue | None,
    origin: str,
    undoes: uuid.UUID | None = None,
) -> BulkBatch:
    """Store the batch and queue its first chunk.

    The queue row commits with the batch row. A token pressed twice
    answers the batch the first press stored.
    """
    try:
        with transaction.atomic():
            batch = BulkBatch.objects.create(
                token=token,
                library=library,
                action=action,
                undoes=undoes,
                choice=choice or "",
                origin=origin,
                rows=[str(key) for key in keys],
                total=len(keys),
                **tally.columns(),
            )
            enqueue(batch.pk, 0)
    except IntegrityError:
        existing = BulkBatch.objects.filter(library=library, token=token).first()
        if existing is None:
            raise
        return existing
    return batch


# ── Running ─────────────────────────────────────────────────────────────────


class _Overtaken(Exception):
    """Another delivery runs this chunk."""


def run_chunk(batch_id: uuid.UUID, chunk: int) -> None:
    """Run one chunk of a batch.

    A stale chunk number, a terminal state, or a start another
    delivery overtook returns at once.
    """
    batch = BulkBatch.objects.filter(pk=batch_id).first()
    if batch is None or batch.chunk != chunk or batch.is_terminal:
        return
    if batch.stop_requested_at is not None:
        _stop(batch)
        return
    act = batch_act(batch)
    if act is None or batch.attempts >= STARTS_ALLOWED:
        logger.error(
            "[bulk]: batch %s of library %s failed at row %s: %s",
            batch.token,
            batch.library_id,
            batch.position,
            "no such act" if act is None else "its chunk keeps not finishing",
        )
        _fail(batch, act.name if act else batch.action, Tally.of(batch), batch.position)
        return
    attempts = batch.attempts + 1
    claimed = (
        BulkBatch.objects.filter(pk=batch.pk, chunk=chunk, attempts=batch.attempts)
        .exclude(state__in=BulkBatch.TERMINAL)
        .update(attempts=attempts, state=BulkBatch.State.RUNNING)
    )
    if not claimed:
        return
    _run(batch, act, chunk, attempts)


def _run(batch: BulkBatch, act: BatchAct, chunk: int, attempts: int) -> None:
    this_run = BulkBatch.objects.filter(pk=batch.pk, chunk=chunk, attempts=attempts)
    rows: list[str] = batch.rows
    tally = Tally.of(batch)
    position = batch.position
    started = monotonic()
    try:
        user = batch.library.user
        while position < len(rows):
            tally = _one_row(batch, act, user, rows[position], tally)
            position += 1
            tally = replace(tally, left=len(rows) - position)
            if not this_run.update(position=position, **tally.columns()):
                raise _Overtaken
            if monotonic() - started >= CHUNK_BUDGET.total_seconds():
                break
        with transaction.atomic():
            if position >= len(rows):
                this_run.update(state=BulkBatch.State.FINISHED, ended_at=timezone.now())
            elif this_run.update(chunk=chunk + 1, attempts=0):
                enqueue(batch.pk, chunk + 1)
    except _Overtaken:
        logger.info("[bulk]: batch %s chunk %s was overtaken", batch.token, chunk)
    except BaseException as error:
        logger.exception(
            "[bulk]: %s met a defect on row %s of library %s under %s",
            act.name,
            rows[position] if position < len(rows) else None,
            batch.library_id,
            batch.token,
        )
        _fail(batch, act.name, tally, position, this_run=this_run)
        #: The cluster's timeout leaves through here.
        if not isinstance(error, Exception):
            raise


class _Defect(Exception):
    """A row's answer ends the batch."""


def _one_row(
    batch: BulkBatch,
    act: BatchAct,
    user: Any,
    key: str,
    tally: Tally,
) -> Tally:
    """Resolve one key again, then act on it."""
    #: Re-resolved: a row gone since is lost.
    resolution = act.resolve(batch.library, uuid.UUID(key))
    log_left_alone(act.name, resolution.refused, batch.library_id, batch.token)
    tally = tally.left_alone(resolution.refused)
    for row in resolution.rows:
        try:
            outcome = act.run(
                user,
                row,
                idempotency_key=f"{act.name}-{batch.token}-{key}",
                correlation_id=batch.token,
            )
        except Http404 as absent:
            #: This batch re-resolved the row moments ago.
            raise _Defect(f"a row library {batch.library_id} does not hold") from absent
        except CommandFailed as failure:
            if failure.status_code != CONFLICT_STATUS:
                raise _Defect(failure.message) from failure
            refusal = Refused(key, failure.message)
            log_left_alone(act.name, (refusal,), batch.library_id, batch.token)
            tally = tally.left_alone((refusal,))
        else:
            tally = tally.counted(outcome)
    return tally


def _fail(
    batch: BulkBatch,
    name: str,
    tally: Tally,
    position: int,
    *,
    this_run: Any = None,
) -> None:
    """Store the end; name every row left."""
    rows: list[str] = batch.rows
    _log_unreached(name, rows[position : position + 1], batch, MET_THE_DEFECT)
    _log_unreached(name, rows[position + 1 :], batch, ENDED_BY_A_DEFECT)
    target = this_run if this_run is not None else BulkBatch.objects.filter(pk=batch.pk)
    target.update(
        position=position,
        state=BulkBatch.State.FAILED,
        ended_at=timezone.now(),
        **tally.columns(),
    )


def _stop(batch: BulkBatch) -> None:
    rows: list[str] = batch.rows
    act = batch_act(batch)
    _log_unreached(
        act.name if act else batch.action,
        rows[batch.position :],
        batch,
        STOPPED_BY_HAND,
    )
    BulkBatch.objects.filter(pk=batch.pk, chunk=batch.chunk).exclude(
        state__in=BulkBatch.TERMINAL
    ).update(state=BulkBatch.State.STOPPED, ended_at=timezone.now())


# ── Following ───────────────────────────────────────────────────────────────


def library_batch(library: UserLibrary, token: BatchToken) -> BulkBatch | None:
    return BulkBatch.objects.filter(library=library, token=token).first()


def request_stop(library: UserLibrary, token: BatchToken) -> bool:
    """Ask the runner to stop; False when absent."""
    held = BulkBatch.objects.filter(library=library, token=token)
    if not held.exists():
        return False
    held.exclude(state__in=BulkBatch.TERMINAL).filter(
        stop_requested_at__isnull=True
    ).update(stop_requested_at=timezone.now())
    return True


def announce(library: UserLibrary, token: BatchToken) -> bool:
    """Mark the end seen; False when absent."""
    held = BulkBatch.objects.filter(library=library, token=token)
    if not held.exists():
        return False
    held.filter(announced_at__isnull=True).update(announced_at=timezone.now())
    return True


def visible_batches(library: UserLibrary) -> list[BulkBatch]:
    """Running ones, and recent unseen ends."""
    since = timezone.now() - ANNOUNCE_WINDOW
    return list(
        BulkBatch.objects.filter(library=library)
        .filter(
            ~Q(state__in=BulkBatch.TERMINAL)
            | Q(announced_at__isnull=True, ended_at__gte=since)
        )
        .defer("rows")
        .order_by("created_at")
    )


def batches_named(
    library: UserLibrary, tokens: Sequence[BatchToken]
) -> list[BulkBatch]:
    """The asked ones this library holds."""
    return list(
        BulkBatch.objects.filter(library=library, token__in=tokens)
        .defer("rows")
        .order_by("created_at")
    )


type BatchState = Literal["queued", "running", "finished", "stopped", "failed"]


class BatchToast(TypedDict):
    """The store's message, composed here."""

    id: str
    message: str
    type: ToastType
    sticky: bool
    action: NotRequired[ToastAction]


class BatchOut(TypedDict):
    token: str
    state: BatchState
    origin: str
    toast: BatchToast


def _title(batch: BulkBatch) -> str:
    declared = bulk_action(batch.action)
    title = declared.title.for_count(batch.total) if declared else UNKNOWN_TITLE
    return f"Undo: {title}" if batch.undoes is not None else title


def _stop_action(batch: BulkBatch) -> ToastAction:
    return ToastAction(
        label="Stop", url=reverse("games:stop_bulk_batch", args=[batch.token])
    )


def _undo_action(batch: BulkBatch) -> ToastAction | None:
    """Only where something moved, never on an Undo."""
    if batch.undoes is not None or not batch.done or bulk_action(batch.action) is None:
        return None
    return Undo(reverse("games:undo_bulk_action", args=[batch.token]))


def error_id(token: BatchToken) -> str:
    """The token's last twelve digits."""
    return str(token)[-12:]


def batch_toast(batch: BulkBatch) -> BatchToast:
    """One toast for one batch's state."""
    tally = Tally.of(batch)
    title = _title(batch)
    reasons = "".join(f" {reason}" for reason in tally.reasons)
    action: ToastAction | None
    if not batch.is_terminal:
        stopping = batch.stop_requested_at is not None
        if stopping:
            said = f"stopping. {tally.sentence()}"
        elif batch.state == BulkBatch.State.QUEUED:
            said = f"waiting to start. {tally.sentence()}"
        else:
            said = tally.sentence()
        kind: ToastType = "info"
        action = None if stopping else _stop_action(batch)
    else:
        ended = tally.sentence(ended=True)
        action = _undo_action(batch)
        if batch.state == BulkBatch.State.FAILED:
            kind = "error"
            said = (
                "a problem on our side stopped it "
                f"(error {error_id(batch.token)}). {ended}"
            )
        elif batch.state == BulkBatch.State.STOPPED:
            kind = "info"
            said = f"stopped. {ended}"
        else:
            kind = "success" if batch.done else "info"
            said = ended
    toast = BatchToast(
        id=f"bulk-batch:{batch.token}",
        message=f"{title}: {said}{reasons}",
        type=kind,
        sticky=not batch.is_terminal or action is not None,
    )
    if action is not None:
        toast["action"] = action
    return toast


def batch_out(batch: BulkBatch) -> BatchOut:
    return BatchOut(
        token=str(batch.token),
        state=batch.state,  # type: ignore[typeddict-item]
        origin=batch.origin,
        toast=batch_toast(batch),
    )
