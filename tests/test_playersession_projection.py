"""One row per session a library records."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.apps import apps as global_apps
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.models import (
    Device,
    Game,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    PlaythroughKind,
)
from games.preflight.session import MODE_VERDICTS
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    unaudited_projection_references,
)

#: Nothing here wants the row the fixture tracks for a new game.
pytestmark = pytest.mark.untracked_games

START = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def tracked(owned_library, game) -> PlayerGame:
    return PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )


@pytest.fixture
def run(owned_library, tracked) -> Playthrough:
    return Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def a_session(run: Playthrough, **columns) -> PlayerSession:
    """One row, written the way the projector writes it."""
    stated = {
        "id": uuid.uuid7(),
        "library": run.library,
        "playthrough": run,
        "device": None,
        "timing_mode": PlayerSessionTimingMode.TIMED,
        "started_at": None,
        "started_at_zone": None,
        "ended_at": None,
        "ended_at_zone": None,
        "stated_day": None,
        "stated_duration": None,
        "day_zone": None,
        "note": "",
        "emulated": False,
        "created_at": timezone.now(),
    } | columns
    return PlayerSession.objects.create(**stated)


def a_timed(run: Playthrough, **columns) -> PlayerSession:
    return a_session(
        run,
        **{
            "timing_mode": PlayerSessionTimingMode.TIMED,
            "started_at": START,
            "day_zone": "Europe/Prague",
        }
        | columns,
    )


def a_duration_only(run: Playthrough, **columns) -> PlayerSession:
    return a_session(
        run,
        **{
            "timing_mode": PlayerSessionTimingMode.DURATION_ONLY,
            "stated_day": date(2026, 3, 5),
            "stated_duration": timedelta(minutes=90),
        }
        | columns,
    )


def a_corrected(run: Playthrough, **columns) -> PlayerSession:
    return a_session(
        run,
        **{
            "timing_mode": PlayerSessionTimingMode.CORRECTED,
            "started_at": START,
            "ended_at": START + timedelta(hours=1),
            "stated_duration": timedelta(minutes=30),
            "day_zone": "Europe/Prague",
        }
        | columns,
    )


def refused(write, *args, **columns) -> None:
    """The database turns this row away."""
    with pytest.raises(IntegrityError), transaction.atomic():
        write(*args, **columns)


def refused_as_data(write, *args, **columns) -> None:
    """Turned away while a generated column is computed.

    Generation runs before any constraint, so a zone PostgreSQL
    cannot read never reaches one.
    """
    with pytest.raises(DataError), transaction.atomic():
        write(*args, **columns)


@pytest.mark.django_db
def test_timed_refuses_a_stated_day(run):
    refused(a_timed, run, stated_day=date(2026, 1, 1))


@pytest.mark.django_db
def test_timed_refuses_a_stated_duration(run):
    refused(a_timed, run, stated_duration=timedelta(minutes=5))


@pytest.mark.django_db
def test_timed_requires_a_day_zone(run):
    refused(a_timed, run, day_zone=None)


@pytest.mark.django_db
def test_corrected_refuses_a_stated_day(run):
    refused(a_corrected, run, stated_day=date(2026, 1, 1))


@pytest.mark.django_db
def test_corrected_requires_both_instants(run):
    refused(a_corrected, run, ended_at=None)


@pytest.mark.django_db
def test_corrected_requires_an_override(run):
    refused(a_corrected, run, stated_duration=None)


@pytest.mark.django_db
def test_duration_only_refuses_an_instant(run):
    refused(a_duration_only, run, started_at=START)


@pytest.mark.django_db
def test_duration_only_refuses_a_day_zone(run):
    refused(a_duration_only, run, day_zone="Europe/Prague")


@pytest.mark.django_db
def test_duration_only_requires_a_duration(run):
    refused(a_duration_only, run, stated_duration=None)


@pytest.mark.django_db
def test_an_endpoint_zone_needs_its_instant(run):
    refused(a_timed, run, ended_at=None, ended_at_zone="Asia/Tokyo")


@pytest.mark.django_db
def test_a_blank_day_zone_is_refused(run):
    refused_as_data(a_timed, run, day_zone="")


@pytest.mark.django_db
def test_a_day_zone_no_tzdata_knows_is_refused(run):
    refused_as_data(a_timed, run, day_zone="Not/AZone")


@pytest.mark.django_db
def test_a_blank_endpoint_zone_is_refused(run):
    refused(a_timed, run, started_at_zone="")


@pytest.mark.django_db
def test_an_end_before_its_start_is_refused(run):
    refused(a_timed, run, ended_at=START - timedelta(hours=1))


@pytest.mark.django_db
def test_a_negative_duration_is_refused(run):
    refused(a_duration_only, run, stated_duration=timedelta(minutes=-5))


@pytest.mark.django_db
def test_an_unknown_mode_is_refused(run):
    refused(a_timed, run, timing_mode="guessed")


@pytest.mark.django_db
def test_an_end_equal_to_its_start_is_admitted(run):
    session = a_timed(run, ended_at=START)

    session.refresh_from_db()
    assert session.effective_duration == timedelta(0)


@pytest.mark.django_db
def test_a_running_timed_row_is_admitted(run):
    session = a_timed(run)

    session.refresh_from_db()
    assert session.ended_at is None


@pytest.mark.django_db
def test_a_timed_row_takes_its_day_from_its_zone(run):
    session = a_timed(run)

    session.refresh_from_db()
    #: 23:30 UTC is half past midnight in Prague.
    assert session.effective_day == date(2026, 1, 2)
    assert session.sort_instant == START


@pytest.mark.django_db
def test_restating_the_zone_moves_the_day(run):
    session = a_timed(run)

    PlayerSession.objects.filter(pk=session.pk).update(day_zone="UTC")

    session.refresh_from_db()
    assert session.effective_day == date(2026, 1, 1)


@pytest.mark.django_db
def test_a_duration_only_row_takes_its_written_day(run):
    session = a_duration_only(run)

    session.refresh_from_db()
    assert session.effective_day == date(2026, 3, 5)
    assert session.sort_instant == datetime(2026, 3, 5, tzinfo=UTC)
    assert session.effective_duration == timedelta(minutes=90)


@pytest.mark.django_db
def test_a_finished_timed_row_measures_elapsed_time(run):
    session = a_timed(run, ended_at=START + timedelta(hours=2))

    session.refresh_from_db()
    assert session.effective_duration == timedelta(hours=2)


@pytest.mark.django_db
def test_a_running_timed_row_measures_nothing(run):
    session = a_timed(run)

    session.refresh_from_db()
    assert session.effective_duration == timedelta(0)


@pytest.mark.django_db
def test_a_corrected_row_answers_its_override(run):
    session = a_corrected(run)

    session.refresh_from_db()
    #: One hour elapsed, and the override replaces it.
    assert session.effective_duration == timedelta(minutes=30)


@pytest.mark.django_db
def test_the_model_passes_the_projection_checks():
    assert check_projection_models(apps=global_apps) == []


@pytest.mark.django_db
def test_both_references_are_registered():
    keys = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}

    assert ("games.PlayerSession", "playthrough") in keys
    assert ("games.PlayerSession", "device") in keys
    assert unaudited_projection_references() == ()


def test_the_manager_states_alive():
    #: BlockingReferrer.on refuses a model whose manager lacks it.
    assert hasattr(PlayerSession._default_manager, "alive")


@pytest.mark.django_db
def test_a_removed_session_leaves_the_reads(run):
    session = a_timed(run)

    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())

    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_run_takes_its_sessions_with_it(run):
    a_timed(run)

    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_tracked_game_takes_its_sessions_with_it(run, tracked):
    a_timed(run)

    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())

    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_catalog_game_leaves_its_sessions_in_place(run, game):
    """The read layer states this mark, and `alive()` does not.

    `blocking_referrer` reads `alive()` to refuse removing a run
    sessions name. A catalog mark here would hide them from that
    check and make the run removable.
    """
    a_timed(run)

    Game.objects.filter(pk=game.pk).update(removed_at=timezone.now())

    assert PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_session_may_name_a_device(owned_library, run):
    device = Device.objects.create(library=owned_library, name="Steam Deck")

    session = a_timed(run, device=device)

    session.refresh_from_db()
    assert session.device == device


def test_the_modes_are_spelled_as_the_census_spells_them():
    assert {mode.value for mode in PlayerSessionTimingMode} == {
        verdict.value for verdict in MODE_VERDICTS
    }
