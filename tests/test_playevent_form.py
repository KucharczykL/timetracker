"""The run form states a draft, and writes nothing itself."""

from zoneinfo import ZoneInfo

import pytest
from django import forms

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.forms import PlayEventForm
from games.models import Game

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


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
    form = PlayEventForm(
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
    form = PlayEventForm(
        {"game": str(other_game.pk), "started": "", "ended": "", "note": ""},
        library=user.library,
        presentation=PRESENTATION,
        locked_game=game,
    )

    assert not form.is_valid()
    assert "game" in form.errors


@pytest.mark.django_db
def test_a_note_longer_than_the_column_is_refused(user, game):
    form = PlayEventForm(
        {"game": str(game.pk), "started": "", "ended": "", "note": "x" * 256},
        library=user.library,
        presentation=PRESENTATION,
    )

    assert not form.is_valid()
    assert "note" in form.errors
