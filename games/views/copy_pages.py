"""What the copy and purchase pages share."""

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from django import forms
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import BadRequest
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from common.components import (
    AddForm,
    FormFieldGroup,
    FormFieldPresentation,
    FormFields,
)
from common.layout import render_page
from common.notices import Undo, notify
from games.entry_forms import SubmissionKind, one_click_key
from games.events.idempotency import IdempotencyKey
from games.models import Game, LibraryEntry
from games.ownership import owned_or_404
from games.reads.entries import library_entries
from games.views.removal import AfterAct, said
from games.views.returns import return_url
from games.views.submission import SUBMISSION_FIELD
from games.writes.answers import CommandFailed


def game_page(request: HttpRequest, game: Game) -> str:
    """The origin, else Game detail."""
    return return_url(
        request, fallback="games:view_game", fallback_args=[game.pk, game.url_slug]
    )


def held_entry(request: HttpRequest, entry_id: uuid.UUID) -> LibraryEntry:
    library = cast(User, request.user).library
    return owned_or_404(
        library_entries(library).select_related(
            "player_game__game", "release__edition", "release__platform"
        ),
        library,
        id=entry_id,
    )


def cancel_url(request: HttpRequest, game: Callable[[], Game | None]) -> str:
    """Origin, else Game detail, else Library."""
    known = game()
    if known is None:
        return return_url(request, fallback="games:library")
    return game_page(request, known)


def form_page(
    request: HttpRequest,
    form: forms.Form,
    *,
    title: str,
    write: Callable[[], object],
    done: AfterAct,
    game: Callable[[], Game | None],
    groups: Sequence[FormFieldGroup] | None = None,
    presentations: Mapping[str, FormFieldPresentation] | None = None,
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
            messages.success(request, said(done))
            return redirect(cancel_url(request, game))
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=FormFields(form, groups=groups, presentations=presentations),
            submit_label=submit_label,
            cancel_url=cancel_url(request, game),
        ),
        title=title,
        status=status,
    )


def press_key(request: HttpRequest, kind: SubmissionKind) -> IdempotencyKey:
    """The press's key; missing is malformed."""
    try:
        token = uuid.UUID(request.POST.get(SUBMISSION_FIELD, ""))
    except ValueError:
        raise BadRequest("A one-click press carries its submission key.") from None
    return one_click_key(kind, token)


def one_click(
    request: HttpRequest,
    game: Game,
    *,
    write: Callable[[], str],
    done: AfterAct,
) -> HttpResponse:
    """Write, offer Undo, return; refusals show."""
    try:
        undo_url = write()
    except CommandFailed as failure:
        messages.error(request, failure.message)
    else:
        notify(request, said(done), level=messages.SUCCESS, action=Undo(undo_url))
    return redirect(game_page(request, game))
