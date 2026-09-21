"""The session form derives one timing statement from what is filled."""

import html
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from session_rows import run_id, session_row
from stated_runs import another_run

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.playersession import (
    CorrectedTiming,
    DurationOnlyTiming,
    TimedTiming,
)
from games.forms import (
    DAY_BESIDE_AN_INSTANT,
    DAY_WITHOUT_DURATION,
    END_BEFORE_START,
    END_WITHOUT_START,
    NEITHER_START_NOR_DAY,
    START_WITH_DURATION_ALONE,
    SessionForm,
)
from games.models import Game

pytestmark = pytest.mark.django_db

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("Europe/Prague")
)
START = "2026-07-01T21:00:00+09:00"
END = "2026-07-01T22:30:00+09:00"
START_INSTANT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
END_INSTANT = datetime(2026, 7, 1, 13, 30, tzinfo=UTC)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Hades")


def _form(library, game, **fields) -> SessionForm:
    data = {
        "game": str(game.pk),
        "playthrough": run_id(library, game),
        "started_at": "",
        "started_at_zone": "",
        "ended_at": "",
        "ended_at_zone": "",
        "day": "",
        "duration": "",
        "device": "",
        "note": "",
    }
    data.update(fields)
    return SessionForm(data=data, library=library, presentation=PRESENTATION)


def test_a_start_alone_is_a_running_timed_session(owned_library, game):
    form = _form(owned_library, game, started_at=START, started_at_zone="Asia/Tokyo")

    assert form.is_valid(), form.errors
    assert form.timing_statement("Europe/Prague") == TimedTiming(
        started_at=START_INSTANT, day_zone="Europe/Prague", started_at_zone="Asia/Tokyo"
    )


def test_a_start_and_an_end_are_a_finished_timed_session(owned_library, game):
    form = _form(owned_library, game, started_at=START, ended_at=END)

    assert form.is_valid(), form.errors
    assert form.timing_statement("UTC") == TimedTiming(
        started_at=START_INSTANT, day_zone="UTC", ended_at=END_INSTANT
    )


def test_both_instants_and_a_duration_are_a_corrected_session(owned_library, game):
    form = _form(
        owned_library, game, started_at=START, ended_at=END, duration="02:00:00"
    )

    assert form.is_valid(), form.errors
    assert form.timing_statement("UTC") == CorrectedTiming(
        started_at=START_INSTANT,
        ended_at=END_INSTANT,
        duration=timedelta(hours=2),
        day_zone="UTC",
    )


def test_a_day_and_a_duration_alone_are_a_duration_only_session(owned_library, game):
    form = _form(owned_library, game, day="2026-07-01", duration="01:30:00")

    assert form.is_valid(), form.errors
    assert form.timing_statement("UTC") == DurationOnlyTiming(
        day=date(2026, 7, 1), duration=timedelta(hours=1, minutes=30)
    )


def test_a_start_with_a_duration_and_no_end_is_refused_on_the_duration(
    owned_library, game
):
    form = _form(owned_library, game, started_at=START, duration="01:00:00")

    assert not form.is_valid()
    assert form.errors["duration"] == [START_WITH_DURATION_ALONE]


def test_a_day_beside_a_start_is_refused_on_the_day(owned_library, game):
    form = _form(owned_library, game, started_at=START, day="2026-07-01")

    assert not form.is_valid()
    assert form.errors["day"] == [DAY_BESIDE_AN_INSTANT]


def test_nothing_filled_is_refused_on_the_start(owned_library, game):
    form = _form(owned_library, game)

    assert not form.is_valid()
    assert form.errors["started_at"] == [NEITHER_START_NOR_DAY]


def test_a_day_without_a_duration_is_refused_on_the_duration(owned_library, game):
    form = _form(owned_library, game, day="2026-07-01")

    assert not form.is_valid()
    assert form.errors["duration"] == [DAY_WITHOUT_DURATION]


def test_an_end_without_a_start_is_refused_on_the_start(owned_library, game):
    form = _form(owned_library, game, ended_at=END)

    assert not form.is_valid()
    assert form.errors["started_at"] == [END_WITHOUT_START]


def test_an_end_before_the_start_is_refused_on_the_end(owned_library, game):
    form = _form(owned_library, game, started_at=END, ended_at=START)

    assert not form.is_valid()
    assert form.errors["ended_at"] == [END_BEFORE_START]


def test_a_run_of_another_game_is_refused_on_the_run(owned_library, game):
    other = Game.objects.create(library=owned_library, name="Celeste")
    form = _form(
        owned_library, game, started_at=START, playthrough=run_id(owned_library, other)
    )

    assert not form.is_valid()
    assert "playthrough" in form.errors


def test_the_edit_form_seeds_a_duration_only_row_by_its_mode(owned_library, game):
    row = session_row(
        game,
        started_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
        duration_manual=timedelta(minutes=45),
    )

    form = SessionForm(instance=row, library=owned_library, presentation=PRESENTATION)

    assert form.initial["day"] == date(2026, 7, 1)
    assert form.initial["duration"] == timedelta(minutes=45)
    assert form.initial["started_at"] is None
    assert form.initial["playthrough"] == row.playthrough_id
    assert form.initial["game"] == game


def test_the_picker_lists_the_known_games_runs_by_display_name(owned_library, game):
    form = SessionForm(
        initial={"game": game}, library=owned_library, presentation=PRESENTATION
    )

    rendered = str(form["playthrough"])
    assert 'search-url="/api/playthrough/search"' in rendered
    assert 'create-url="/api/playthrough/"' in rendered
    assert '"game_id": {"field": "game"}' in html.unescape(rendered)
    assert str(run_id(owned_library, game)) not in rendered


def test_the_picker_offers_the_run_the_form_holds(owned_library, game):
    """A bound render labels the held run through the numbering."""
    held = run_id(owned_library, game)
    form = SessionForm(
        initial={"game": game, "playthrough": held},
        library=owned_library,
        presentation=PRESENTATION,
    )

    rendered = str(form["playthrough"])
    assert str(held) in rendered
    assert "Playthrough 1" in rendered


def test_only_the_run_picker_holds_a_sole_option(owned_library, game):
    """A required field takes the one run; an optional one waits."""
    form = SessionForm(
        initial={"game": game}, library=owned_library, presentation=PRESENTATION
    )

    assert 'commit-sole-option="true"' in str(form["playthrough"])
    assert 'commit-sole-option="false"' in str(form["device"])


def test_the_device_picker_offers_to_make_a_device(owned_library):
    """A device the library lacks is made from the picker."""
    form = SessionForm(library=owned_library, presentation=PRESENTATION)

    assert 'create-url="/api/devices/"' in str(form["device"])


@pytest.mark.django_db(transaction=True)
def test_the_page_seeds_a_sole_run_and_nothing_else(client, owned_user):
    """The seed states the rule the picker states.

    The picker holds the one run an answer states, so a page
    that seeds the field holds one run and no more: choosing
    among several for somebody is a choice they must notice
    to undo.
    """
    library = owned_user.library
    game = Game.objects.create(library=library, name="Tunic")
    born = run_id(library, game)
    client.force_login(owned_user)
    url = reverse("games:add_session_for_game", args=[game.pk])

    assert born in client.get(url).content.decode()

    later = another_run(owned_user, game)
    rendered = client.get(url).content.decode()
    assert born not in rendered
    #: Nor the latest of them, which is the seed this replaced.
    assert str(later.pk) not in rendered
