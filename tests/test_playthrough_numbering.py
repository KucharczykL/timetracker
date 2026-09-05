"""Playthrough N, derived at read time."""

import uuid

import pytest
from django.db import connection, transaction
from django.utils import timezone

from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.playthrough import playthrough_created
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
    columns.setdefault("id", uuid.uuid7())
    columns.setdefault("kind", PlaythroughKind.ORDINARY)
    return Playthrough.objects.create(
        library=tracked.library,
        player_game=tracked,
        started=started,
        completed=completed,
        created_at=created_at or timezone.now(),
        **columns,
    )


def numbered(tracked):
    """The one queryset every assertion below reads."""
    return with_display_number(
        Playthrough.objects.filter(player_game=tracked)
    ).order_by("display_number")


def numbers(tracked):
    return [(row.pk, row.display_number) for row in numbered(tracked)]


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
    """The case the id key exists for.

    Written highest key first, so the wanted order is the one order the
    rows were not written in. A window over peers follows the plan's
    input order, and the planner is held to a sort: reading
    `playthrough_display_order` would answer in key order whether or not
    the key is in the window, which is how this test would pass without
    testing anything.
    """
    stamp = timezone.now()
    identities = sorted(uuid.uuid7() for _ in range(4))
    for identity in reversed(identities):
        make_run(tracked, id=identity, created_at=stamp)
    #: Held for the rest of this test's transaction, which the plain
    #: `django_db` mark supplies. Under `transaction=True` there is none,
    #: and `SET LOCAL` reverts with no error -- so the plan is asserted
    #: below rather than assumed.
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_indexscan = off")
        cursor.execute("SET LOCAL enable_bitmapscan = off")

    #: The plan of the query the assertion below runs, not of a cousin.
    assert "Seq Scan" in numbered(tracked).explain()

    assert numbers(tracked) == [
        (identity, position) for position, identity in enumerate(identities, start=1)
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
    """A swap cannot reshuffle a total order.

    Five runs: the one `TrackGame` creates, then four in one append,
    which stamps one `recorded_at` across every event it writes. Those
    four tie on all three of the earlier sort fields, so only the key
    tells them apart.
    """
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked = PlayerGame.objects.get()
    with transaction.atomic():
        lock_stream(owned_library).append(
            [playthrough_created(tracked.pk) for _ in range(4)],
            actor=owned_user,
            correlation_id=uuid.uuid7(),
            idempotency_key="four-runs",
        )
    before = numbers(tracked)
    #: Two stamps over the five rows -- one per append -- so the four
    #: that went up together really do tie.
    assert len({row.created_at for row in Playthrough.objects.all()}) == 2

    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert numbers(tracked) == before
    assert [number for _, number in before] == [1, 2, 3, 4, 5]
