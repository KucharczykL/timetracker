"""Game holdings read for Log a game."""

from datetime import UTC, datetime

import pytest
from django.utils import timezone
from entries import record_entry
from historical_playtime_rows import record_row
from session_rows import timed_row, tracked_run

from games.catalog_release import release_on
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.models import Game, Platform, PlayerGame, PlayerGameStatus, Playthrough
from games.reads.log_game import copy_release_for, held_facts
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playthrough import start_run

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def library(user):
    return user.library


@pytest.fixture
def game(library):
    return Game.objects.create(library=library, name="Halo")


@pytest.fixture
def pc(library):
    return Platform.objects.create(library=library, name="PC")


@pytest.fixture
def console(library):
    return Platform.objects.create(library=library, name="Xbox")


def _release(library, game, platform):
    return release_on(library, game, platform).release


def test_an_untracked_game_reads_nothing(library, game):
    facts = held_facts(library, game)

    assert facts.removed is False
    assert facts.status is None
    assert facts.run is None
    assert facts.platform is None
    assert facts.note == ""


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_reads_removed(user, library, game):
    track_game(user, game, correlation_id=new_correlation_id())
    PlayerGame.objects.filter(library=library, game=game).update(
        removed_at=timezone.now()
    )

    facts = held_facts(library, game)

    assert facts.removed is True
    assert facts.status is None


@pytest.mark.django_db(transaction=True)
def test_status_mastery_and_the_run_note_come_from_the_tracked_row(user, library, game):
    track_game(user, game, correlation_id=new_correlation_id())
    PlayerGame.objects.filter(library=library, game=game).update(
        status=PlayerGameStatus.ABANDONED, mastered=True
    )
    Playthrough.objects.filter(library=library, player_game__game=game).update(
        note="Left at the bridge"
    )

    facts = held_facts(library, game)

    assert facts.status == PlayerGameStatus.ABANDONED
    assert facts.mastered is True
    assert facts.note == "Left at the bridge"
    assert facts.run is not None


@pytest.mark.django_db(transaction=True)
def test_an_act_stated_with_no_day_reads_as_stated_but_dayless(user, library, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = Playthrough.objects.get(library=library, player_game__game=game)
    start_run(
        user,
        run,
        None,
        implies_status=False,
        correlation_id=new_correlation_id(),
    )

    facts = held_facts(library, game)

    assert facts.started is not None
    assert facts.started.when is None
    assert facts.completed is None


def test_a_newer_session_names_the_platform_over_a_newer_copy(
    library, game, pc, console
):
    played = _release(library, game, pc)
    owned = _release(library, game, console)
    run = tracked_run(library, game)
    timed_row(
        run,
        datetime(2024, 5, 1, 12, tzinfo=UTC),
        datetime(2024, 5, 1, 13, tzinfo=UTC),
        release=played,
    )
    record_entry(library, owned)

    assert held_facts(library, game).platform == pc


def test_without_a_session_the_newest_copy_names_the_platform(
    library, game, pc, console
):
    record_entry(library, _release(library, game, pc))
    record_entry(library, _release(library, game, console))

    assert held_facts(library, game).platform == console


def test_a_removed_platform_does_not_name_the_platform(library, game, pc, console):
    record_entry(library, _release(library, game, pc))
    record_entry(library, _release(library, game, console))
    Platform.objects.filter(pk=console.pk).update(removed_at=timezone.now())

    assert held_facts(library, game).platform == pc


def test_copy_release_for_names_the_held_release_on_that_platform(
    library, game, pc, console
):
    held = _release(library, game, pc)
    record_entry(library, held)

    assert copy_release_for(library, game, pc) == held
    assert copy_release_for(library, game, console) is None


def test_several_copies_of_one_release_name_that_release(library, game, pc):
    held = _release(library, game, pc)
    record_entry(library, held)
    record_entry(library, held)

    assert copy_release_for(library, game, pc) == held


def test_a_record_names_the_platform_over_an_older_copy(library, game, pc, console):
    record_entry(library, _release(library, game, pc))
    record_row([tracked_run(library, game)], release=_release(library, game, console))

    assert held_facts(library, game).platform == console


def test_a_dated_record_names_the_platform_over_an_undated_one(
    library, game, pc, console
):
    run = tracked_run(library, game)
    record_row([run], when="2020/2022", release=_release(library, game, pc))
    record_row([run], release=_release(library, game, console))

    assert held_facts(library, game).platform == pc


def test_copy_release_for_names_the_release_the_newest_session_names(library, game, pc):
    first = _release(library, game, pc)
    second = _release_beside(library, game, pc)
    record_entry(library, first)
    record_entry(library, second)
    timed_row(
        tracked_run(library, game),
        datetime(2024, 5, 1, 12, tzinfo=UTC),
        datetime(2024, 5, 1, 13, tzinfo=UTC),
        release=second,
    )

    assert copy_release_for(library, game, pc) == second


def _release_beside(library, game, platform):
    edition_state = EditionState(
        key="edition-1",
        edition=None,
        name="Deluxe",
        is_default=False,
        releases=(ReleaseState(key="edition-1-release-0", platform=platform),),
    )
    written = state_catalog_graph(game=game, library=library, editions=[edition_state])
    return written.editions[0].releases[0].release
