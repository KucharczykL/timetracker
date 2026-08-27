# PlayerGame Baseline Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn every catalog game a library holds into a game the library tracks, by recording baseline `PlayerGame` events and letting the `PlayerGames` projector fold them.

**Architecture:** A new `games/backfill/` package holds the logic; a data migration and `load_sample_data` are two callers of it. Per game it appends up to four events — one creation, an optional mastery fact, one status fact per legacy `GameStatusChange` row, and a corrective status fact when those do not fold to `Game.status`. Each event is its own `idempotent_append` with its own `recorded_at`, `effective_time` and deterministic key, because `LockedStream.append()` stamps one timestamp across a whole call.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django, the in-repo event machinery (`games/events/`), `timetracker.temporal.TemporalValue`.

**Spec:** `docs/superpowers/specs/2026-08-27-issue-676-playergame-baseline-backfill-design.md`

## Global Constraints

- Run everything through `make`. Never `direnv exec .`, never a raw `uv run` or `pytest`. Focused runs are `make test ARGS="tests/test_playergame_backfill.py -k created -x"`.
- Iterate with `make check-fast`. The gate before declaring done is the full `make check`, including `e2e/`.
- Python 3.14 is a hard prerequisite. `python --version` must read 3.14.x.
- Never write to a `GeneratedField`: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`.
- Never write a `PlayerGame` row directly. Only the `PlayerGames` projector writes it, and it is driven by appended events.
- Name variables with complete words: `event` not `e`, `element` not `el`, `change` not `c`.
- Name compound types explicitly. A `tuple`/`dict` crossing a function boundary gets a `TypedDict`, `NamedTuple`, `dataclass` or `type` alias.
- One act, one verb: an event type, its command and its projection column share one verb.
- `PGAME_ISSUE = 676` and `KEY_PREFIX = "backfill:676:playergame"` are the literal values used throughout. Idempotency keys must stay within 255 characters.
- The status map is exactly: `"u"` → `unplayed`, `"p"` → `played`, `"f"` → `completed`, `"r"` → `retired`, `"a"` → `abandoned`. `shelved` has no legacy source and is never emitted.
- Machine reconciliation prefix: `PLAYERGAME_BASELINE_RECONCILIATION_JSON=`. Human prefix: `PGAME baseline reconciliation:`.

---

## File Structure

**Create:**

- `games/backfill/__init__.py` — opens the package, no contents.
- `games/backfill/playergame.py` — the whole backfill: status map, temporal helpers, per-game emission, per-library driver, pre-flight scan, reconciliation. One responsibility (turn catalog rows into baseline events), and it sits beside `games/commands/playergame.py` and `games/projectors/playergame.py` so the three modules of this aggregate are neighbours.
- `games/migrations/0033_playergame_baseline_backfill.py` — the vehicle: run, run again, reconcile, emit, fail.
- `tests/test_playergame_backfill.py` — everything about the module.
- `tests/test_playergame_backfill_migration.py` — the migration through `MigrationExecutor`, mirroring `tests/test_catalog_hierarchy_migration.py`.

**Modify:**

- `games/management/commands/load_sample_data.py` — one call inside the existing `transaction.atomic()` block.

**Why one module and not several:** the backfill is a single pass with one shared vocabulary of counts and mismatches. Splitting emission from reconciliation would put the count types in a third file and give two importers of the same constants. It stays under roughly 250 lines.

---

### Task 1: The status map and the temporal helpers

The pure parts, with no database writes. Getting the map and the two temporal
rules right first means every later task asserts against settled behaviour.

**Files:**
- Create: `games/backfill/__init__.py`
- Create: `games/backfill/playergame.py`
- Create: `tests/test_playergame_backfill.py`

**Interfaces:**
- Consumes: `games.models.Game.Status`, `games.models.PlayerGameStatus`, `timetracker.temporal.TemporalValue`.
- Produces:
  - `PGAME_ISSUE: int`
  - `KEY_PREFIX: str`
  - `LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus]`
  - `type LegacyStatus = str`
  - `class UnmappedLegacyStatus(ValueError)`
  - `def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus`
  - `def transition_effective_time(timestamp: datetime | None) -> TemporalValue`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playergame_backfill.py`:

```python
"""Backfilling the baseline events a library's tracked games fold from."""

from datetime import datetime, timedelta, timezone as datetime_timezone

import pytest
from django.utils import timezone

from games.backfill.playergame import (
    LEGACY_STATUS_TO_PLAYER_STATUS,
    UnmappedLegacyStatus,
    player_status_for,
    transition_effective_time,
)
from games.models import Game, PlayerGameStatus


def test_every_legacy_status_letter_is_mapped():
    #: A sixth letter added to Game.Status fails here rather than at run time.
    assert set(LEGACY_STATUS_TO_PLAYER_STATUS) == set(Game.Status.values)


def test_the_map_names_the_statuses_the_charter_names():
    assert LEGACY_STATUS_TO_PLAYER_STATUS == {
        "u": PlayerGameStatus.UNPLAYED,
        "p": PlayerGameStatus.PLAYED,
        "f": PlayerGameStatus.COMPLETED,
        "r": PlayerGameStatus.RETIRED,
        "a": PlayerGameStatus.ABANDONED,
    }


def test_shelved_has_no_legacy_source():
    assert PlayerGameStatus.SHELVED not in LEGACY_STATUS_TO_PLAYER_STATUS.values()


def test_an_unknown_letter_is_refused_by_name():
    with pytest.raises(UnmappedLegacyStatus, match="'z'"):
        player_status_for("z")


def test_a_null_timestamp_stays_unknown():
    #: The charter puts an undated transition in approximate history only.
    assert transition_effective_time(None).is_unknown


def test_a_dated_timestamp_becomes_the_local_day():
    #: 23:30 UTC is already the next day in Europe/Prague.
    timestamp = datetime(2023, 6, 2, 23, 30, tzinfo=datetime_timezone.utc)
    expected = timezone.localtime(timestamp).date().isoformat()
    assert transition_effective_time(timestamp).serialize() == expected


def test_a_dated_timestamp_is_day_precision_not_a_range():
    timestamp = timezone.now() - timedelta(days=400)
    value = transition_effective_time(timestamp)
    assert value.is_range is False
    assert value.has_known_day is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_backfill.py -x"`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'games.backfill'`.

- [ ] **Step 3: Create the package**

Create `games/backfill/__init__.py` as an empty file (zero bytes).

- [ ] **Step 4: Write the minimal implementation**

Create `games/backfill/playergame.py`:

```python
"""Baseline PlayerGame events for the games a library already holds.

Issue #676. The catalog states which games a library has; the event log
states nothing until this runs. Every live game becomes a tracked game,
expressed as events and folded by the PlayerGames projector, because a
projection row is written by its projector and by nothing else.
"""

from collections.abc import Mapping
from datetime import datetime

from django.utils import timezone

from games.models import Game, PlayerGameStatus
from timetracker.temporal import TemporalValue

#: Names the issue in every key and every source_metadata blob.
PGAME_ISSUE = 676
KEY_PREFIX = "backfill:676:playergame"

#: One letter of Game.Status.
type LegacyStatus = str  # "f"

#: A recorded payload cannot be upcast, so the letters become words here and
#: never reach an event. SHELVED is absent: no legacy column states it.
LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus] = {
    Game.Status.UNPLAYED: PlayerGameStatus.UNPLAYED,
    Game.Status.PLAYED: PlayerGameStatus.PLAYED,
    Game.Status.FINISHED: PlayerGameStatus.COMPLETED,
    Game.Status.RETIRED: PlayerGameStatus.RETIRED,
    Game.Status.ABANDONED: PlayerGameStatus.ABANDONED,
}


class UnmappedLegacyStatus(ValueError):
    """Raised for a legacy letter the map does not know."""


def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus:
    """The word a recorded payload carries for one legacy letter."""
    try:
        return LEGACY_STATUS_TO_PLAYER_STATUS[legacy_status]
    except KeyError:
        raise UnmappedLegacyStatus(
            f"{legacy_status!r} is not a legacy status this backfill maps. "
            "Every member of Game.Status names a PlayerGameStatus."
        ) from None


def transition_effective_time(timestamp: datetime | None) -> TemporalValue:
    """When the transition happened, at the precision that is honest.

    A non-null legacy timestamp is the effective transition time rather than
    a recording time: live signals wrote the moment of the player's action,
    and the original data migration used the earliest Session, the refund or
    drop date, or the PlayEvent completion date. A null one stays unknown, so
    it enters approximate history rather than claiming a day.
    """
    if timestamp is None:
        return TemporalValue.unknown()
    return TemporalValue.from_day(timezone.localtime(timestamp).date())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_backfill.py -x"`
Expected: PASS, 7 tests.

- [ ] **Step 6: Commit**

```bash
git add games/backfill/__init__.py games/backfill/playergame.py tests/test_playergame_backfill.py
git commit -m "Map legacy statuses and date their transitions"
```

---

### Task 2: Emitting one game's baseline facts

The core. Four facts per game, each its own append, each with its own two
times.

**Files:**
- Modify: `games/backfill/playergame.py`
- Test: `tests/test_playergame_backfill.py`

**Interfaces:**
- Consumes: `player_status_for`, `transition_effective_time`, `KEY_PREFIX`, `PGAME_ISSUE` from Task 1.
- Produces:
  - `@dataclass(frozen=True, slots=True) class BackfillCounts` with integer fields `games`, `tracked`, `created_events`, `status_events`, `mastered_events`, `corrective_events`, `unknown_effective_times`, `skipped_tombstoned`, and an `__add__` returning `BackfillCounts`.
  - `NO_COUNTS: BackfillCounts` — the all-zero value to accumulate from.
  - `def backfill_game(game: Game, *, library: UserLibrary, actor: User, run_time: datetime) -> BackfillCounts`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_backfill.py`. Add these imports to the existing import block at the top of the file:

```python
import uuid

from games.backfill.playergame import backfill_game
from games.models import GameStatusChange, LibraryEvent, PlayerGame
```

Then append the tests:

```python
def backdate(game, created_at):
    """Game.created_at is auto_now_add, so a test moves it with UPDATE."""
    Game.objects.filter(pk=game.pk).update(created_at=created_at)
    game.refresh_from_db()
    return game


def run_for(game, owned_user, owned_library, run_time=None):
    return backfill_game(
        game,
        library=owned_library,
        actor=owned_user,
        run_time=run_time or timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_an_unplayed_game_with_no_history_records_only_its_creation(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(library=owned_library, name="Outer Wilds"), added
    )

    counts = run_for(game, owned_user, owned_library)

    assert (counts.created_events, counts.status_events) == (1, 0)
    assert counts.corrective_events == 0
    event = LibraryEvent.objects.get()
    assert event.event_type == "library.playergame.created"
    assert event.recorded_at == added
    assert event.effective_time is None
    assert event.source_metadata == {"origin": "backfill", "issue": 676}
    row = PlayerGame.objects.get()
    assert (row.status, row.tracked_at) == (PlayerGameStatus.UNPLAYED, added)


@pytest.mark.django_db(transaction=True)
def test_a_finished_game_with_no_history_gets_an_undated_corrective_event(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    run_time = timezone.now()
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Tunic", status=Game.Status.FINISHED
        ),
        added,
    )

    counts = run_for(game, owned_user, owned_library, run_time=run_time)

    assert (counts.status_events, counts.corrective_events) == (0, 1)
    assert counts.unknown_effective_times == 1
    corrective = LibraryEvent.objects.get(
        event_type="library.playergame.status_changed"
    )
    assert corrective.payload == {"status": "completed"}
    #: auto_now would be a fabrication; the run time is the honest recording.
    assert corrective.recorded_at == run_time
    assert corrective.effective_time is None
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_dated_history_that_reaches_the_current_status_needs_no_correction(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Hades", status=Game.Status.FINISHED
        ),
        added,
    )
    played_at = added + timedelta(days=10)
    finished_at = added + timedelta(days=40)
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=played_at
    )
    GameStatusChange.objects.create(
        game=game, old_status="p", new_status="f", timestamp=finished_at
    )

    counts = run_for(game, owned_user, owned_library)

    assert (counts.status_events, counts.corrective_events) == (2, 0)
    statuses = list(
        LibraryEvent.objects.filter(event_type="library.playergame.status_changed")
        .order_by("sequence")
        .values_list("payload", "recorded_at")
    )
    assert [payload["status"] for payload, _ in statuses] == ["played", "completed"]
    assert [recorded_at for _, recorded_at in statuses] == [played_at, finished_at]
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_dated_history_that_misses_the_current_status_is_corrected(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Celeste", status=Game.Status.ABANDONED
        ),
        added,
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=added + timedelta(days=3)
    )

    counts = run_for(game, owned_user, owned_library)

    assert (counts.status_events, counts.corrective_events) == (1, 1)
    assert PlayerGame.objects.get().status == PlayerGameStatus.ABANDONED


@pytest.mark.django_db(transaction=True)
def test_a_dated_transition_carries_its_local_day_and_names_its_source_row(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Inscryption", status=Game.Status.PLAYED
        ),
        added,
    )
    played_at = added + timedelta(days=10)
    change = GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=played_at
    )

    run_for(game, owned_user, owned_library)

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    assert event.effective_time.serialize() == (
        timezone.localtime(played_at).date().isoformat()
    )
    assert event.source_metadata == {
        "origin": "backfill",
        "issue": 676,
        "status_change_id": str(change.pk),
    }


@pytest.mark.django_db(transaction=True)
def test_an_undated_transition_records_an_unknown_effective_time(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Braid", status=Game.Status.PLAYED
        ),
        added,
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=None
    )

    counts = run_for(game, owned_user, owned_library)

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    assert event.effective_time is None
    #: Not coerced to a date; only the recording falls back to created_at.
    assert event.recorded_at == added
    assert counts.unknown_effective_times == 1


@pytest.mark.django_db(transaction=True)
def test_undated_transitions_are_folded_before_dated_ones(owned_user, owned_library):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Hollow Knight", status=Game.Status.FINISHED
        ),
        added,
    )
    GameStatusChange.objects.create(
        game=game, old_status="p", new_status="f", timestamp=added + timedelta(days=9)
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=None
    )

    counts = run_for(game, owned_user, owned_library)

    ordered = list(
        LibraryEvent.objects.filter(event_type="library.playergame.status_changed")
        .order_by("sequence")
        .values_list("payload", flat=True)
    )
    assert [payload["status"] for payload in ordered] == ["played", "completed"]
    assert counts.corrective_events == 0


@pytest.mark.django_db(transaction=True)
def test_a_mastered_game_records_the_mastery_fact(owned_user, owned_library):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(library=owned_library, name="Katana Zero", mastered=True),
        added,
    )

    counts = run_for(game, owned_user, owned_library)

    assert counts.mastered_events == 1
    event = LibraryEvent.objects.get(event_type="library.playergame.mastered_changed")
    assert event.payload == {"mastered": True}
    assert event.recorded_at == added
    assert event.effective_time is None
    assert PlayerGame.objects.get().mastered is True


@pytest.mark.django_db(transaction=True)
def test_an_unmastered_game_records_no_mastery_fact(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Gris")

    counts = run_for(game, owned_user, owned_library)

    assert counts.mastered_events == 0
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.mastered_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_no_exclusion_or_archive_fact_is_invented(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Signalis", status=Game.Status.RETIRED
    )

    run_for(game, owned_user, owned_library)

    recorded = set(LibraryEvent.objects.values_list("event_type", flat=True))
    assert "library.playergame.excluded_from_unfinished_changed" not in recorded
    assert "library.playergame.archived" not in recorded
    assert PlayerGame.objects.get().archived_at is None


@pytest.mark.django_db(transaction=True)
def test_running_a_game_twice_appends_nothing_the_second_time(
    owned_user, owned_library
):
    game = Game.objects.create(
        library=owned_library, name="Disco Elysium", status=Game.Status.FINISHED
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="f", timestamp=timezone.now()
    )

    first = run_for(game, owned_user, owned_library)
    before = LibraryEvent.objects.count()
    second = run_for(game, owned_user, owned_library)

    assert first.created_events == 1
    assert LibraryEvent.objects.count() == before
    assert (second.created_events, second.status_events) == (0, 0)
    assert (second.mastered_events, second.corrective_events) == (0, 0)
    assert second.tracked == 1
    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_creation_event_is_always_sequenced_first(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.FINISHED
    )

    run_for(game, owned_user, owned_library)

    first = LibraryEvent.objects.order_by("sequence").first()
    assert first.event_type == "library.playergame.created"
    assert first.payload["game"]["id"] == str(game.pk)
    assert first.aggregate_id == PlayerGame.objects.get().pk


@pytest.mark.django_db(transaction=True)
def test_every_baseline_event_names_the_library_owner_as_actor(
    owned_user, owned_library
):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.PLAYED
    )

    run_for(game, owned_user, owned_library)

    actors = set(LibraryEvent.objects.values_list("actor_id", flat=True))
    assert actors == {owned_user.pk}


@pytest.mark.django_db(transaction=True)
def test_each_baseline_event_gets_its_own_correlation_id(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.PLAYED
    )

    run_for(game, owned_user, owned_library)

    correlation_ids = list(
        LibraryEvent.objects.values_list("correlation_id", flat=True)
    )
    assert len(correlation_ids) == len(set(correlation_ids)) == 2
    assert all(isinstance(value, uuid.UUID) for value in correlation_ids)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_backfill.py -x"`
Expected: FAIL at collection with `ImportError: cannot import name 'backfill_game'`.

- [ ] **Step 3: Write the implementation**

Add to `games/backfill/playergame.py`. Extend the import block at the top to:

```python
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, cast

from django.contrib.auth.models import User
from django.db.models import F
from django.utils import timezone

from games.events.append import LockedStream, SourceMetadata
from games.events.idempotency import ReplayedAppend, idempotent_append
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent
from games.models import (
    Game,
    GameStatusChange,
    PlayerGame,
    PlayerGameStatus,
    UserLibrary,
)
from timetracker.temporal import TemporalValue
```

Then append below the Task 1 helpers:

```python
@dataclass(frozen=True, slots=True)
class BackfillCounts:
    """What one pass did, summable across games and libraries."""

    games: int = 0
    tracked: int = 0
    created_events: int = 0
    status_events: int = 0
    mastered_events: int = 0
    corrective_events: int = 0
    unknown_effective_times: int = 0
    skipped_tombstoned: int = 0

    def __add__(self, other: "BackfillCounts") -> "BackfillCounts":
        return BackfillCounts(
            games=self.games + other.games,
            tracked=self.tracked + other.tracked,
            created_events=self.created_events + other.created_events,
            status_events=self.status_events + other.status_events,
            mastered_events=self.mastered_events + other.mastered_events,
            corrective_events=self.corrective_events + other.corrective_events,
            unknown_effective_times=(
                self.unknown_effective_times + other.unknown_effective_times
            ),
            skipped_tombstoned=self.skipped_tombstoned + other.skipped_tombstoned,
        )


#: The value an accumulation starts from.
NO_COUNTS = BackfillCounts()


def _append(
    library: UserLibrary,
    event: NewEvent,
    *,
    actor: User,
    idempotency_key: str,
    command_input: dict[str, Any],
    recorded_at: datetime,
    source_metadata: SourceMetadata,
) -> bool:
    """Append one event, or replay its key. True when it appended.

    One append per event, never one append per game: LockedStream.append()
    stamps one recorded_at across every row of a call, and these events carry
    four different dates.

    dispatch() is not used. It needs a Command, and a command validates
    against current state to refuse a duplicate -- SetPlayerGameStatus rejects
    the status a game already has, which is the ordinary case here.
    run_in_transaction is not used either: its retry answers a concurrent
    writer, and a backfill has none.
    """

    def build(stream: LockedStream) -> Sequence[NewEvent]:
        #: The append contract passes it; nothing here consults it.
        del stream
        return [event]

    outcome = idempotent_append(
        library,
        idempotency_key=idempotency_key,
        command_input=command_input,
        build=build,
        actor=actor,
        #: Its own, per event. #685 pairs these with lifecycle facts later, and
        #: adopts these ids rather than mutating an immutable column.
        correlation_id=uuid.uuid7(),
        source_metadata=source_metadata,
        recorded_at=recorded_at,
    )
    return not isinstance(outcome, ReplayedAppend)


def _legacy_changes(game: Game) -> list[GameStatusChange]:
    """One game's status history, oldest first, undated first.

    The order is stated rather than inherited: GameStatusChange.Meta.ordering
    is -timestamp, and a descending fold would end on the oldest fact.
    """
    return list(
        GameStatusChange.objects.filter(game=game).order_by(
            F("timestamp").asc(nulls_first=True), "pk"
        )
    )


def backfill_game(
    game: Game, *, library: UserLibrary, actor: User, run_time: datetime
) -> BackfillCounts:
    """Record the baseline facts for one game this library holds."""
    metadata: SourceMetadata = {"origin": "backfill", "issue": PGAME_ISSUE}
    counts = BackfillCounts(games=1, tracked=1)

    #: Always first. amend() raises ProjectionRowMissing against a row no
    #: creation event made, so every later fact depends on this one.
    if _append(
        library,
        PLAYERGAME_CREATED.new(
            aggregate_id=uuid.uuid7(),
            payload={"game": capture_reference(game)},
        ),
        actor=actor,
        idempotency_key=f"{KEY_PREFIX}:created:{game.pk}",
        command_input={"fact": "created", "game_id": str(game.pk)},
        #: A real recording time: the row was written then, and the projector
        #: takes tracked_at from it.
        recorded_at=game.created_at,
        source_metadata=metadata,
    ):
        counts = replace(counts, created_events=1)

    #: The projector wrote the row synchronously, inside this transaction.
    tracked_id = PlayerGame.objects.values_list("pk", flat=True).get(
        library=library, game=game
    )

    if game.mastered and _append(
        library,
        PLAYERGAME_MASTERED_CHANGED.new(
            aggregate_id=tracked_id,
            payload={"mastered": True},
        ),
        actor=actor,
        idempotency_key=f"{KEY_PREFIX}:mastered:{game.pk}",
        command_input={"fact": "mastered", "game_id": str(game.pk)},
        recorded_at=game.created_at,
        source_metadata=metadata,
    ):
        counts = replace(counts, mastered_events=1)

    folded = PlayerGameStatus.UNPLAYED
    for change in _legacy_changes(game):
        status = player_status_for(change.new_status)
        effective_time = transition_effective_time(change.timestamp)
        if _append(
            library,
            PLAYERGAME_STATUS_CHANGED.new(
                aggregate_id=tracked_id,
                #: A test pins Literal and choices equal.
                payload={"status": cast("StatusValue", status.value)},
                effective_time=effective_time,
            ),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:status:{change.pk}",
            command_input={"fact": "status", "status_change_id": str(change.pk)},
            recorded_at=change.timestamp or game.created_at,
            source_metadata={**metadata, "status_change_id": str(change.pk)},
        ):
            counts = replace(counts, status_events=counts.status_events + 1)
            if effective_time.is_unknown:
                counts = replace(
                    counts,
                    unknown_effective_times=counts.unknown_effective_times + 1,
                )
        #: old_status is ignored: the fold sets a value rather than applying a
        #: delta, so a broken chain cannot change the result.
        folded = status

    current = player_status_for(game.status)
    if folded != current and _append(
        library,
        PLAYERGAME_STATUS_CHANGED.new(
            aggregate_id=tracked_id,
            payload={"status": cast("StatusValue", current.value)},
            #: Game.updated_at is auto_now -- the last time any field moved --
            #: so dating this with it would fabricate precision the charter
            #: forbids. The status is known; when it changed is not.
            effective_time=TemporalValue.unknown(),
        ),
        actor=actor,
        idempotency_key=f"{KEY_PREFIX}:status:current:{game.pk}",
        command_input={
            "fact": "status_current",
            "game_id": str(game.pk),
            #: Named, so a changed current status is a loud mismatch.
            "status": current.value,
        },
        recorded_at=run_time,
        source_metadata=metadata,
    ):
        counts = replace(
            counts,
            corrective_events=1,
            unknown_effective_times=counts.unknown_effective_times + 1,
        )

    return counts
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_backfill.py -x"`
Expected: PASS, 21 tests.

- [ ] **Step 5: Run the type checker**

Run: `make typecheck`
Expected: no errors. If mypy complains that `PlayerGame.objects.values_list(...).get(...)` is `Any`, annotate the local as `tracked_id: uuid.UUID`.

- [ ] **Step 6: Commit**

```bash
git add games/backfill/playergame.py tests/test_playergame_backfill.py
git commit -m "Record one game's baseline facts as events"
```

---

### Task 3: The per-library driver, its skips, and its ordering

**Files:**
- Modify: `games/backfill/playergame.py`
- Test: `tests/test_playergame_backfill.py`

**Interfaces:**
- Consumes: `backfill_game`, `BackfillCounts`, `NO_COUNTS` from Task 2.
- Produces: `def backfill_library(library: UserLibrary, *, run_time: datetime | None = None) -> BackfillCounts`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_backfill.py`. Add to the import block:

```python
from games.backfill.playergame import backfill_library
from games.events.rebuild import RebuildMode, rebuild_projections
```

Then append:

```python
@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")


@pytest.fixture
def other_library(other_user):
    return other_user.library


@pytest.mark.django_db(transaction=True)
def test_a_library_tracks_every_live_game_it_holds(owned_user, owned_library):
    for name in ("Outer Wilds", "Tunic", "Hades"):
        Game.objects.create(library=owned_library, name=name)

    counts = backfill_library(owned_library)

    assert (counts.games, counts.tracked, counts.created_events) == (3, 3, 3)
    assert PlayerGame.objects.filter(library=owned_library).count() == 3


@pytest.mark.django_db(transaction=True)
def test_a_tombstoned_game_is_skipped(owned_user, owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")
    husk = Game.objects.create(library=owned_library, name="Deleted")
    Game.objects.filter(pk=husk.pk).update(tombstoned_at=timezone.now())

    counts = backfill_library(owned_library)

    assert (counts.games, counts.tracked, counts.skipped_tombstoned) == (2, 1, 1)
    assert not PlayerGame.objects.filter(game_id=husk.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_a_shared_game_is_not_tracked_by_the_backfill(owned_user, owned_library):
    #: No library: the shared catalog. #677 gives a player the way to track it.
    Game.objects.create(name="Shared Title")

    counts = backfill_library(owned_library)

    assert (counts.games, counts.tracked) == (0, 0)
    assert PlayerGame.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_one_librarys_backfill_leaves_another_alone(
    owned_user, owned_library, other_user, other_library
):
    Game.objects.create(library=owned_library, name="Mine")
    Game.objects.create(library=other_library, name="Theirs")

    backfill_library(owned_library)

    assert PlayerGame.objects.filter(library=other_library).count() == 0
    assert LibraryEvent.objects.filter(library=other_library).count() == 0
    assert PlayerGame.objects.get().library_id == owned_library.pk


@pytest.mark.django_db(transaction=True)
def test_running_a_library_twice_appends_nothing_the_second_time(
    owned_user, owned_library
):
    for name in ("Outer Wilds", "Tunic"):
        Game.objects.create(
            library=owned_library, name=name, status=Game.Status.FINISHED
        )

    first = backfill_library(owned_library)
    before = LibraryEvent.objects.count()
    second = backfill_library(owned_library)

    assert first.created_events == 2
    assert LibraryEvent.objects.count() == before
    assert (second.tracked, second.created_events) == (2, 0)
    assert (second.status_events, second.corrective_events) == (0, 0)


@pytest.mark.django_db(transaction=True)
def test_games_are_processed_oldest_first(owned_user, owned_library):
    now = timezone.now()
    newer = Game.objects.create(library=owned_library, name="Newer")
    older = Game.objects.create(library=owned_library, name="Older")
    Game.objects.filter(pk=newer.pk).update(created_at=now - timedelta(days=10))
    Game.objects.filter(pk=older.pk).update(created_at=now - timedelta(days=100))

    backfill_library(owned_library)

    ordered = list(
        LibraryEvent.objects.filter(event_type="library.playergame.created")
        .order_by("sequence")
        .values_list("payload", flat=True)
    )
    assert [payload["game"]["id"] for payload in ordered] == [
        str(older.pk),
        str(newer.pk),
    ]


@pytest.mark.django_db(transaction=True)
def test_the_projection_replays_from_the_backfilled_log_without_drift(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=300)
    for name, status in (("Outer Wilds", "f"), ("Tunic", "p"), ("Hades", "u")):
        game = Game.objects.create(library=owned_library, name=name, status=status)
        Game.objects.filter(pk=game.pk).update(created_at=added)
        GameStatusChange.objects.create(
            game=game, old_status="u", new_status=status, timestamp=None
        )

    backfill_library(owned_library)
    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [(0, 0, 0)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_backfill.py -k library -x"`
Expected: FAIL at collection with `ImportError: cannot import name 'backfill_library'`.

- [ ] **Step 3: Write the implementation**

Append to `games/backfill/playergame.py`:

```python
def backfill_library(
    library: UserLibrary, *, run_time: datetime | None = None
) -> BackfillCounts:
    """Record baseline facts for every live game this library holds.

    A shared game -- library is null -- is never reached: the query scopes to
    the library, and #677 gives a player the way to track one. A tombstoned
    game is skipped and counted: retention gutted the row and kept it only for
    the events that name it, so there is nothing left to track.
    """
    resolved_run_time = run_time or timezone.now()
    actor = library.user
    counts = NO_COUNTS
    #: Deterministic, so two runs order the stream identically.
    games = Game.objects.filter(library=library).order_by("created_at", "pk")
    for game in games.iterator(chunk_size=200):
        if game.tombstoned_at is not None:
            counts = counts + BackfillCounts(games=1, skipped_tombstoned=1)
            continue
        counts = counts + backfill_game(
            game,
            library=library,
            actor=actor,
            run_time=resolved_run_time,
        )
    return counts
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_backfill.py -x"`
Expected: PASS, 28 tests.

- [ ] **Step 5: Commit**

```bash
git add games/backfill/playergame.py tests/test_playergame_backfill.py
git commit -m "Backfill every live game one library holds"
```

---

### Task 4: The pre-flight scan and the reconciliation

**Files:**
- Modify: `games/backfill/playergame.py`
- Test: `tests/test_playergame_backfill.py`

**Interfaces:**
- Consumes: `player_status_for`, `LEGACY_STATUS_TO_PLAYER_STATUS`, `UnmappedLegacyStatus`.
- Produces:
  - `@dataclass(frozen=True, slots=True) class Mismatch` with `code: str`, `game_id: str`, `detail: str`, and `def as_dict(self) -> dict[str, str]`.
  - `def unmapped_statuses(library: UserLibrary) -> list[Mismatch]`
  - `def reconcile(library: UserLibrary) -> list[Mismatch]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_backfill.py`. Add to the import block:

```python
from games.backfill.playergame import Mismatch, reconcile, unmapped_statuses
```

Then append:

```python
@pytest.mark.django_db(transaction=True)
def test_a_clean_backfill_reconciles_with_no_mismatch(owned_user, owned_library):
    for name, status in (("Outer Wilds", "f"), ("Tunic", "u"), ("Hades", "a")):
        Game.objects.create(library=owned_library, name=name, status=status)

    backfill_library(owned_library)

    assert reconcile(owned_library) == []


@pytest.mark.django_db(transaction=True)
def test_a_game_with_no_projection_row_is_a_mismatch(owned_user, owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")
    #: Not backfilled: the row is simply absent.

    codes = [mismatch.code for mismatch in reconcile(owned_library)]

    assert codes == ["missing_projection_row"]


@pytest.mark.django_db(transaction=True)
def test_a_status_the_fold_missed_is_a_mismatch(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.UNPLAYED
    )
    backfill_library(owned_library)
    #: Move the catalog behind the projection's back.
    Game.objects.filter(pk=game.pk).update(status=Game.Status.FINISHED)

    mismatches = reconcile(owned_library)

    assert [mismatch.code for mismatch in mismatches] == ["status_disagreement"]
    assert mismatches[0].game_id == str(game.pk)
    assert "completed" in mismatches[0].detail


@pytest.mark.django_db(transaction=True)
def test_a_mastery_the_fold_missed_is_a_mismatch(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    backfill_library(owned_library)
    Game.objects.filter(pk=game.pk).update(mastered=True)

    assert [mismatch.code for mismatch in reconcile(owned_library)] == [
        "mastered_disagreement"
    ]


@pytest.mark.django_db(transaction=True)
def test_an_unmapped_catalog_letter_is_found_before_anything_is_appended(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(status="z")

    mismatches = unmapped_statuses(owned_library)

    assert [mismatch.code for mismatch in mismatches] == ["unmapped_legacy_status"]
    assert mismatches[0].game_id == str(game.pk)
    assert LibraryEvent.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_an_unmapped_history_letter_is_found_too(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    change = GameStatusChange.objects.create(
        game=game, old_status="u", new_status="u", timestamp=timezone.now()
    )
    GameStatusChange.objects.filter(pk=change.pk).update(new_status="z")

    mismatches = unmapped_statuses(owned_library)

    assert [mismatch.code for mismatch in mismatches] == ["unmapped_legacy_status"]
    assert str(change.pk) in mismatches[0].detail


@pytest.mark.django_db(transaction=True)
def test_a_mapped_library_pre_flights_clean(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.FINISHED
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="f", timestamp=timezone.now()
    )

    assert unmapped_statuses(owned_library) == []


def test_a_mismatch_serializes_to_sorted_json_safe_keys():
    mismatch = Mismatch(code="status_disagreement", game_id="abc", detail="x")

    assert mismatch.as_dict() == {
        "code": "status_disagreement",
        "detail": "x",
        "game_id": "abc",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_backfill.py -k 'reconcile or mismatch or unmapped or pre_flight' -x"`
Expected: FAIL at collection with `ImportError: cannot import name 'Mismatch'`.

- [ ] **Step 3: Write the implementation**

Append to `games/backfill/playergame.py`:

```python
@dataclass(frozen=True, slots=True)
class Mismatch:
    """One reason the backfill must not commit."""

    code: str
    game_id: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "game_id": self.game_id}


def unmapped_statuses(library: UserLibrary) -> list[Mismatch]:
    """Every legacy letter the map does not know, found before any append.

    A pre-flight rather than a KeyError mid-run: an unmapped letter is a
    reconciliation mismatch, reported with its neighbours and rolled back.
    """
    known = set(LEGACY_STATUS_TO_PLAYER_STATUS)
    mismatches = [
        Mismatch(
            code="unmapped_legacy_status",
            game_id=str(game_id),
            detail=f"catalog status {status!r}",
        )
        for game_id, status in Game.objects.filter(library=library)
        .exclude(status__in=known)
        .order_by("pk")
        .values_list("pk", "status")
    ]
    mismatches.extend(
        Mismatch(
            code="unmapped_legacy_status",
            game_id=str(game_id),
            detail=f"status change {change_id} records {status!r}",
        )
        for change_id, game_id, status in GameStatusChange.objects.filter(
            game__library=library
        )
        .exclude(new_status__in=known)
        .order_by("pk")
        .values_list("pk", "game_id", "new_status")
    )
    return mismatches


def reconcile(library: UserLibrary) -> list[Mismatch]:
    """Compare every live game against the row its events folded to."""
    rows = {
        row.game_id: row
        for row in PlayerGame.objects.filter(library=library).only(
            "game_id", "status", "mastered"
        )
    }
    mismatches: list[Mismatch] = []
    live = Game.objects.filter(library=library, tombstoned_at__isnull=True).order_by(
        "pk"
    )
    for game in live.iterator(chunk_size=200):
        row = rows.get(game.pk)
        if row is None:
            mismatches.append(
                Mismatch(
                    code="missing_projection_row",
                    game_id=str(game.pk),
                    detail="the backfill covered this game and no row folded",
                )
            )
            continue
        expected_status = player_status_for(game.status)
        if row.status != expected_status:
            mismatches.append(
                Mismatch(
                    code="status_disagreement",
                    game_id=str(game.pk),
                    detail=f"catalog says {expected_status.value!r}, "
                    f"the fold says {row.status!r}",
                )
            )
        if row.mastered != game.mastered:
            mismatches.append(
                Mismatch(
                    code="mastered_disagreement",
                    game_id=str(game.pk),
                    detail=f"catalog says {game.mastered}, "
                    f"the fold says {row.mastered}",
                )
            )
    return mismatches
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_backfill.py -x"`
Expected: PASS, 36 tests.

- [ ] **Step 5: Commit**

```bash
git add games/backfill/playergame.py tests/test_playergame_backfill.py
git commit -m "Refuse a backfill the catalog disagrees with"
```

---

### Task 5: The migration

**Files:**
- Create: `games/migrations/0033_playergame_baseline_backfill.py`
- Create: `tests/test_playergame_backfill_migration.py`

**Interfaces:**
- Consumes: `backfill_library`, `reconcile`, `unmapped_statuses`, `Mismatch`, `BackfillCounts`, `NO_COUNTS` from Tasks 1 to 4.
- Produces: module constants `MACHINE_PREFIX`, `HUMAN_PREFIX`, `SUMMARY_KEYS`, and `def backfill_playergame_baseline(apps, schema_editor) -> None`.

Before writing, confirm `0032_playergame_archived_at` is still the leaf:
`ls games/migrations/ | tail -5`. If a sibling issue landed a later migration,
renumber to the next free number and depend on the real leaf.

- [ ] **Step 1: Write the failing test**

Create `tests/test_playergame_backfill_migration.py`:

```python
"""Migration 0033 turns a held catalog into a tracked one, once."""

import json

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

#: The migration is reached through MigrationExecutor, never imported: a
#: module whose name starts with a digit is not an importable identifier.
pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_BASELINE = ("games", "0032_playergame_archived_at")
WITH_BASELINE = ("games", "0033_playergame_baseline_backfill")


@pytest.fixture
def baseline_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_BASELINE])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_BASELINE]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_baseline():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_BASELINE])
    return executor.loader.project_state([WITH_BASELINE]).apps


def reconciliation_payload(captured):
    for line in captured.out.splitlines():
        if line.startswith("PLAYERGAME_BASELINE_RECONCILIATION_JSON="):
            return json.loads(line.split("=", 1)[1])
    raise AssertionError(f"No machine reconciliation line in:\n{captured.out}")


def seed(old_apps, *, status="u", mastered=False):
    """A user, its library, and one game, in the pre-migration state."""
    User = old_apps.get_model("auth", "User")
    UserLibrary = old_apps.get_model("games", "UserLibrary")
    Game = old_apps.get_model("games", "Game")
    user = User.objects.create(username="owner")
    library = UserLibrary.objects.create(user=user)
    game = Game.objects.create(
        library=library, name="Outer Wilds", status=status, mastered=mastered
    )
    return library, game


def test_the_migration_tracks_every_game_and_reports_it(
    baseline_migration_harness, capsys
):
    library, game = seed(baseline_migration_harness, status="f")

    new_apps = migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert payload["mismatches"] == []
    assert payload["summary"]["tracked"] == 1
    assert payload["summary"]["created_events"] == 1
    assert payload["summary"]["corrective_events"] == 1
    assert payload["summary"]["unknown_effective_times"] == 1
    PlayerGame = new_apps.get_model("games", "PlayerGame")
    row = PlayerGame.objects.get()
    assert (row.game_id, row.library_id, row.status) == (
        game.pk,
        library.pk,
        "completed",
    )


def test_the_second_pass_appends_nothing(baseline_migration_harness, capsys):
    seed(baseline_migration_harness, status="p")

    new_apps = migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert payload["summary"]["mismatches"] == 0
    LibraryEvent = new_apps.get_model("games", "LibraryEvent")
    #: Creation plus one corrective status, and nothing from the second pass.
    assert LibraryEvent.objects.count() == 2


def test_an_unmapped_letter_fails_the_migration(baseline_migration_harness, capsys):
    old_apps = baseline_migration_harness
    _, game = seed(old_apps, status="u")
    Game = old_apps.get_model("games", "Game")
    Game.objects.filter(pk=game.pk).update(status="z")

    with pytest.raises(RuntimeError, match="baseline backfill failed"):
        migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert [entry["code"] for entry in payload["mismatches"]] == [
        "unmapped_legacy_status"
    ]


def test_a_failed_migration_leaves_no_event_behind(baseline_migration_harness):
    old_apps = baseline_migration_harness
    _, game = seed(old_apps, status="u")
    Game = old_apps.get_model("games", "Game")
    Game.objects.filter(pk=game.pk).update(status="z")

    with pytest.raises(RuntimeError):
        migrate_to_baseline()

    #: The migration's transaction rolled back, records and all.
    LibraryEvent = old_apps.get_model("games", "LibraryEvent")
    assert LibraryEvent.objects.count() == 0


def test_a_tombstoned_game_is_reported_as_skipped(baseline_migration_harness, capsys):
    old_apps = baseline_migration_harness
    _, game = seed(old_apps, status="u")
    Game = old_apps.get_model("games", "Game")
    Game.objects.filter(pk=game.pk).update(tombstoned_at=timezone.now())

    migrate_to_baseline()

    payload = reconciliation_payload(capsys.readouterr())
    assert payload["summary"]["skipped_tombstoned"] == 1
    assert payload["summary"]["tracked"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playergame_backfill_migration.py -x"`
Expected: FAIL with `NodeNotFoundError` or `KeyError` naming `0033_playergame_baseline_backfill`.

- [ ] **Step 3: Write the migration**

Create `games/migrations/0033_playergame_baseline_backfill.py`:

```python
import json

from django.db import migrations
from django.utils import timezone

MACHINE_PREFIX = "PLAYERGAME_BASELINE_RECONCILIATION_JSON="
HUMAN_PREFIX = "PGAME baseline reconciliation:"
SUMMARY_KEYS = (
    "libraries",
    "games",
    "tracked",
    "created_events",
    "status_events",
    "mastered_events",
    "corrective_events",
    "unknown_effective_times",
    "skipped_tombstoned",
    "shared_games",
    "mismatches",
)


def _emit(summary, mismatches):
    entries = sorted(
        (mismatch.as_dict() for mismatch in mismatches),
        key=lambda entry: (entry["code"], entry["game_id"], entry["detail"]),
    )
    payload = {
        "schema_version": 1,
        "summary": summary,
        "mismatches": entries,
    }
    print(MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    print(
        HUMAN_PREFIX + " " + " ".join(f"{key}={summary[key]}" for key in SUMMARY_KEYS)
    )
    for entry in entries:
        print(f"  {entry['code']} game={entry['game_id']} {entry['detail']}")


def _fail_if_mismatched(mismatches):
    if mismatches:
        raise RuntimeError(
            f"PGAME baseline backfill failed with {len(mismatches)} mismatch(es)."
        )


def _summary(counts, libraries, shared_games, mismatch_count):
    return {
        "libraries": libraries,
        "games": counts.games,
        "tracked": counts.tracked,
        "created_events": counts.created_events,
        "status_events": counts.status_events,
        "mastered_events": counts.mastered_events,
        "corrective_events": counts.corrective_events,
        "unknown_effective_times": counts.unknown_effective_times,
        "skipped_tombstoned": counts.skipped_tombstoned,
        "shared_games": shared_games,
        "mismatches": mismatch_count,
    }


def backfill_playergame_baseline(apps, schema_editor):
    """Record the baseline events every library's games fold from.

    The live models and the live event machinery, deliberately: historical
    models cannot run a projector or validate a payload, so an apps.get_model
    backfill would have to write events and projection rows by hand, and that
    is a second event writer. The cost is that this migration is pinned to the
    application as it stands when it runs, and the reconciliation below is what
    keeps a future incompatibility loud.
    """
    del apps, schema_editor
    from games.backfill.playergame import (
        NO_COUNTS,
        Mismatch,
        backfill_library,
        reconcile,
        unmapped_statuses,
    )
    from games.models import Game, UserLibrary

    run_time = timezone.now()
    libraries = list(UserLibrary.objects.order_by("pk"))
    shared_games = Game.objects.filter(library__isnull=True).count()

    #: Pre-flight, so an unmapped letter is a report rather than a KeyError.
    mismatches = [
        mismatch for library in libraries for mismatch in unmapped_statuses(library)
    ]
    if mismatches:
        _emit(
            _summary(NO_COUNTS, len(libraries), shared_games, len(mismatches)),
            mismatches,
        )
        _fail_if_mismatched(mismatches)

    counts = NO_COUNTS
    for library in libraries:
        counts = counts + backfill_library(library, run_time=run_time)
        #: A second pass appends nothing, and proves it by counting nothing.
        repeat = backfill_library(library, run_time=run_time)
        drifted = (
            repeat.created_events
            + repeat.status_events
            + repeat.mastered_events
            + repeat.corrective_events
        )
        if drifted:
            mismatches.append(
                Mismatch(
                    code="count_drift",
                    game_id=str(library.pk),
                    detail=f"a second pass appended {drifted} event(s)",
                )
            )
        mismatches.extend(reconcile(library))

    _emit(
        _summary(counts, len(libraries), shared_games, len(mismatches)),
        mismatches,
    )
    _fail_if_mismatched(mismatches)


class Migration(migrations.Migration):
    dependencies = [("games", "0032_playergame_archived_at")]

    operations = [
        migrations.RunPython(
            backfill_playergame_baseline,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_playergame_backfill_migration.py -x"`
Expected: PASS, 5 tests. These are slow — each rewinds and replays the whole
migration graph. Run with `PYTEST_WORKERS=0` if the output interleaves.

- [ ] **Step 5: Confirm the migration graph is consistent**

Run: `make makemigrations ARGS="--check --dry-run"`
Expected: "No changes detected". A data migration adds no schema, so a model
change would be a mistake.

- [ ] **Step 6: Commit**

```bash
git add games/migrations/0033_playergame_baseline_backfill.py tests/test_playergame_backfill_migration.py
git commit -m "Run the baseline backfill once, and reconcile it"
```

---

### Task 6: The sample loader gets the same baseline

**Files:**
- Modify: `games/management/commands/load_sample_data.py:112-145`
- Test: `tests/test_playergame_backfill.py`

**Interfaces:**
- Consumes: `backfill_library` from Task 3.
- Produces: nothing new; `load_sample_data` gains one call.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playergame_backfill.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_the_sample_loader_leaves_every_loaded_game_tracked(owned_user):
    from django.core.management import call_command

    call_command("load_sample_data", user=owned_user.username, verbosity=0)

    library = owned_user.library
    live = Game.objects.filter(library=library, tombstoned_at__isnull=True).count()
    assert live > 0
    assert PlayerGame.objects.filter(library=library).count() == live
    assert reconcile(library) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playergame_backfill.py -k sample_loader -x"`
Expected: FAIL on `assert PlayerGame.objects.filter(library=library).count() == live`,
with the left side 0. (`--user` is the command's one required argument, declared
at `games/management/commands/load_sample_data.py:99`.)

- [ ] **Step 3: Write the implementation**

In `games/management/commands/load_sample_data.py`, add to the import block:

```python
from games.backfill.playergame import backfill_library
```

Then, inside the existing `with transaction.atomic():` block, immediately after
the `if cache_mismatch or state.requested_version != state.published_version:`
branch and before the block ends, add:

```python
            #: The same baseline a migrated database gets: every loaded game
            #: becomes a tracked game, recorded as events and folded by the
            #: projector. lock_stream requires this atomic block.
            backfill_library(user.library)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_playergame_backfill.py -k sample_loader -x"`
Expected: PASS.

- [ ] **Step 5: Verify the loader still works end to end**

Run: `make test ARGS="tests/test_load_sample_data.py"` if that file exists;
otherwise `make test ARGS="tests -k sample"`.
Expected: PASS. If a test asserts an exact object count in the loader's success
message, it is unaffected — the message counts fixture records, not events.

- [ ] **Step 6: Commit**

```bash
git add games/management/commands/load_sample_data.py tests/test_playergame_backfill.py
git commit -m "Give sample data the same tracked baseline"
```

---

### Task 7: Pin the consequences and pass the gate

The backfill changes two things outside itself. Both are correct, and both
should fail loudly if they ever change by accident.

**Files:**
- Test: `tests/test_playergame_backfill.py`

**Interfaces:**
- Consumes: `backfill_library` from Task 3.
- Produces: nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_backfill.py`. Add to the import block:

```python
from games.retention import Retirement, tombstone_or_delete
```

Then append:

```python
@pytest.mark.django_db(transaction=True)
def test_a_backfilled_game_is_tombstoned_rather_than_deleted(owned_user, owned_library):
    #: catalog.game is a REQUIRED reference kind, so after the backfill every
    #: live game is named by its creation event and retention must keep the row.
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    backfill_library(owned_library)

    outcome = tombstone_or_delete(game)

    assert outcome is Retirement.TOMBSTONED
    game.refresh_from_db()
    assert game.tombstoned_at is not None


@pytest.mark.django_db(transaction=True)
def test_a_game_with_no_events_is_still_deleted_outright(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Never Tracked")

    assert tombstone_or_delete(game) is Retirement.DELETED
    assert not Game.objects.filter(pk=game.pk).exists()
```

- [ ] **Step 2: Run the tests to verify they fail or pass for the right reason**

Run: `make test ARGS="tests/test_playergame_backfill.py -k tombstoned_rather -x"`
Expected: PASS already, because the behaviour follows from retention's existing
policy. That is the point — the test pins it. If it FAILS with
`Retirement.DELETED`, the reference was not recorded: check that
`capture_reference(game)` reached the creation payload in Task 2.

- [ ] **Step 3: Run the aggregate**

Run: `make check-fast`
Expected: green. Fix anything red before continuing.

- [ ] **Step 4: Run the gate**

Run: `make check`
Expected: green, including `e2e/`. This is the verification gate; never
substitute a hand-picked subset.

- [ ] **Step 5: Commit**

```bash
git add tests/test_playergame_backfill.py
git commit -m "Pin what a backfilled catalog does to deletion"
```

---

## Pre-deploy rehearsal (not a code task)

The spec requires this and no test can stand in for it. Before the Phase 2
deploy, restore a production database, run `make migrate`, and read the
reconciliation output:

```
make migrate 2>&1 | grep "PGAME baseline reconciliation:"
```

Confirm `mismatches=0`, that `tracked` equals the live own-library game count,
and that `created_events` equals `tracked`. `make anonymize-sample` documents
the restored-production-database workflow. The migration runs exactly once and
is rehearsed nowhere else, so this output is the only evidence the run produces.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the four facts and
their two clocks to Tasks 1 and 2; ordering and the fold to Tasks 2 and 3; the
status map to Task 1; the skips to Task 3; one-append-per-event and the keys to
Task 2; actor and correlation IDs to Task 2; the module's home to Task 1; the
migration and its reconciliation to Tasks 4 and 5; sample data to Task 6; the
retention consequence to Task 7; the verification list across all seven; the
rehearsal to the section above.

**Two deliberate deviations from the spec's wording, both recorded here.** The
spec lists "skipped shared games" among the summary counts; a per-library count
of games no library owns is meaningless, so the migration reports `shared_games`
as one global count instead. And the spec attributes `count_drift` to
reconciliation; it is produced in the migration, which is where the two passes
are and therefore the only place that can see drift. Neither changes behaviour.

**Names checked against the code, not remembered.** `Retirement.DELETED` and
`Retirement.TOMBSTONED` are the two members in `games/retention.py:44`.
`TemporalValue` really does expose `unknown()`, `from_day()`, `serialize()`,
`is_unknown`, `is_range` and `has_known_day`. `RebuildReport` has no `drifted`
flag — parity is read off `report.tables`, matching
`tests/test_playergame_projection.py:226-232`.
