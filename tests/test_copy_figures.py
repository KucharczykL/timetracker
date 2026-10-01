"""The statistics' copy figures."""

from datetime import UTC, datetime

import pytest
from django.utils import timezone
from entries import end_entry_access, record_entry
from graphs import default_graph
from historical_playtime_rows import record_row
from purchases import record_purchase
from session_rows import session_row

from games.end_ways import EndWay
from games.models import (
    EditionKind,
    Game,
    GameKind,
    LibraryEntry,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
)
from games.reads.copy_figures import (
    backlog_decrease_copies,
    bought_and_finished_copies,
    copies_matching,
    dropped_copies,
    finished_copies,
    finished_released_copies,
    owned,
    owned_held,
    played_copies,
    unfinished_copies,
)
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

YEAR = 2021
IN_YEAR = TemporalValue.parse(f"{YEAR}-03-01")
BEFORE = TemporalValue.parse(f"{YEAR - 1}-03-01")


def copy_of(
    library,
    name: str,
    *,
    access: str = "owned",
    acquired: TemporalValue | None = IN_YEAR,
    edition_kind: EditionKind | None = None,
    year_released: int | None = None,
    kind: GameKind = GameKind.MAIN,
    parent: Game | None = None,
) -> LibraryEntry:
    game = Game(
        library=library,
        name=name,
        year_released=year_released,
        kind=kind,
        parent=parent,
    )
    graph = default_graph(game, library, edition_kind=edition_kind)
    return record_entry(library, graph.release, access=access, acquired=acquired)


def state(entry: LibraryEntry, **facts) -> LibraryEntry:
    PlayerGame.objects.filter(pk=entry.player_game_id).update(**facts)
    return entry


def complete(entry: LibraryEntry, value: str | None) -> LibraryEntry:
    Playthrough.objects.filter(player_game=entry.player_game_id).update(
        completed=None if value is None else TemporalValue.parse(value),
        completion_recorded_at=timezone.now(),
    )
    return entry


def matching(library, entry_filter) -> set[LibraryEntry]:
    return set(copies_matching(library, entry_filter))


@pytest.mark.parametrize("year", [YEAR, None])
def test_unfinished_counts_owned_held_full_copies(owned_library, year):
    kept = copy_of(owned_library, "Kept")
    copy_of(owned_library, "Rented", access="rented")
    end_entry_access(copy_of(owned_library, "Sold"), way=EndWay.SOLD)
    copy_of(owned_library, "Demo", edition_kind=EditionKind.PRERELEASE)
    state(copy_of(owned_library, "Excluded"), excluded_from_unfinished=True)
    state(copy_of(owned_library, "Abandoned"), status=PlayerGameStatus.ABANDONED)
    state(copy_of(owned_library, "Done"), status=PlayerGameStatus.COMPLETED)
    complete(copy_of(owned_library, "Finished"), f"{YEAR}-06-01")

    assert matching(owned_library, unfinished_copies(year)) == {kept}


def test_unfinished_reads_acquisition_by_containment(owned_library):
    copy_of(owned_library, "Straddle", acquired=TemporalValue.parse("2021-12/2022-01"))

    assert matching(owned_library, unfinished_copies(2021)) == set()
    assert matching(owned_library, unfinished_copies(2022)) == set()
    assert len(matching(owned_library, unfinished_copies(None))) == 1


def test_a_finish_in_another_year_leaves_it_unfinished_for_this_one(owned_library):
    copy = complete(copy_of(owned_library, "Later"), f"{YEAR + 1}-06-01")

    assert matching(owned_library, unfinished_copies(YEAR)) == {copy}
    assert matching(owned_library, unfinished_copies(None)) == set()


def test_unfinished_denominator_is_owned_held_full(owned_library):
    held = copy_of(owned_library, "Held")
    end_entry_access(copy_of(owned_library, "Sold"), way=EndWay.SOLD)
    copy_of(owned_library, "Rented", access="rented")

    assert matching(owned_library, owned_held(YEAR)) == {held}
    assert len(matching(owned_library, owned(YEAR))) == 2


@pytest.mark.parametrize("year", [YEAR, None])
def test_dropped_is_abandoned_or_refund_ended(owned_library, year):
    abandoned = state(
        copy_of(owned_library, "Abandoned"), status=PlayerGameStatus.ABANDONED
    )
    refunded = end_entry_access(copy_of(owned_library, "Refunded"), way=EndWay.REFUNDED)
    end_entry_access(copy_of(owned_library, "Sold"), way=EndWay.SOLD)
    state(
        copy_of(owned_library, "Hidden"),
        status=PlayerGameStatus.ABANDONED,
        excluded_from_dropped=True,
    )
    complete(
        state(copy_of(owned_library, "Finished"), status=PlayerGameStatus.ABANDONED),
        f"{YEAR}-06-01",
    )

    assert matching(owned_library, dropped_copies(year)) == {abandoned, refunded}


def test_backlog_decrease_for_a_year(owned_library):
    decreased = complete(
        state(
            copy_of(owned_library, "Old", acquired=BEFORE),
            status=PlayerGameStatus.COMPLETED,
        ),
        f"{YEAR}-06-01",
    )
    complete(
        state(copy_of(owned_library, "New"), status=PlayerGameStatus.COMPLETED),
        f"{YEAR}-06-01",
    )
    state(
        copy_of(owned_library, "Undated", acquired=BEFORE),
        status=PlayerGameStatus.COMPLETED,
    )

    assert matching(owned_library, backlog_decrease_copies(YEAR)) == {decreased}


def test_backlog_decrease_all_time(owned_library):
    done = state(copy_of(owned_library, "Done"), status=PlayerGameStatus.RETIRED)
    finished = complete(copy_of(owned_library, "Finished"), None)
    complete(copy_of(owned_library, "Rented", access="rented"), "2021-06-01")

    assert matching(owned_library, backlog_decrease_copies(None)) == {done, finished}


def test_finished_counts_any_access(owned_library):
    rented = complete(copy_of(owned_library, "Rented", access="rented"), "2021-06-01")
    owned_copy = complete(copy_of(owned_library, "Owned"), "2021-06-01")
    copy_of(owned_library, "Playing")

    assert matching(owned_library, finished_copies(YEAR)) == {rented, owned_copy}


def test_finished_all_time_takes_a_done_status(owned_library):
    done = state(copy_of(owned_library, "Done"), status=PlayerGameStatus.COMPLETED)

    assert matching(owned_library, finished_copies(None)) == {done}
    assert matching(owned_library, finished_copies(YEAR)) == set()


def test_finished_released_reads_the_release_year(owned_library):
    fresh = complete(copy_of(owned_library, "Fresh", year_released=YEAR), "2021-06-01")
    complete(copy_of(owned_library, "Old", year_released=YEAR - 5), "2021-06-01")

    assert matching(owned_library, finished_released_copies(YEAR)) == {fresh}


def test_bought_and_finished_leaves_a_refunded_copy(owned_library):
    bought = complete(copy_of(owned_library, "Bought"), "2021-06-01")
    end_entry_access(
        complete(copy_of(owned_library, "Refunded"), "2021-06-01"),
        way=EndWay.REFUNDED,
    )
    complete(copy_of(owned_library, "Earlier", acquired=BEFORE), "2021-06-01")

    assert matching(owned_library, bought_and_finished_copies(YEAR)) == {bought}


def test_played_copies_take_a_session_or_a_record(owned_library):
    sessioned = copy_of(owned_library, "Sessioned", year_released=YEAR)
    recorded = copy_of(owned_library, "Recorded", year_released=YEAR)
    copy_of(owned_library, "Idle", year_released=YEAR)
    old = copy_of(owned_library, "Old", year_released=YEAR - 1)
    session_row(
        sessioned.player_game.game, started_at=datetime(YEAR, 6, 1, 12, tzinfo=UTC)
    )
    session_row(old.player_game.game, started_at=datetime(YEAR, 6, 1, 12, tzinfo=UTC))
    record_row(
        list(Playthrough.objects.filter(player_game=recorded.player_game_id)),
        when=f"{YEAR}-05",
    )

    assert matching(owned_library, played_copies(YEAR)) == {sessioned, recorded}
    assert matching(owned_library, played_copies(None)) == {sessioned, recorded, old}


def test_a_pass_purchase_holds_no_backlog_place(owned_library):
    base = copy_of(owned_library, "Base")
    record_purchase(base, kind="season_pass", name="Pass", purchased=IN_YEAR)

    assert matching(owned_library, unfinished_copies(YEAR)) == {base}


def test_a_dlc_copy_counts_through_its_own_game(owned_library):
    base = state(copy_of(owned_library, "Base"), status=PlayerGameStatus.COMPLETED)
    dlc = copy_of(
        owned_library, "Expansion", kind=GameKind.DLC, parent=base.player_game.game
    )

    assert matching(owned_library, unfinished_copies(YEAR)) == {dlc}
