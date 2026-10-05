"""One batch, run chunk by chunk in the background."""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import partial
from time import monotonic
from typing import Any, Literal, TypedDict, TypeIs, get_args

from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.db.models import F, Q, QuerySet
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django_q.tasks import async_task

from common.notices import ToastAction, ToastPayload, ToastType, Undo
from games.bulk_actions import BulkAction, bulk_action
from games.bulk_parts import (
    BoundRow,
    BulkActionName,
    ChoiceValue,
    Refused,
    Resolution,
    RowKey,
    RowOutcome,
)
from games.models import (
    BULK_BATCH_LIVE_UNDO_CONSTRAINT,
    BULK_BATCH_TOKEN_CONSTRAINT,
    BulkBatch,
    UserLibrary,
)
from games.writes.answers import CONFLICT_STATUS, CommandFailed

logger = logging.getLogger("games")

#: Time one task spends on rows.
#: No transaction: each row commits on its own.
CHUNK_BUDGET = timedelta(seconds=3)

#: Starts a chunk gets; the next fails.
STARTS_ALLOWED = 2

#: How long an unseen end is shown.
ANNOUNCE_WINDOW = timedelta(days=1)

#: Silence after which no worker owns it.
STALE_AFTER = timedelta(minutes=10)

#: The log's words for a row unreached.
STOPPED_BY_HAND = "The batch was stopped before this row was reached."
ENDED_BY_A_DEFECT = "A problem on our side ended the batch before this row was reached."
NO_WORKER = "No background worker reached this row before the batch was ended."

#: A two-write act may half-finish.
MET_THE_DEFECT = (
    "A problem on our side was met on this row. An act that states two writes "
    "may have made the first, so read this row before acting on it again."
)

#: Title for an act the table lost.
UNKNOWN_TITLE = "A bulk change"

#: Prefix of a batch's toast id.
TOAST_ID_PREFIX = "bulk-batch:"

type BatchToken = uuid.UUID
#: An act's name, or its Undo's.
type ActKeyPrefix = str  # "session.edit.undo"
type ResolveOne = Callable[[UserLibrary, uuid.UUID], Resolution]
type BatchRows = QuerySet[BulkBatch, BulkBatch]

type BatchState = Literal["queued", "running", "finished", "stopped", "failed"]
BATCH_STATES: tuple[BatchState, ...] = get_args(BatchState.__value__)
if set(BATCH_STATES) != set(BulkBatch.State.values):
    raise RuntimeError(f"BatchState {BATCH_STATES} differs from BulkBatch.State")


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
    #: Rows the batch acts on.
    total: int = 0
    #: Rows not reached yet.
    left: int = 0

    def __post_init__(self) -> None:
        counts = (self.done, self.unchanged, self.lost, self.refused, self.total)
        if any(count < 0 for count in counts):
            raise ValueError(f"a tally counts below zero: {self!r}")
        if not 0 <= self.left <= self.total:
            raise ValueError(f"{self.left} left of {self.total}")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError(f"a reason repeats: {self.reasons!r}")

    @classmethod
    def of(cls, batch: BulkBatch) -> Tally:
        return cls(
            done=batch.done,
            unchanged=batch.unchanged,
            lost=batch.lost,
            refused=batch.refused,
            reasons=tuple(batch.reasons),
            total=batch.total,
            left=batch.total - batch.position,
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

    def reached(self, position: int) -> Tally:
        return replace(self, left=self.total - position)

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

    #: Act and its Undo never share.
    name: ActKeyPrefix
    resolve: ResolveOne
    #: Choice or undone batch, bound.
    run: BoundRow


def undo_name(action: BulkAction[Any]) -> ActKeyPrefix:
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


def _backward(action: BulkAction[Any], undoes: BatchToken) -> BatchAct:
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


def _name_of(batch: BulkBatch) -> ActKeyPrefix:
    act = batch_act(batch)
    return act.name if act else batch.action


def log_left_alone(
    name: ActKeyPrefix,
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
    name: ActKeyPrefix,
    keys: Sequence[RowKey],
    batch: BulkBatch,
    sentence: str,
) -> None:
    log_left_alone(
        name,
        [Refused(key, sentence) for key in keys],
        batch.library_id,
        batch.token,
    )


# ── Writes ──────────────────────────────────────────────────────────────────


def _live(batch: BulkBatch, *, chunk: int, attempts: int) -> BatchRows:
    """The row while this owner holds it."""
    return BulkBatch.objects.filter(
        pk=batch.pk, chunk=chunk, attempts=attempts, state__in=BulkBatch.LIVE
    )


def _store(rows: BatchRows, **columns: Any) -> int:
    """`update()` skips `auto_now`; stamp it here."""
    return rows.update(updated_at=timezone.now(), **columns)


# ── Starting ────────────────────────────────────────────────────────────────


def enqueue(batch_id: uuid.UUID, chunk: int) -> None:
    """Queue one chunk; tests replace it."""
    async_task("games.tasks.run_bulk_batch", str(batch_id), chunk)


def _constraint_of(error: IntegrityError) -> str | None:
    diagnosis = getattr(error.__cause__, "diag", None)
    return getattr(diagnosis, "constraint_name", None)


def start_batch(
    library: UserLibrary,
    action: BulkActionName,
    *,
    token: BatchToken,
    keys: Sequence[uuid.UUID],
    tally: Tally,
    choice: ChoiceValue | None,
    origin: str,
    undoes: BatchToken | None = None,
) -> BulkBatch:
    """Store the batch; queue chunk 0 with it."""
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
    except IntegrityError as error:
        existing = _already_started(library, error, token=token, undoes=undoes)
        if existing is None:
            raise
        if (existing.action, existing.undoes) != (action, undoes):
            logger.warning(
                "[bulk]: %s pressed as %s, stored as %s",
                token,
                action,
                existing.action,
            )
        return existing
    return batch


def _already_started(
    library: UserLibrary,
    error: IntegrityError,
    *,
    token: BatchToken,
    undoes: BatchToken | None,
) -> BulkBatch | None:
    """A double press, or a live Undo."""
    held = BulkBatch.objects.filter(library=library)
    constraint = _constraint_of(error)
    if constraint == BULK_BATCH_TOKEN_CONSTRAINT:
        return held.filter(token=token).first()
    if constraint == BULK_BATCH_LIVE_UNDO_CONSTRAINT:
        return held.filter(undoes=undoes, state__in=BulkBatch.LIVE).first()
    return None


# ── Running ─────────────────────────────────────────────────────────────────


class _Overtaken(Exception):
    """Another delivery runs this chunk."""


def run_chunk(batch_id: uuid.UUID, chunk: int) -> None:
    """Run one chunk; stale deliveries do nothing."""
    batch = BulkBatch.objects.filter(pk=batch_id).first()
    if batch is None or batch.chunk != chunk or batch.is_terminal:
        return
    if batch.stop_requested_at is not None:
        _end_unreached(batch, BulkBatch.State.STOPPED, STOPPED_BY_HAND)
        return
    act = batch_act(batch)
    if act is None:
        logger.error(
            "[bulk]: batch %s of library %s names no act: %s",
            batch.token,
            batch.library_id,
            batch.action,
        )
        _end_unreached(batch, BulkBatch.State.FAILED, ENDED_BY_A_DEFECT)
        return
    owner = _live(batch, chunk=chunk, attempts=batch.attempts)
    if batch.attempts >= STARTS_ALLOWED:
        logger.error(
            "[bulk]: batch %s of library %s failed at row %s: chunk %s started "
            "%s times without ending; a worker likely died",
            batch.token,
            batch.library_id,
            batch.position,
            chunk,
            batch.attempts,
        )
        _fail(batch, act.name, Tally.of(batch), batch.position, owner=owner)
        return
    attempts = batch.attempts + 1
    if _store(owner, attempts=attempts, state=BulkBatch.State.RUNNING):
        _run(batch, act, chunk, attempts)


def _run(batch: BulkBatch, act: BatchAct, chunk: int, attempts: int) -> None:
    this_run = _live(batch, chunk=chunk, attempts=attempts)
    keys = batch.keys
    tally = Tally.of(batch)
    position = batch.position
    started = monotonic()
    try:
        user = batch.library.user
        while position < len(keys):
            tally = _one_row(batch, act, user, keys[position], tally)
            position += 1
            tally = tally.reached(position)
            if not _store(this_run, position=position, **tally.columns()):
                raise _Overtaken
            if monotonic() - started >= CHUNK_BUDGET.total_seconds():
                break
        with transaction.atomic():
            if position >= len(keys):
                ended = _store(
                    this_run, state=BulkBatch.State.FINISHED, ended_at=timezone.now()
                )
            else:
                ended = _store(this_run, chunk=chunk + 1, attempts=0)
                if ended:
                    enqueue(batch.pk, chunk + 1)
            if not ended:
                raise _Overtaken
    except _Overtaken:
        logger.info("[bulk]: batch %s chunk %s was overtaken", batch.token, chunk)
    except BaseException as error:
        logger.exception(
            "[bulk]: %s met a defect on row %s of library %s under %s",
            act.name,
            keys[position] if position < len(keys) else None,
            batch.library_id,
            batch.token,
        )
        _store_failure(batch, act.name, tally, position, owner=this_run)
        # Re-raise the cluster's timeout.
        if not isinstance(error, Exception):
            raise


class _Defect(Exception):
    """A row's answer ends the batch."""


def _one_row(
    batch: BulkBatch,
    act: BatchAct,
    user: User,
    key: RowKey,
    tally: Tally,
) -> Tally:
    """Resolve one key again, then act on it."""
    #: A forward row gone since is lost.
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
            #: Resolved moments ago, so ours.
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


def _store_failure(
    batch: BulkBatch,
    name: ActKeyPrefix,
    tally: Tally,
    position: int,
    *,
    owner: BatchRows,
) -> None:
    """`_fail`, surviving a broken connection once."""
    try:
        _fail(batch, name, tally, position, owner=owner)
    except Exception:
        logger.exception("[bulk]: could not store batch %s as failed", batch.token)
        connection.close()
        try:
            _fail(batch, name, tally, position, owner=owner)
        except Exception:
            logger.exception("[bulk]: batch %s stays unended", batch.token)


def _fail(
    batch: BulkBatch,
    name: ActKeyPrefix,
    tally: Tally,
    position: int,
    *,
    owner: BatchRows,
) -> None:
    """Store the end; name every row left."""
    ended = _store(
        owner,
        position=position,
        state=BulkBatch.State.FAILED,
        ended_at=timezone.now(),
        **tally.reached(position).columns(),
    )
    if not ended:
        logger.info("[bulk]: batch %s failed after another took over", batch.token)
        return
    keys = batch.keys
    _log_unreached(name, keys[position : position + 1], batch, MET_THE_DEFECT)
    _log_unreached(name, keys[position + 1 :], batch, ENDED_BY_A_DEFECT)


def _end_unreached(batch: BulkBatch, state: BulkBatch.State, sentence: str) -> bool:
    """End before the next row; fences out any run."""
    ended = _store(
        _live(batch, chunk=batch.chunk, attempts=batch.attempts),
        state=state,
        ended_at=timezone.now(),
        attempts=F("attempts") + 1,
    )
    if ended:
        _log_unreached(_name_of(batch), batch.keys[batch.position :], batch, sentence)
    return bool(ended)


# ── Following ───────────────────────────────────────────────────────────────


def library_batch(library: UserLibrary, token: BatchToken) -> BulkBatch | None:
    return BulkBatch.objects.filter(library=library, token=token).first()


def is_stale(batch: BulkBatch) -> bool:
    """Live, yet no worker wrote lately."""
    return not batch.is_terminal and batch.updated_at < timezone.now() - STALE_AFTER


def end_stale(batch: BulkBatch) -> bool:
    """Stop a batch no worker owns."""
    if not is_stale(batch):
        return False
    logger.error(
        "[bulk]: batch %s of library %s had no worker for %s; ended",
        batch.token,
        batch.library_id,
        STALE_AFTER,
    )
    return _end_unreached(batch, BulkBatch.State.STOPPED, NO_WORKER)


def request_stop(library: UserLibrary, token: BatchToken) -> bool:
    """Ask the runner to stop; False when absent."""
    batch = library_batch(library, token)
    if batch is None:
        return False
    if not end_stale(batch):
        _store(
            BulkBatch.objects.filter(
                pk=batch.pk, state__in=BulkBatch.LIVE, stop_requested_at__isnull=True
            ),
            stop_requested_at=timezone.now(),
        )
    return True


def announce(library: UserLibrary, token: BatchToken) -> bool:
    """Mark the end seen; False when absent."""
    held = BulkBatch.objects.filter(library=library, token=token)
    if not held.exists():
        return False
    _store(
        held.filter(announced_at__isnull=True, ended_at__isnull=False),
        announced_at=timezone.now(),
    )
    return True


def visible_batches(library: UserLibrary) -> list[BulkBatch]:
    """Running ones, and recent unseen ends."""
    since = timezone.now() - ANNOUNCE_WINDOW
    return list(
        BulkBatch.objects.filter(
            Q(state__in=BulkBatch.LIVE)
            | Q(announced_at__isnull=True, ended_at__gte=since),
            library=library,
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


class BatchToast(ToastPayload):
    """The store's message, composed here."""

    id: str
    sticky: bool


class BatchOut(TypedDict):
    token: str
    state: BatchState
    terminal: bool
    origin: str
    toast: BatchToast


def is_batch_state(word: str) -> TypeIs[BatchState]:
    return word in BATCH_STATES


def _title(batch: BulkBatch) -> str:
    declared = bulk_action(batch.action)
    title = declared.title.for_count(batch.total) if declared else UNKNOWN_TITLE
    return f"Undo: {title}" if batch.undoes is not None else title


def _stop_action(batch: BulkBatch) -> ToastAction:
    return ToastAction(
        label="Stop", url=reverse("games:stop_bulk_batch", args=[batch.token])
    )


def _undo_action(batch: BulkBatch) -> ToastAction | None:
    """Where rows moved; an Undo's own has none."""
    if batch.undoes is not None or not batch.done or bulk_action(batch.action) is None:
        return None
    return Undo(reverse("games:undo_bulk_action", args=[batch.token]))


def error_id(token: BatchToken) -> str:
    """The token's last twelve digits."""
    return str(token)[-12:]


@dataclass(frozen=True, slots=True)
class _ToastWords:
    """What a toast says, and offers."""

    kind: ToastType
    said: str
    action: ToastAction | None


def _words_while_live(batch: BulkBatch, tally: Tally) -> _ToastWords:
    if is_stale(batch):
        said = (
            "not running; the background worker may be down "
            f"(error {error_id(batch.token)}). {tally.sentence()}"
        )
        return _ToastWords("warning", said, _stop_action(batch))
    if batch.stop_requested_at is not None:
        return _ToastWords("info", f"stopping. {tally.sentence()}", None)
    if batch.state == BulkBatch.State.QUEUED:
        said = f"waiting to start. {tally.sentence()}"
        return _ToastWords("info", said, _stop_action(batch))
    return _ToastWords("info", tally.sentence(), _stop_action(batch))


def _words_once_ended(batch: BulkBatch, tally: Tally) -> _ToastWords:
    ended = tally.sentence(ended=True)
    action = _undo_action(batch)
    if batch.state == BulkBatch.State.FAILED:
        said = (
            f"a problem on our side stopped it (error {error_id(batch.token)}). {ended}"
        )
        return _ToastWords("error", said, action)
    if batch.state == BulkBatch.State.STOPPED:
        return _ToastWords("info", f"stopped. {ended}", action)
    return _ToastWords("success" if batch.done else "info", ended, action)


def batch_toast(batch: BulkBatch) -> BatchToast:
    """One toast for one batch's state."""
    tally = Tally.of(batch)
    words = (
        _words_once_ended(batch, tally)
        if batch.is_terminal
        else _words_while_live(batch, tally)
    )
    reasons = "".join(f" {reason}" for reason in tally.reasons)
    toast = BatchToast(
        id=f"{TOAST_ID_PREFIX}{batch.token}",
        message=f"{_title(batch)}: {words.said}{reasons}",
        type=words.kind,
        sticky=not batch.is_terminal or words.action is not None,
    )
    if words.action is not None:
        toast["action"] = words.action
    return toast


def batch_out(batch: BulkBatch) -> BatchOut:
    if not is_batch_state(batch.state):
        raise ValueError(f"batch {batch.token} holds state {batch.state!r}")
    return BatchOut(
        token=str(batch.token),
        state=batch.state,
        terminal=batch.is_terminal,
        origin=batch.origin,
        toast=batch_toast(batch),
    )
