"""Stating how many times a game was played."""

import uuid
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import AddForm
from common.layout import render_page
from common.notices import Undo, notify
from games.forms import PrimitiveWidgetsMixin
from games.models import Game
from games.ownership import owned_or_404
from games.reads.playthrough_runs import completed_run_count, tracked_game
from games.views.removal import restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.playthrough_count import state_times_played, undo_times_played


class TimesPlayedForm(PrimitiveWidgetsMixin, forms.Form):
    count = forms.IntegerField(
        min_value=0,
        label="Times played through",
        help_text="Adds or removes playthroughs with no days stated.",
    )
    #: Rendered once per page; a repeat replays.
    submission = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid7)


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def _tracked_game(request: HttpRequest, game_id: UUID) -> Game:
    library = cast(User, request.user).library
    return owned_or_404(Game.objects.tracked_by(library), library, id=game_id)


def _game_page(request: HttpRequest, game: Game) -> str:
    return return_url(
        request, fallback="games:view_game", fallback_args=[game.pk, game.url_slug]
    )


@login_required
def state_times_played_view(request: HttpRequest, game_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    game = _tracked_game(request, game_id)
    current = completed_run_count(user.library, tracked_game(user.library, game))
    form = TimesPlayedForm(request.POST or None, initial={"count": current})
    status = 200
    if form.is_valid():
        try:
            answer = state_times_played(
                user,
                game,
                form.cleaned_data["count"],
                submission=form.cleaned_data["submission"],
            )
        except CommandFailed as failure:
            form.add_error("count", failure.message)
            status = failure.status_code
        else:
            if answer.changed:
                notify(
                    request,
                    f"Played {_times(answer.stated)}.",
                    level=messages.SUCCESS,
                    action=Undo(
                        reverse(
                            "games:undo_times_played",
                            args=[game.pk, answer.statement, answer.stated],
                        )
                    ),
                )
            else:
                messages.info(request, f"Already played {_times(answer.stated)}.")
            return redirect(_game_page(request, game))
    return render_page(
        request,
        AddForm(form, request=request),
        title=f"Times played - {game.name}",
        status=status,
        width="form",
    )


@login_required
@require_POST
def undo_times_played_view(
    request: HttpRequest, game_id: UUID, statement: UUID, stated: int
) -> HttpResponse:
    user = cast(User, request.user)
    game = _tracked_game(request, game_id)
    return restore_and_return(
        request,
        action=lambda: undo_times_played(user, game, statement, stated),
        restored="Times played undone.",
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
    )
