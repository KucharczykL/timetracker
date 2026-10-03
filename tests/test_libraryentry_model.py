"""The LibraryEntry table: its CHECKs, index, marks and audit."""

import uuid
from typing import cast

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import timed_row, tracked_run

from games.models import (
    EntryAccess,
    EntryFormat,
    Game,
    LibraryEntry,
    PlayerGame,
    Release,
)
from games.projections import cross_library_violations, release_game_violations

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library


def _tracked(library, game: Game) -> PlayerGame:
    return PlayerGame.objects.create(
        id=uuid.uuid7(), library=library, game=game, tracked_at=timezone.now()
    )


def _row(library, tracked: PlayerGame, release: Release, **words) -> LibraryEntry:
    stated = {
        "id": uuid.uuid7(),
        "library": library,
        "player_game": tracked,
        "release": release,
        "access": "owned",
        "format": "digital",
        "acquisition_recorded_at": timezone.now(),
        "created_at": timezone.now(),
    } | words
    return LibraryEntry._base_manager.create(**stated)


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("access", "games_libraryentry_access_known"),
        ("format", "games_libraryentry_format_known"),
    ],
)
def test_a_foreign_word_is_refused_by_the_check(
    owned_library, graph, column, constraint
):
    tracked = _tracked(owned_library, graph.game)
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        _row(owned_library, tracked, graph.release, **{column: "stolen"})


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        (
            {"access_end_way": "melted", "access_end_recorded_at": timezone.now()},
            "games_libraryentry_access_end_way_known",
        ),
        (
            {"access_end_way": "returned"},
            "games_libraryentry_access_end_way_with_marker",
        ),
        (
            {"access_end_recorded_at": timezone.now()},
            "games_libraryentry_access_end_way_with_marker",
        ),
    ],
)
def test_the_end_checks_back_the_command(owned_library, graph, columns, constraint):
    tracked = _tracked(owned_library, graph.game)
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        _row(owned_library, tracked, graph.release, **columns)


def test_an_ended_copy_states_its_way_beside_its_marker(owned_library, graph):
    tracked = _tracked(owned_library, graph.game)
    row = _row(
        owned_library,
        tracked,
        graph.release,
        access_end_way="expired",
        access_end_recorded_at=timezone.now(),
    )
    assert LibraryEntry.objects.get(pk=row.pk).access_end_way == "expired"


def test_the_meta_states_the_index_and_every_check() -> None:
    names = {constraint.name for constraint in LibraryEntry._meta.constraints}
    assert names == {
        "unique_games_libraryentry_library_identity",
        "games_libraryentry_access_known",
        "games_libraryentry_format_known",
        "games_libraryentry_access_end_way_known",
        "games_libraryentry_access_end_way_with_marker",
    }
    (index,) = LibraryEntry._meta.indexes
    assert (index.name, index.fields) == (
        "live_entry_per_release_idx",
        ["library", "release"],
    )
    assert index.condition is not None


def test_alive_hides_a_row_under_a_removed_player_game(owned_library, graph):
    tracked = _tracked(owned_library, graph.game)
    row = _row(owned_library, tracked, graph.release)

    assert list(LibraryEntry.objects.alive()) == [row]
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())
    assert not LibraryEntry.objects.alive().exists()
    assert LibraryEntry.objects.get(pk=row.pk) == row


def test_two_entries_on_one_release_are_two_copies(owned_library, graph):
    tracked = _tracked(owned_library, graph.game)
    first = _row(owned_library, tracked, graph.release)
    second = _row(owned_library, tracked, graph.release)

    assert {first.pk, second.pk} <= set(
        LibraryEntry.objects.alive().values_list("pk", flat=True)
    )


def test_an_entry_naming_a_foreign_private_release_is_reported(
    owned_library, other_library, graph, stated_graph
):
    theirs = stated_graph(Game(name="Hades", library=other_library), other_library)
    tracked = _tracked(owned_library, graph.game)
    row = _row(owned_library, tracked, theirs.release)

    assert cross_library_violations([owned_library.pk]) == [
        f"LibraryEntry.release: {row.pk} names Release {theirs.release.pk}"
    ]


def test_an_entry_naming_a_shared_release_is_no_violation(owned_library, graph):
    Game.objects.filter(pk=graph.game.pk).update(library=None)
    tracked = _tracked(owned_library, graph.game)
    _row(owned_library, tracked, graph.release)

    assert cross_library_violations([owned_library.pk]) == []


def test_an_entry_naming_a_foreign_player_game_is_reported(
    owned_library, other_library, graph
):
    Game.objects.filter(pk=graph.game.pk).update(library=None)
    theirs = _tracked(other_library, graph.game)
    row = _row(owned_library, theirs, graph.release)

    assert cross_library_violations([owned_library.pk]) == [
        f"LibraryEntry.player_game: {row.pk} names PlayerGame {theirs.pk}"
    ]


def test_the_word_columns_fit_every_word() -> None:
    access = cast(int, LibraryEntry._meta.get_field("access").max_length)
    format = cast(int, LibraryEntry._meta.get_field("format").max_length)
    assert max(len(word) for word in EntryAccess.values) <= access
    assert max(len(word) for word in EntryFormat.values) <= format


def test_an_entry_on_another_games_release_is_reported(
    owned_library, graph, stated_graph
):
    other = stated_graph(Game(name="Celeste", library=owned_library), owned_library)
    tracked = _tracked(owned_library, graph.game)
    row = _row(owned_library, tracked, other.release)

    sentence = (
        f"LibraryEntry.release: {row.pk} names a Release of Game "
        f"{other.game.pk}, and its PlayerGame tracks Game {graph.game.pk}"
    )
    assert release_game_violations([owned_library.pk]) == [sentence]
    assert release_game_violations([]) == []


def test_a_session_or_record_on_another_games_release_is_reported(
    owned_library, graph, stated_graph
):
    other = stated_graph(Game(name="Celeste", library=owned_library), owned_library)
    run = tracked_run(owned_library, graph.game)
    session = timed_row(run, timezone.now(), None, release=other.release)
    record = record_row([run], release=other.release)

    tail = f"names a Release of Game {other.game.pk}, and its PlayerGame tracks Game {graph.game.pk}"
    assert release_game_violations([owned_library.pk]) == [
        f"PlayerSession.release: {session.pk} {tail}",
        f"HistoricalPlaytime.release: {record.pk} {tail}",
    ]


def test_a_session_or_record_stating_no_release_is_no_violation(owned_library, graph):
    run = tracked_run(owned_library, graph.game)
    timed_row(run, timezone.now(), None)
    record_row([run])
    timed_row(run, timezone.now(), None, release=graph.release)

    assert release_game_violations([owned_library.pk]) == []
