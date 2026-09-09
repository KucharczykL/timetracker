# PlayerGame and Playthrough replay-parity gate implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that replaying one library's whole event stream reproduces its
`PlayerGame` and `Playthrough` rows exactly, on both the command-built stream
and the conversion-built one, and give an operator a read-only way to run the
same claim against a restored production copy.

**Architecture:** One new test module assembles a stream through the fourteen
commands of both families, empties the two projection tables, replays, and
compares whole rows; a coverage guard fails the module when a registered event
type never reaches the stream. The benchmark seed grows a second event per
game so its rebuild scenario swaps both tables. `rebuild_projections` gains the
`--user`/`--library`/`--all-libraries` scope group both sibling commands
already carry, plus `--fail-on-drift`, and `make verify-replay-parity` runs it.

**Tech Stack:** Django 6, PostgreSQL 18, pytest + pytest-django (xdist),
Python 3.14. No new dependency, no migration, no model change.

**Spec:** `docs/superpowers/specs/2026-09-09-issue-688-replay-parity-gate-design.md`

## Global Constraints

- **Everything through `make`.** No raw `uv run`, `pytest`, or `pnpm`. Focused
  runs are `make test ARGS="tests/test_x.py -k name -x"`.
- **The gate is a full `make check`**, including `e2e/`. `make check-fast` is
  for iterating only.
- **Python 3.14** is a hard prerequisite; ruff 0.16.x formats to PEP 758
  `except A, B:`.
- **Refused words.** `make vale` enforces `docs/vocabulary.md` over docs and
  code comments. A projector *replays*; the row it leaves is a *projection*.
  Never write `fold` in either sense.
- **Complete words in identifiers** — `element` not `el`, `event` not `e`.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest,
  so every test that dispatches carries
  `@pytest.mark.django_db(transaction=True)`.
- **Never write a `GeneratedField`** — `started_lower`, `started_upper`,
  `completed_lower`, `completed_upper`, `days_to_finish`.
- **Nothing destroys a record** in application code; the gate's `.delete()`
  calls are test setup that empties a projection table, which is what a replay
  fills back in.
- Every commit message ends with the project's usual trailer; no
  `Co-Authored-By` line is added unless the repository's own history shows one.

---

### Task 1: The gate module, its stream, and the coverage guard

**Files:**
- Create: `tests/test_playergame_playthrough_gate.py`

**Interfaces:**
- Consumes: `games.commands.playergame.{TrackGame, SetPlayerGameStatus,
  SetPlayerGameMastered, SetPlayerGameExcludedFromUnfinished, RemovePlayerGame,
  RestorePlayerGame}`; `games.commands.playthrough.{CreatePlaythrough,
  StartPlaythrough, CompletePlaythrough, DescribePlaythrough,
  CorrectPlaythroughStart, CorrectPlaythroughCompletion, RemovePlaythrough,
  RestorePlaythrough}`; `games.events.dispatch.dispatch`;
  `games.events.replay.replay`;
  `games.events.rebuild.{RebuildMode, rebuild_projections}`;
  `games.projectors.playergame.PlayerGames`;
  `games.projectors.playthrough.Playthroughs`.
- Produces (module-local, used by Task 2):
  `DispatchedCommand = NamedTuple(command: Command, key: str)`;
  `build_stream(user, library) -> list[DispatchedCommand]`;
  `projection_rows() -> tuple[list[dict], list[dict]]`;
  `empty_projections(library) -> None`.

- [ ] **Step 1: Write the module header, the stream builder, and the coverage
      guard test**

Create `tests/test_playergame_playthrough_gate.py`:

```python
"""One stream carrying every event type of both families, replayed.

Issue #688. Each event type already has a projection test of its own;
this module holds the claim those tests cannot make between them --
that a whole stream, built the way the write path builds one, replays
into the rows it produced.

The dispatches need real transactions, and the conftest tracking
fixture would otherwise write projection rows no event states.
"""

import uuid
from datetime import date
from typing import NamedTuple

import pytest

from games.commands.playergame import (
    RemovePlayerGame,
    RestorePlayerGame,
    SetPlayerGameExcludedFromUnfinished,
    SetPlayerGameMastered,
    SetPlayerGameStatus,
    TrackGame,
)
from games.commands.playthrough import (
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    DescribePlaythrough,
    RemovePlaythrough,
    RestorePlaythrough,
    StartPlaythrough,
)
from games.events.dispatch import Command, CommandOutcome, dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.replay import replay
from games.models import (
    Game,
    LibraryEvent,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
)
from games.projectors.playergame import PlayerGames
from games.projectors.playthrough import Playthroughs
from timetracker.temporal import TemporalValue

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


class DispatchedCommand(NamedTuple):
    """One command of the stream, and the key it was dispatched under."""

    command: Command
    key: str


def build_stream(user, library) -> list[DispatchedCommand]:
    """Every event type of both families, through commands only.

    Nothing appends by hand: the gate is a claim about what the write
    path produces, and an event this module wrote itself would prove
    only that the projector reads it.
    """
    first = Game.objects.create(library=library, name="Outer Wilds")
    second = Game.objects.create(library=library, name="Tunic")
    dispatched: list[DispatchedCommand] = []

    def run(command: Command, key: str) -> None:
        result = dispatch(command, actor=user, library=library, idempotency_key=key)
        assert result.outcome is CommandOutcome.APPENDED, (
            f"{key} recorded nothing, so the stream misses its event types."
        )
        dispatched.append(DispatchedCommand(command, key))

    run(TrackGame(game_id=first.pk), "track-first")
    run(TrackGame(game_id=second.pk), "track-second")

    first_run = Playthrough.objects.get(player_game__game=first)
    run(
        SetPlayerGameStatus(game_id=first.pk, status=PlayerGameStatus.PLAYED),
        "status-first",
    )
    run(SetPlayerGameMastered(game_id=first.pk, mastered=True), "mastered-first")
    run(
        SetPlayerGameExcludedFromUnfinished(
            game_id=first.pk, excluded_from_unfinished=True
        ),
        "excluded-first",
    )
    run(
        StartPlaythrough(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 1, 1)),
            note="Began here",
        ),
        "start-first-run",
    )
    run(
        CompletePlaythrough(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 2, 1)),
            note="Ended here",
        ),
        "complete-first-run",
    )
    run(
        CorrectPlaythroughStart(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2023, 12, 24)),
            note="Played before that",
        ),
        "correct-start-first-run",
    )
    run(
        CorrectPlaythroughCompletion(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 2, 14)),
            note="Finished later",
        ),
        "correct-completion-first-run",
    )
    run(
        DescribePlaythrough(
            playthrough_id=first_run.pk, name="Blind run", note="No hints"
        ),
        "describe-first-run",
    )

    run(CreatePlaythrough(game_id=first.pk), "create-second-run")
    second_run = (
        Playthrough.objects.filter(player_game__game=first)
        .exclude(pk=first_run.pk)
        .get()
    )
    run(RemovePlaythrough(playthrough_id=second_run.pk), "remove-second-run")
    run(RestorePlaythrough(playthrough_id=second_run.pk), "restore-second-run")

    run(RemovePlayerGame(game_id=second.pk), "remove-second-game")
    run(RestorePlayerGame(game_id=second.pk), "restore-second-game")
    return dispatched


def registered_event_types() -> set[str]:
    """Every type the two CURRENT_STATE projectors read."""
    return {
        spec.event_type
        for handles in (PlayerGames.handles, Playthroughs.handles)
        for spec in handles
    }


def test_the_stream_carries_every_registered_event_type(owned_user, owned_library):
    """A type the stream never appends is a leg nobody runs.

    The guard is what keeps this module honest when #700 and #701 give
    Session its reference to a run, and whenever a family gains a type
    after that.
    """
    build_stream(owned_user, owned_library)
    appended = set(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "event_type", flat=True
        )
    )

    assert registered_event_types() - appended == set()
```

- [ ] **Step 2: Run it to see the guard pass on a complete stream**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py -x"`
Expected: PASS. A failure listing event types means a command in
`build_stream` refused or stated nothing; read the assertion message
`run()` raises, which names the key.

- [ ] **Step 3: Write the guard's own proof, and the second library**

Append to the module:

```python
def test_the_guard_names_a_type_the_stream_missed():
    """The guard fails loudly, so a silent gap cannot pass.

    Subtracting a stream that never restored a run leaves exactly the
    restore, which is the sentence a reader of the failure needs.
    """
    complete = registered_event_types()
    missing = "library.playthrough.restored"
    assert missing in complete

    assert complete - (complete - {missing}) == {missing}


def build_neighbour(user, library) -> None:
    """A shorter stream nobody's assertion reads.

    Every leg states that these rows did not move: a replay scoped to
    one library must leave a neighbour alone, and an unscoped one
    could not tell the difference.
    """
    game = Game.objects.create(library=library, name="Hollow Knight")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=library,
        idempotency_key="neighbour-track",
    )
    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
        actor=user,
        library=library,
        idempotency_key="neighbour-status",
    )


@pytest.fixture
def neighbour(django_user_model):
    """A second owner, with a library of their own."""
    user = django_user_model.objects.create_user(
        username="gate-neighbour", password="p"
    )
    build_neighbour(user, user.library)
    return user.library


def rows_of(library) -> tuple[list[dict], list[dict]]:
    """Both tables' whole rows, in key order.

    `.values()` rather than a column list, so a column added later is
    in the comparison the day it lands.
    """
    return (
        list(PlayerGame.objects.filter(library=library).order_by("pk").values()),
        list(Playthrough.objects.filter(library=library).order_by("pk").values()),
    )


def empty_projections(library) -> None:
    """Scoped by library, the child first: player_game RESTRICTs."""
    Playthrough.objects.filter(library=library).delete()
    PlayerGame.objects.filter(library=library).delete()
```

- [ ] **Step 4: Run the module again**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py -x"`
Expected: PASS, two tests.

- [ ] **Step 5: Write leg 1 — the empty-database replay**

Append:

```python
def test_replaying_an_emptied_library_reproduces_both_tables(
    owned_user, owned_library, neighbour
):
    """Every column, including the clock-derived ones.

    tracked_at, created_at, removed_at, start_recorded_at and
    completion_recorded_at are each written from event.recorded_at,
    so nothing in either row legitimately differs between the write
    path and the replay.
    """
    build_stream(owned_user, owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    empty_projections(owned_library)

    result = replay(owned_library)

    assert result.replayed_through == (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
    )
    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched
```

- [ ] **Step 6: Run leg 1**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py -k replaying -x"`
Expected: PASS.

- [ ] **Step 7: Write leg 2 — the rebuild and swap**

Append:

```python
def test_a_rebuild_swaps_both_tables_with_an_empty_diff(
    owned_user, owned_library, neighbour
):
    """The rebuild's own FULL OUTER JOIN, rather than this module's."""
    build_stream(owned_user, owned_library)
    untouched = rows_of(neighbour)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
    assert rows_of(neighbour) == untouched
```

- [ ] **Step 8: Run leg 2**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py -k rebuild -x"`
Expected: PASS.

- [ ] **Step 9: Write leg 3 — idempotency**

Append:

```python
def test_every_command_repeated_under_its_key_records_nothing(
    owned_user, owned_library, neighbour
):
    """A repeat answers from the record instead of appending.

    The head is the claim: a second append would move it, and a
    projection written twice would show in the rows beside it.
    """
    dispatched = build_stream(owned_user, owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    head_before = LibraryEventStreamHead.objects.get(
        library=owned_library
    ).current_sequence
    events_before = LibraryEvent.objects.filter(library=owned_library).count()

    for command, key in dispatched:
        result = dispatch(
            command, actor=owned_user, library=owned_library, idempotency_key=key
        )
        assert result.outcome is CommandOutcome.REPLAYED, key

    assert (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
        == head_before
    )
    assert LibraryEvent.objects.filter(library=owned_library).count() == events_before
    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched
    assert LibraryIdempotencyRecord.objects.filter(
        library=owned_library
    ).count() == len({key for _command, key in dispatched})
```

- [ ] **Step 10: Run the whole module**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py"`
Expected: PASS, five tests.

If leg 3 reports `CommandOutcome.UNCHANGED` for a key, that command
answered without appending on its *first* dispatch too, and
`build_stream`'s `run()` assertion would have caught it first — so an
UNCHANGED here means the repeat re-entered `build`, which is the bug
the leg exists to find.

- [ ] **Step 11: Commit**

```bash
git add tests/test_playergame_playthrough_gate.py
git commit -m "Replay one stream carrying both families"
```

---

### Task 2: The conversion leg

**Files:**
- Modify: `tests/test_playergame_playthrough_gate.py` (append)

**Interfaces:**
- Consumes: `games.backfill.playergame.backfill_library`;
  `games.backfill.playthrough.convert_library`;
  `games.reads.playthrough_numbering.numbered_for`; `rows_of`,
  `empty_projections` from Task 1.
- Produces: nothing later tasks read.

The stream a live library builds is not the stream production holds: #684
converts legacy `PlayEvent` rows, and its events carry backdated recorded
times. `tests/test_playthrough_conversion.py:438` already diffs a converted
library in `CHECK` mode, which fills a shadow table and writes no live row.
These three tests are what it does not do.

- [ ] **Step 1: Write the converted-library fixture and its replay leg**

Append to `tests/test_playergame_playthrough_gate.py`:

```python
from games.backfill.playergame import backfill_library
from games.backfill.playthrough import convert_library
from games.models import PlayEvent
from games.reads.playthrough_numbering import numbered_for
from games.removal import remove
```

(place the imports with the others at the top of the module, in the order
ruff's isort profile leaves them), then append at the end:

```python
def build_converted(library) -> Game:
    """A library whose runs came out of the legacy rows.

    backfill_library() writes the #676 PlayerGame baseline;
    convert_library() is #684, whose events are backdated to each
    legacy row's own created_at.
    """
    game = Game.objects.create(library=library, name="Chrono Trigger")
    PlayEvent.objects.create(
        game=game, started=date(2024, 1, 1), ended=date(2024, 1, 9), note="One"
    )
    PlayEvent.objects.create(game=game)
    remove(PlayEvent.objects.create(game=game, started=date(2023, 1, 1)))
    backfill_library(library)
    convert_library(library)
    return game


def test_a_converted_library_replays_into_its_live_rows(owned_library, neighbour):
    """The live tables, not a shadow."""
    build_converted(owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    empty_projections(owned_library)

    replay(owned_library)

    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched


def test_a_converted_library_rebuilds_with_an_empty_diff(owned_library, neighbour):
    """A real REBUILD, which swaps."""
    build_converted(owned_library)
    untouched = rows_of(neighbour)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
    assert rows_of(neighbour) == untouched
```

- [ ] **Step 2: Run the two conversion tests**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py -k converted -x"`
Expected: PASS.

- [ ] **Step 3: Write the display-number leg over a tied pair**

The conversion stamps `recorded_at` from each legacy row's `created_at`
(`games/backfill/playthrough.py:224-226`), so two undated rows written in one
instant convert into two runs tied on `started_lower`, `completed_lower` and
`created_at` alike, separated only by the key. `PlayEvent.created_at` is
`auto_now_add`, so the tie is forced with an `UPDATE`. Append:

```python
def test_the_display_number_survives_a_rebuild_of_tied_runs(owned_library):
    """The key is the fourth sort field, and here it is the only one.

    RowNumber over peers follows the plan's input order, which a swap
    changes -- so a tie is the case a rebuild can renumber.
    """
    game = Game.objects.create(library=owned_library, name="Chrono Trigger")
    first = PlayEvent.objects.create(game=game)
    second = PlayEvent.objects.create(game=game)
    #: created_at is auto_now_add, so the tie is stated by hand.
    instant = PlayEvent.objects.get(pk=first.pk).created_at
    PlayEvent.objects.filter(pk__in=(first.pk, second.pk)).update(created_at=instant)
    backfill_library(owned_library)
    convert_library(owned_library)
    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    def numbers() -> dict[uuid.UUID, int]:
        return {
            run.pk: run.display_number
            for run in numbered_for(owned_library, [tracked.pk])
        }

    before = numbers()
    assert len(before) == 2
    assert sorted(before.values()) == [1, 2]

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert numbers() == before
```

- [ ] **Step 4: Run it**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py -k display_number -x"`
Expected: PASS. If `len(before)` is 3 rather than 2, the conversion also
stated the default run #684 gives a tracked game holding no legacy row —
in that case assert `sorted(before.values()) == [1, 2, 3]` and keep the
rest, because the claim is that every number is unchanged, not that there
are two of them.

- [ ] **Step 5: Run the whole module**

Run: `make test ARGS="tests/test_playergame_playthrough_gate.py"`
Expected: PASS, eight tests.

- [ ] **Step 6: Commit**

```bash
git add tests/test_playergame_playthrough_gate.py
git commit -m "Replay the stream a conversion built"
```

---

### Task 3: Seed both creation events per game in the benchmark

**Files:**
- Modify: `games/events/benchmark_workload.py:52-94` (`_SEEDED_TABLES`,
  `seed_library`)
- Modify: `games/events/benchmark.py:286-301` (`SeedReport`, `REPORT_SCHEMA`)
- Modify: `games/events/benchmark_run.py:84-85` (`_measure_scratch`)
- Modify: `games/management/commands/benchmark_events.py:44-49,132-149`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Produces: `seed_library(library, *, actor: User, games: int, spares: int) ->
  SeedReport` — the keyword is `games`, not `events`.
  `SeedReport(catalog_rows: int, catalog_seconds: Seconds, games: int,
  events: int, append_seconds: Seconds, events_per_second: float)`.
  `REPORT_SCHEMA = 2`.
- Unchanged: `run_benchmark(*, seed, ...)` keeps `seed` meaning **events**, and
  divides. `--seed N` on the command keeps meaning events. That is what holds
  the recorded 100,000-event comparison, and what keeps
  `test_a_run_replays_the_events_both_write_paths_produced`'s
  `replayed_through == 44` true.

- [ ] **Step 1: Write the failing tests**

In `tests/test_event_benchmark.py`, replace
`test_seeding_writes_the_events_and_the_projection_rows` (at :257) with:

```python
@pytest.mark.django_db
def test_seeding_writes_both_creation_events_and_both_projection_rows(owned_library):
    """A pair per game, as TrackGame appends one since #679."""
    report = seed_library(owned_library, actor=owned_library.user, games=25, spares=4)
    assert isinstance(report, SeedReport)
    assert report.games == 25
    assert report.events == 50
    assert report.catalog_rows == 29
    assert LibraryEvent.objects.filter(library=owned_library).count() == 50
    #: append() runs inline; the rows exist already.
    assert PlayerGame.objects.filter(library=owned_library).count() == 25
    assert Playthrough.objects.filter(library=owned_library).count() == 25


@pytest.mark.django_db
def test_a_seeded_run_names_the_tracked_game_it_belongs_to(owned_library):
    """Not another library's, and not another game's."""
    seed_library(owned_library, actor=owned_library.user, games=3, spares=0)
    pairs = {
        (run.player_game_id, run.player_game.game_id)
        for run in Playthrough.objects.select_related("player_game")
    }
    assert pairs == {
        (tracked.pk, tracked.game_id) for tracked in PlayerGame.objects.all()
    }
```

Add `Playthrough` to the `games.models` import list at the top of the file if
it is not already there.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test ARGS="tests/test_event_benchmark.py -k seeding_writes_both or names_the_tracked -x"`
Expected: FAIL with `TypeError: seed_library() got an unexpected keyword
argument 'games'`.

- [ ] **Step 3: Reshape `seed_library`**

In `games/events/benchmark_workload.py`, add `playthrough_created` and
`Playthrough` to the imports:

```python
from games.events.playthrough import playthrough_created
```

and add `Playthrough` to the `games.models` import list. Extend
`_SEEDED_TABLES`:

```python
#: Every table the seed writes, for ANALYZE.
_SEEDED_TABLES = (
    Game,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    PlayerGame,
    Playthrough,
)
```

Replace `seed_library` with:

```python
def seed_library(
    library: UserLibrary, *, actor: User, games: int, spares: int
) -> SeedReport:
    """Fill `library`, and leave `spares` untracked games.

    Two events a game, in the order and shape TrackGame writes since
    #679: the tracked game, then the run it comes with, under one
    correlation_id. The parameter counts games rather than events
    because the two numbers differ, and one named for the other reads
    wrong at every call site.
    """
    catalog_started = monotonic()
    _create_catalog(library, prefix=SEEDED_NAME_PREFIX, count=games)
    _create_catalog(library, prefix=SPARE_NAME_PREFIX, count=spares)
    catalog_seconds = monotonic() - catalog_started

    append_started = monotonic()
    correlation_id = uuid.uuid7()
    events = 0
    for batch in batched(_seeded_games(library), APPEND_BATCH):
        with transaction.atomic():
            lock_stream(library).append(
                [event for game in batch for event in _creation_pair(game)],
                actor=actor,
                correlation_id=correlation_id,
                idempotency_key=SEED_IDEMPOTENCY_KEY,
            )
        events += 2 * len(batch)
    append_seconds = monotonic() - append_started
    _analyze()

    return SeedReport(
        catalog_rows=games + spares,
        catalog_seconds=catalog_seconds,
        games=games,
        events=events,
        append_seconds=append_seconds,
        events_per_second=events / append_seconds if append_seconds else 0.0,
    )


def _creation_pair(game: Game) -> tuple[NewEvent, NewEvent]:
    """What TrackGame appends: the tracked game, then its run.

    The run's identity is minted with the event, as the command mints
    it, and the tracked game's is what the run names.
    """
    tracked_id = uuid.uuid7()
    return (
        PLAYERGAME_CREATED.new(
            aggregate_id=tracked_id, payload={"game": capture_reference(game)}
        ),
        playthrough_created(tracked_id),
    )
```

Add `NewEvent` to the imports:

```python
from games.events.vocabulary import NewEvent
```

- [ ] **Step 4: Add `games` to `SeedReport` and bump the schema**

In `games/events/benchmark.py`:

```python
class SeedReport:
    """Setup, timed apart from the measurement."""

    catalog_rows: int
    catalog_seconds: Seconds
    #: Games seeded; the events are two a game.
    games: int
    events: int
    append_seconds: Seconds
    #: The bulk-write number; no bulk command exists.
    events_per_second: float
```

and:

```python
#: 2 since #688: SeedReport gained `games`.
REPORT_SCHEMA = 2
```

- [ ] **Step 5: Divide in `_measure_scratch`**

In `games/events/benchmark_run.py`, replace lines 84-85 with:

```python
    spares = 2 * iterations + warmup
    #: `seed` counts events, as --seed's help says; the seed takes
    #: games, and a pair is two events. An odd seed is one event fewer.
    seeded = seed_library(library, actor=user, games=seed // 2, spares=spares)
```

- [ ] **Step 6: Correct the command's help and its estimate**

In `games/management/commands/benchmark_events.py`, the `--seed` help:

```python
help = (
    (
        f"Events to seed (default {DEFAULT_SEED_EVENTS}). Two events "
        "are seeded per game, so an odd count seeds one event fewer."
    ),
)
```

and the estimate's catalog term:

```python
        notice = (
            f"About to create a scratch user, {seed} events and "
            f"{seed // 2 + 2 * iterations + warmup} catalog rows, then remove "
            f"them. Estimate: {estimate / 60:.1f} minute(s)."
        )
```

- [ ] **Step 7: Convert the remaining `events=` call sites**

In `tests/test_event_benchmark.py`, rename the keyword at each remaining
`seed_library` call: lines 271, 280, 291, 300, 314, 332, 349, 379, 391, 457
and 484 all read `events=N` and become `games=N`. Every count those tests
assert is a game count or a `PlayerGame` count, so none of the numbers move —
with two exceptions, handled in the next two steps.

- [ ] **Step 8: Fix the two tests whose numbers do move**

`test_the_replay_counts_the_shadow_table_as_its_projection` (:388) sums the
projection statements over three tables and now needs the fourth, because the
`Playthrough` shadow table is written too:

```python
@pytest.mark.django_db
def test_the_replay_counts_the_shadow_table_as_its_projection(owned_library):
    """A replay writes the shadow; the swap writes live."""
    seed_library(owned_library, actor=owned_library.user, games=10, spares=0)
    _report, replay = run_rebuild_scenario(
        owned_library, mode=RebuildMode.REBUILD, count_replay=True
    )
    assert replay is not None
    live = PlayerGame._meta.db_table
    shadow = f"{live}{SHADOW_SUFFIX}"
    run_live = Playthrough._meta.db_table
    run_shadow = f"{run_live}{SHADOW_SUFFIX}"
    assert replay.statements_per_table[shadow] == 10
    assert replay.statements_per_table[run_shadow] == 10
    #: Empty here, so only its swap counts.
    assert replay.projection_statements == (
        replay.statements_per_table[shadow]
        + replay.statements_per_table[live]
        + replay.statements_per_table[run_shadow]
        + replay.statements_per_table[run_live]
    )
```

`test_replaying_one_event_costs_one_statement` (:373) measures a slope per
**event**, and a game is now two:

```python
@pytest.mark.django_db
def test_replaying_one_event_costs_one_statement(django_user_model):
    """The replay is one upsert.

    A rebuild also pays a fixed cost, so a small one averages more.
    The slope between two sizes is the per-event number, and it is
    exact. Two events a game, so twenty games are forty events.
    """
    totals: dict[int, int] = {}
    for games in (10, 30):
        user = django_user_model.objects.create_user(username=f"replay-{games}")
        seed_library(user.library, actor=user, games=games, spares=0)
        _report, replay = run_rebuild_scenario(
            user.library, mode=RebuildMode.REBUILD, count_replay=True
        )
        assert replay is not None
        totals[games] = replay.statements
    assert (totals[30] - totals[10]) / 40 == pytest.approx(1.0, abs=0.01)
```

- [ ] **Step 9: Rewrite the two schema-pinning tests**

At :500 and :507, and at :564, `1` becomes `2`:

```python
    assert report.schema == 2
```
```python
    assert parsed["schema"] == 2
```
```python
def test_json_output_parses_and_carries_the_schema():
    parsed = json.loads(run_command(seed=25, iterations=2, warmup=1, json=True))
    assert parsed["schema"] == 2
```

- [ ] **Step 10: Add the seed's arithmetic to the tests**

Append to `tests/test_event_benchmark.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_an_odd_seed_seeds_one_event_fewer():
    """A pair is two events, so an odd count cannot be met."""
    report = run_benchmark(seed=7, iterations=1, warmup=0, keep=True)
    assert report.seed is not None
    assert report.seed.games == 3
    assert report.seed.events == 6


@pytest.mark.django_db
def test_seeding_no_game_writes_no_head(owned_library):
    """Zero stays legal, and provisions nothing."""
    report = seed_library(owned_library, actor=owned_library.user, games=0, spares=1)
    assert report.events == 0
    assert not LibraryEventStreamHead.objects.filter(library=owned_library).exists()
```

- [ ] **Step 11: Run the benchmark tests**

Run: `make test ARGS="tests/test_event_benchmark.py"`
Expected: PASS.

- [ ] **Step 12: Prove the seeded library still rebuilds clean**

Append:

```python
@pytest.mark.django_db(transaction=True)
def test_a_seeded_library_rebuilds_both_tables_with_no_row_differing(owned_library):
    """The seed writes what a replay of it produces."""
    seed_library(owned_library, actor=owned_library.user, games=6, spares=0)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
```

Add `rebuild_projections` to the `games.events.rebuild` import at the top of
the file if it is not already imported there.

- [ ] **Step 13: Run the benchmark tests again**

Run: `make test ARGS="tests/test_event_benchmark.py"`
Expected: PASS.

- [ ] **Step 14: Commit**

```bash
git add games/events/benchmark_workload.py games/events/benchmark.py \
  games/events/benchmark_run.py \
  games/management/commands/benchmark_events.py tests/test_event_benchmark.py
git commit -m "Seed both creation events per game"
```

---

### Task 4: The scope group on `rebuild_projections`

**Files:**
- Modify: `games/management/commands/rebuild_projections.py:29-80`
- Modify: `tests/test_projection_rebuild.py:1138-1141,1190,1200,1212,1231,1253,1259,1267,1478`
- Modify: `tests/test_reference_reconciliation.py:693-697,711,731,747`
- Modify: `docs/event-retention.md:140`
- Modify: `docs/superpowers/specs/2026-08-25-issue-667-shadow-rebuild-design.md:12`

**Interfaces:**
- Produces: `manage.py rebuild_projections (--user USERNAME | --library UUID |
  --all-libraries) [--check]`. The positional argument is gone. The command
  keeps its own refusal sentences — `"<raw>' is not a library id."` and
  `"No library <uuid>."` — so the two tests matching on them still match.

- [ ] **Step 1: Write the failing tests**

In `tests/test_projection_rebuild.py`, convert the helper at :1139 to name the
scope, so every caller reads the same way:

```python
def run_command(*arguments) -> str:
    output = StringIO()
    call_command("rebuild_projections", *arguments, stdout=output)
    return output.getvalue()
```

stays as it is; the callers change. Convert them:

- :1190 → `run_command("--library", str(owned_library.pk), "--check")`
- :1200 → `run_command("--library", str(owned_library.pk))`
- :1212 → `run_command("--library", str(owned_library.pk), "--check")`
- :1231 → `run_command("--library", str(owned_library.pk), "--check")`
- :1253 → `run_command("--library", str(owned_library.pk))`
- :1259 → `run_command("--library", str(uuid7()))`
- :1267 → `run_command("--library", "the-one-with-the-games")`
- :1478's direct `call_command("rebuild_projections", str(owned_library.pk),
  stdout=output, stderr=errors)` →
  `call_command("rebuild_projections", "--library", str(owned_library.pk),
  stdout=output, stderr=errors)`

In `tests/test_reference_reconciliation.py`:

- :711 and :731's direct `call_command("rebuild_projections",
  str(owned_library.pk), ...)` each gain `"--library"` before the id
- :747 → `run_command("--library", str(owned_library.pk))`

Then append the scope tests to `tests/test_projection_rebuild.py`:

```python
@pytest.mark.django_db
def test_the_command_takes_a_user_instead_of_a_library(owned_library):
    output = run_command("--user", owned_library.user.username, "--check")

    assert str(owned_library.pk) in output


@pytest.mark.django_db
def test_an_unknown_user_fails_before_anything_is_read(owned_library):
    with pytest.raises(CommandError, match="No user is named"):
        run_command("--user", "nobody", "--check")

    assert not LibraryEventStreamHead.objects.exists()


@pytest.mark.django_db
def test_a_user_owning_no_library_fails(django_user_model):
    """A missing user is not a user missing a library."""
    user = django_user_model.objects.create_user(username="libraryless")
    UserLibrary.objects.filter(user=user).delete()

    with pytest.raises(CommandError, match="owns no library"):
        run_command("--user", "libraryless", "--check")


@pytest.mark.django_db
def test_a_scope_is_required(owned_library):
    with pytest.raises(CommandError, match="one of the arguments"):
        run_command("--check")


@pytest.mark.django_db
def test_two_scopes_are_refused(owned_library):
    with pytest.raises(CommandError, match="not allowed with argument"):
        run_command("--user", owned_library.user.username, "--all-libraries", "--check")


@pytest.mark.django_db
def test_all_libraries_reports_each_one_in_key_order(owned_library, django_user_model):
    """Key order, so two runs of the same scope read the same."""
    second = django_user_model.objects.create_user(username="second-owner")
    ordered = sorted((str(owned_library.pk), str(second.library.pk)))

    output = run_command("--all-libraries", "--check")

    assert [output.index(key) for key in ordered] == sorted(
        output.index(key) for key in ordered
    )
```

Add `UserLibrary` to the `games.models` import at the top of
`tests/test_projection_rebuild.py` if it is not already imported.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test ARGS="tests/test_projection_rebuild.py tests/test_reference_reconciliation.py -x"`
Expected: FAIL — `CommandError: Error: unrecognized arguments: --library`.

- [ ] **Step 3: Add the scope group**

Replace `add_arguments` and `_get_library` in
`games/management/commands/rebuild_projections.py`:

```python
def add_arguments(self, parser):
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user", help="Rebuild the library owned by USERNAME.")
    scope.add_argument("--library", dest="library_id", help="Rebuild one library UUID.")
    scope.add_argument(
        "--all-libraries",
        action="store_true",
        help="Explicitly rebuild every library, in key order.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Replay and diff only: take no lock and write nothing.",
    )
```

and, beside it:

```python
def _resolve_libraries(self, options) -> list[UserLibrary]:
    libraries = UserLibrary.objects.select_related("user").order_by("pk")
    if options["all_libraries"]:
        return list(libraries)
    if options["user"]:
        return [self._library_of_user(libraries, options["user"])]
    return [self._library_by_id(libraries, options["library_id"])]


@staticmethod
def _library_of_user(libraries, username: str) -> UserLibrary:
    """A missing user is not a user missing a library."""
    user_model = get_user_model()
    try:
        user = user_model.objects.get(username=username)
    except user_model.DoesNotExist as error:
        raise CommandError(f"No user is named {username!r}.") from error
    try:
        return libraries.get(user=user)
    except UserLibrary.DoesNotExist as error:
        raise CommandError(f"User {username!r} owns no library.") from error


@staticmethod
def _library_by_id(libraries, raw_id: str) -> UserLibrary:
    try:
        library_id = UUID(raw_id)
    except ValueError as error:
        raise CommandError(f"{raw_id!r} is not a library id.") from error
    try:
        return libraries.get(pk=library_id)
    except UserLibrary.DoesNotExist as error:
        raise CommandError(f"No library {library_id}.") from error
```

Delete the old `_get_library`. Add the import:

```python
from django.contrib.auth import get_user_model
```

- [ ] **Step 4: Loop `handle` over the resolved scope**

Replace the body of `handle` down to the last `self.stdout.write` with:

```python
def handle(self, *args, **options):
    libraries = self._resolve_libraries(options)
    mode = RebuildMode.CHECK if options["check"] else RebuildMode.REBUILD
    for library in libraries:
        self._run_one(library, mode)


def _run_one(self, library: UserLibrary, mode: RebuildMode) -> None:
    try:
        report = rebuild_projections(library, mode=mode)
    except UnresolvedReferences as error:
        self._write_reconciliation(error.reconciliation)
        #: Both modes fail. No rebuild repairs this.
        raise CommandError(
            f"The events name {error.reconciliation.unresolved} row(s) that "
            "no longer exist, so nothing was replayed."
        ) from error
    except SwapRefusedByReference as error:
        #: handle() has no report to print.
        for table in error.tables:
            self._write_table(table, self.stderr)
        raise CommandError(str(error)) from error
    self._write_report(report)

    if mode is RebuildMode.CHECK:
        self._write_check_outcome(report)
        return
    if not report.swapped:
        raise CommandError(
            f"The rebuild lost to a concurrent write on all "
            f"{len(report.attempts)} attempt(s); nothing was swapped. The "
            "library is busy enough that a quieter moment is the fix."
        )
    self.stdout.write(
        self.style.SUCCESS(f"Swapped {len(report.tables)} table(s) into place.")
    )
    #: True by having got this far.
    self.stdout.write(self.style.SUCCESS("References: all resolved."))
```

Update the `help` string's first sentence:

```python
    help = (
        "Rebuild the projections of one library, or of every library, from "
        "their event streams -- or, with --check, report what a rebuild would "
        "change without writing anything. Exits non-zero when a rebuild did "
        "not swap."
    )
```

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_projection_rebuild.py tests/test_reference_reconciliation.py"`
Expected: PASS.

- [ ] **Step 6: Correct the one document that prints the positional form**

`docs/event-retention.md` mentions the command twice, at :138 and :140, and
neither line prints an argument. Both stay as they are. The spec's claim that
two documents need correcting is one too many; this is the other:

`docs/superpowers/specs/2026-08-25-issue-667-shadow-rebuild-design.md:12`:

```markdown
`manage.py rebuild_projections (--user USERNAME | --library UUID |
--all-libraries) [--check]` prints the report. The command exits with an error
when a rebuild does not swap. #688 replaced the positional library with that
scope group.
```

- [ ] **Step 7: Commit**

```bash
git add games/management/commands/rebuild_projections.py \
  tests/test_projection_rebuild.py tests/test_reference_reconciliation.py \
  docs/superpowers/specs/2026-08-25-issue-667-shadow-rebuild-design.md
git commit -m "Scope a rebuild the way its siblings scope one"
```

---

### Task 5: `--fail-on-drift`

**Files:**
- Modify: `games/management/commands/rebuild_projections.py`
- Modify: `docs/event-retention.md:138-143`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Produces: `--fail-on-drift`, which exits non-zero when any library reported a
  differing, only-live or only-rebuilt row. `--check` alone keeps exiting zero,
  which is what `docs/event-retention.md:141` documents and why the flag exists
  rather than a changed exit code.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projection_rebuild.py`:

```python
def drifted_library(library) -> None:
    """A projection row no event states."""
    PlayerGame.objects.create(
        id=uuid7(),
        library=library,
        game=Game.objects.create(library=library, name="Unreplayed"),
        tracked_at=timezone.now(),
    )


@pytest.mark.django_db
def test_a_check_alone_still_exits_zero_on_drift(owned_library):
    """A rebuild removes drift, so a check that found some found work."""
    drifted_library(owned_library)

    output = run_command("--library", str(owned_library.pk), "--check")

    assert "row(s) differ from the replay" in output


@pytest.mark.django_db
def test_fail_on_drift_fails_the_check(owned_library):
    drifted_library(owned_library)

    with pytest.raises(CommandError, match="row\\(s\\) differ from the replay"):
        run_command("--library", str(owned_library.pk), "--check", "--fail-on-drift")


@pytest.mark.django_db
def test_fail_on_drift_is_silent_when_nothing_drifted(owned_library):
    output = run_command(
        "--library", str(owned_library.pk), "--check", "--fail-on-drift"
    )

    assert "Projections match the replayed events." in output


@pytest.mark.django_db
def test_all_libraries_fails_on_the_one_that_drifted(owned_library, django_user_model):
    """One drifted neighbour fails the whole run."""
    second = django_user_model.objects.create_user(username="drifted-owner")
    drifted_library(second.library)

    with pytest.raises(CommandError, match="row\\(s\\) differ from the replay"):
        run_command("--all-libraries", "--check", "--fail-on-drift")
```

Add `timezone`, `Game` and `PlayerGame` to the imports at the top of the file
if they are not already there.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test ARGS="tests/test_projection_rebuild.py -k drift -x"`
Expected: FAIL — `unrecognized arguments: --fail-on-drift`.

- [ ] **Step 3: Add the flag**

In `add_arguments`, beside `--check`:

```python
        parser.add_argument(
            "--fail-on-drift",
            action="store_true",
            help=(
                "Exit non-zero when a check found a differing row. A check "
                "alone exits zero, because a rebuild removes drift; an "
                "operator rehearsing a deployment wants the opposite."
            ),
        )
```

Thread it through `handle` and `_run_one`:

```python
    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        mode = RebuildMode.CHECK if options["check"] else RebuildMode.REBUILD
        for library in libraries:
            self._run_one(library, mode, fail_on_drift=options["fail_on_drift"])
```

```python
    def _run_one(
        self, library: UserLibrary, mode: RebuildMode, *, fail_on_drift: bool
    ) -> None:
```

and, in the `CHECK` branch:

```python
if mode is RebuildMode.CHECK:
    drifted = self._write_check_outcome(report)
    if drifted and fail_on_drift:
        raise CommandError(
            f"{drifted} row(s) differ from the replay in library {report.library_id}."
        )
    return
```

Make `_write_check_outcome` answer the count it already computes:

```python
def _write_check_outcome(self, report: RebuildReport) -> int:
    """Print the outcome, and say how many rows drifted."""
    if report.head_at_diff != report.replayed_through:
        #: No lock: the drift may be false.
        self.stdout.write(
            self.style.WARNING(
                "The head moved while the check ran, so the diff above is "
                "advisory. Re-run it, or rebuild -- a rebuild turns the same "
                "race into a redo."
            )
        )
    drifted = sum(
        table.only_live + table.only_rebuilt + table.differing
        for table in report.tables
    )
    if not drifted:
        self.stdout.write(self.style.SUCCESS("Projections match the replayed events."))
        return 0
    tables = sum(
        1
        for table in report.tables
        if table.only_live or table.only_rebuilt or table.differing
    )
    self.stdout.write(
        self.style.WARNING(
            f"{drifted} row(s) differ from the replay across {tables} table(s)."
        )
    )
    return drifted
```

- [ ] **Step 4: Run the drift tests**

Run: `make test ARGS="tests/test_projection_rebuild.py -k drift"`
Expected: PASS.

- [ ] **Step 5: Document the flag beside the rule it does not change**

In `docs/event-retention.md`, after the sentence "A `--check` exits zero for
drift, because a rebuild removes drift.", add:

```markdown
`--fail-on-drift` reverses that exit for the run that asks for it. The rule
above holds: a check found work, not a fault. An operator who rehearses a
deployment wants a non-zero exit for the same finding, and states the flag to
get one. `make verify-replay-parity` is that run.
```

- [ ] **Step 6: Commit**

```bash
git add games/management/commands/rebuild_projections.py \
  tests/test_projection_rebuild.py docs/event-retention.md
git commit -m "Fail a rehearsal on the drift a check reports"
```

---

### Task 6: `make verify-replay-parity`, and the docs the reshape made false

**Files:**
- Modify: `Makefile:336-343`
- Modify: `CLAUDE.md` (the command table, beside `make bench`)
- Modify: `docs/event-benchmarks.md`

**Interfaces:**
- Produces: `make verify-replay-parity`, running
  `manage.py rebuild_projections --all-libraries --check --fail-on-drift`.
  Read-only, and **not** in `make check`: it needs a database with a stream in
  it, like `bench`, `audit-uuid-identity` and `preflight-playthroughs`.

- [ ] **Step 1: Add the target**

In `Makefile`, between `preflight-playthroughs` and `bench`:

```make
# Read-only: replays every library and fails on a differing row.
verify-replay-parity: ensure-postgres
	uv run --frozen python manage.py rebuild_projections --all-libraries --check --fail-on-drift
```

- [ ] **Step 2: Run it against the development database**

Run: `make verify-replay-parity`
Expected: one block per library, each ending
`Projections match the replayed events.`, and a zero exit. An empty
development database prints nothing and exits zero, which is also a pass.

- [ ] **Step 3: Add the row to the CLAUDE.md command table**

Beside the `make bench` row:

```markdown
| Replay every library and fail on a differing row | `make verify-replay-parity` (read-only; **not** in `make check`) |
```

- [ ] **Step 4: Correct the benchmark document's `--seed` line**

In `docs/event-benchmarks.md`, the fenced block at :7-12 keeps its commands;
add a line under it:

```markdown
`--seed` counts **events**, and the seed writes two a game — the pair
`TrackGame` appends since #679 — so `--seed 100000` seeds 50,000 games. An odd
count seeds one event fewer.
```

- [ ] **Step 5: Mark the recorded run as superseded**

The pasted report at :36-63 describes a one-family seed and its numbers are no
longer reproducible. Do not invent replacements: leave the block, and change
its heading sentence at :34 to

```markdown
`make bench`, 2026-09-05, the first recording with two projection tables. The
seed wrote one event a game then; #688 made it two, so the row counts below
describe a seed this repository no longer has. The run under **The #688
recording** replaces it.
```

- [ ] **Step 6: Correct the three passages the reshape makes false**

At :65-69, replace the paragraph with:

```markdown
The event count moved because #679 made `TrackGame` two events: the 200
commands the scenario dispatches append 400, and each states one `PlayerGame`
row and one `Playthrough` row. In the recording above the 100,000 seeded events
were appended directly and stated one row each, which is why the second table
holds 410 rows against the first table's 100,410. #688 gave the seed the same
pair, so both tables now hold half the seeded event count.
```

At :117-120 (the Parity paragraph), replace the second sentence:

```markdown
It holds across both write paths. The seeded events were appended in batches
through `LockedStream.append`; the 820 that follow were written two at a time
through `dispatch`, with its idempotency record and its own transaction. The
replay cannot tell them apart, which is the point. Since #688 the seeded
batches append the same pair the commands do, so the two paths differ in
batching alone.
```

At :208-210, replace the last sentence of the ceiling analysis:

```markdown
The two write-shape rows are the `games_playergame` shadow table alone. In the
recording above the 410 `games_playthrough` rows beside it were inside the
replay figure and too few to move it; since #688 that table holds half the
seeded rows, so a re-measurement of the ceiling has to write both.
```

At :242, the seed's ANALYZE sentence:

```markdown
The seed ends with an `ANALYZE` of the seven tables it wrote, so the time above
includes it.
```

- [ ] **Step 7: Add the heading the evidence run fills**

At the end of `docs/event-benchmarks.md`, before `## Teardown`, add:

```markdown
## The #688 recording

Recorded when the gate landed, against the seed that writes both creation
events. Paste what the tool prints; do not edit a number here.
```

- [ ] **Step 8: Lint the prose**

Run: `make vale`
Expected: no findings. A refused word in a new sentence fails here.

- [ ] **Step 9: Commit**

```bash
git add Makefile CLAUDE.md docs/event-benchmarks.md
git commit -m "Give an operator the parity run"
```

---

### Task 7: The evidence, and the gate

**Files:**
- Modify: `docs/event-benchmarks.md` (the `## The #688 recording` section)
- Modify: `docs/superpowers/specs/2026-09-09-issue-688-replay-parity-gate-design.md`
  (the Evidence table)

**Interfaces:** none. This task records measurements and runs the gate.

- [ ] **Step 1: Run the benchmark with the gate on**

Run: `make bench ARGS="--gate"`
Expected: ~1.7 minutes, a verdict line per budget, exit zero. A
`RebuildDiffNotEmpty` here is a hard failure of the whole issue, not a flake.

Paste the whole output under `## The #688 recording` in
`docs/event-benchmarks.md`, in a fenced block, exactly as printed.

- [ ] **Step 2: Run it again without the statement counter**

Run: `make bench ARGS="--gate --no-count-replay"`
Expected: exit zero.

Paste the `Rebuild:` block and the `rebuild:` verdict line under the first,
the way the 2026-09-05 recording pairs its two runs.

- [ ] **Step 3: Write the sentences the two runs support**

Under the two blocks, state three things in prose: the command p95 against the
0.100 s budget, recorded as a **new baseline** rather than compared with the
0.005 s of the one-family seed — the seeded `PlayerGame` table is half the size
`TrackGame`'s duplicate check reads
(`games/events/benchmark_workload.py:172`); the rebuild seconds against the
scaled allowance, whose event count is unchanged; and the per-event statement
count over two tables. A missed budget is a finding, not a licence to raise the
limit.

- [ ] **Step 4: Rehearse against a restored production copy**

Run: `make fetch-dump`, then `make verify-dump KEEP=1`
Expected: the restore migrates, the copy is kept, and its `DATABASE_URL` is
printed. `KEEP=1` matters — the plain target drops the copy on success and the
next step needs it. Production stands behind the #676 backfill, so the copy is
migrated first and the parity run reads the state the deployment will leave.

Run: `DATABASE_URL=<the printed URL> make verify-replay-parity`
Expected: one block per library, each ending
`Projections match the replayed events.`, and exit zero. A non-zero exit here
is drift in production data and is the finding the whole issue exists to
produce: record it and stop, rather than rebuilding the copy to make the run
pass.

If the dump targets are unavailable (`PROD_SSH_HOST`/`PROD_DB_CONTAINER` unset
in `.env`), record that in the Evidence table as **not run** with the reason,
and say so in the issue rather than leaving the row blank.

- [ ] **Step 5: Fill the spec's Evidence table**

In
`docs/superpowers/specs/2026-09-09-issue-688-replay-parity-gate-design.md`,
fill the five rows with the measured values and a verdict each.

- [ ] **Step 6: Lint the prose**

Run: `make vale`
Expected: no findings.

- [ ] **Step 7: Run the gate**

Run: `make check`
Expected: green, including `e2e/`. This is the verification gate; a
hand-picked subset is not.

- [ ] **Step 8: Commit**

```bash
git add docs/event-benchmarks.md \
  docs/superpowers/specs/2026-09-09-issue-688-replay-parity-gate-design.md
git commit -m "Record what the gate measured"
```
