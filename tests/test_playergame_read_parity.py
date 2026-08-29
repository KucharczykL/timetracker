"""Old catalog read against new projection read, id set by id set.

Created by #678 A and deleted by #678 D. Its whole purpose is to
guard the switch, so it does not outlive it. Every case builds both
queries here rather than calling a view, so it holds before, during
and after each child re-points its surface.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus, Purchase
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


#: The catalog column each alias replaced. GAME_SORTS names
#: the projection now, so the old side is stated here.
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


def _one_purchase_per_game(owned_library, games):
    #: Not the shelved game. No letter says shelved, so its column
    #: sits at the `u` default and the letter side would read it as
    #: unplayed. Excluded from both sides, as everywhere else here.
    shelved = PlayerGame.objects.get(
        library=owned_library, status=PlayerGameStatus.SHELVED
    ).game_id
    for game in games:
        if game.pk == shelved:
            continue
        purchase = Purchase.objects.create(
            library=owned_library,
            price_currency="CZK",
            type=Purchase.GAME,
            date_purchased=timezone.now(),
        )
        purchase.games.set([game])


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("legacy_status", "player_status"),
    sorted(LEGACY_STATUS_TO_PLAYER_STATUS.items()),
)
def test_a_purchase_predicate_selects_the_same_purchases(
    owned_library, a_library_of_every_status, legacy_status, player_status
):
    """A letter over the catalog, a word over the projection.

    Both directions: a statistic negates three of its four
    predicates, and a negation over a join is the shape most likely
    to differ.
    """
    _one_purchase_per_game(owned_library, a_library_of_every_status)

    purchases = Purchase.objects.for_library(owned_library)
    old = Q(games__status=legacy_status)
    new = Q(
        games__in=Game.objects.tracked_by(owned_library, tracked__status=player_status)
    )

    assert ids(purchases.filter(old)) == ids(purchases.filter(new))
    assert ids(purchases.filter(~old)) == ids(purchases.filter(~new))


@pytest.mark.django_db
def test_two_negated_statuses_merge_into_one(owned_library, a_library_of_every_status):
    """`~a & ~b` is `~(a or b)`, and the second reads one column."""
    _one_purchase_per_game(owned_library, a_library_of_every_status)

    purchases = Purchase.objects.for_library(owned_library)
    old = ~Q(games__status="r") & ~Q(games__status="a")
    new = ~Q(
        games__in=Game.objects.tracked_by(
            owned_library,
            tracked__status__in=[
                PlayerGameStatus.RETIRED,
                PlayerGameStatus.ABANDONED,
            ],
        )
    )

    assert ids(purchases.filter(old)) == ids(purchases.filter(new))


@pytest.mark.django_db
def test_an_unscoped_annotation_drops_no_game(owned_library, a_library_of_every_status):
    """Registering the alias alone changes no result.

    A filter compiles `tracked__status` against a queryset it never
    executes, so this takes no library and filters nothing. Naming
    the alias is what opens the join, and unscoped it has no
    condition: a game two libraries track then comes back twice.
    `tracked_by()` is the scoped read.
    """
    other = (
        get_user_model().objects.create_user(username="second", password="x").library
    )
    shared = Game.objects.create(library=None, name="Shared Title")
    for library in (owned_library, other):
        PlayerGame.objects.create(
            pk=uuid.uuid7(), library=library, game=shared, tracked_at=timezone.now()
        )

    annotated = Game.objects.annotated_for_filtering()

    assert ids(annotated) == ids(Game.objects.all())
    assert annotated.count() == Game.objects.count()
    named = annotated.filter(tracked__isnull=False)
    assert named.count() == Game.objects.count() + 1
