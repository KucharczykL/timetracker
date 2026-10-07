"""Stating how many times a game was played."""

from typing import cast
from uuid import UUID, uuid7

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import AddForm
from common.layout import render_page
from common.notices import Undo, notify
from games.commands.playthrough_count import TimesPlayedCount
from games.events.dispatch import CommandOutcome
from games.forms import PrimitiveWidgetsMixin
from games.models import Game
from games.ownership import owned_or_404
from games.reads.playthrough_runs import completed_run_count, tracked_game
from games.views.removal import restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.playthrough_count import (
    TimesPlayed,
    UndoneCount,
    state_times_played,
    undo_times_played,
)


class TimesPlayedForm(PrimitiveWidgetsMixin, forms.Form):
    count = forms.IntegerField(
        min_value=0,
        label="Times played through",
        help_text="Adds or removes playthroughs with no days stated.",
    )
    #: Rendered once per page; a repeat replays.
    submission = forms.UUIDField(widget=forms.HiddenInput, initial=uuid7)


def _times(count: TimesPlayedCount) -> str:
    return "once" if count == 1 else f"{count} times"


def _game_page(request: HttpRequest, game: Game) -> str:
    return return_url(
        request, fallback="games:view_game", fallback_args=[game.pk, game.url_slug]
    )


def _said(request: HttpRequest, game: Game, answer: TimesPlayed) -> None:
    if answer.undoable is not None:
        notify(
            request,
            f"Played {_times(answer.stated)}.",
            level=messages.SUCCESS,
            action=Undo(
                reverse(
                    "games:undo_times_played",
                    args=[game.pk, answer.undoable, answer.stated],
                )
            ),
        )
    elif answer.outcome is CommandOutcome.REPLAYED:
        messages.info(request, "That was already saved.")
    else:
        messages.info(request, f"Already played {_times(answer.stated)}.")


@login_required
def state_times_played_view(request: HttpRequest, game_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    game = owned_or_404(Game.objects.tracked_by(library), library, id=game_id)
    current = completed_run_count(library, tracked_game(library, game))
    #: Mutable, so a refusal can rekey it.
    posted = request.POST.copy()
    form = TimesPlayedForm(
        posted if request.method == "POST" else None, initial={"count": current}
    )
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
            #: The old key may be spent.
            posted["submission"] = str(uuid7())
            status = failure.status_code
        else:
            _said(request, game, answer)
            return redirect(_game_page(request, game))
    return render_page(
        request,
        AddForm(form, request=request),
        title=f"Times played - {game.name}",
        status=status,
        width="form",
    )


def _undone(answers: list[UndoneCount]) -> str:
    if answers and answers[0].status_kept:
        return "Times played undone. The status you set since was kept."
    return "Times played undone."


@login_required
@require_POST
def undo_times_played_view(
    request: HttpRequest, game_id: UUID, statement_id: UUID, stated: TimesPlayedCount
) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    #: Removed too: the command says why.
    game = owned_or_404(
        Game.objects.filter(Q(library__isnull=True) | Q(library=library)),
        library,
        id=game_id,
    )
    answers: list[UndoneCount] = []

    def undo() -> None:
        answers.append(undo_times_played(user, game, statement_id, stated))

    return restore_and_return(
        request,
        action=undo,
        restored=lambda: _undone(answers),
        fallback="games:view_game",
        fallback_args=[game.pk, game.url_slug],
    )
