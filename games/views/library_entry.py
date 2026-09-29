"""Add, edit, end, resume, remove and restore a copy; one page each."""

from collections.abc import Callable, Sequence
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

from common.components import AddForm, ControlButton, FormFieldGroup, FormFields
from common.components.core import Node
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from common.returns import action_url
from games.endpoints import ENTRY_ACCESS_END
from games.entry_forms import (
    EntryAddForm,
    EntryEditForm,
    EntryEndEditForm,
    EntryEndForm,
    EntryResumeForm,
    copy_groups,
)
from games.models import Game, LibraryEntry
from games.ownership import owned_or_404
from games.reads.endpoints import stated
from games.reads.entries import library_entries
from games.views.general import request_calendar_today
from games.views.library_cards import release_words
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


def _copy_title(act: str, entry: LibraryEntry) -> str:
    return f"{act} - {entry.player_game.game.name} ({release_words(entry)})"


def _form_page(
    request: HttpRequest,
    form: forms.Form,
    *,
    title: str,
    write: Callable[[], object],
    done: str,
    game: Callable[[], Game],
    groups: Sequence[FormFieldGroup] | None = None,
    additional: Node | str = "",
) -> HttpResponse:
    """Render the form; a valid POST writes and returns."""
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            write()
        except CommandFailed as failure:
            messages.error(request, failure.message)
            status = failure.status_code
        else:
            messages.success(request, done)
            return redirect(_game_page(request, game()))
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=FormFields(form, groups=groups),
            additional_row=additional,
        ),
        title=title,
        status=status,
    )


def _add(request: HttpRequest, game: Game | None) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    form = EntryAddForm(
        request.POST or None,
        library=library,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, library),
        game=game,
    )
    return _form_page(
        request,
        form,
        title="Add to library" if game is None else f"Add to library - {game.name}",
        write=lambda: record_entry(
            user,
            form.draft(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        done="Added to your library.",
        game=lambda: game or form.cleaned_data["game"],
        groups=copy_groups(form),
    )


@login_required
def add_library_entry(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    return _add(
        request, owned_or_404(Game.objects.visible_to(library), library, id=game_id)
    )


@login_required
def add_to_library(request: HttpRequest) -> HttpResponse:
    """Add, with a Game picker in front."""
    return _add(request, None)


@login_required
def edit_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    form = EntryEditForm(
        request.POST or None,
        entry=entry,
        library=user.library,
        presentation=date_time_presentation_for_request(request),
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
            correlation_id=new_correlation_id(),
        )

    return _form_page(
        request,
        form,
        title=_copy_title("Edit copy", entry),
        write=restate,
        done="Copy saved.",
        game=lambda: entry.player_game.game,
        groups=copy_groups(form),
    )


@login_required
def end_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    if stated(entry, ENTRY_ACCESS_END) is not None:
        #: An ended copy's end is edited, not stated again.
        return redirect(
            action_url(
                "games:edit_library_entry_end",
                entry.pk,
                origin=request.GET.get("origin"),
            )
        )
    form = EntryEndForm(
        request.POST or None,
        entry=entry,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, user.library),
    )
    return _form_page(
        request,
        form,
        title=_copy_title("End access", entry),
        write=lambda: end_entry_access(
            user,
            entry,
            form.statement(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        done="Access ended.",
        game=lambda: entry.player_game.game,
    )


@login_required
def edit_library_entry_end(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    if stated(entry, ENTRY_ACCESS_END) is None:
        #: A held copy has no end to edit; it may state one.
        return redirect(
            action_url(
                "games:end_library_entry", entry.pk, origin=request.GET.get("origin")
            )
        )
    form = EntryEndEditForm(
        request.POST or None,
        entry=entry,
        presentation=date_time_presentation_for_request(request),
    )
    return _form_page(
        request,
        form,
        title=_copy_title("Edit end of access", entry),
        write=lambda: restate_entry(
            user,
            entry,
            access_end=form.access_end(),
            correlation_id=new_correlation_id(),
        ),
        done="Access still held." if form.voids() else "End of access saved.",
        game=lambda: entry.player_game.game,
        additional=ControlButton(
            type="submit",
            name=EntryEndEditForm.VOID,
            value="1",
            color="gray",
            formnovalidate=True,
        )["It didn't end"],
    )


@login_required
def resume_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    form = EntryResumeForm(
        request.POST or None,
        entry=entry,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, user.library),
    )
    return _form_page(
        request,
        form,
        title=_copy_title("Resume access", entry),
        write=lambda: resume_entry_access(
            user,
            entry,
            form.statement(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        done="Access resumed.",
        game=lambda: entry.player_game.game,
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
