"""Every act on one copy."""

import uuid
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, cast
from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import BadRequest
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import AddForm, FormFieldGroup, FormFields
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from common.notices import Undo, notify
from common.returns import action_url
from games.catalog_release import SHARED_GAME_RELEASE
from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import EntryStatement
from games.end_ways import EndWay
from games.endpoints import ENTRY_ACCESS_END
from games.entry_forms import (
    EntryAddForm,
    EntryEditForm,
    EntryEndEditForm,
    EntryEndForm,
    EntryResumeForm,
    SubmissionAct,
    copy_groups,
    one_click_key,
)
from games.events.dispatch import CommandResult
from games.events.idempotency import IdempotencyKey
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS
from games.events.vocabulary import EventSpec
from games.models import (
    Game,
    LibraryEntry,
    LibraryEvent,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.reads.endpoints import stated
from games.reads.entries import (
    EventSequence,
    latest_end_act,
    library_entries,
    taken_back_end,
)
from games.reads.releases import game_releases
from games.views.entry_menu import SUBMISSION_FIELD
from games.views.general import request_calendar_today
from games.views.library_cards import release_words
from games.views.removal import confirm_and_remove, restore_and_return
from games.views.returns import return_url
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.libraryentry import (
    end_entry_access,
    record_entry,
    remove_entry,
    restate_entry,
    restore_entry,
    resume_entry_access,
)
from games.writes.playergame import new_correlation_id
from timetracker.temporal import TemporalValue


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


def _cancel_url(request: HttpRequest, game: Callable[[], Game | None]) -> str:
    """Origin, else Game detail, else Library."""
    known = game()
    if known is None:
        return return_url(request, fallback="games:library")
    return _game_page(request, known)


def _copy_title(act: str, entry: LibraryEntry) -> str:
    return f"{act} - {entry.player_game.game.name} ({release_words(entry)})"


def _form_page(
    request: HttpRequest,
    form: forms.Form,
    *,
    title: str,
    write: Callable[[], object],
    done: str,
    game: Callable[[], Game | None],
    groups: Sequence[FormFieldGroup] | None = None,
    submit_label: str = "Save",
) -> HttpResponse:
    """Render; a valid POST writes and returns."""
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            write()
        except CommandFailed as failure:
            messages.error(request, failure.message)
            status = failure.status_code
        else:
            messages.success(request, done)
            return redirect(_cancel_url(request, game))
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=FormFields(form, groups=groups),
            submit_label=submit_label,
            cancel_url=_cancel_url(request, game),
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
        game=lambda: game or getattr(form, "cleaned_data", {}).get("game"),
        groups=copy_groups(form),
        submit_label="Add to library",
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
        title=_copy_title("Edit details", entry),
        write=restate,
        done="Saved.",
        game=lambda: entry.player_game.game,
        groups=copy_groups(form),
    )


@login_required
def end_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    if stated(entry, ENTRY_ACCESS_END) is not None:
        #: An ended copy's end is edited.
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
        title=_copy_title("I no longer have it", entry),
        write=lambda: end_entry_access(
            user,
            entry,
            form.statement(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        done="Marked as no longer yours.",
        game=lambda: entry.player_game.game,
    )


@login_required
def edit_library_entry_end(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    if stated(entry, ENTRY_ACCESS_END) is None:
        #: A held copy has no end to edit.
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
        title=_copy_title("Edit how it left", entry),
        write=lambda: restate_entry(
            user,
            entry,
            access_end=form.access_end(),
            correlation_id=new_correlation_id(),
        ),
        done="Saved.",
        game=lambda: entry.player_game.game,
    )


@login_required
def resume_library_entry(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    if stated(entry, ENTRY_ACCESS_END) is None:
        #: A held copy has nothing to resume.
        return redirect(
            action_url(
                "games:end_library_entry", entry.pk, origin=request.GET.get("origin")
            )
        )
    form = EntryResumeForm(
        request.POST or None,
        entry=entry,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, user.library),
    )
    return _form_page(
        request,
        form,
        title=_copy_title("I have it again", entry),
        write=lambda: resume_entry_access(
            user,
            entry,
            form.statement(),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        done="Marked as yours again.",
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


# --- one click, then Undo ----------------------------------------------------

UNDO_OVERTAKEN = "This copy changed since; nothing was undone."
NO_RELEASE = "This game has no version yet; add one on the Add page."


def _one_click_key(request: HttpRequest, act: SubmissionAct) -> IdempotencyKey:
    """The press's key; missing is malformed."""
    try:
        token = uuid.UUID(request.POST.get(SUBMISSION_FIELD, ""))
    except ValueError:
        raise BadRequest("A one-click press carries its submission key.") from None
    return one_click_key(act, token)


def _one_click(
    request: HttpRequest,
    game: Game,
    *,
    write: Callable[[], str],
    done: str,
) -> HttpResponse:
    """Write, offer Undo, return; refusals show."""
    try:
        undo_url = write()
    except CommandFailed as failure:
        messages.error(request, failure.message)
    else:
        notify(request, done, level=messages.SUCCESS, action=Undo(undo_url))
    return redirect(_game_page(request, game))


def _appended_at(result: CommandResult) -> EventSequence:
    """The one end event this press wrote."""
    if result.sequences is None:
        raise CommandFailed(UNDO_OVERTAKEN, CONFLICT_STATUS)
    return result.sequences.last


def _still_latest(
    library: UserLibrary,
    entry: LibraryEntry,
    spec: EventSpec[Any],
    sequence: EventSequence,
) -> LibraryEvent:
    """Refuses an Undo a later act overtook."""
    latest = latest_end_act(library, entry.pk)
    if (
        latest is None
        or latest.sequence != sequence
        or latest.event_type != spec.event_type
    ):
        raise CommandFailed(UNDO_OVERTAKEN, CONFLICT_STATUS)
    return latest


@login_required
@require_POST
def add_library_entry_now(request: HttpRequest, game_id: UUID) -> HttpResponse:
    """The game's default version, Owned, Digital, today."""
    user = cast(User, request.user)
    library = user.library
    game = owned_or_404(Game.objects.visible_to(library), library, id=game_id)
    key = _one_click_key(request, "add")
    release = game_releases(library, game).first()
    if release is None:
        messages.error(
            request,
            NO_RELEASE if game.library_id == library.pk else SHARED_GAME_RELEASE,
        )
        return redirect(_game_page(request, game))
    today = TemporalValue.from_day(request_calendar_today(request, library))

    def add() -> str:
        entry_id = record_entry(
            user,
            EntryStatement(
                release_id=release.pk,
                access="owned",
                format="digital",
                note="",
                acquired=ActStatement(today, ""),
            ),
            correlation_id=new_correlation_id(),
            idempotency_key=key,
        ).entry_id
        return reverse("games:remove_library_entry", args=[entry_id])

    return _one_click(request, game, write=add, done="Added to your library.")


@login_required
@require_POST
def end_library_entry_now(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Gone for a reason nobody stated, today."""
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    key = _one_click_key(request, "end")
    today = TemporalValue.from_day(request_calendar_today(request, user.library))

    def end() -> str:
        result = end_entry_access(
            user,
            entry,
            WayActStatement(today, EndWay.UNSTATED, ""),
            correlation_id=new_correlation_id(),
            idempotency_key=key,
        )
        return reverse(
            "games:undo_library_entry_end", args=[entry.pk, _appended_at(result)]
        )

    return _one_click(
        request, entry.player_game.game, write=end, done="Marked as no longer yours."
    )


@login_required
@require_POST
def resume_library_entry_now(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Had again, today."""
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    key = _one_click_key(request, "resume")
    today = TemporalValue.from_day(request_calendar_today(request, user.library))

    def resume() -> str:
        result = resume_entry_access(
            user,
            entry,
            ActStatement(today, ""),
            correlation_id=new_correlation_id(),
            idempotency_key=key,
        )
        return reverse(
            "games:undo_library_entry_resume", args=[entry.pk, _appended_at(result)]
        )

    return _one_click(
        request, entry.player_game.game, write=resume, done="Marked as yours again."
    )


@login_required
@require_POST
def undo_library_entry_end(
    request: HttpRequest, entry_id: UUID, sequence: EventSequence
) -> HttpResponse:
    """Void this press's end, if still latest."""
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    game = entry.player_game.game

    def void() -> None:
        _still_latest(user.library, entry, ENTRY_ACCESS_END_EVENTS.stated, sequence)
        restate_entry(user, entry, access_end=None, correlation_id=new_correlation_id())

    return restore_and_return(
        request,
        action=void,
        restored="Marked as yours again.",
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
    )


@login_required
@require_POST
def undo_library_entry_resume(
    request: HttpRequest, entry_id: UUID, sequence: EventSequence
) -> HttpResponse:
    """Restate the end this resume took back."""
    user = cast(User, request.user)
    entry = _held_entry(request, entry_id)
    game = entry.player_game.game

    def end_again() -> None:
        resumed = _still_latest(
            user.library, entry, ENTRY_ACCESS_END_EVENTS.resumed, sequence
        )
        taken_back = taken_back_end(user.library, entry.pk, resumed_at=resumed.sequence)
        if taken_back is None:
            raise CommandFailed(UNDO_OVERTAKEN, CONFLICT_STATUS)
        end_entry_access(user, entry, taken_back, correlation_id=new_correlation_id())

    return restore_and_return(
        request,
        action=end_again,
        restored="Marked as no longer yours.",
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
    )
