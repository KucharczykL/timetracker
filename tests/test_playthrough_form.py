"""The run form states a draft only."""

from zoneinfo import ZoneInfo

import pytest
from django import forms

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.forms import PlaythroughForm
from games.models import Game, PlayerGameStatus
from games.writes.playergame import new_correlation_id, record_facts, track_game

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def _completed_game(owned_user, owned_library) -> Game:
    """A game this library completed once."""
    game = Game.objects.create(library=owned_library, name="Tunic")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )
    return game


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def other_game(owned_library):
    return Game.objects.create(library=owned_library, name="Tunic")


@pytest.mark.django_db
def test_the_form_writes_no_row(user, game):
    form = PlaythroughForm(
        {"game": str(game.pk), "started": "2026-01-02", "ended": "", "note": "12h"},
        library=user.library,
        presentation=PRESENTATION,
    )

    assert form.is_valid(), form.errors
    assert not isinstance(form, forms.ModelForm)
    assert not hasattr(form, "save")
    assert form.cleaned_data["note"] == "12h"
    assert form.cleaned_data["ended"] is None


@pytest.mark.django_db
def test_a_locked_game_refuses_a_different_one(user, game, other_game):
    form = PlaythroughForm(
        {"game": str(other_game.pk), "started": "", "ended": "", "note": ""},
        library=user.library,
        presentation=PRESENTATION,
        locked_game=game,
    )

    assert not form.is_valid()
    assert "game" in form.errors


@pytest.mark.django_db
def test_a_long_note_is_accepted(user, game):
    """The 255 came from the legacy column.

    `Playthrough.note` is a TextField, so the form that
    states it caps nothing.
    """
    form = PlaythroughForm(
        {"game": str(game.pk), "started": "", "ended": "", "note": "x" * 4096},
        library=user.library,
        presentation=PRESENTATION,
    )

    assert form.is_valid()
    assert form.cleaned_data["note"] == "x" * 4096


@pytest.mark.django_db
def test_both_boxes_render_checked_for_an_untracked_game(user, game):
    form = PlaythroughForm(
        library=user.library, presentation=PRESENTATION, offered_game=game
    )

    assert form.fields["also_mark_played"].label == "Also mark this game Played"
    assert form.fields["also_mark_played"].initial is True
    assert form.fields["also_mark_completed"].label == "Also mark this game Completed"
    assert form.fields["also_mark_completed"].initial is True
    assert "mark_as_finished" not in form.fields


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_the_add_form_offers_the_played_box_before_a_game(owned_library):
    """No game states no status, so nothing rules the box out.

    clean() asks again against the game the submit names.
    """
    form = PlaythroughForm(
        library=owned_library, presentation=PRESENTATION, offered_game=None
    )

    assert "also_mark_played" in form.fields


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_a_completed_game_renders_no_played_box(owned_user, owned_library):
    game = _completed_game(owned_user, owned_library)

    form = PlaythroughForm(
        library=owned_library, presentation=PRESENTATION, offered_game=game
    )

    assert "also_mark_played" not in form.fields
    assert "also_mark_completed" in form.fields


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_a_posted_played_box_is_dropped_for_a_completed_game(owned_user, owned_library):
    """The Add form renders it unbound."""
    game = _completed_game(owned_user, owned_library)

    form = PlaythroughForm(
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "",
            "note": "",
            "also_mark_played": "on",
            "also_mark_completed": "on",
        },
        library=owned_library,
        presentation=PRESENTATION,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["also_mark_played"] is False
    assert form.cleaned_data["also_mark_completed"] is True


@pytest.mark.django_db
def test_an_unticked_box_cleans_to_false(user, game):
    form = PlaythroughForm(
        {"game": str(game.pk), "started": "", "ended": "", "note": ""},
        library=user.library,
        presentation=PRESENTATION,
        offered_game=game,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["also_mark_played"] is False
    assert form.cleaned_data["also_mark_completed"] is False
