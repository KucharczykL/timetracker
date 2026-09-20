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
from dataclasses import dataclass
from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_POST

from common.criteria import FilterError
from common.layout import render_page
from games.bulk_actions import BulkAction, BulkActionName, Refused, bulk_action
from games.models import UserLibrary
from games.views.bulk_pages import ConfirmBatch
from games.views.returns import return_url

logger = logging.getLogger("games")

#: The statement a selection makes; the confirm POST carries it.
STATEMENT_FIELD = "selection"
#: The batch's identity, minted by the confirmation.
TOKEN_FIELD = "submission"
#: The rows left and the tally so far; the act POST carries it.
PROGRESS_FIELD = "progress"

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
    token = str(uuid.uuid7())
    progress = json.dumps({"rows": [str(key) for key in keys]})
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


@login_required
@require_POST
def run_bulk_action(request: HttpRequest, action: BulkActionName) -> HttpResponse:
    """Confirm the act, or run a chunk of it."""
    declared = bulk_action(action)
    if declared is None:
        raise Http404("No such bulk action.")
    user = cast(User, request.user)

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
