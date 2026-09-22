"""One act on many rows, one batch."""

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import partial
from time import monotonic
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import SELECTION_STATEMENT_FIELD
from common.components.core import Node
from common.criteria import FilterError
from common.date_time_presentation import date_time_presentation_for_request
from common.duration_presentation import duration_presentation_for_request
from common.layout import render_page
from common.notices import Undo, notify
from common.returns import UrlName
from games.bulk_actions import (
    BoundRow,
    BulkAction,
    BulkActionName,
    ChoiceValue,
    Control,
    Presentations,
    Refused,
    RefusedAct,
    Resolution,
    RowOutcome,
    bulk_action,
)
from games.events.dispatch import CommandRejected
from games.models import UserLibrary
from games.reads.events import batch_aggregate_ids, batch_events
from games.views.bulk_pages import (
    ConfirmBatch,
    ProgressBatch,
    RefusedBatch,
)
from games.views.returns import return_url
from games.writes.answers import CONFLICT_STATUS, DEFECT_STATUS, CommandFailed

logger = logging.getLogger("games")

#: What a selection states; the confirm POST.
#: One spelling: the line renders it, this route reads it.
STATEMENT_FIELD = SELECTION_STATEMENT_FIELD
#: The batch's identity, minted by the confirmation.
TOKEN_FIELD = "submission"
#: The rows left and the tally so far.
PROGRESS_FIELD = "progress"
#: Pressed on the waypoint: end the batch.
STOP_FIELD = "stop"
#: Where an act's question is answered.
CHOICE_FIELD = "choice"

#: The rows one request acts on.
#: No transaction: each row commits on its own.
CHUNK_BUDGET = timedelta(seconds=3)

#: What a person reads; keys ride PROGRESS_FIELD.
CONFIRMATION_SAMPLE = 50

UNREADABLE_STATEMENT = (
    "That selection could not be read, so nothing was changed. Choose the rows again."
)
UNREADABLE_CHOICE = (
    "That request did not say what to do, so nothing was changed. Answer the "
    "question below and press again."
)
UNREADABLE_FILTER = (
    "The filter behind that selection could not be read, so nothing was "
    "changed. Open the list again and reapply it."
)
#: Where an undeclared act's Undo returns.
UNDO_FALLBACK: UrlName = "games:library"

UNKNOWN_ACT = (
    "That batch was made by something this app no longer does, so it "
    "cannot be taken back. Nothing was changed."
)

#: What the page says after a defect.
DEFECT_SENTENCE = (
    "A problem on our side stopped this request. It has been reported, and "
    "the rows it had not reached were left as they are."
)

#: An Undo acts on its batch's rows.
NOT_THIS_BATCH = "One of those rows is not part of this batch, so it was left as it is."

#: The log's words for a row unreached.
STOPPED_BY_HAND = "The batch was stopped before this row was reached."
ENDED_BY_A_DEFECT = "A problem on our side ended the batch before this row was reached."


@dataclass(frozen=True, slots=True)
class SelectionStatement:
    """Keys, or a scope and exclusions."""

    #: None under "all": the scope names them.
    keys: tuple[uuid.UUID, ...] | None
    filter_json: str
    #: What the person was told it held.
    count: int
    excluded: frozenset[uuid.UUID]


@dataclass(frozen=True, slots=True)
class Tally:
    """What the batch did, and what remains.

    It rides the progress form, so the runner keeps nothing between
    requests, and a person may edit their own. The counts decide
    nothing beyond their own toast, and every key is resolved again
    before a dispatch reads it, so a forged key comes out lost.
    """

    rows: tuple[uuid.UUID, ...]
    done: int = 0
    unchanged: int = 0
    lost: int = 0
    #: Refused on merits: not moved, not gone.
    refused: int = 0
    #: Each distinct reason once, in order.
    reasons: tuple[str, ...] = ()
    #: The denominator: what the confirmation resolved.
    total: int = 0

    def as_json(self) -> str:
        return json.dumps(
            {
                "rows": [str(key) for key in self.rows],
                "done": self.done,
                "unchanged": self.unchanged,
                "lost": self.lost,
                "refused": self.refused,
                "reasons": list(self.reasons),
                "total": self.total,
            }
        )

    @classmethod
    def read(cls, posted: str) -> Tally:
        try:
            stated = json.loads(posted)
            return cls(
                rows=_keys(stated.get("rows")),
                done=int(stated.get("done", 0)),
                unchanged=int(stated.get("unchanged", 0)),
                lost=int(stated.get("lost", 0)),
                refused=int(stated.get("refused", 0)),
                reasons=tuple(str(one) for one in stated.get("reasons", [])),
                total=int(stated.get("total", 0)),
            )
        except (ValueError, TypeError, AttributeError) as error:
            raise StatementUnreadable(f"progress is unreadable: {error}") from error

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

    def sentence(self) -> str:
        """What the toast says."""
        parts = [f"{self.done} of {self.total} done"]
        if self.unchanged:
            parts.append(f"{self.unchanged} already done")
        if self.refused:
            parts.append(f"{self.refused} left as {_as_it_is(self.refused)}")
        if self.lost:
            parts.append(f"{self.lost} no longer there")
        left = len(self.rows)
        if left:
            parts.append(f"{left} left")
        return ", ".join(parts) + "."


def _as_it_is(count: int) -> str:
    """Singular or plural pronoun for a count."""
    return "it is" if count == 1 else "they are"


class StatementUnreadable(Exception):
    """The posted selection cannot be read."""


def _keys(raw: Any) -> tuple[uuid.UUID, ...]:
    if not isinstance(raw, list):
        raise StatementUnreadable(f"keys is {type(raw).__name__}, not a list")
    try:
        return tuple(uuid.UUID(str(key)) for key in raw)
    except ValueError as error:
        raise StatementUnreadable(f"a key is not a uuid: {error}") from error


def parse_statement(posted: str) -> SelectionStatement:
    """Read the statement a selection posted."""
    try:
        stated = json.loads(posted)
    except ValueError as error:
        raise StatementUnreadable(f"not json: {error}") from error
    if not isinstance(stated, dict):
        raise StatementUnreadable("not an object")
    mode = stated.get("mode")
    if mode == "some":
        return SelectionStatement(
            keys=_keys(stated.get("keys")),
            filter_json="",
            count=0,
            excluded=frozenset(),
        )
    if mode == "all":
        filter_json = stated.get("filter")
        if not isinstance(filter_json, str):
            raise StatementUnreadable("all names no filter")
        count = stated.get("count")
        if not isinstance(count, int):
            raise StatementUnreadable("all states no count")
        return SelectionStatement(
            keys=None,
            filter_json=filter_json,
            count=count,
            excluded=frozenset(_keys(stated.get("except", []))),
        )
    raise StatementUnreadable(f"mode is {mode!r}")


def resolved_keys(
    action: BulkAction[Any], library: UserLibrary, statement: SelectionStatement
) -> list[uuid.UUID]:
    """The keys the statement names, now.

    Through the act's own scope, never the filter alone, so a rule no
    filter field can state still holds.
    """
    if statement.keys is not None:
        return list(statement.keys)
    scoped = action.scope(library, statement.filter_json)
    return [
        key
        for key in scoped.values_list("pk", flat=True)
        if key not in statement.excluded
    ]


def _confirmation(
    request: HttpRequest,
    action: BulkAction[Any],
    *,
    rows: list[Any],
    refused: tuple[Refused, ...],
    keys: list[uuid.UUID],
) -> HttpResponse:
    """What the act would do, and asks."""
    library = cast(User, request.user).library
    choice: Node | None = None
    if action.choice is not None:
        offered = action.choice.offer(library, rows, CHOICE_FIELD)
        if isinstance(offered, RefusedAct):
            return _act_refused(request, action, offered.sentence)
        choice = offered.node if isinstance(offered, Control) else None
    #: The token is the batch's correlation id.
    token = str(uuid.uuid7())
    #: Named once: the batch carries only its rows.
    _log_left_alone(action.name, refused, library, uuid.UUID(token))
    progress = Tally(rows=tuple(keys), total=len(keys)).left_alone(refused).as_json()
    return _confirm_page(
        request,
        action,
        rows=rows,
        refused=refused,
        token=token,
        progress=progress,
        choice=choice,
    )


def _confirm_page(
    request: HttpRequest,
    action: BulkAction[Any],
    *,
    rows: Sequence[Any],
    refused: Sequence[Refused],
    token: str,
    progress: str,
    choice: Node | None,
    refusal: Sequence[str] = (),
) -> HttpResponse:
    """The confirmation, on the caller's token."""
    return render_page(
        request,
        ConfirmBatch(
            action,
            rows=rows,
            refused=refused,
            hidden=[(TOKEN_FIELD, token), (PROGRESS_FIELD, progress)],
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            cancel_url=return_url(request, fallback=action.fallback),
            sample_cap=CONFIRMATION_SAMPLE,
            presentations=Presentations(
                dates=date_time_presentation_for_request(request),
                durations=duration_presentation_for_request(request),
            ),
            choice=choice,
            refusal=refusal,
        ),
        title=action.title.for_count(len(rows)),
        status=400 if refusal else 200,
    )


def _reconfirmation(
    request: HttpRequest,
    action: BulkAction[Any],
    *,
    token: str,
    tally: Tally,
    sentence: str,
    undo_url: str | None,
) -> HttpResponse:
    """Ask again, about the rows left.

    The posted token and tally ride on verbatim. Minting
    fresh ones would split one batch across two correlation
    ids, and the final toast's Undo would then reach the
    second half alone.
    """
    library = cast(User, request.user).library
    correlation_id = uuid.UUID(token)
    resolution = action.resolve(library, list(tally.rows))
    _log_left_alone(action.name, resolution.refused, library, correlation_id)
    tally = tally.left_alone(resolution.refused)
    choice: Node | None = None
    if action.choice is not None:
        offered = action.choice.offer(library, resolution.rows, CHOICE_FIELD)
        if isinstance(offered, RefusedAct):
            #: The act cannot ask again, so the batch ends here.
            #: The rows done stay done and keep their Undo; a page
            #: saying nothing happened would strand them.
            said = offered.sentence
            _log_abandoned(action.name, tally.rows, library, correlation_id, said)
            return _answer(
                request,
                action,
                replace(tally, rows=(), reasons=(*tally.reasons, said)),
                undo_url=undo_url,
            )
        choice = offered.node if isinstance(offered, Control) else None
    return _confirm_page(
        request,
        action,
        rows=list(resolution.rows),
        refused=(),
        token=token,
        progress=tally.as_json(),
        choice=choice,
        refusal=[sentence],
    )


def _refused_page(
    request: HttpRequest,
    sentence: str,
    *,
    title: str,
    fallback: UrlName,
) -> HttpResponse:
    """Nothing was done, and why."""
    return render_page(
        request,
        RefusedBatch(
            title=title,
            sentence=sentence,
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            cancel_url=return_url(request, fallback=fallback),
        ),
        title=title,
        status=400,
    )


def _act_refused(
    request: HttpRequest, action: BulkAction[Any], sentence: str
) -> HttpResponse:
    """An act turned down before it resolved anything.

    The plural: a refusal ahead of the resolve counts no rows.
    """
    return _refused_page(
        request, sentence, title=action.title.many, fallback=action.fallback
    )


@dataclass(frozen=True, slots=True)
class BatchAct:
    """What one batch does to each of its rows."""

    #: The idempotency key's prefix, so an act and its undo
    #: never share a key space.
    name: str
    resolve: Callable[[UserLibrary, uuid.UUID], Resolution]
    #: Its own fact is bound; the row and the keys remain.
    run: BoundRow


def _forward(action: BulkAction[Any], choice: ChoiceValue | None = None) -> BatchAct:
    """The act itself, over the settled answer."""
    return BatchAct(
        name=action.name,
        resolve=lambda library, key: action.resolve(library, [key]),
        run=partial(action.run, choice=choice),
    )


def _undo_name(action: BulkAction[Any]) -> str:
    """One spelling, for the key prefix and the log."""
    return f"{action.name}.undo"


def _backward(
    action: BulkAction[Any],
    written: frozenset[uuid.UUID],
    correlation_id: uuid.UUID,
) -> BatchAct:
    """The inverse, over this batch's keys.

    The row is removed by now, so the batch says whether a key is its
    own. A key that is not comes out lost, as a row gone since the
    confirmation does when the act runs: one rule, both batches.

    `_run_a_chunk` derives its correlation id from the undo's own
    fresh token, so this is the one way the batch's id reaches the
    inverse.
    """
    return BatchAct(
        name=_undo_name(action),
        resolve=lambda library, key: _of_this_batch(key, written),
        run=partial(action.inverse, undoes=correlation_id),
    )


def _of_this_batch(key: uuid.UUID, written: frozenset[uuid.UUID]) -> Resolution:
    if key in written:
        return Resolution((key,), ())
    return Resolution((), (Refused(str(key), NOT_THIS_BATCH, lost=True),))


def _run_a_chunk(
    request: HttpRequest,
    action: BulkAction[Any],
    *,
    token: str,
    tally: Tally,
    act: BatchAct,
    undo_url: str | None,
    carried_choice: ChoiceValue | None = None,
) -> HttpResponse:
    """Act on as many rows as allowed.

    Each row is its own dispatch and transaction, keyed from the token
    and the row, so a token posted twice acts once.
    """
    user = cast(User, request.user)
    correlation_id = uuid.UUID(token)
    left = list(tally.rows)
    started = monotonic()

    while left:
        #: Re-resolved: a row gone since is lost.
        resolution = act.resolve(user.library, left[0])
        _log_left_alone(act.name, resolution.refused, user.library, correlation_id)
        tally = tally.left_alone(resolution.refused)
        acted = left.pop(0)
        for row in resolution.rows:
            try:
                outcome = act.run(
                    user,
                    row,
                    idempotency_key=f"{act.name}-{token}-{acted}",
                    correlation_id=correlation_id,
                )
            except Http404 as absent:
                #: This batch re-resolved the row moments ago.
                #: Said anyway, so no batch ends in silence.
                _log_abandoned(
                    act.name,
                    [acted, *left],
                    user.library,
                    correlation_id,
                    ENDED_BY_A_DEFECT,
                )
                logger.error(
                    "[bulk]: %s met a row library %s does not hold: %s",
                    act.name,
                    user.library.pk,
                    absent,
                )
                return _defect(
                    request,
                    action,
                    replace(tally, rows=tuple(left)),
                    undo_url=undo_url,
                )
            except CommandFailed as failure:
                if failure.status_code != CONFLICT_STATUS:
                    #: Ours, not theirs: the batch ends here.
                    #: No dispatch answered for the row that met
                    #: it either, so it is named with the rest.
                    _log_abandoned(
                        act.name,
                        [acted, *left],
                        user.library,
                        correlation_id,
                        ENDED_BY_A_DEFECT,
                    )
                    return _defect(
                        request,
                        action,
                        replace(tally, rows=tuple(left)),
                        undo_url=undo_url,
                    )
                refusal = Refused(str(acted), failure.message)
                _log_left_alone(act.name, (refusal,), user.library, correlation_id)
                tally = tally.left_alone((refusal,))
            else:
                tally = _counted(tally, outcome)
        if monotonic() - started >= CHUNK_BUDGET.total_seconds():
            break

    tally = replace(tally, rows=tuple(left))
    if left:
        return _progress(
            request, action, token=token, tally=tally, choice=carried_choice
        )
    return _answer(request, action, tally, undo_url=undo_url)


def _log_left_alone(
    name: str,
    refused: Sequence[Refused],
    library: UserLibrary,
    correlation_id: uuid.UUID,
) -> None:
    """The page prints sentences; the log, keys."""
    for entry in refused:
        logger.info(
            "[bulk]: %s left row %s of library %s under %s: %s",
            name,
            entry.key,
            library.pk,
            correlation_id,
            entry.sentence,
        )


def _log_abandoned(
    name: str,
    keys: Sequence[uuid.UUID],
    library: UserLibrary,
    correlation_id: uuid.UUID,
    sentence: str,
) -> None:
    """Name the rows no dispatch reached."""
    _log_left_alone(
        name,
        [Refused(str(key), sentence) for key in keys],
        library,
        correlation_id,
    )


def _counted(tally: Tally, outcome: RowOutcome) -> Tally:
    """Moved, or already in that state."""
    if outcome is RowOutcome.UNCHANGED:
        return replace(tally, unchanged=tally.unchanged + 1)
    return replace(tally, done=tally.done + 1)


def _progress(
    request: HttpRequest,
    action: BulkAction[Any],
    *,
    token: str,
    tally: Tally,
    choice: ChoiceValue | None = None,
) -> HttpResponse:
    """The waypoint, which states any choice again."""
    hidden = [(TOKEN_FIELD, token), (PROGRESS_FIELD, tally.as_json())]
    if choice is not None:
        hidden.append((CHOICE_FIELD, choice))
    return render_page(
        request,
        ProgressBatch(
            action,
            done=tally.done,
            total=tally.total,
            refused=tally.refused,
            reasons=tally.reasons,
            hidden=hidden,
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            stop_name=STOP_FIELD,
        ),
        title=action.title.for_count(tally.total),
    )


def _defect(
    request: HttpRequest,
    action: BulkAction[Any],
    tally: Tally,
    *,
    undo_url: str | None,
) -> HttpResponse:
    """A defect stopped the batch.

    The rows done stay done, so the Undo rides the toast beside this
    page: the answer that would carry it is never reached.
    """
    notify(
        request,
        tally.sentence(),
        level=messages.ERROR,
        action=Undo(undo_url) if undo_url and tally.done else None,
    )
    heading = action.title.for_count(tally.total)
    return render_page(
        request,
        RefusedBatch(
            title=heading,
            sentence=DEFECT_SENTENCE,
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            cancel_url=return_url(request, fallback=action.fallback),
        ),
        title=heading,
        status=DEFECT_STATUS,
    )


def _answer(
    request: HttpRequest,
    action: BulkAction[Any],
    tally: Tally,
    *,
    undo_url: str | None,
) -> HttpResponse:
    """One toast, then back.

    The Undo is offered only where something was done, and never by an
    Undo: undoing an Undo is pressing the act again.
    """
    notify(
        request,
        tally.sentence(),
        level=messages.SUCCESS if tally.done else messages.INFO,
        action=Undo(undo_url) if undo_url and tally.done else None,
    )
    for reason in tally.reasons:
        notify(request, reason, level=messages.INFO)
    return redirect(return_url(request, fallback=action.fallback))


@login_required
@require_POST
def run_bulk_action(request: HttpRequest, action: BulkActionName) -> HttpResponse:
    """Confirm the act, or run a chunk."""
    declared = bulk_action(action)
    if declared is None:
        raise Http404("No such bulk action.")
    user = cast(User, request.user)

    token = request.POST.get(TOKEN_FIELD, "")
    if token:
        try:
            tally = Tally.read(request.POST.get(PROGRESS_FIELD, ""))
            uuid.UUID(token)
        except (StatementUnreadable, ValueError) as unreadable:
            logger.warning("[bulk]: %s refused a progress: %s", action, unreadable)
            return _act_refused(request, declared, UNREADABLE_STATEMENT)
        if request.POST.get(STOP_FIELD):
            #: Ended here; the rows done stay done.
            _log_abandoned(
                declared.name,
                tally.rows,
                user.library,
                uuid.UUID(token),
                STOPPED_BY_HAND,
            )
            return _answer(
                request, declared, replace(tally, rows=()), undo_url=_undo_url(token)
            )
        choice: ChoiceValue | None = None
        if declared.choice is not None:
            #: Every chunk settles again. The field is
            #: person-editable, and a value carried on trust
            #: reaches the command, whose scope miss answers
            #: a 500 page that blames the app.
            try:
                choice = declared.choice.settle(user.library, request.POST)
            except CommandRejected as refusal:
                logger.info(
                    "[bulk]: %s refused a choice under %s: %s",
                    action,
                    token,
                    refusal,
                )
                return _reconfirmation(
                    request,
                    declared,
                    token=token,
                    tally=tally,
                    sentence=refusal.sentence or UNREADABLE_CHOICE,
                    undo_url=_undo_url(token),
                )
        return _run_a_chunk(
            request,
            declared,
            token=token,
            tally=tally,
            act=_forward(declared, choice),
            undo_url=_undo_url(token),
            carried_choice=choice,
        )

    try:
        statement = parse_statement(request.POST.get(STATEMENT_FIELD, ""))
    except StatementUnreadable as unreadable:
        logger.warning("[bulk]: %s refused a statement: %s", action, unreadable)
        return _act_refused(request, declared, UNREADABLE_STATEMENT)

    try:
        keys = resolved_keys(declared, user.library, statement)
    except FilterError as unreadable:
        #: Never `apply_structured_filter`, which fails open.
        #: A dropped filter would widen the act to the whole base.
        logger.warning("[bulk]: %s refused a filter: %s", action, unreadable)
        return _act_refused(request, declared, UNREADABLE_FILTER)

    resolution = declared.resolve(user.library, keys)
    return _confirmation(
        request,
        declared,
        rows=list(resolution.rows),
        refused=resolution.refused,
        keys=[row.pk for row in resolution.rows],
    )


def _undo_url(token: str) -> str:
    """Where the act's toast points."""
    return reverse("games:undo_bulk_action", args=[token])


def _act_of(library: UserLibrary, correlation_id: uuid.UUID) -> BulkAction[Any] | None:
    """Which act wrote this batch.

    A correlation nothing wrote, and one that is no batch, are not
    found. A name the table no longer holds answers None: that batch
    is real, and it is its Undo that is gone.
    """
    first = batch_events(library, correlation_id).first()
    if first is None:
        raise Http404("No such batch.")
    stated = first.source_metadata.get("bulk", {})
    name = stated.get("action") if isinstance(stated, dict) else None
    if not isinstance(name, str):
        raise Http404("That act is no batch.")
    #: Nothing validates the name at the append.
    return bulk_action(name)


@login_required
@require_POST
def undo_bulk_action(request: HttpRequest, correlation_id: uuid.UUID) -> HttpResponse:
    """One batch's inverse, as its own batch.

    Its own token and correlation id: sharing the act's would make a
    second press read its own appends as rows to take back.
    """
    user = cast(User, request.user)
    declared = _act_of(user.library, correlation_id)
    if declared is None:
        logger.warning("[bulk]: %s names an act nothing declares", correlation_id)
        return _refused_page(
            request,
            UNKNOWN_ACT,
            title="Undo",
            fallback=UNDO_FALLBACK,
        )

    #: Read once a request: this is it.
    rows = batch_aggregate_ids(user.library, correlation_id, declared.inverse_aggregate)

    token = request.POST.get(TOKEN_FIELD, "")
    if token:
        try:
            tally = Tally.read(request.POST.get(PROGRESS_FIELD, ""))
            uuid.UUID(token)
        except (StatementUnreadable, ValueError) as unreadable:
            logger.warning("[bulk]: an undo refused a progress: %s", unreadable)
            return _act_refused(request, declared, UNREADABLE_STATEMENT)
        if request.POST.get(STOP_FIELD):
            _log_abandoned(
                _undo_name(declared),
                tally.rows,
                user.library,
                uuid.UUID(token),
                STOPPED_BY_HAND,
            )
            return _answer(request, declared, replace(tally, rows=()), undo_url=None)
    else:
        tally = Tally(rows=tuple(rows), total=len(rows))
        token = str(uuid.uuid7())

    return _run_a_chunk(
        request,
        declared,
        token=token,
        tally=tally,
        act=_backward(declared, frozenset(rows), correlation_id),
        undo_url=None,
    )
