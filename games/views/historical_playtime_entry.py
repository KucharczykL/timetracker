"""Record, restate, remove and restore historical playtime from a game."""

from functools import partial
from typing import cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from common.components import AddForm, FormFields, Fragment, ModuleScript
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from games.forms import HistoricalPlaytimeForm
from games.models import Game, HistoricalPlaytime
from games.ownership import owned_or_404
from games.reads.historical_playtime_records import readable_records
from games.views.removal import UndoOffer, confirm_and_apply, restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.historical_playtime import (
    record_historical_playtime,
    restate_historical_playtime,
)
from games.writes.historical_playtime import (
    remove_historical_playtime as remove_record,
)
from games.writes.historical_playtime import (
    restore_historical_playtime as restore_record,
)
from games.writes.playergame import new_correlation_id

#: Widgets render to text, so their Media never bubbles.
FORM_SCRIPTS = (
    "dist/elements/temporal-field.js",
    "dist/elements/search-select.js",
)


def _game_page(request: HttpRequest, game: Game) -> str:
    """Where a finished act returns without an origin."""
    return return_url(
        request, fallback="games:view_game", fallback_args=[game.pk, game.url_slug]
    )


def _library_record(request: HttpRequest, record_id: UUID) -> HistoricalPlaytime:
    library = cast(User, request.user).library
    return owned_or_404(readable_records(library), library, id=record_id)


def _any_library_record(request: HttpRequest, record_id: UUID) -> HistoricalPlaytime:
    """Removed or not: removal and its undo both reach one."""
    library = cast(User, request.user).library
    return owned_or_404(
        HistoricalPlaytime.objects.filter(library=library).select_related(
            "player_game__game"
        ),
        library,
        id=record_id,
    )


def _render_form(
    request: HttpRequest, form: HistoricalPlaytimeForm, title: str
) -> HttpResponse:
    return render_page(
        request,
        AddForm(form, request=request, submit_class="", fields=FormFields(form)),
        title=title,
        scripts=Fragment(*(ModuleScript(path) for path in FORM_SCRIPTS)),
    )


@login_required
def add_historical_playtime(request: HttpRequest, game_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    game = owned_or_404(Game.objects.tracked_by(library), library, id=game_id)
    form = HistoricalPlaytimeForm(
        request.POST or None,
        library=library,
        game=game,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        try:
            record_historical_playtime(
                user, form.statement(), correlation_id=new_correlation_id()
            )
        except CommandFailed as failure:
            messages.error(request, failure.message)
        else:
            messages.success(request, "Historical playtime recorded.")
            return redirect(_game_page(request, game))
    return _render_form(request, form, f"Add historical playtime - {game.name}")


@login_required
def edit_historical_playtime(request: HttpRequest, record_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    record = _library_record(request, record_id)
    game = record.player_game.game
    form = HistoricalPlaytimeForm(
        request.POST or None,
        library=user.library,
        game=game,
        presentation=date_time_presentation_for_request(request),
        record=record,
    )
    if form.is_valid():
        try:
            restate_historical_playtime(
                user, record, form.statement(), correlation_id=new_correlation_id()
            )
        except CommandFailed as failure:
            messages.error(request, failure.message)
        else:
            #: An unchanged statement is a success too.
            messages.success(request, "Historical playtime saved.")
            return redirect(_game_page(request, game))
    return _render_form(request, form, f"Edit historical playtime - {game.name}")


@login_required
def remove_historical_playtime(request: HttpRequest, record_id: UUID) -> HttpResponse:
    record = _any_library_record(request, record_id)
    game = record.player_game.game
    return confirm_and_apply(
        request,
        action=partial(
            remove_record,
            cast(User, request.user),
            record,
            correlation_id=new_correlation_id(),
        ),
        title="Remove historical playtime",
        message=f"Remove this historical playtime record of {game.name}?",
        confirm_label="Remove",
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
        undo=UndoOffer(
            "Historical playtime removed.",
            "games:restore_historical_playtime",
            [record.pk],
        ),
    )


@login_required
@require_POST
def restore_historical_playtime(request: HttpRequest, record_id: UUID) -> HttpResponse:
    record = _any_library_record(request, record_id)
    game = record.player_game.game
    return restore_and_return(
        request,
        action=partial(
            restore_record,
            cast(User, request.user),
            record,
            correlation_id=new_correlation_id(),
        ),
        restored="Historical playtime restored.",
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
    )
