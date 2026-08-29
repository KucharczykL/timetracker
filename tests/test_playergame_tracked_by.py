"""GameQuerySet.tracked_by(): the join every authenticated game read uses."""

import uuid

import pytest
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library


@pytest.mark.django_db
def test_a_tracked_game_is_listed(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    assert list(Game.objects.tracked_by(owned_library)) == [game]


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_an_untracked_game_is_absent(owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    assert not Game.objects.tracked_by(owned_library).exists()


@pytest.mark.django_db
def test_a_removed_game_is_absent(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(tombstoned_at=timezone.now())

    assert not Game.objects.tracked_by(owned_library).exists()


@pytest.mark.django_db
def test_an_archived_game_is_absent(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        archived_at=timezone.now()
    )

    assert not Game.objects.tracked_by(owned_library).exists()


@pytest.mark.django_db
def test_another_library_sees_nothing(owned_library, other_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    assert not Game.objects.tracked_by(other_library).exists()


@pytest.mark.django_db
def test_the_two_facts_are_readable(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        status=PlayerGameStatus.COMPLETED, mastered=True
    )

    row = Game.objects.tracked_by(owned_library).get()
    assert row.tracked_status == PlayerGameStatus.COMPLETED
    assert row.tracked_mastered is True


@pytest.mark.django_db
def test_a_shared_game_this_library_tracks_is_listed(owned_library):
    #: for_library() hides it; tracked_by() does not, because a list
    #: of tracked games is what the page claims to be.
    shared = Game.objects.create(library=None, name="Shared")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.PLAYED,
    )

    assert list(Game.objects.tracked_by(owned_library)) == [shared]


@pytest.mark.django_db
def test_two_filter_calls_stay_in_one_library(owned_library, other_library):
    #: Django opens a join per filter() call on a multi-valued
    #: relation. On a plain path the second join carries no library
    #: condition and this shared game comes back on the strength of
    #: another library's row.
    shared = Game.objects.create(library=None, name="Shared")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.UNPLAYED,
        mastered=False,
    )
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=other_library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.PLAYED,
        mastered=True,
    )

    matched = (
        Game.objects.tracked_by(owned_library)
        .filter(tracked__status=PlayerGameStatus.PLAYED)
        .filter(tracked__mastered=True)
    )
    assert not matched.exists()


@pytest.mark.django_db
def test_a_condition_selects_the_matching_games(owned_library):
    completed = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.create(library=owned_library, name="Tunic")
    PlayerGame.objects.filter(library=owned_library, game=completed).update(
        status=PlayerGameStatus.COMPLETED
    )

    matched = Game.objects.tracked_by(
        owned_library, tracked__status=PlayerGameStatus.COMPLETED
    )

    assert list(matched) == [completed]


@pytest.mark.django_db
def test_a_condition_opens_one_join(owned_library):
    """One filter() call, so one join."""
    sql = str(
        Game.objects.tracked_by(
            owned_library, tracked__status=PlayerGameStatus.COMPLETED
        ).query
    )

    assert sql.count('JOIN "games_playergame"') == 1


@pytest.mark.django_db
def test_an_unscoped_annotation_drops_no_game(owned_library, other_library):
    """Registering the alias alone changes no result.

    A filter compiles `tracked__status` against a queryset it never
    executes, so this takes no library and filters nothing. Naming
    the alias is what opens the join, and unscoped it has no
    condition: a game two libraries track then comes back twice.
    `tracked_by()` is the scoped read.
    """
    shared = Game.objects.create(library=None, name="Shared Title")
    for library in (owned_library, other_library):
        PlayerGame.objects.create(
            pk=uuid.uuid7(), library=library, game=shared, tracked_at=timezone.now()
        )

    annotated = Game.objects.annotated_for_filtering()

    assert set(annotated) == set(Game.objects.all())
    assert annotated.count() == Game.objects.count()
    named = annotated.filter(tracked__isnull=False)
    assert named.count() == Game.objects.count() + 1
