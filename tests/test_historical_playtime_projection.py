"""One row per historical playtime record a library states."""

import uuid
from datetime import date, timedelta

import pytest
from django.apps import apps as global_apps
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    unaudited_projection_references,
)

#: Nothing here wants the row the fixture tracks for a new game.
pytestmark = pytest.mark.untracked_games


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


def a_record(tracked, **stated) -> HistoricalPlaytime:
    """One row, written the way the projector writes it."""
    columns = {
        "id": uuid.uuid7(),
        "library": tracked.library,
        "player_game": tracked,
        "duration": timedelta(hours=100),
        "when": "2005",
        "provenance": HistoricalPlaytimeProvenance.ESTIMATED,
        "device": None,
        "emulated": False,
        "note": "",
        "created_at": timezone.now(),
    } | stated
    return HistoricalPlaytime.objects.create(**columns)


def a_join(record, run) -> HistoricalPlaytimeRun:
    return HistoricalPlaytimeRun.objects.create(
        id=uuid.uuid7(), library=record.library, record=record, playthrough=run
    )


@pytest.mark.django_db
def test_a_zero_duration_is_refused(tracked):
    with pytest.raises(IntegrityError), transaction.atomic():
        a_record(tracked, duration=timedelta(0))


@pytest.mark.django_db
def test_a_negative_duration_is_refused(tracked):
    with pytest.raises(IntegrityError), transaction.atomic():
        a_record(tracked, duration=timedelta(hours=-1))


@pytest.mark.django_db
def test_an_unknown_provenance_is_refused(tracked):
    with pytest.raises(IntegrityError), transaction.atomic():
        a_record(tracked, provenance="guessed")


@pytest.mark.django_db
def test_a_run_is_named_once_per_record(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    with pytest.raises(IntegrityError), transaction.atomic():
        a_join(record, run)


@pytest.mark.django_db
def test_an_unknown_when_is_admitted(tracked):
    record = a_record(tracked, when=None)
    record.refresh_from_db()
    assert record.when is None
    assert record.when_lower is None
    assert record.when_upper is None


@pytest.mark.django_db
def test_a_year_bounds_to_its_first_and_last_day(tracked):
    record = a_record(tracked, when="2005")
    record.refresh_from_db()
    assert record.when_lower == date(2005, 1, 1)
    assert record.when_upper == date(2005, 12, 31)


@pytest.mark.django_db
def test_an_open_range_has_no_upper_bound(tracked):
    record = a_record(tracked, when="2005/")
    record.refresh_from_db()
    assert record.when_lower == date(2005, 1, 1)
    assert record.when_upper is None


def test_the_model_passes_the_projection_checks():
    assert check_projection_models(apps=global_apps) == []


def test_the_four_references_are_registered():
    keys = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}
    assert ("games.HistoricalPlaytime", "player_game") in keys
    assert ("games.HistoricalPlaytime", "device") in keys
    assert ("games.HistoricalPlaytimeRun", "record") in keys
    assert ("games.HistoricalPlaytimeRun", "playthrough") in keys
    assert unaudited_projection_references() == ()


def test_both_managers_state_alive():
    assert hasattr(HistoricalPlaytime._default_manager, "alive")
    assert hasattr(HistoricalPlaytimeRun._default_manager, "alive")


@pytest.mark.django_db
def test_a_removed_record_hides_its_join_rows(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    HistoricalPlaytime.objects.filter(pk=record.pk).update(removed_at=timezone.now())
    assert not HistoricalPlaytimeRun.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_tracked_game_hides_the_record(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())
    assert not HistoricalPlaytime.objects.alive().exists()
    assert not HistoricalPlaytimeRun.objects.alive().exists()


def test_the_record_reaches_the_game_in_one_hop():
    assert HistoricalPlaytime.comparison_through == (("player_game__game", "Game"),)
