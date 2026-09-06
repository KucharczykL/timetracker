# Legacy PlayEvent conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn every legacy `PlayEvent` row into Playthrough events, give every
tracked game that holds no run a default one, and pair each lifecycle fact with
the #676 status event that recorded the same day.

**Architecture:** One new backfill module, `games/backfill/playthrough.py`,
shaped like `games/backfill/playergame.py`: one event per `idempotent_append`,
its own atomic block per game, no `dispatch()`. It imports the row classifiers
from `games/preflight/playthrough.py` so the run and the #686 report cannot
answer differently. A new migration `0045_playthrough_conversion_backfill` runs
it against every library, checks six gates, prints a JSON line, and raises on
any mismatch so the whole run rolls back.

**Tech Stack:** Django 6, PostgreSQL 18, pytest + pytest-django, `uv`, `make`.

**Spec:** `docs/superpowers/specs/2026-09-06-issue-684-playthrough-conversion-design.md`

## Global Constraints

- Python 3.14. Run everything through `make`; never bare `uv run` / `pytest`.
- Focused runs: `make test ARGS="tests/test_playthrough_conversion.py -k name -x"`.
- The verification gate is full `make check`, plus `make audit-uuid-identity`.
- Complete words in identifiers: `event` not `e`, `element` not `el`.
- Refused words (`make vale` fails the build): `fold`, `delete <row>`, `archive`,
  `tombstone`, `heal`. Code identifiers are out of scope; comments are not.
- Never write a `GeneratedField`: `started_lower`, `started_upper`,
  `completed_lower`, `completed_upper` are read-only.
- Nothing destroys a record. This module appends events only.
- `KEY_PREFIX = "backfill:684:playthrough"`, `PTHROUGH_ISSUE = 684`.
- **No `command_input` may name an aggregate id.** Each identity is minted
  fresh per pass; a fingerprint holding one would raise
  `IdempotencyKeyMismatch` on the second pass instead of reporting drift.
- Every aggregate id comes from `identity_at(recorded_at)`, never
  `uuid.uuid7()`. `games_playthrough` is in the identity audit's table set.
- Every model query reads through `.only()` over an explicit field tuple.

---

### Task 1: An explicit identity for a creation event, and a public classifier

The conversion must choose each run's primary key, and it must read the #676
status events the preflight already reads. Two small openings, one commit.

**Files:**
- Modify: `games/events/playthrough.py:43-52`
- Modify: `games/preflight/playthrough.py:337`
- Test: `tests/test_playthrough_events.py`

**Interfaces:**
- Produces: `playthrough_created(player_game_id: uuid.UUID, *, kind:
  PlaythroughKindValue = "ordinary", playthrough_id: uuid.UUID | None = None)
  -> NewEvent`
- Produces: `candidate_events(library: UserLibrary) -> CandidateEvents`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_events.py`:

```python
def test_a_creation_event_takes_the_identity_it_is_given():
    #: #684 mints from identity_at(), so the row's key sorts by its created_at.
    identity = uuid.uuid7()
    event = playthrough_created(uuid.uuid7(), playthrough_id=identity)
    assert event.aggregate_id == identity


def test_a_creation_event_mints_its_own_identity_by_default():
    first = playthrough_created(uuid.uuid7())
    second = playthrough_created(uuid.uuid7())
    assert first.aggregate_id != second.aggregate_id
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playthrough_events.py -k identity -x"`
Expected: FAIL, `TypeError: playthrough_created() got an unexpected keyword
argument 'playthrough_id'`.

- [ ] **Step 3: Add the parameter**

Replace the body of `playthrough_created` in `games/events/playthrough.py`:

```python
def playthrough_created(
    player_game_id: uuid.UUID,
    *,
    kind: PlaythroughKindValue = "ordinary",
    playthrough_id: uuid.UUID | None = None,
) -> NewEvent:
    """The one creation event, for both commands.

    A caller states the identity where the row's order matters: #684
    records a past instant, and the identity audit holds every
    Playthrough key to its created_at order.
    """
    return PLAYTHROUGH_CREATED.new(
        aggregate_id=playthrough_id or uuid.uuid7(),
        payload={"player_game": str(player_game_id), "kind": kind},
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_playthrough_events.py -k identity -x"`
Expected: PASS.

- [ ] **Step 5: Make the classifier public**

In `games/preflight/playthrough.py`, rename `_candidate_events` to
`candidate_events` (definition at line 337 and its one call inside
`preflight_library`). Change the module docstring's second line to name what
#684 takes:

```python
"""What the legacy PlayEvent rows hold.

#684 imports `classify_row`, `legacy_order_key`, `candidate_events` and
`pair_endpoints`, so the two agree.
"""
```

- [ ] **Step 6: Run the preflight suite and the type checker**

Run: `make test ARGS="tests/test_playthrough_preflight.py -x"` then
`make typecheck`
Expected: PASS, and no reference to `_candidate_events` remains
(`grep -rn "_candidate_events" games/ tests/` prints nothing).

- [ ] **Step 7: Commit**

```bash
git add games/events/playthrough.py games/preflight/playthrough.py tests/test_playthrough_events.py
git commit -m "Let a creation event take the identity it is given"
```

---

### Task 2: The conversion module — counts, one append, one row

The heart of the run: one legacy row becomes one run stating both acts.

**Files:**
- Create: `games/backfill/playthrough.py`
- Test: `tests/test_playthrough_conversion.py`

**Interfaces:**
- Consumes: `playthrough_created(..., playthrough_id=...)` from Task 1.
- Produces: `PTHROUGH_ISSUE`, `KEY_PREFIX`, `CONVERSION_PAGE_SIZE`,
  `ConversionCounts` (frozen dataclass, `__add__`, `as_dict()`), `NO_COUNTS`,
  `convert_row(row: PlayEvent, *, library: UserLibrary, actor: User,
  tracked_id: uuid.UUID, pairings: Mapping[Endpoint, Pairing]) ->
  ConversionCounts`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playthrough_conversion.py`:

```python
"""What the legacy rows become. Issue #684."""

import uuid
from datetime import UTC, date, datetime

import pytest

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import NO_COUNTS, ConversionCounts, convert_row
from games.models import Game, PlayerGame, Playthrough, PlayEvent
from games.removal import remove

pytestmark = pytest.mark.django_db


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _row(game, started=None, ended=None, note=""):
    return PlayEvent.objects.create(game=game, started=started, ended=ended, note=note)


def _tracked(library, game):
    return PlayerGame.objects.get(library=library, game=game)


def _convert(library, row, tracked):
    return convert_row(
        row,
        library=library,
        actor=library.user,
        tracked_id=tracked.pk,
        pairings={},
    )


def test_a_dated_row_states_both_days(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2014, 6, 7), ended=date(2014, 6, 17))
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.started_lower == date(2014, 6, 7)
    assert run.completed_lower == date(2014, 6, 17)
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None
    assert run.kind == "ordinary"
    assert run.created_at == row.created_at


def test_an_endpoint_less_row_states_both_acts_and_no_days(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game)
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.started_lower is None
    assert run.completed_lower is None
    #: The marker is the act; the null day is only an unknown day.
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None


def test_a_reversed_row_is_recorded_as_it_stands(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.started_lower == date(2024, 5, 9)
    assert run.completed_lower == date(2024, 5, 1)


def test_a_note_becomes_the_run_note(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1), note="First playthrough")
    counts = _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.note == "First playthrough"
    assert run.start_note == ""
    assert counts.notes == 1


def test_a_blank_note_appends_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1))
    counts = _convert(owned_library, row, _tracked(owned_library, game))
    assert counts.notes == 0


def test_a_removed_row_becomes_a_removed_run(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1))
    remove(row)
    row.refresh_from_db()
    counts = _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    assert run.removed_at == row.removed_at
    assert counts.rows_removed_converted == 1


def test_an_identity_sorts_by_the_row_it_came_from(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2014, 1, 1))
    PlayEvent.objects.filter(pk=row.pk).update(
        created_at=datetime(2014, 1, 1, 12, 0, tzinfo=UTC)
    )
    row.refresh_from_db()
    _convert(owned_library, row, _tracked(owned_library, game))

    run = Playthrough.objects.get(player_game__game=game)
    #: A UUIDv7 carries its instant in the high bits.
    assert run.pk < uuid.uuid7()
    assert run.created_at == datetime(2014, 1, 1, 12, 0, tzinfo=UTC)


def test_a_second_pass_over_one_row_appends_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    row = _row(game, started=date(2024, 1, 1))
    tracked = _tracked(owned_library, game)
    _convert(owned_library, row, tracked)
    repeat = _convert(owned_library, row, tracked)

    assert repeat.events_appended == 0
    assert Playthrough.objects.filter(player_game=tracked).count() == 1


def test_counts_add_field_by_field():
    total = ConversionCounts(live_rows=1) + ConversionCounts(live_rows=2, notes=1)
    assert total.live_rows == 3
    assert total.notes == 1
    assert NO_COUNTS.live_rows == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_conversion.py -x"`
Expected: FAIL at collection, `ModuleNotFoundError: No module named
'games.backfill.playthrough'`.

- [ ] **Step 3: Write the module**

Create `games/backfill/playthrough.py`:

```python
"""Playthrough facts for the legacy PlayEvent rows.

Issue #684. The legacy table is the only record of which games a library
played through and when. Every row in scope becomes one ordinary run
stating both acts, because a row carrying no date is still the library's
record that a run happened -- #681's "played before", which is a marker
set beside a null day.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import datetime
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction

from games.events.append import LockedStream, SourceMetadata, identity_at
from games.events.idempotency import ReplayedAppend, idempotent_append
from games.events.playthrough import (
    playthrough_completed,
    playthrough_created,
    playthrough_note_changed,
    playthrough_removed,
    playthrough_started,
)
from games.events.vocabulary import NewEvent
from games.models import PlayEvent, UserLibrary
from games.preflight.playthrough import (
    Endpoint,
    EndpointKind,
    Pairing,
    RowVerdict,
    classify_row,
)
from timetracker.temporal import TemporalValue

#: Named in every key and every source_metadata value.
PTHROUGH_ISSUE = 684
KEY_PREFIX = "backfill:684:playthrough"

#: A page, not a cursor chunk.
CONVERSION_PAGE_SIZE = 200

#: Every PlayEvent field this module reads.
#:
#: 0045 replays this code against the concrete model, so a bare query
#: selects the columns PlayEvent declares today while the schema stands
#: at 0045. A field read here and missing from this tuple is deferred,
#: and reading it raises UndefinedColumn one page later. #771 takes this
#: table, so the tuple is what keeps the run readable until then.
PLAYEVENT_FIELDS = (
    "created_at",
    "ended",
    "game_id",
    "note",
    "removed_at",
    "started",
)


@dataclass(frozen=True, slots=True)
class ConversionCounts:
    """What one pass did, summable across rows, games and libraries."""

    libraries: int = 0
    tracked: int = 0
    tracked_on_removed_game: int = 0
    live_rows: int = 0
    rows_removed_converted: int = 0
    clean_both: int = 0
    clean_start_only: int = 0
    clean_end_only: int = 0
    no_known_endpoint: int = 0
    reversed_endpoints: int = 0
    runs_converted: int = 0
    runs_default: int = 0
    notes: int = 0
    endpoints_paired: int = 0
    endpoints_fresh: int = 0
    endpoints_dayless: int = 0
    events_appended: int = 0

    def __add__(self, other: "ConversionCounts") -> "ConversionCounts":
        return ConversionCounts(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: The value an accumulation starts from.
NO_COUNTS = ConversionCounts()

#: The counts field one row verdict adds to. A dict rather than a match,
#: because every arm is the enum's own value.
VERDICT_FIELD = {
    RowVerdict.CLEAN_BOTH: "clean_both",
    RowVerdict.CLEAN_START_ONLY: "clean_start_only",
    RowVerdict.CLEAN_END_ONLY: "clean_end_only",
    RowVerdict.NO_KNOWN_ENDPOINT: "no_known_endpoint",
    RowVerdict.REVERSED_ENDPOINTS: "reversed_endpoints",
}


def _append(
    library: UserLibrary,
    event: NewEvent,
    *,
    actor: User,
    idempotency_key: str,
    command_input: dict[str, Any],
    recorded_at: datetime,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata,
) -> bool:
    """Append one event, or replay its key. True when it appended.

    One append per event, never one append per row: LockedStream.append()
    stamps one recorded_at across every row of a call, and a removed
    legacy row carries two different instants.

    No command_input names an aggregate id. Every identity here is minted
    fresh per pass, so a fingerprint holding one would answer a second
    pass with IdempotencyKeyMismatch rather than with the drift the gate
    reads.

    dispatch() is not used. A command validates against current state,
    and every refusal #681 and #1011 wrote guards what a person states
    next. This run states what the library already recorded.
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
        correlation_id=correlation_id,
        source_metadata=source_metadata,
        recorded_at=recorded_at,
    )
    return not isinstance(outcome, ReplayedAppend)


def convert_row(
    row: PlayEvent,
    *,
    library: UserLibrary,
    actor: User,
    tracked_id: uuid.UUID,
    pairings: Mapping[Endpoint, Pairing],
) -> ConversionCounts:
    """State one legacy row as one run.

    The atomic block is this function's own: lock_stream refuses the head
    lock outside a transaction, and one row's facts are recorded whole or
    not at all. Inside a caller's transaction it is a savepoint, so the
    migration still rolls the whole run back.
    """
    metadata: SourceMetadata = {
        "origin": "backfill",
        "issue": PTHROUGH_ISSUE,
        #: Provenance, not a lookup: nothing reads it back. A string,
        #: because canonical_json refuses a UUID.
        "play_event_id": str(row.pk),
    }
    verdict = classify_row(row)
    counts = ConversionCounts(
        runs_converted=1,
        live_rows=int(row.removed_at is None),
        rows_removed_converted=int(row.removed_at is not None),
        **{VERDICT_FIELD[verdict]: 1},
    )
    #: The row's own instant, so the projector's created_at is the day
    #: the row was written and the identity sorts with it.
    recorded_at = row.created_at
    run_id = identity_at(recorded_at)

    with transaction.atomic():
        #: Always first. amend() raises ProjectionRowMissing against a
        #: row no creation event made.
        if _append(
            library,
            playthrough_created(tracked_id, playthrough_id=run_id),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:created:{row.pk}",
            command_input={"fact": "created", "play_event_id": str(row.pk)},
            recorded_at=recorded_at,
            correlation_id=uuid.uuid7(),
            source_metadata=metadata,
        ):
            counts = replace(counts, events_appended=counts.events_appended + 1)

        if row.note and _append(
            library,
            playthrough_note_changed(run_id, note=row.note),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:note:{row.pk}",
            command_input={
                "fact": "note",
                "play_event_id": str(row.pk),
                #: Named, so a changed note is a loud mismatch.
                "note": row.note,
            },
            recorded_at=recorded_at,
            correlation_id=uuid.uuid7(),
            source_metadata=metadata,
        ):
            counts = replace(
                counts, notes=1, events_appended=counts.events_appended + 1
            )

        for kind, day, build_event, word in (
            (EndpointKind.START, row.started, playthrough_started, "started"),
            (EndpointKind.COMPLETION, row.ended, playthrough_completed, "completed"),
        ):
            correlation_id = uuid.uuid7()
            if day is None:
                counts = replace(counts, endpoints_dayless=counts.endpoints_dayless + 1)
            else:
                paired = pairings.get(
                    Endpoint(
                        row_id=row.pk,
                        kind=kind,
                        day=day,
                        aggregate_id=tracked_id,
                    )
                )
                adopted = None if paired is None else paired.correlation_id
                if adopted is None:
                    counts = replace(counts, endpoints_fresh=counts.endpoints_fresh + 1)
                else:
                    correlation_id = adopted
                    counts = replace(
                        counts, endpoints_paired=counts.endpoints_paired + 1
                    )
            if _append(
                library,
                build_event(
                    run_id,
                    #: None rather than TemporalValue.unknown(): an event
                    #: that says nothing about a day is plainer than one
                    #: spelling out an unknown, and the column holds
                    #: None either way.
                    when=None if day is None else TemporalValue.from_day(day),
                    note="",
                ),
                actor=actor,
                idempotency_key=f"{KEY_PREFIX}:{word}:{row.pk}",
                command_input={
                    "fact": word,
                    "play_event_id": str(row.pk),
                    #: Named, so a changed source day is a loud mismatch.
                    "day": day,
                },
                recorded_at=recorded_at,
                correlation_id=correlation_id,
                source_metadata=metadata,
            ):
                counts = replace(counts, events_appended=counts.events_appended + 1)

        if row.removed_at is not None and _append(
            library,
            playthrough_removed(run_id),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:removed:{row.pk}",
            command_input={"fact": "removed", "play_event_id": str(row.pk)},
            #: The row's own mark, which is why this is a second append.
            recorded_at=row.removed_at,
            correlation_id=uuid.uuid7(),
            source_metadata=metadata,
        ):
            counts = replace(counts, events_appended=counts.events_appended + 1)

    return counts
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_conversion.py -x"`
Expected: PASS, 10 tests.

- [ ] **Step 5: Lint and type check**

Run: `make lint && make typecheck && make vale`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add games/backfill/playthrough.py tests/test_playthrough_conversion.py
git commit -m "State one legacy row as one run"
```

---

### Task 3: The library walk, the pairing, and the default run

One row is not the run. This task walks a library's tracked games, pairs each
dated endpoint with the #676 status event that recorded the same day, and gives
every tracked game that ends with no live run the default one.

**Files:**
- Modify: `games/backfill/playthrough.py`
- Test: `tests/test_playthrough_conversion.py`

**Interfaces:**
- Consumes: `convert_row(...)`, `ConversionCounts` from Task 2.
- Produces: `convert_game(rows: Sequence[PlayEvent], *, library: UserLibrary,
  actor: User, tracked_id: uuid.UUID, tracked_at: datetime, candidates:
  Sequence[CandidateEvent]) -> ConversionCounts` and
  `convert_library(library: UserLibrary) -> ConversionCounts`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_conversion.py`:

```python
def test_a_tracked_game_with_no_rows_receives_one_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    counts = convert_library(owned_library)

    tracked = _tracked(owned_library, game)
    run = Playthrough.objects.get(player_game=tracked)
    assert counts.runs_default == 1
    assert counts.tracked == 1
    assert run.created_at == tracked.tracked_at
    assert run.start_recorded_at is None
    assert run.completion_recorded_at is None


def test_a_game_whose_only_row_was_removed_still_receives_a_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    remove(_row(game, started=date(2024, 1, 1)))
    counts = convert_library(owned_library)

    runs = Playthrough.objects.filter(player_game__game=game)
    assert counts.runs_converted == 1
    assert counts.runs_default == 1
    assert runs.filter(removed_at__isnull=True).count() == 1


def test_a_game_holding_a_live_row_receives_no_default(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    counts = convert_library(owned_library)

    assert counts.runs_default == 0
    assert Playthrough.objects.filter(player_game__game=game).count() == 1


def test_a_tracked_game_on_a_removed_catalog_row_is_skipped(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    remove(game)
    counts = convert_library(owned_library)

    assert counts.tracked_on_removed_game == 1
    assert counts.runs_converted == 0
    assert counts.runs_default == 0


def test_an_unambiguous_endpoint_adopts_the_status_event_correlation(owned_library):
    game = Game.objects.create(library=owned_library, name="Celeste", status="f")
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="f",
        timestamp=datetime(2024, 1, 9, 12, 0, tzinfo=UTC),
    )
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    counts = convert_library(owned_library)

    status_event = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playergame.status_changed"
    )
    completion = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playthrough.completed"
    )
    assert completion.correlation_id == status_event.correlation_id
    assert counts.endpoints_paired == 1
    #: The start had no #676 event to pair with.
    assert counts.endpoints_fresh == 1


def test_an_ambiguous_group_mints_fresh_ids(owned_library):
    game = Game.objects.create(library=owned_library, name="Hades", status="f")
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="f",
        timestamp=datetime(2024, 1, 9, 12, 0, tzinfo=UTC),
    )
    backfill_library(owned_library)
    #: Two rows completed on one day: the group pairs nothing.
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    _row(game, started=date(2024, 1, 2), ended=date(2024, 1, 9))
    counts = convert_library(owned_library)

    assert counts.endpoints_paired == 0
    assert counts.endpoints_fresh == 4


def test_a_dayless_endpoint_mints_a_fresh_id(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game)
    counts = convert_library(owned_library)

    assert counts.endpoints_dayless == 2
    assert counts.endpoints_paired == 0


def test_a_removed_row_joins_the_pairing_set(owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic", status="f")
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="f",
        timestamp=datetime(2024, 1, 9, 12, 0, tzinfo=UTC),
    )
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    remove(_row(game, started=date(2024, 1, 2), ended=date(2024, 1, 9)))
    counts = convert_library(owned_library)

    #: The preflight, which sees live rows only, would call this
    #: unambiguous. This run sees both, so the group pairs nothing.
    assert counts.endpoints_paired == 0


def test_a_second_pass_over_a_library_appends_nothing(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    repeat = convert_library(owned_library)

    assert repeat.events_appended == 0
    assert Playthrough.objects.count() == 1


def test_a_shared_game_converts_once_per_library(owned_library, django_user_model):
    shared = Game.objects.create(library=None, name="Shared")
    _row(shared, started=date(2024, 1, 1))
    other = django_user_model.objects.create_user(username="other", password="x")
    for library in (owned_library, other.library):
        PlayerGame.objects.create(
            library=library, game=shared, status="unplayed", tracked_at=timezone.now()
        )
        convert_library(library)

    assert Playthrough.objects.filter(player_game__library=owned_library).count() == 1
    assert Playthrough.objects.filter(player_game__library=other.library).count() == 1
    for run in Playthrough.objects.all():
        assert run.library_id == run.player_game.library_id
```

Add these imports at the top of the test module:

```python
from django.utils import timezone

from games.backfill.playthrough import convert_library
from games.models import GameStatusChange, LibraryEvent
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_conversion.py -k library -x"`
Expected: FAIL, `ImportError: cannot import name 'convert_library'`.

- [ ] **Step 3: Write the walk**

Append to `games/backfill/playthrough.py`:

```python
def convert_game(
    rows: Sequence[PlayEvent],
    *,
    library: UserLibrary,
    actor: User,
    tracked_id: uuid.UUID,
    tracked_at: datetime,
    candidates: Sequence[CandidateEvent],
) -> ConversionCounts:
    """State one tracked game's rows, and its default run where it needs one.

    Pairing runs here rather than over the whole library because a group
    is keyed on the PlayerGame, so no group spans two games. The
    candidates are this game's alone, which is why unclaimed_events is
    not read: every other game's events would count as unclaimed.
    """
    endpoints = [
        Endpoint(row_id=row.pk, kind=kind, day=day, aggregate_id=tracked_id)
        for row in rows
        for kind, day in (
            (EndpointKind.START, row.started),
            (EndpointKind.COMPLETION, row.ended),
        )
        if day is not None
    ]
    pairings = pair_endpoints(endpoints, candidates).pairings

    counts = NO_COUNTS
    #: legacy_order_key, so the run a person entered first is numbered
    #: first: the identities ascend with the rows.
    for row in sorted(rows, key=legacy_order_key):
        counts = counts + convert_row(
            row,
            library=library,
            actor=actor,
            tracked_id=tracked_id,
            pairings=pairings,
        )

    #: "No live run", not "no legacy row": a game whose only row was
    #: removed keeps a removed run and still needs the live one every
    #: tracked game holds. One live row is one live run, so the rows
    #: answer this without a query.
    if any(row.removed_at is None for row in rows):
        return counts

    counts = counts + ConversionCounts(runs_default=1)
    if _append(
        library,
        playthrough_created(tracked_id, playthrough_id=identity_at(tracked_at)),
        actor=actor,
        idempotency_key=f"{KEY_PREFIX}:default:{tracked_id}",
        command_input={"fact": "default", "player_game_id": str(tracked_id)},
        #: The tracked game's own instant: the run has been open since
        #: the library started tracking it.
        recorded_at=tracked_at,
        correlation_id=uuid.uuid7(),
        source_metadata={"origin": "backfill", "issue": PTHROUGH_ISSUE},
    ):
        counts = counts + ConversionCounts(events_appended=1)
    return counts


def convert_library(library: UserLibrary) -> ConversionCounts:
    """State every legacy row this library tracks, live and removed alike.

    The preflight's walk, with one difference: it takes live rows only,
    and this takes both. Nothing the library removed is destroyed, and
    #771 destroys the legacy table, so a skipped removed row would be a
    record that survives this run and not the next one.
    """
    actor = library.user
    counts = ConversionCounts(libraries=1)
    candidates_by_game: dict[uuid.UUID, list[CandidateEvent]] = defaultdict(list)
    for candidate in candidate_events(library).candidates:
        candidates_by_game[candidate.key.aggregate_id].append(candidate)

    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True).only(
        "id", "game_id", "tracked_at"
    )
    for batch in batched(
        keyset_pages(tracked, key=("id",), page_size=CONVERSION_PAGE_SIZE),
        CONVERSION_PAGE_SIZE,
    ):
        rows_for_game = _rows_for_games(batch)
        for row in batch:
            counts = counts + ConversionCounts(tracked=1)
            if row.game_id not in rows_for_game:
                counts = counts + ConversionCounts(tracked_on_removed_game=1)
                continue
            counts = counts + convert_game(
                rows_for_game[row.game_id],
                library=library,
                actor=actor,
                tracked_id=row.pk,
                tracked_at=row.tracked_at,
                candidates=candidates_by_game.get(row.pk, []),
            )
    return counts


def _rows_for_games(
    batch: Sequence[PlayerGame],
) -> dict[uuid.UUID, list[PlayEvent]]:
    """One batch's live catalog games, each with its legacy rows.

    A game the catalog marks removed is absent from the answer, which is
    what the caller counts as tracked_on_removed_game.
    """
    live_games = set(
        Game.objects.filter(
            pk__in=[row.game_id for row in batch], removed_at__isnull=True
        )
        .only("id")
        .values_list("pk", flat=True)
    )
    rows: dict[uuid.UUID, list[PlayEvent]] = {game_id: [] for game_id in live_games}
    for row in PlayEvent.objects.filter(game_id__in=live_games).only(*PLAYEVENT_FIELDS):
        rows[row.game_id].append(row)
    return rows
```

Extend the module's imports:

```python
from collections import defaultdict
from itertools import batched

from common.keyset import keyset_pages
from games.models import Game, PlayerGame, PlayEvent, Playthrough, UserLibrary
from games.preflight.playthrough import (
    CandidateEvent,
    Endpoint,
    EndpointKind,
    Pairing,
    RowVerdict,
    candidate_events,
    classify_row,
    legacy_order_key,
    pair_endpoints,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_conversion.py -x"`
Expected: PASS.

- [ ] **Step 5: Lint, type check, prose**

Run: `make lint && make typecheck && make vale`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add games/backfill/playthrough.py tests/test_playthrough_conversion.py
git commit -m "Walk a library's tracked games and give each one its runs"
```

---

### Task 4: The gate — six checks, each with its own code

The run must not commit against a state it cannot explain. Every check compares
what was written against the source rows, never against a second count of the
source.

**Files:**
- Modify: `games/backfill/playthrough.py`
- Test: `tests/test_playthrough_conversion.py`

**Interfaces:**
- Consumes: `convert_library(...)` from Task 3.
- Produces: `Mismatch` (frozen dataclass: `code: str`, `game_id: str`,
  `detail: str`, `as_dict() -> dict[str, str]`), `reconcile(library:
  UserLibrary) -> list[Mismatch]`, `ordering_violations() -> list[Mismatch]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_conversion.py`:

```python
def test_a_converted_library_reconciles_clean(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9), note="One")
    _row(game)
    remove(_row(game, started=date(2023, 1, 1)))
    _game(owned_library, name="Untouched")
    backfill_library(owned_library)
    convert_library(owned_library)

    assert reconcile(owned_library) == []
    assert ordering_violations() == []


def test_a_missing_run_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    #: A projection row nothing replayed: the source now says more than
    #: the events do.
    _row(game, started=date(2024, 2, 1))

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "endpoint_disagreement" in codes


def test_a_missing_marker_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    Playthrough.objects.update(completion_recorded_at=None)

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "missing_marker" in codes


def test_a_note_disagreement_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), note="First playthrough")
    convert_library(owned_library)
    Playthrough.objects.update(note="Something else")

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "endpoint_disagreement" in codes


def test_a_removed_row_without_a_removed_run_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    remove(_row(game, started=date(2024, 1, 1)))
    convert_library(owned_library)
    Playthrough.objects.filter(removed_at__isnull=False).update(removed_at=None)

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "removed_run_missing" in codes


def test_a_tracked_game_with_no_live_run_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    convert_library(owned_library)
    Playthrough.objects.update(removed_at=timezone.now())

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "no_live_run" in codes


def test_the_display_order_follows_the_legacy_order(owned_library):
    #: The Dark Souls 2 shape: one dated run and two nobody dated.
    game = _game(owned_library, name="Dark Souls 2")
    backfill_library(owned_library)
    _row(game, started=date(2014, 6, 7), ended=date(2014, 6, 17))
    _row(game)
    _row(game)
    convert_library(owned_library)

    numbered = with_display_number(Playthrough.objects.filter(player_game__game=game))
    by_number = sorted(numbered, key=lambda run: run.display_number)
    assert [run.display_number for run in by_number] == [1, 2, 3]
    assert by_number[0].started_lower == date(2014, 6, 7)
    assert reconcile(owned_library) == []


def test_rows_sharing_an_instant_are_numbered_in_either_order(owned_library):
    #: The sample fixture's shape: its anonymizer stamps every undated
    #: row one instant, so nothing the projection carries tells the two
    #: apart and the gate must not fail on it.
    game = _game(owned_library, name="Witcher")
    backfill_library(owned_library)
    _row(game)
    _row(game)
    PlayEvent.objects.filter(game=game).update(
        created_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    convert_library(owned_library)

    numbered = with_display_number(Playthrough.objects.filter(player_game__game=game))
    assert sorted(run.display_number for run in numbered) == [1, 2]
    assert reconcile(owned_library) == []


def test_a_display_order_disagreement_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    _row(game, started=date(2024, 2, 1))
    convert_library(owned_library)
    #: Both runs claim the later day, so the sequence no longer matches
    #: the rows.
    Playthrough.objects.filter(started_lower=date(2024, 1, 1)).update(
        started=TemporalValue.from_day(date(2024, 3, 1))
    )

    codes = {mismatch.code for mismatch in reconcile(owned_library)}
    assert "display_order_disagreement" in codes


def test_an_identity_out_of_order_is_reported(owned_library):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2014, 1, 1))
    convert_library(owned_library)
    #: A key minted now against a created_at from 2014.
    Playthrough.objects.update(created_at=datetime(2014, 1, 1, tzinfo=UTC))
    Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=_tracked(owned_library, game),
        kind="ordinary",
        created_at=datetime(2013, 1, 1, tzinfo=UTC),
    )

    codes = {mismatch.code for mismatch in ordering_violations()}
    assert "identity_ordering" in codes
```

Extend the test imports:

```python
from games.backfill.playthrough import Mismatch, ordering_violations, reconcile
from games.reads.playthrough_numbering import with_display_number
from timetracker.temporal import TemporalValue
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_conversion.py -k reconcile -x"`
Expected: FAIL, `ImportError: cannot import name 'reconcile'`.

- [ ] **Step 3: Write the gate**

Append to `games/backfill/playthrough.py`:

```python
@dataclass(frozen=True, slots=True)
class Mismatch:
    """One reason the conversion must not commit."""

    code: str
    game_id: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "game_id": self.game_id}


class RunShape(NamedTuple):
    """What a row and the run it became must both say."""

    started: date | None
    completed: date | None
    note: str


def _row_shape(row: PlayEvent) -> RunShape:
    return RunShape(started=row.started, completed=row.ended, note=row.note)


def _run_shape(run: Playthrough) -> RunShape:
    #: The generated bounds, which the database computed from the value
    #: the endpoint event carried.
    return RunShape(
        started=run.started_lower, completed=run.completed_lower, note=run.note
    )


def reconcile(library: UserLibrary) -> list[Mismatch]:
    """Compare every row the walk reached against the run it became.

    Scoped to those rows, never to PlayEvent.objects whole. A row on an
    untracked game, on a removed catalog game, or on a game with no
    projection row is outside this run by design, and a gate demanding a
    run for it would fail a migration that did nothing wrong.

    No column links a run back to the row it came from, and none is
    added: the projection carries what the library states, not where a
    one-time conversion read it. So the comparison is per game, over
    what both sides say.
    """
    mismatches: list[Mismatch] = []
    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True).only(
        "id", "game_id"
    )
    for batch in batched(
        keyset_pages(tracked, key=("id",), page_size=CONVERSION_PAGE_SIZE),
        CONVERSION_PAGE_SIZE,
    ):
        rows_for_game = _rows_for_games(batch)
        for tracked_row in batch:
            rows = rows_for_game.get(tracked_row.game_id)
            if rows is None:
                #: The catalog marks the game removed. The walk skipped
                #: it, so nothing is owed.
                continue
            mismatches.extend(
                _reconcile_game(str(tracked_row.game_id), rows, tracked_row.pk)
            )
    return mismatches


def _reconcile_game(
    game_id: str, rows: Sequence[PlayEvent], tracked_id: uuid.UUID
) -> list[Mismatch]:
    """The four row-to-row checks over one tracked game."""
    mismatches: list[Mismatch] = []
    runs = list(Playthrough.objects.filter(player_game_id=tracked_id))
    live_runs = [run for run in runs if run.removed_at is None]
    live_rows = [row for row in rows if row.removed_at is None]
    removed_rows = [row for row in rows if row.removed_at is not None]
    removed_runs = [run for run in runs if run.removed_at is not None]

    #: Check 1. A multiset, because nothing distinguishes two rows that
    #: say the same thing, and neither side is ordered here.
    expected = Counter(_row_shape(row) for row in live_rows)
    #: The default run says nothing about a day, so it is not a row's.
    converted = Counter(
        _run_shape(run)
        for run in live_runs
        if run.start_recorded_at is not None or run.completion_recorded_at is not None
    )
    if expected != converted:
        mismatches.append(
            Mismatch(
                code="endpoint_disagreement",
                game_id=game_id,
                detail=f"the rows say {sorted(expected.items())}, "
                f"the runs say {sorted(converted.items())}",
            )
        )
    for run in live_runs:
        markers = (run.start_recorded_at, run.completion_recorded_at)
        if any(marker is None for marker in markers) and not all(
            marker is None for marker in markers
        ):
            mismatches.append(
                Mismatch(
                    code="missing_marker",
                    game_id=game_id,
                    detail=f"run {run.pk} states one act and not the other",
                )
            )

    #: Check 2.
    if len(removed_runs) != len(removed_rows):
        mismatches.append(
            Mismatch(
                code="removed_run_missing",
                game_id=game_id,
                detail=f"{len(removed_rows)} removed row(s), "
                f"{len(removed_runs)} removed run(s)",
            )
        )

    #: Check 3.
    if not live_runs:
        mismatches.append(
            Mismatch(
                code="no_live_run",
                game_id=game_id,
                detail="a tracked game holds no live ordinary run",
            )
        )

    #: Check 4. Rows that are peers on all three come back in either
    #: order, and the triples they compare as are equal, so a peer
    #: swap cannot be seen here -- which is the point.
    by_display = [
        (run.started_lower, run.completed_lower, run.created_at)
        for run in sorted(
            with_display_number(Playthrough.objects.filter(player_game_id=tracked_id)),
            key=lambda run: run.display_number,
        )
        if run.start_recorded_at is not None or run.completion_recorded_at is not None
    ]
    by_legacy = [
        (row.started, row.ended, row.created_at)
        for row in sorted(live_rows, key=legacy_order_key)
    ]
    if by_display != by_legacy:
        mismatches.append(
            Mismatch(
                code="display_order_disagreement",
                game_id=game_id,
                detail=f"the rows order as {by_legacy}, the runs as {by_display}",
            )
        )
    return mismatches


def ordering_violations() -> list[Mismatch]:
    """Check 6: every Playthrough key still sorts by its created_at.

    The one invariant no constraint enforces, and the one this run is
    most able to break: it records instants from years ago, where a
    uuid7() minted now would stamp today and pass every other check.
    """
    entries = [
        entry for entry in identity_models() if entry.table == "games_playthrough"
    ]
    return [
        Mismatch(
            code="identity_ordering",
            game_id=violation.subject,
            detail=violation.detail,
        )
        for violation in check_ordering(entries).violations
    ]
```

Extend the module's imports:

```python
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, NamedTuple

from games.identity_audit import check_ordering, identity_models
from games.reads.playthrough_numbering import with_display_number
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_conversion.py -x"`
Expected: PASS.

- [ ] **Step 5: Lint, type check, prose**

Run: `make lint && make typecheck && make vale`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add games/backfill/playthrough.py tests/test_playthrough_conversion.py
git commit -m "Gate the conversion on what the rows say"
```

---

### Task 5: Migration 0045, and the drift check

The run happens once, on the way to the deployed schema, and reports what it
did in one machine-readable line.

**Files:**
- Create: `games/migrations/0045_playthrough_conversion_backfill.py`
- Test: `tests/test_playthrough_conversion.py`

**Interfaces:**
- Consumes: `convert_library`, `reconcile`, `ordering_violations`, `Mismatch`,
  `NO_COUNTS` from Tasks 3 and 4.
- Produces: `MACHINE_PREFIX =
  "PLAYTHROUGH_CONVERSION_RECONCILIATION_JSON="`, module function
  `convert_legacy_playevents(apps, schema_editor)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_conversion.py`:

```python
def test_the_migration_converts_and_reports(owned_library, capsys):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    convert_legacy_playevents(None, None)

    line = next(
        text
        for text in capsys.readouterr().out.splitlines()
        if text.startswith(MACHINE_PREFIX)
    )
    payload = json.loads(line[len(MACHINE_PREFIX) :])
    assert payload["mismatches"] == []
    assert payload["summary"]["runs_converted"] == 1
    assert payload["summary"]["libraries"] == 1


def test_the_migration_raises_on_a_mismatch(owned_library, monkeypatch):
    game = _game(owned_library)
    backfill_library(owned_library)
    _row(game, started=date(2024, 1, 1))
    monkeypatch.setattr(
        "games.migrations.0045_playthrough_conversion_backfill.reconcile",
        lambda library: [Mismatch(code="test", game_id=str(game.pk), detail="x")],
        raising=False,
    )
    with pytest.raises(RuntimeError, match="1 mismatch"):
        convert_legacy_playevents(None, None)
```

The second test imports the migration by path, which a module name beginning
with a digit forbids. Import it once at the top of the test module with
`importlib`:

```python
import importlib
import json

_migration = importlib.import_module(
    "games.migrations.0045_playthrough_conversion_backfill"
)
MACHINE_PREFIX = _migration.MACHINE_PREFIX
convert_legacy_playevents = _migration.convert_legacy_playevents
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playthrough_conversion.py -k migration -x"`
Expected: FAIL, `ModuleNotFoundError: No module named
'games.migrations.0045_playthrough_conversion_backfill'`.

- [ ] **Step 3: Write the migration**

Create `games/migrations/0045_playthrough_conversion_backfill.py`:

```python
import json

from django.db import migrations

MACHINE_PREFIX = "PLAYTHROUGH_CONVERSION_RECONCILIATION_JSON="
HUMAN_PREFIX = "Playthrough conversion reconciliation:"
SUMMARY_KEYS = (
    "libraries",
    "tracked",
    "tracked_on_removed_game",
    "live_rows",
    "rows_removed_converted",
    "runs_converted",
    "runs_default",
    "notes",
    "endpoints_paired",
    "endpoints_fresh",
    "endpoints_dayless",
    "events_appended",
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
            f"Playthrough conversion failed with {len(mismatches)} mismatch(es)."
        )


def convert_legacy_playevents(apps, schema_editor):
    """State every legacy row as Playthrough events.

    The live models and the live event machinery, deliberately, for the
    reason 0033 records: historical models cannot run a projector or
    validate a payload, so a backfill that wrote events and projection
    rows by hand would be a second event writer. The cost is that this
    migration is pinned to the application as it stands when it runs,
    and the gate below is what keeps a future incompatibility loud.
    """
    del apps, schema_editor
    from games.backfill.playthrough import (
        NO_COUNTS,
        Mismatch,
        convert_library,
        ordering_violations,
        reconcile,
    )
    from games.models import UserLibrary

    counts = NO_COUNTS
    mismatches = []
    for library in UserLibrary.objects.order_by("pk"):
        counts = counts + convert_library(library)
        #: A second pass appends nothing, and proves it by counting
        #: nothing. Check 5.
        repeat = convert_library(library)
        if repeat.events_appended:
            mismatches.append(
                Mismatch(
                    code="count_drift",
                    game_id=str(library.pk),
                    detail=f"a second pass appended {repeat.events_appended} event(s)",
                )
            )
        mismatches.extend(reconcile(library))
    mismatches.extend(ordering_violations())

    summary = counts.as_dict() | {"mismatches": len(mismatches)}
    _emit(summary, mismatches)
    _fail_if_mismatched(mismatches)


class Migration(migrations.Migration):
    dependencies = [("games", "0044_playthrough_endpoint_columns")]

    operations = [
        migrations.RunPython(
            convert_legacy_playevents,
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_conversion.py -x"`
Expected: PASS.

- [ ] **Step 5: Confirm no model state moved**

Run: `make makemigrations ARGS="--check --dry-run"`
Expected: "No changes detected" — 0045 is data only.

- [ ] **Step 6: Commit**

```bash
git add games/migrations/0045_playthrough_conversion_backfill.py tests/test_playthrough_conversion.py
git commit -m "Run the conversion once, on the way to the deployed schema"
```

---

### Task 6: The sample fixture gets its runs

A loaded fixture currently leaves every tracked game without the run every
tracked game holds, because `backfill_library()` appends
`library.playergame.created` rather than dispatching `TrackGame`.

**Files:**
- Modify: `games/management/commands/load_sample_data.py:153`
- Test: `tests/test_playthrough_conversion.py`

**Interfaces:**
- Consumes: `convert_library(library)` from Task 3.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_conversion.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_the_sample_fixture_leaves_every_tracked_game_holding_a_run():
    call_command("load_sample_data", "--username", "sample", "--password", "sample")
    library = UserLibrary.objects.get(user__username="sample")
    tracked = PlayerGame.objects.filter(library=library, removed_at__isnull=True)
    with_runs = tracked.filter(
        playthroughs__removed_at__isnull=True, playthroughs__kind="ordinary"
    ).distinct()

    assert tracked.count() > 0
    assert with_runs.count() == tracked.count()
    assert reconcile(library) == []
```

Extend the test imports:

```python
from django.core.management import call_command

from games.models import UserLibrary
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playthrough_conversion.py -k sample_fixture -x"`
Expected: FAIL — `with_runs.count()` is 0 against a non-zero `tracked.count()`.

- [ ] **Step 3: Call the conversion**

In `games/management/commands/load_sample_data.py`, directly below the
`backfill_library(user.library)` call and inside the same block:

```python
            backfill_library(user.library)
            #: And the runs those tracked games hold: #684 states one
            #: per legacy row, and one default for every game holding
            #: none. Inside this block, so a load either lands whole or
            #: does not land.
            convert_library(user.library)
```

Add the import beside the existing backfill import:

```python
from games.backfill.playthrough import convert_library
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_playthrough_conversion.py -k sample_fixture -x"`
Expected: PASS. Note the wall time this test adds — the fixture holds 209
legacy rows over 858 tracked games, so the call appends roughly 1290 events.

- [ ] **Step 5: Run every suite that loads the fixture**

Run: `make test ARGS="tests/test_bootstrap_container.py tests/test_anonymize_sample.py tests/test_external_references.py tests/test_library_commands.py"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add games/management/commands/load_sample_data.py tests/test_playthrough_conversion.py
git commit -m "Give a loaded fixture the runs its tracked games hold"
```

---

### Task 7: The gate, and the rehearsal against the deployed database

Nothing here changes code. It is the verification the spec names, and it is a
task because its output decides whether the branch ships.

**Files:**
- Modify (only if a check fails): whichever file the failure names.

- [ ] **Step 1: Run the full check**

Run: `make check`
Expected: green, including `e2e/`. A hand-picked subset is not the gate.

- [ ] **Step 2: Run the identity audit**

Run: `make audit-uuid-identity`
Expected: no violation. A violation on `games_playthrough` means an identity
was minted with `uuid.uuid7()` somewhere the plan says `identity_at()`.

- [ ] **Step 3: Rehearse against a copy of the deployed database**

Run: `make fetch-dump` then `make verify-dump KEEP=1`

The dump stands at `0022_external_references`, so the run applies 0033 and 0045
in one pass, in that order. Watch for the `count_drift` mismatch: it is the one
failure that means the second pass appended, and it aborts the migration.

- [ ] **Step 4: Diff the emitted counts against the issue**

Read the `PLAYTHROUGH_CONVERSION_RECONCILIATION_JSON=` line from the migration
output. Against the counts #686 published on
[issue #684](https://github.com/KucharczykL/timetracker/issues/684), expect:

| Field | Expected | Where it comes from |
|---|---|---|
| `libraries` | 1 | the deployed database holds one |
| `tracked` | 858 | #686's `tracked` |
| `live_rows` | 209 | #686's `live_rows` |
| `rows_removed_converted` | 0 | `games_playevent` has no `removed_at` at 0022 |
| `runs_converted` | 209 | one per row |
| `runs_default` | 663 | #686's `tracked_without_rows` |
| `clean_both` | 203 | #686's `clean_both` |
| `no_known_endpoint` | 6 | #686's `no_known_endpoint` |
| `notes` | 45 | read from the dump; #686 publishes no note count |
| `endpoints_paired` | 296 | #686's `pairs_unambiguous` |
| `endpoints_fresh` | 110 | #686's `pairs_ambiguous` 7 + `pairs_absent` 103 |
| `endpoints_dayless` | 12 | 6 rows × 2 endpoints |

`endpoints_paired + endpoints_fresh + endpoints_dayless` must be 418, which is
209 × 2. A number that is off by a little is a bug in this run; a number that
is off by a lot is a database that moved since #686 measured, and the preflight
should be re-run before reading further.

- [ ] **Step 5: Run the identity audit against the restored copy**

With the scratch database `verify-dump KEEP=1` left behind, run
`make audit-uuid-identity` against its `DATABASE_URL`.
Expected: no violation, over real rows rather than test rows.

- [ ] **Step 6: Open the pull request**

```bash
git push -u origin issue-684-playthrough-conversion
gh pr create --fill
```

---

## Self-Review

**Spec coverage.** Every section of the spec has a task: the row rule and its
five shapes (Task 2), the identity rule (Tasks 1, 2, 4), the note (Task 2),
pairing recomputed over this run's own set (Task 3), idempotency keys and the
`command_input` rule (Task 2), the default run (Task 3), removed rows (Tasks 2
and 3), scope (Task 3), all six gate checks (Tasks 4 and 5), where it runs
(Tasks 5 and 6), and verification (Task 7). Rollback needs no task: the
migration reverses as `noop` and #667 already rebuilds the projection.

**Placeholders.** None. Every step names its command and its expected result,
and every code step carries the code.

**Type consistency.** `ConversionCounts` fields are named once in Task 2 and
read by name in Tasks 3, 5 and 7. `convert_row` / `convert_game` /
`convert_library` keep the same parameter names throughout. `Mismatch(code,
game_id, detail)` matches what `_emit` sorts on in Task 5. `Endpoint(row_id,
kind, day, aggregate_id)` is the preflight's own NamedTuple, so the lookup in
Task 2 and the construction in Task 3 compare equal by value.

**One thing an implementer will want to know.** The conversion never reads a
run's identity back out of the database. It mints one, uses it for that row's
events, and on a second pass mints a different one that every key replays past
without appending. That is only sound because no `command_input` names it —
which is why that constraint is in the Global Constraints and not buried in a
comment.
