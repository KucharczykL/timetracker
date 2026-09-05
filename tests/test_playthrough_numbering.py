"""Playthrough N, derived at read time."""

import uuid

import pytest
from django.utils import timezone

from games.commands.playergame import TrackGame
from games.commands.playthrough import CreatePlaythrough
from games.events.dispatch import dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import Game, PlayerGame, Playthrough, PlaythroughKind
from games.reads.playthrough_numbering import (
    UnnumberedPlaythrough,
    display_name,
    with_display_number,
)
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


@pytest.fixture
def tracked(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    return PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )


def make_run(tracked, *, started=None, completed=None, created_at=None, **columns):
    return Playthrough.objects.create(
        id=uuid.uuid7(),
        library=tracked.library,
        player_game=tracked,
        started=started,
        completed=completed,
        created_at=created_at or timezone.now(),
        **columns,
    )


def numbers(tracked):
    return [
        (row.pk, row.display_number)
        for row in with_display_number(
            Playthrough.objects.filter(player_game=tracked)
        ).order_by("display_number")
    ]


def test_a_known_start_orders_before_an_unknown_one(tracked):
    """NULLS LAST on the start bound."""
    unknown = make_run(tracked)
    known = make_run(tracked, started=TemporalValue.from_year(2024))

    assert numbers(tracked) == [(known.pk, 1), (unknown.pk, 2)]


def test_a_removed_row_does_not_shift_the_number(tracked):
    first = make_run(tracked)
    removed = make_run(tracked, removed_at=timezone.now())
    last = make_run(tracked)

    assert [pk for pk, _ in numbers(tracked)] == [first.pk, last.pk]
    assert numbers(tracked) == [(first.pk, 1), (last.pk, 2)]
    assert removed.pk not in {pk for pk, _ in numbers(tracked)}


def test_a_system_row_does_not_shift_the_number(tracked):
    first = make_run(tracked)
    bucket = make_run(
        tracked, kind=PlaythroughKind.IMPORTED_HISTORY, name="Imported history"
    )
    last = make_run(tracked)

    assert numbers(tracked) == [(first.pk, 1), (last.pk, 2)]
    assert bucket.pk not in {pk for pk, _ in numbers(tracked)}


def test_rows_that_share_every_other_key_are_ordered_by_identity(tracked):
    """The case the id key exists for."""
    stamp = timezone.now()
    created = sorted(
        [make_run(tracked, created_at=stamp) for _ in range(4)],
        key=lambda row: row.pk,
    )

    assert numbers(tracked) == [
        (row.pk, position) for position, row in enumerate(created, start=1)
    ]


def test_the_number_partitions_by_tracked_game(owned_library, tracked):
    other_game = Game.objects.create(library=owned_library, name="Tunic")
    other = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=other_game,
        tracked_at=timezone.now(),
    )
    make_run(tracked)
    theirs = make_run(other)

    assert numbers(other) == [(theirs.pk, 1)]


def test_a_blank_name_displays_as_the_number(tracked):
    make_run(tracked)
    row = with_display_number(Playthrough.objects.all()).get()

    assert display_name(row) == "Playthrough 1"


def test_a_named_row_displays_its_name(tracked):
    make_run(tracked, name="Blind run")
    row = with_display_number(Playthrough.objects.all()).get()

    assert display_name(row) == "Blind run"


def test_a_named_row_needs_no_number(tracked):
    """The bucket #700 creates carries a name."""
    bucket = make_run(
        tracked, kind=PlaythroughKind.IMPORTED_HISTORY, name="Imported history"
    )

    assert display_name(bucket) == "Imported history"


def test_a_blank_name_with_no_number_is_refused(tracked):
    """A row from outside the numbered queryset."""
    unnumbered = make_run(tracked)

    with pytest.raises(UnnumberedPlaythrough):
        display_name(unnumbered)


@pytest.mark.django_db(transaction=True)
def test_the_number_is_unchanged_across_a_rebuild(owned_user, owned_library):
    """A swap cannot reshuffle a total order."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked = PlayerGame.objects.get()
    for index in range(4):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key=f"run-{index}",
        )
    before = numbers(tracked)

    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert numbers(tracked) == before
    assert [number for _, number in before] == [1, 2, 3, 4, 5]
