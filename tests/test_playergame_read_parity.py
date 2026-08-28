"""Old catalog read against new projection read, id set by id set.

Created by #678 A and deleted by #678 D. Its whole purpose is to
guard the switch, so it does not outlive it. Every case builds both
queries here rather than calling a view, so it holds before, during
and after each child re-points its surface.
"""

import pytest

from games.models import Game, PlayerGame, PlayerGameStatus
from games.playergame_status import (
    LEGACY_STATUS_TO_PLAYER_STATUS,
    legacy_status_for,
)
from games.sorting import GAME_SORTS


@pytest.fixture
def a_library_of_every_status(owned_library):
    """One game per status, one mastered, one of each sort key's value."""
    games = []
    for index, player_status in enumerate(PlayerGameStatus):
        game = Game.objects.create(
            library=owned_library,
            name=f"Game {index}",
            sort_name=f"game {index}",
            year_released=2000 + index,
            wikidata=f"Q{index}",
        )
        mastered = index % 2 == 0
        PlayerGame.objects.filter(library=owned_library, game=game).update(
            status=player_status, mastered=mastered
        )
        if player_status is not PlayerGameStatus.SHELVED:
            #: The catalog holds what the mirror would have written.
            Game.objects.filter(pk=game.pk).update(
                status=legacy_status_for(player_status), mastered=mastered
            )
        games.append(game)
    return games


#: The catalog column each projection alias replaced. GAME_SORTS
#: names the projection from #678 B on, so the old side is stated
#: here rather than read back out of the map under test.
CATALOG_SORT_EXPRESSIONS = {"tracked_status": "status"}


def ids(queryset):
    return set(queryset.values_list("id", flat=True))


def ordered_ids(queryset):
    return list(queryset.values_list("id", flat=True))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("legacy_status", "player_status"),
    sorted(LEGACY_STATUS_TO_PLAYER_STATUS.items()),
)
def test_a_status_selects_the_same_games(
    owned_library, a_library_of_every_status, legacy_status, player_status
):
    #: No letter says shelved, and `Game.status` has no absent value
    #: either: the column sits at its default and the old query reads
    #: the shelved game as unplayed. Excluded from both sides, as in
    #: every other case here.
    shelved = PlayerGame.objects.get(
        library=owned_library, status=PlayerGameStatus.SHELVED
    ).game_id
    old = (
        Game.objects.for_library(owned_library)
        .filter(status=legacy_status)
        .exclude(pk=shelved)
    )
    new = (
        Game.objects.tracked_by(owned_library)
        .filter(tracked__status=player_status)
        .exclude(pk=shelved)
    )

    assert ids(old) == ids(new)


@pytest.mark.django_db
@pytest.mark.parametrize("mastered", [True, False])
def test_mastery_selects_the_same_games(
    owned_library, a_library_of_every_status, mastered
):
    #: The shelved game has no catalog letter, so the old query cannot
    #: see it. Exclude it from both sides rather than from one.
    shelved = PlayerGame.objects.get(
        library=owned_library, status=PlayerGameStatus.SHELVED
    ).game_id
    old = (
        Game.objects.for_library(owned_library)
        .filter(mastered=mastered)
        .exclude(pk=shelved)
    )
    new = (
        Game.objects.tracked_by(owned_library)
        .filter(tracked__mastered=mastered)
        .exclude(pk=shelved)
    )

    assert ids(old) == ids(new)


@pytest.mark.django_db
@pytest.mark.parametrize("sort_key", sorted(GAME_SORTS))
@pytest.mark.parametrize("descending", [False, True])
def test_a_sort_returns_the_same_order(
    owned_library, a_library_of_every_status, sort_key, descending
):
    """Ordering by letter and ordering by word agree.

    a, f, p, r, u against abandoned, completed, played, retired,
    unplayed: the two orders match, so ?sort=status returns the same
    page. shelved takes its place between retired and unplayed and is
    excluded here, because the catalog side cannot hold it.
    """
    shelved = PlayerGame.objects.get(
        library=owned_library, status=PlayerGameStatus.SHELVED
    ).game_id
    spec = GAME_SORTS[sort_key]
    new_expression = spec.expression
    old_expression = CATALOG_SORT_EXPRESSIONS.get(new_expression, new_expression)
    prefix = "-" if descending else ""

    old = Game.objects.for_library(owned_library).exclude(pk=shelved)
    new = Game.objects.tracked_by(owned_library).exclude(pk=shelved)
    if spec.annotate:
        old = old.annotate(**spec.annotate)
        new = new.annotate(**spec.annotate)
    if old_expression == "filtered_playtime":
        pytest.skip("list_games pre-annotates this alias; no parity to check here")

    assert ordered_ids(old.order_by(f"{prefix}{old_expression}", "id")) == ordered_ids(
        new.order_by(f"{prefix}{new_expression}", "id")
    )


@pytest.mark.django_db
def test_an_unscoped_annotation_drops_no_game(owned_library, a_library_of_every_status):
    """`annotated_for_filtering()` annotates; it does not select.

    `tracked_by()` is the one that filters. The unscoped form exists
    so a filter can compile its lookups against a queryset that
    executes nothing, which means it must leave the row set alone.
    """
    annotated = Game.objects.annotated_for_filtering()

    assert ids(annotated) == ids(Game.objects.all())
