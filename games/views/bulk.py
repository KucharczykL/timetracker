"""One act on many rows, one batch."""

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from common.components import SELECTION_STATEMENT_FIELD
from common.components.core import Node
from common.criteria import FilterError
from common.date_time_presentation import date_time_presentation_for_request
from common.duration_presentation import duration_presentation_for_request
from common.layout import render_page
from common.notices import notify
from common.returns import UrlName
from games.batch_ledger import batch_act
from games.bulk_actions import BulkAction, bulk_action
from games.bulk_jobs import (
    Tally,
    announce,
    end_stale,
    library_batch,
    log_left_alone,
    request_stop,
    start_batch,
)
from games.bulk_parts import (
    BulkActionName,
    ChoiceValue,
    Control,
    Presentations,
    Refused,
    RefusedAct,
)
from games.events.dispatch import CommandRejected
from games.models import BulkBatch, UserLibrary
from games.reads.events import batch_events
from games.views.bulk_pages import ConfirmBatch, RefusedBatch
from games.views.returns import return_url
from timetracker.uuidv7 import UUIDv7ParseError, parse_uuidv7

logger = logging.getLogger("games")

#: What a selection states; the confirm POST.
#: One spelling: the line renders it, this route reads it.
STATEMENT_FIELD = SELECTION_STATEMENT_FIELD
#: The batch's identity, minted by the confirmation.
TOKEN_FIELD = "submission"
#: The confirmation's keys and refusals.
PROGRESS_FIELD = "progress"
#: Where an act's question is answered.
CHOICE_FIELD = "choice"

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

#: An Undo waits for its batch's end.
STILL_RUNNING = (
    "That batch is still running, so it cannot be taken back yet. Stop it "
    "or wait for it to end, then press Undo again."
)

UNDO_OF_AN_UNDO = (
    "An Undo cannot be taken back. To act again, select the rows and press "
    "the act. Nothing was changed."
)

#: An Undo with no rows left.
NOTHING_TO_UNDO = "Nothing from that batch is left to take back."


@dataclass(frozen=True, slots=True)
class SelectionStatement:
    """Keys, or a scope and exclusions."""

    #: None under "all": the scope names them.
    keys: tuple[uuid.UUID, ...] | None
    filter_json: str
    #: What the person was told it held.
    count: int
    excluded: frozenset[uuid.UUID]


class ProgressJson(TypedDict):
    """`PROGRESS_FIELD`'s wire shape."""

    rows: list[str]
    refused: int
    lost: int
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class Progress:
    """The confirmation's keys and refusals.

    Nothing has run yet, so nothing is done.
    """

    keys: tuple[uuid.UUID, ...]
    tally: Tally

    def as_json(self) -> str:
        return json.dumps(
            ProgressJson(
                rows=[str(key) for key in self.keys],
                refused=self.tally.refused,
                lost=self.tally.lost,
                reasons=list(self.tally.reasons),
            )
        )

    @classmethod
    def read(cls, posted: str) -> Progress:
        try:
            stated = json.loads(posted)
            keys = _keys(stated.get("rows"))
            return cls(
                keys=keys,
                tally=Tally(
                    lost=_count(stated.get("lost", 0)),
                    refused=_count(stated.get("refused", 0)),
                    reasons=tuple(str(one) for one in stated.get("reasons", [])),
                    total=len(keys),
                    left=len(keys),
                ),
            )
        except (ValueError, TypeError, AttributeError) as error:
            raise StatementUnreadable(f"progress is unreadable: {error}") from error


def _count(raw: Any) -> int:
    """A whole number, never a bool."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(f"{raw!r} is no count")
    return raw


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


type OfferedChoice = Node | RefusedAct | None


def _offered_choice(
    library: UserLibrary, action: BulkAction[Any], rows: Sequence[Any]
) -> OfferedChoice:
    """The act's question, if it asks one."""
    if action.choice is None:
        return None
    offered = action.choice.offer(library, rows, CHOICE_FIELD)
    if isinstance(offered, RefusedAct):
        return offered
    return offered.node if isinstance(offered, Control) else None


def _confirmation(
    request: HttpRequest,
    action: BulkAction[Any],
    *,
    rows: list[Any],
    refused: tuple[Refused, ...],
) -> HttpResponse:
    """What the act would do, and asks."""
    library = cast(User, request.user).library
    choice = _offered_choice(library, action, rows)
    if isinstance(choice, RefusedAct):
        return _act_refused(request, action, choice.sentence)
    #: The token is the batch's correlation id.
    token = uuid.uuid7()
    #: Named once: the batch carries only its rows.
    log_left_alone(action.name, refused, library.pk, token)
    keys = tuple(row.pk for row in rows)
    tally = Tally(total=len(keys), left=len(keys)).left_alone(refused)
    return _confirm_page(
        request,
        action,
        rows=rows,
        refused=refused,
        token=str(token),
        progress=Progress(keys, tally).as_json(),
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
    progress: Progress,
    sentence: str,
) -> HttpResponse:
    """Ask again, on the posted token."""
    library = cast(User, request.user).library
    resolution = action.resolve(library, list(progress.keys))
    log_left_alone(action.name, resolution.refused, library.pk, uuid.UUID(token))
    tally = progress.tally.left_alone(resolution.refused)
    choice = _offered_choice(library, action, resolution.rows)
    if isinstance(choice, RefusedAct):
        return _act_refused(request, action, choice.sentence)
    keys = tuple(row.pk for row in resolution.rows)
    return _confirm_page(
        request,
        action,
        rows=list(resolution.rows),
        refused=(),
        token=token,
        progress=Progress(keys, tally).as_json(),
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
        request, sentence, title=action.title.for_count(None), fallback=action.fallback
    )


@login_required
@require_POST
def run_bulk_action(request: HttpRequest, action: BulkActionName) -> HttpResponse:
    """Confirm the act, or start the batch."""
    declared = bulk_action(action)
    if declared is None:
        raise Http404("No such bulk action.")
    user = cast(User, request.user)

    token = request.POST.get(TOKEN_FIELD, "")
    if token:
        return _press(request, declared, token)

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
        request, declared, rows=list(resolution.rows), refused=resolution.refused
    )


def _press(request: HttpRequest, action: BulkAction[Any], token: str) -> HttpResponse:
    """Store the batch, then back."""
    user = cast(User, request.user)
    try:
        progress = Progress.read(request.POST.get(PROGRESS_FIELD, ""))
        correlation_id = parse_uuidv7(token)
    except (StatementUnreadable, UUIDv7ParseError) as unreadable:
        logger.warning("[bulk]: %s refused a progress: %s", action.name, unreadable)
        return _act_refused(request, action, UNREADABLE_STATEMENT)
    choice: ChoiceValue | None = None
    if action.choice is not None:
        #: The field is person-editable; settled once, here.
        try:
            choice = action.choice.settle(user.library, request.POST)
        except CommandRejected as refusal:
            logger.info(
                "[bulk]: %s refused a choice under %s: %s", action.name, token, refusal
            )
            return _reconfirmation(
                request,
                action,
                token=token,
                progress=progress,
                sentence=refusal.sentence or UNREADABLE_CHOICE,
            )
    origin = return_url(request, fallback=action.fallback)
    start_batch(
        user.library,
        action.name,
        token=correlation_id,
        keys=progress.keys,
        tally=progress.tally,
        choice=choice,
        origin=origin,
    )
    return redirect(origin)


def _act_of(library: UserLibrary, correlation_id: uuid.UUID) -> BulkAction[Any] | None:
    """Which act wrote this batch.

    A correlation nothing wrote, and one that is no batch, are not
    found. A name the table no longer holds answers None: that batch
    is real, and it is its Undo that is gone. Without events, the
    ledger names it.
    """
    first = batch_events(library, correlation_id).first()
    if first is None:
        return _ledger_act_of(library, correlation_id)
    stated = first.source_metadata.get("bulk", {})
    name = stated.get("action") if isinstance(stated, dict) else None
    if not isinstance(name, str):
        raise Http404("That act is no batch.")
    #: Nothing validates the name at the append.
    return bulk_action(name)


def _ledger_act_of(
    library: UserLibrary, correlation_id: uuid.UUID
) -> BulkAction[Any] | None:
    """The act the ledger names for this batch.

    Such an act writes no event, so nothing else names it.
    """
    name = batch_act(library, correlation_id)
    if name is None:
        logger.warning("[bulk]: %s names no event and no ledger row", correlation_id)
        raise Http404("No such batch.")
    return bulk_action(name)


@login_required
@require_POST
def undo_bulk_action(request: HttpRequest, correlation_id: uuid.UUID) -> HttpResponse:
    """One batch's inverse, as its own batch.

    Its own token and correlation id: sharing the act's would make a
    second press read its own appends as rows to take back.
    """
    user = cast(User, request.user)
    target = library_batch(user.library, correlation_id)
    if target is not None and target.undoes is not None:
        logger.info("[bulk]: %s is an Undo; refused its Undo", correlation_id)
        return _refused_page(
            request, UNDO_OF_AN_UNDO, title="Undo", fallback=UNDO_FALLBACK
        )
    #: Older batches have no row.
    declared = (
        _act_of(user.library, correlation_id)
        if target is None
        else bulk_action(target.action)
    )
    if declared is None:
        logger.warning("[bulk]: %s names an act nothing declares", correlation_id)
        return _refused_page(request, UNKNOWN_ACT, title="Undo", fallback=UNDO_FALLBACK)

    if target is not None and not target.is_terminal and not end_stale(target):
        return _refused_page(
            request, STILL_RUNNING, title="Undo", fallback=declared.fallback
        )
    origin = return_url(request, fallback=declared.fallback)
    if BulkBatch.objects.filter(
        library=user.library, undoes=correlation_id, state__in=BulkBatch.LIVE
    ).exists():
        return redirect(origin)
    if target is not None:
        announce(user.library, correlation_id)
    rows = declared.undo_rows.rows(user.library, correlation_id)
    if not rows:
        notify(request, NOTHING_TO_UNDO, level=messages.INFO)
        return redirect(origin)
    start_batch(
        user.library,
        declared.name,
        token=uuid.uuid7(),
        keys=rows,
        tally=Tally(total=len(rows), left=len(rows)),
        choice=None,
        origin=origin,
        undoes=correlation_id,
    )
    return redirect(origin)


@login_required
@require_POST
def stop_bulk_batch(request: HttpRequest, token: uuid.UUID) -> HttpResponse:
    """Stop between chunks; done rows stay."""
    library = cast(User, request.user).library
    if not request_stop(library, token):
        raise Http404("No such batch.")
    return redirect(return_url(request, fallback=UNDO_FALLBACK))
