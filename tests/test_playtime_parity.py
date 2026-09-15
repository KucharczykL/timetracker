"""Playtime figures compared across both tables."""

from datetime import UTC, date, datetime, time, timedelta
from io import StringIO
from typing import get_protocol_members

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from session_rows import (
    TWIN_ZONE,
    corrected_twin,
    duration_only_twin,
    timed_row,
    timed_twin,
    tracked_run,
)

from games.models import Game, Platform, PlayerSession, Session
from games.reads.playtime import legacy, projection
from games.reads.playtime.source import FullPlaytimeSource
from games.reads.playtime_parity import (
    COMPARED_MEMBERS,
    UNCOMPARED_MEMBERS,
    FigureKind,
    SourcePair,
    differing,
    playtime_figures,
)

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
    scopes = {str(figure.scope) for figure in figures}
    assert {"all-time", "year 2025", "year 2026", "month 2026-03"} <= scopes


def test_a_day_across_a_year_boundary_is_named(owned_library, game):
    twin = duration_only_twin(
        owned_library, game, date(2025, 12, 31), timedelta(hours=1)
    )
    PlayerSession.objects.filter(pk=twin.projection.pk).update(
        stated_day=date(2026, 1, 1)
    )

    scopes = {
        str(figure.scope)
        for figure in differing(playtime_figures(owned_library, TWIN_ZONE))
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

    assert "0 of " in output.getvalue()


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


def test_a_session_on_another_game_is_named(owned_library, game):
    other = Game.objects.create(
        library=owned_library, name="Tunic", platform=game.platform
    )
    start = prague(10, date(2026, 3, 5))
    end = start + timedelta(hours=1)
    Session.objects.create(game=game, timestamp_start=start, timestamp_end=end)
    timed_row(tracked_run(owned_library, other), start, end, day_zone=TWIN_ZONE.key)

    kinds = {
        figure.scope.kind
        for figure in differing(playtime_figures(owned_library, TWIN_ZONE))
    }

    assert kinds == {
        FigureKind.GAME,
        FigureKind.GAME_DETAIL,
        FigureKind.GAME_IN_WINDOW,
        FigureKind.GAME_IN_YEAR,
    }


def test_a_games_window_is_its_days_in_the_projection(owned_library, game):
    """Legacy time outside the projection's own span is named."""
    day = date(2026, 3, 5)
    timed_twin(owned_library, game, prague(10, day), prague(11, day))
    Session.objects.create(
        game=game,
        timestamp_start=prague(10, date(2026, 3, 1)),
        timestamp_end=prague(11, date(2026, 3, 1)),
    )

    figures = playtime_figures(owned_library, TWIN_ZONE)

    windows = [
        figure for figure in figures if figure.scope.kind == FigureKind.GAME_IN_WINDOW
    ]
    assert [str(figure.scope) for figure in windows] == [
        f"game Outer Wilds {game.pk} between 2026-03-05 and 2026-03-05"
    ]
    assert windows[0].legacy == windows[0].projection == timedelta(hours=1)
    assert FigureKind.GAME in {figure.scope.kind for figure in differing(figures)}


def test_a_game_the_projection_holds_no_session_for_has_no_window(owned_library, game):
    Session.objects.create(
        game=game,
        timestamp_start=prague(10, date(2026, 3, 1)),
        timestamp_end=prague(11, date(2026, 3, 1)),
    )

    kinds = {figure.scope.kind for figure in playtime_figures(owned_library, TWIN_ZONE)}

    assert FigureKind.GAME in kinds
    assert FigureKind.GAME_IN_WINDOW not in kinds


def test_a_day_moved_within_its_month_is_named(owned_library, game):
    twin = duration_only_twin(owned_library, game, date(2026, 3, 5), timedelta(hours=1))
    PlayerSession.objects.filter(pk=twin.projection.pk).update(
        stated_day=date(2026, 3, 6)
    )

    scopes = {
        str(figure.scope)
        for figure in differing(playtime_figures(owned_library, TWIN_ZONE))
    }

    assert scopes == {
        "day 2026-03-05",
        "day 2026-03-06",
        f"game Outer Wilds {game.pk} between 2026-03-06 and 2026-03-06",
    }


def test_every_protocol_member_is_compared_or_exempt():
    members = get_protocol_members(FullPlaytimeSource)

    assert members == COMPARED_MEMBERS | UNCOMPARED_MEMBERS.keys()
    assert not COMPARED_MEMBERS & UNCOMPARED_MEMBERS.keys()


class _Recording:
    """A source that notes each member read."""

    def __init__(self, source, read: set[str]):
        self._source = source
        self._read = read

    def __getattr__(self, name):
        self._read.add(name)
        return getattr(self._source, name)


def test_every_compared_member_is_read(owned_library, game):
    day = date(2026, 3, 5)
    timed_twin(owned_library, game, prague(10, day), prague(12, day))
    read: set[str] = set()

    playtime_figures(
        owned_library,
        TWIN_ZONE,
        sources=SourcePair(_Recording(legacy, read), _Recording(projection, read)),
    )

    assert read == COMPARED_MEMBERS


def test_the_command_refuses_an_empty_scope():
    with pytest.raises(CommandError, match="No library matched"):
        call_command("verify_playtime_parity", "--all-libraries", stdout=StringIO())


def test_the_command_reads_the_library_display_zone(owned_user, game, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Asia/Tokyo")
    late = datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
    Session.objects.create(
        game=game, timestamp_start=late, timestamp_end=late + timedelta(minutes=20)
    )
    output = StringIO()

    with pytest.raises(CommandError):
        call_command(
            "verify_playtime_parity", "--user", owned_user.username, stdout=output
        )

    assert "year 2026" in output.getvalue()
    assert "Asia/Tokyo" in output.getvalue()


def test_the_command_refuses_an_empty_username():
    with pytest.raises(CommandError, match="username is not empty"):
        call_command("verify_playtime_parity", "--user", "", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_the_command_reads_one_snapshot_outside_a_transaction(owned_user, game):
    day = date(2026, 3, 5)
    timed_twin(owned_user.library, game, prague(10, day), prague(12, day))
    output = StringIO()

    call_command("verify_playtime_parity", "--user", owned_user.username, stdout=output)

    assert "0 of " in output.getvalue()
