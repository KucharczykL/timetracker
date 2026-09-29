"""Add, edit, end, resume, remove and restore a copy."""

from collections.abc import Callable
from functools import partial
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from common.date_time_presentation import date_time_presentation_for_request
from games.entry_forms import (
    EntryAddForm,
    EntryEditForm,
    EntryEndForm,
    EntryResumeForm,
)
from games.models import Game, LibraryEntry
from games.ownership import owned_or_404
from games.reads.entries import library_entries
from games.views.game import game_detail_page
from games.views.general import request_calendar_today
from games.views.library_cards import (
    ADD_PREFIX,
    LibraryAct,
    OpenForm,
    act_prefix,
    open_url,
    release_words,
)
from games.views.removal import confirm_and_remove, restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.libraryentry import (
    end_entry_access,
    record_entry,
    remove_entry,
    restate_entry,
    restore_entry,
    resume_entry_access,
)
from games.writes.playergame import new_correlation_id


def _game_page(request: HttpRequest, game: Game) -> str:
    """The origin, else Game detail."""
    return return_url(
        request, fallback="games:view_game", fallback_args=[game.pk, game.url_slug]
    )


def _held_entry(request: HttpRequest, entry_id: UUID) -> LibraryEntry:
    library = cast(User, request.user).library
    return owned_or_404(
        library_entries(library).select_related(
            "player_game__game", "release__edition", "release__platform"
        ),
        library,
        id=entry_id,
    )


def _any_library_entry(request: HttpRequest, entry_id: UUID) -> LibraryEntry:
    """Removed or not, for remove and restore."""
    library = cast(User, request.user).library
    return owned_or_404(
        LibraryEntry.objects.filter(library=library).select_related(
            "player_game__game", "release__edition", "release__platform"
        ),
        library,
        id=entry_id,
    )


def _act(
    request: HttpRequest,
    game: Game,
    open_form: OpenForm,
    form: forms.Form,
    write: Callable[[], object],
    done: str,
) -> HttpResponse:
    """Write a valid form; else Game detail with it open."""
    if not form.is_valid():
        return game_detail_page(request, _detail_game(request, game), open_form)
    try:
        write()
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return game_detail_page(
            request,
            _detail_game(request, game),
            open_form,
            status=failure.status_code,
        )
    messages.success(request, done)
    return redirect(_game_page(request, game))


def _detail_game(request: HttpRequest, game: Game) -> Game:
    """The Game as Game detail reads it."""
    library = cast(User, request.user).library
    return owned_or_404(Game.objects.tracked_by(library), library, id=game.pk)


def _opened(game: Game, act: LibraryAct, entry_id: UUID | None = None) -> HttpResponse:
    """A GET lands on Game detail with that form open."""
    return redirect(open_url(game, act, entry_id))


@login_required
def add_library_entry(request: HttpRequest, game_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    game = owned_or_404(Game.objects.visible_to(library), library, id=game_id)
    if request.method != "POST":
        return _opened(game, "add")
    form = EntryAddForm(
        request.POST,
        library=library,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, library),
        game=game,
        prefix=ADD_PREFIX,
    )
    return _act(
        request,
        game,
        OpenForm("add", None, form),
        form,
        lambda: record_entry(
            user,
            form.draft(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        "Added to your library.",
    )


@login_required
def edit_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    game = entry.player_game.game
    if request.method != "POST":
        return _opened(game, "edit", entry.pk)
    form = EntryEditForm(
        request.POST,
        entry=entry,
        library=user.library,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, user.library),
        prefix=act_prefix(entry.pk, "edit"),
    )

    def restate() -> bool:
        cleaned = form.cleaned_data
        return restate_entry(
            user,
            entry,
            access=cleaned["access"],
            format=cleaned["format"],
            note=cleaned["note"],
            release_id=cleaned["release"].pk,
            acquired=form.acquired(),
            access_end=form.access_end(),
            correlation_id=new_correlation_id(),
        )

    return _act(
        request, game, OpenForm("edit", entry.pk, form), form, restate, "Copy saved."
    )


@login_required
def end_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    game = entry.player_game.game
    if request.method != "POST":
        return _opened(game, "end", entry.pk)
    form = EntryEndForm(
        request.POST,
        entry=entry,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, user.library),
        prefix=act_prefix(entry.pk, "end"),
    )
    return _act(
        request,
        game,
        OpenForm("end", entry.pk, form),
        form,
        lambda: end_entry_access(
            user,
            entry,
            form.statement(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        "Access ended.",
    )


@login_required
def resume_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    game = entry.player_game.game
    if request.method != "POST":
        return _opened(game, "resume", entry.pk)
    form = EntryResumeForm(
        request.POST,
        entry=entry,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, user.library),
        prefix=act_prefix(entry.pk, "resume"),
    )
    return _act(
        request,
        game,
        OpenForm("resume", entry.pk, form),
        form,
        lambda: resume_entry_access(
            user,
            entry,
            form.statement(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        "Access resumed.",
    )


@login_required
def remove_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    entry = _any_library_entry(request, entry_id)
    game = entry.player_game.game
    return confirm_and_remove(
        request,
        entry,
        title="Remove copy",
        message=f"Remove this {release_words(entry)} copy of {game.name}?",
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
        action=partial(
            remove_entry,
            cast(User, request.user),
            entry,
            correlation_id=new_correlation_id(),
        ),
        removed="Copy removed.",
        undo="games:restore_library_entry",
    )


@login_required
@require_POST
def restore_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    entry = _any_library_entry(request, entry_id)
    game = entry.player_game.game
    return restore_and_return(
        request,
        action=partial(
            restore_entry,
            cast(User, request.user),
            entry,
            correlation_id=new_correlation_id(),
        ),
        restored="Copy restored.",
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
    )
