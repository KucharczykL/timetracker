"""Every playtime figure, compared across the two session tables."""

from datetime import UTC, date, datetime, time, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from session_rows import TWIN_ZONE, corrected_twin, duration_only_twin, timed_twin

from games.models import Game, Platform, PlayerSession, Session
from games.reads.playtime_parity import differing, playtime_figures

pytestmark = pytest.mark.django_db

ZERO = timedelta(0)


@pytest.fixture
def game(owned_library) -> Game:
    platform = Platform.objects.create(name="PC", icon="pc")
    return Game.objects.create(
        library=owned_library, name="Outer Wilds", platform=platform
    )


def prague(hour: int, day: date) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=TWIN_ZONE)


def test_every_figure_agrees_for_a_twin_of_each_mode(owned_library, game):
    day = date(2026, 3, 5)
    timed_twin(owned_library, game, prague(10, day), prague(12, day))
    duration_only_twin(owned_library, game, date(2025, 11, 2), timedelta(minutes=90))
    corrected_twin(
        owned_library,
        game,
        prague(20, day),
        prague(21, day),
        timedelta(minutes=30),
    )

    figures = playtime_figures(owned_library, TWIN_ZONE)

    assert differing(figures) == []
    scopes = {figure.scope for figure in figures}
    assert {"all-time", "year 2025", "year 2026", "month 2026-03"} <= scopes


def test_a_day_across_a_year_boundary_is_named(owned_library, game):
    twin = duration_only_twin(
        owned_library, game, date(2025, 12, 31), timedelta(hours=1)
    )
    PlayerSession.objects.filter(pk=twin.projection.pk).update(
        stated_day=date(2026, 1, 1)
    )

    scopes = {
        figure.scope for figure in differing(playtime_figures(owned_library, TWIN_ZONE))
    }

    assert {"year 2025", "year 2026"} <= scopes
    assert "all-time" not in scopes


def test_the_empty_projection_differs_on_every_non_zero_figure(owned_library, game):
    start = prague(10, date(2026, 3, 5))
    Session.objects.create(
        game=game, timestamp_start=start, timestamp_end=start + timedelta(hours=2)
    )

    figures = playtime_figures(owned_library, TWIN_ZONE)
    non_zero = [figure for figure in figures if figure.legacy != ZERO]

    assert non_zero
    assert all(figure.projection == ZERO for figure in figures)
    assert differing(figures) == non_zero


def test_the_command_exits_non_zero_on_a_difference(owned_user, owned_library, game):
    start = prague(10, date(2026, 3, 5))
    Session.objects.create(
        game=game, timestamp_start=start, timestamp_end=start + timedelta(hours=2)
    )
    output = StringIO()

    with pytest.raises(CommandError, match="figures differ"):
        call_command(
            "verify_playtime_parity",
            "--user",
            owned_user.username,
            "--day-zone",
            TWIN_ZONE.key,
            stdout=output,
        )

    assert "all-time" in output.getvalue()


def test_the_command_passes_when_every_figure_agrees(owned_user, owned_library, game):
    day = date(2026, 3, 5)
    timed_twin(owned_library, game, prague(10, day), prague(12, day))
    output = StringIO()

    call_command(
        "verify_playtime_parity",
        "--user",
        owned_user.username,
        "--day-zone",
        TWIN_ZONE.key,
        stdout=output,
    )

    assert "0 figures differ" in output.getvalue()


def test_the_command_reads_the_day_zone_override(owned_user, game):
    late = datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
    Session.objects.create(
        game=game, timestamp_start=late, timestamp_end=late + timedelta(minutes=20)
    )
    in_utc, in_tokyo = StringIO(), StringIO()

    for zone, output in (("UTC", in_utc), ("Asia/Tokyo", in_tokyo)):
        with pytest.raises(CommandError):
            call_command(
                "verify_playtime_parity",
                "--user",
                owned_user.username,
                "--day-zone",
                zone,
                stdout=output,
            )

    assert "year 2025" in in_utc.getvalue()
    assert "year 2026" not in in_utc.getvalue()
    assert "year 2026" in in_tokyo.getvalue()


def test_the_command_refuses_a_zone_it_does_not_know(owned_user):
    with pytest.raises(CommandError, match="names no time zone"):
        call_command(
            "verify_playtime_parity",
            "--user",
            owned_user.username,
            "--day-zone",
            "Mars/Olympus",
            stdout=StringIO(),
        )
