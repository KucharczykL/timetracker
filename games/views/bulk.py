"""One act on many rows, run as one batch.

A new flow, not a generalisation of `confirm_and_apply`, whose one shape
is "GET confirms, POST acts". Here both arrive by POST, and the
submission token tells them apart: without one the request is asking
what would happen, with one it is doing it.

The token is also the batch's correlation id. One identity, so a batch
that spans two requests is still one batch and its Undo names the value
the confirmation wrote.
"""

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
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

from common.criteria import FilterError
from common.layout import render_page
from common.notices import Undo, notify
from common.returns import UrlName
from games.bulk_actions import (
    BulkAction,
    BulkActionName,
    Refused,
    Resolution,
    RowOutcome,
    bulk_action,
)
from games.events.idempotency import IdempotencyKey
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

#: The statement a selection makes; the confirm POST carries it.
STATEMENT_FIELD = "selection"
#: The batch's identity, minted by the confirmation.
TOKEN_FIELD = "submission"
#: The rows left and the tally so far; the act POST carries it.
PROGRESS_FIELD = "progress"
#: Pressed on the progress page: end the batch where it stands.
STOP_FIELD = "stop"

#: A chunk is the rows one request acts on inside this. Not a
#: transaction: each row commits on its own, so the budget bounds the
#: request rather than the work that survives it.
CHUNK_BUDGET = timedelta(seconds=3)

#: What a person reads. Every key still rides PROGRESS_FIELD.
CONFIRMATION_SAMPLE = 50

UNREADABLE_STATEMENT = (
    "That selection could not be read, so nothing was changed. Choose the rows again."
)
UNREADABLE_FILTER = (
    "The filter behind that selection could not be read, so nothing was "
    "changed. Open the list again and reapply it."
)
#: Where an Undo returns when it carries no origin: an act it cannot
#: name states no fallback of its own.
UNDO_FALLBACK: UrlName = "games:library"

UNKNOWN_ACT = (
    "That batch was made by something this app no longer does, so it "
    "cannot be taken back. Nothing was changed."
)

#: What the page says when a defect ends a batch. How far it got is a
#: toast, which is where the batch's Undo rides.
DEFECT_SENTENCE = (
    "A problem on our side stopped this request. It has been reported, and "
    "the rows it had not reached were left as they are."
)

#: An Undo acts on the rows its own batch wrote, and on no others.
NOT_THIS_BATCH = "One of those rows is not part of this batch, so it was left as it is."


@dataclass(frozen=True, slots=True)
class SelectionStatement:
    """What a person chose: the keys, or a scope and its exclusions."""

    #: None under "all": the scope names the rows, not a list of keys.
    keys: tuple[uuid.UUID, ...] | None
    filter_json: str
    #: What the person was told the scope held.
    count: int
    excluded: frozenset[uuid.UUID]


@dataclass(frozen=True, slots=True)
class Tally:
    """What the batch has done so far, and what is left.

    It rides the progress form rather than the session, so the runner
    keeps nothing between requests -- as an origin is kept nowhere but
    its own parameter. A person may edit their own tally: the counts
    decide nothing beyond their own toast, and every key it names is
    resolved again before a dispatch reads it, so a key that was never
    theirs comes out counted and lost rather than acted on.
    """

    rows: tuple[uuid.UUID, ...]
    done: int = 0
    unchanged: int = 0
    lost: int = 0
    refused: tuple[str, ...] = ()
    #: The denominator: what the confirmation resolved.
    total: int = 0

    def as_json(self) -> str:
        return json.dumps(
            {
                "rows": [str(key) for key in self.rows],
                "done": self.done,
                "unchanged": self.unchanged,
                "lost": self.lost,
                "refused": list(self.refused),
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
                refused=tuple(str(one) for one in stated.get("refused", [])),
                total=int(stated.get("total", 0)),
            )
        except (ValueError, TypeError, AttributeError) as error:
            raise StatementUnreadable(f"progress is unreadable: {error}") from error

    def with_reasons(self, refused: Sequence[Refused]) -> Tally:
        """Count what was left alone, keeping each reason once."""
        reasons = list(self.refused)
        for entry in refused:
            if entry.sentence not in reasons:
                reasons.append(entry.sentence)
        lost = sum(1 for entry in refused if entry.lost)
        return replace(
            self,
            lost=self.lost + lost,
            refused=tuple(reasons),
        )

    def sentence(self) -> str:
        """What the toast says."""
        parts = [f"{self.done} of {self.total} done"]
        if self.unchanged:
            parts.append(f"{self.unchanged} already done")
        if self.lost:
            parts.append(f"{self.lost} no longer there")
        left = len(self.rows)
        if left:
            parts.append(f"{left} left")
        return ", ".join(parts) + "."


class StatementUnreadable(Exception):
    """The posted selection is not one this runner can read."""


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
    action: BulkAction, library: UserLibrary, statement: SelectionStatement
) -> list[uuid.UUID]:
    """The keys the statement names, at this instant.

    An "all" statement is resolved through the act's own scope rather
    than through the filter alone, so a rule no filter field can state
    still holds.
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
    action: BulkAction,
    *,
    rows: list[Any],
    refused: tuple[Refused, ...],
    keys: list[uuid.UUID],
) -> HttpResponse:
    """What the act would do, and a fresh token to make it do it."""
    #: The token is the batch's correlation id: one identity, so a
    #: batch that spans two requests is still one batch.
    token = str(uuid.uuid7())
    #: The keys of a row left alone reach the act no further than this:
    #: the batch carries the rows it will act on. Here is where they are
    #: named, once, under the identity the batch will run as.
    _log_left_alone(
        action.name, refused, cast(User, request.user).library, uuid.UUID(token)
    )
    progress = Tally(rows=tuple(keys), total=len(keys)).with_reasons(refused).as_json()
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
        ),
        title=action.title,
    )


def _refused_page(
    request: HttpRequest,
    sentence: str,
    *,
    title: str,
    fallback: UrlName,
) -> HttpResponse:
    """Nothing was done, and here is why."""
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
    request: HttpRequest, action: BulkAction, sentence: str
) -> HttpResponse:
    return _refused_page(
        request, sentence, title=action.title, fallback=action.fallback
    )


@dataclass(frozen=True, slots=True)
class Leg:
    """One direction of an act, as the chunk loop needs it.

    Forward, a key must become a row and may refuse on the way. Back,
    the row is removed by now -- that is what the act did to it -- so
    what the key is sorted against is the batch rather than the table.
    Both legs answer one shape, so a key neither can act on is counted
    and lost either way. The loop is otherwise the same loop, and the
    two directions share one budget, one progress page and one answer.
    """

    #: The idempotency key's prefix, so a direction never claims the
    #: key of the other.
    name: str
    resolve: Callable[[UserLibrary, uuid.UUID], Resolution]
    run: Callable[[User, Any, IdempotencyKey, uuid.UUID], RowOutcome]


def _forward(action: BulkAction) -> Leg:
    return Leg(
        name=action.name,
        resolve=lambda library, key: action.resolve(library, [key]),
        run=action.run,
    )


def _backward(action: BulkAction, written: frozenset[uuid.UUID]) -> Leg:
    """The inverse, over the keys this batch wrote and no others.

    The row is removed by now -- that is what the act did to it -- so
    the batch itself is what says whether a key is one of its own. A key
    that is not comes out counted and lost, as a row gone since the
    confirmation does on the way forward: one rule, read by both legs.
    """
    return Leg(
        name=f"{action.name}.undo",
        resolve=lambda library, key: _of_this_batch(key, written),
        run=action.inverse,
    )


def _of_this_batch(key: uuid.UUID, written: frozenset[uuid.UUID]) -> Resolution:
    if key in written:
        return Resolution((key,), ())
    return Resolution((), (Refused(str(key), NOT_THIS_BATCH, lost=True),))


def _run_a_chunk(
    request: HttpRequest,
    action: BulkAction,
    *,
    token: str,
    tally: Tally,
    leg: Leg,
    undo_url: str | None,
) -> HttpResponse:
    """Act on as many of the rows left as the budget allows.

    Each row is its own dispatch and its own transaction, keyed from
    the token and the row, so a token posted twice converts nothing
    twice. A refusal names its row and the next row runs; a defect ends
    the batch, and the rows already done stay done because each
    committed on its own.
    """
    user = cast(User, request.user)
    correlation_id = uuid.UUID(token)
    left = list(tally.rows)
    started = monotonic()

    while left:
        #: Re-resolved each time round, so a row gone since the
        #: confirmation is counted lost rather than refused.
        resolution = leg.resolve(user.library, left[0])
        _log_left_alone(leg.name, resolution.refused, user.library, correlation_id)
        tally = tally.with_reasons(resolution.refused)
        acted = left.pop(0)
        for row in resolution.rows:
            try:
                outcome = leg.run(
                    user, row, f"{leg.name}-{token}-{acted}", correlation_id
                )
            except CommandFailed as failure:
                if failure.status_code != CONFLICT_STATUS:
                    #: Ours, not theirs: the batch ends here.
                    return _defect(
                        request,
                        action,
                        replace(tally, rows=tuple(left)),
                        undo_url=undo_url,
                    )
                refusal = Refused(str(acted), failure.message)
                _log_left_alone(leg.name, (refusal,), user.library, correlation_id)
                tally = tally.with_reasons((refusal,))
            else:
                tally = _counted(tally, outcome)
        if monotonic() - started >= CHUNK_BUDGET.total_seconds():
            break

    tally = replace(tally, rows=tuple(left))
    if left:
        return _progress(request, action, token=token, tally=tally)
    return _answer(request, action, tally, undo_url=undo_url)


def _log_left_alone(
    name: str,
    refused: Sequence[Refused],
    library: UserLibrary,
    correlation_id: uuid.UUID,
) -> None:
    """The page prints sentences; the log prints keys.

    A person reading a toast wants how many and why. Whoever reads the
    log afterwards wants which ones, and a row refused before it
    reaches a dispatch is left alone as surely as one the command
    refused.
    """
    for entry in refused:
        logger.info(
            "[bulk]: %s left row %s of library %s under %s: %s",
            name,
            entry.key,
            library.pk,
            correlation_id,
            entry.sentence,
        )


def _counted(tally: Tally, outcome: RowOutcome) -> Tally:
    """A row the dispatch moved, or one already in that state."""
    if outcome is RowOutcome.UNCHANGED:
        return replace(tally, unchanged=tally.unchanged + 1)
    return replace(tally, done=tally.done + 1)


def _progress(
    request: HttpRequest, action: BulkAction, *, token: str, tally: Tally
) -> HttpResponse:
    return render_page(
        request,
        ProgressBatch(
            action,
            done=tally.done,
            total=tally.total,
            refused=(),
            hidden=[(TOKEN_FIELD, token), (PROGRESS_FIELD, tally.as_json())],
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            stop_name=STOP_FIELD,
        ),
        title=action.title,
    )


def _defect(
    request: HttpRequest,
    action: BulkAction,
    tally: Tally,
    *,
    undo_url: str | None,
) -> HttpResponse:
    """A problem on our side stopped the batch; say how far it got.

    Every row already done committed on its own and stays done, so the
    batch's Undo is the only way back from here. A batch that finishes
    offers it on the answer it redirects to, which this one never
    reaches, so it is offered on the toast beside the page. The rule is
    the answer's own: an Undo offers none of its own.
    """
    notify(
        request,
        tally.sentence(),
        level=messages.ERROR,
        action=Undo(undo_url) if undo_url and tally.done else None,
    )
    return render_page(
        request,
        RefusedBatch(
            title=action.title,
            sentence=DEFECT_SENTENCE,
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            cancel_url=return_url(request, fallback=action.fallback),
        ),
        title=action.title,
        status=DEFECT_STATUS,
    )


def _answer(
    request: HttpRequest,
    action: BulkAction,
    tally: Tally,
    *,
    undo_url: str | None,
) -> HttpResponse:
    """One toast, then back where the person stood.

    The Undo is offered only where there is something to take back, and
    never by an Undo: taking back a batch that took one back is pressing
    the act again, which is not what the word says.
    """
    notify(
        request,
        tally.sentence(),
        level=messages.SUCCESS if tally.done else messages.INFO,
        action=Undo(undo_url) if undo_url and tally.done else None,
    )
    for reason in tally.refused:
        notify(request, reason, level=messages.INFO)
    return redirect(return_url(request, fallback=action.fallback))


@login_required
@require_POST
def run_bulk_action(request: HttpRequest, action: BulkActionName) -> HttpResponse:
    """Confirm the act, or run a chunk of it."""
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
            #: Ended where it stands; the rows done stay done.
            return _answer(
                request, declared, replace(tally, rows=()), undo_url=_undo_url(token)
            )
        return _run_a_chunk(
            request,
            declared,
            token=token,
            tally=tally,
            leg=_forward(declared),
            undo_url=_undo_url(token),
        )

    try:
        statement = parse_statement(request.POST.get(STATEMENT_FIELD, ""))
    except StatementUnreadable as unreadable:
        logger.warning("[bulk]: %s refused a statement: %s", action, unreadable)
        return _act_refused(request, declared, UNREADABLE_STATEMENT)

    try:
        keys = resolved_keys(declared, user.library, statement)
    except FilterError as unreadable:
        #: Never apply_structured_filter: dropping the filter would
        #: widen the act to every row the act's base holds.
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
    """Where the act's toast points. The element stamps the origin."""
    return reverse("games:undo_bulk_action", args=[token])


def _act_of(library: UserLibrary, correlation_id: uuid.UUID) -> BulkAction | None:
    """Which act wrote this batch, read from the batch itself.

    Every append of a batch states the name, so one event answers. A
    correlation nothing wrote, and one written by something that is no
    batch, are both not found: neither names an act at all. A name the
    table no longer holds answers None instead, because that batch is
    real and it is the Undo that is gone.
    """
    first = batch_events(library, correlation_id).first()
    if first is None:
        raise Http404("No such batch.")
    stated = first.source_metadata.get("bulk", {})
    name = stated.get("action") if isinstance(stated, dict) else None
    if not isinstance(name, str):
        raise Http404("That act is no batch.")
    #: Nothing validates the name at the append, so this is where a
    #: name the table does not hold is met.
    return bulk_action(name)


@login_required
@require_POST
def undo_bulk_action(request: HttpRequest, correlation_id: uuid.UUID) -> HttpResponse:
    """Apply the inverse of one batch, as a batch of its own.

    Its own token and correlation id: sharing the act's would make the
    Undo part of the batch it undoes, and a second press would read its
    own appends as rows to take back.
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

    #: Read once a request, not once a row: this is the batch, and a
    #: key the posted progress names that is not in it is not its own.
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
            return _answer(request, declared, replace(tally, rows=()), undo_url=None)
    else:
        tally = Tally(rows=tuple(rows), total=len(rows))
        token = str(uuid.uuid7())

    return _run_a_chunk(
        request,
        declared,
        token=token,
        tally=tally,
        leg=_backward(declared, frozenset(rows)),
        undo_url=None,
    )
