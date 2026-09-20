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
from collections.abc import Sequence
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
from django.views.decorators.http import require_POST

from common.criteria import FilterError
from common.layout import render_page
from common.notices import notify
from games.bulk_actions import BulkAction, BulkActionName, Refused, bulk_action
from games.models import UserLibrary
from games.views.bulk_pages import ConfirmBatch, ProgressBatch
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
    its own parameter. A person may edit their own tally; it names no
    row and decides nothing, so the worst of that is a wrong number on
    their own toast.
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
    request: HttpRequest, action: BulkAction, sentence: str
) -> HttpResponse:
    """Nothing was done, and here is why.

    Rendered without a token, so the page it draws cannot act.
    """
    return render_page(
        request,
        ConfirmBatch(
            action,
            rows=[],
            refused=(Refused("", sentence),),
            hidden=[],
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            cancel_url=return_url(request, fallback=action.fallback),
            sample_cap=CONFIRMATION_SAMPLE,
        ),
        title=action.title,
        status=400,
    )


def _run_a_chunk(
    request: HttpRequest,
    action: BulkAction,
    *,
    token: str,
    tally: Tally,
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
        resolution = action.resolve(user.library, [left[0]])
        tally = tally.with_reasons(resolution.refused)
        acted = left.pop(0)
        for row in resolution.rows:
            try:
                action.run(user, row, f"{action.name}-{token}-{acted}", correlation_id)
            except CommandFailed as failure:
                if failure.status_code != CONFLICT_STATUS:
                    #: Ours, not theirs: the batch ends here.
                    return _defect(request, action, replace(tally, rows=tuple(left)))
                logger.info(
                    "[bulk]: %s left row %s of library %s under %s: %s",
                    action.name,
                    acted,
                    user.library.pk,
                    correlation_id,
                    failure.message,
                )
                tally = tally.with_reasons((Refused(str(acted), failure.message),))
            else:
                tally = replace(tally, done=tally.done + 1)
        if monotonic() - started >= CHUNK_BUDGET.total_seconds():
            break

    tally = replace(tally, rows=tuple(left))
    if left:
        return _progress(request, action, token=token, tally=tally)
    return _answer(request, action, tally)


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


def _defect(request: HttpRequest, action: BulkAction, tally: Tally) -> HttpResponse:
    """A problem on our side stopped the batch; say how far it got."""
    return render_page(
        request,
        ConfirmBatch(
            action,
            rows=[],
            refused=(
                Refused(
                    "",
                    f"{tally.done} of {tally.total} were done before a problem on "
                    "our side stopped the request. The problem has been reported, "
                    "and the rest were left as they are.",
                ),
            ),
            hidden=[],
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            cancel_url=return_url(request, fallback=action.fallback),
            sample_cap=CONFIRMATION_SAMPLE,
        ),
        title=action.title,
        status=DEFECT_STATUS,
    )


def _answer(request: HttpRequest, action: BulkAction, tally: Tally) -> HttpResponse:
    """One toast, then back where the person stood."""
    notify(
        request,
        tally.sentence(),
        level=messages.SUCCESS if tally.done else messages.INFO,
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
            return _refused_page(request, declared, UNREADABLE_STATEMENT)
        if request.POST.get(STOP_FIELD):
            #: Ended where it stands; the rows done stay done.
            return _answer(request, declared, replace(tally, rows=()))
        return _run_a_chunk(request, declared, token=token, tally=tally)

    try:
        statement = parse_statement(request.POST.get(STATEMENT_FIELD, ""))
    except StatementUnreadable as unreadable:
        logger.warning("[bulk]: %s refused a statement: %s", action, unreadable)
        return _refused_page(request, declared, UNREADABLE_STATEMENT)

    try:
        keys = resolved_keys(declared, user.library, statement)
    except FilterError as unreadable:
        #: Never apply_structured_filter: dropping the filter would
        #: widen the act to every row the act's base holds.
        logger.warning("[bulk]: %s refused a filter: %s", action, unreadable)
        return _refused_page(request, declared, UNREADABLE_FILTER)

    resolution = declared.resolve(user.library, keys)
    return _confirmation(
        request,
        declared,
        rows=list(resolution.rows),
        refused=resolution.refused,
        keys=[row.pk for row in resolution.rows],
    )
