# Playthrough start repair implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** State a `started` endpoint for the 542 Playthrough runs #684 minted
with no acts, dated by the earlier of the library's own two records of a start.

**Architecture:** One append-only pass in the shape of
`games/backfill/playthrough.py`, gated by a data migration that converts,
checks and rolls back. Scope keys on the creation event's own origin, so the
pass reaches exactly the runs #684 minted and no blank a person chose. #684's
`reconcile()` is amended to read a repaired run as stating no act, without
which it reports three mismatches for every repaired game. A read-only report
target prints the same figures against a restored copy.

**Tech Stack:** Django 6, PostgreSQL 18, Python 3.14, pytest with pytest-xdist,
the event stream in `games/events/`, `TemporalValue` in `timetracker/temporal.py`.

**Spec:**
[docs/superpowers/specs/2026-09-10-issue-1038-playthrough-start-repair-design.md](../specs/2026-09-10-issue-1038-playthrough-start-repair-design.md)

## Global Constraints

- Drive everything through `make`. No bare `uv run`, `pnpm`, `pytest`.
  Focused runs: `make test ARGS="tests/test_playthrough_start_repair.py -x"`.
- The verification gate is the full `make check`, `e2e/` included. Use
  `make check-fast` while iterating; it is not the gate.
- Python 3.14 is a hard prerequisite. `python --version` must read 3.14.x.
- **Never write to a `GeneratedField`**: `started_lower`, `started_upper`,
  `completed_lower`, `completed_upper` are written by the database.
- **Nothing destroys a record.** No `.delete()`.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest.
  This pass appends rather than dispatching, for the reason `_append` records.
- **Nothing opens a server-side cursor.** No `QuerySet.iterator()`. Page with
  `keyset_pages()` from `common/keyset.py`.
- **One act, one verb.** The event type, its command and its projection column
  share one verb.
- **Refused words** are enforced by `make vale` over every tracked `.md` and
  over Python comments and docstrings: `fold`, `seam`, `tombstone`, `archive`,
  `delete` beside a record noun, `heal`. See [Vocabulary](../../vocabulary.md).
- **Complete words in identifiers.** `element` not `el`, `event` not `e`.
- **Name compound types.** A tuple or dict passed between functions gets a
  `NamedTuple`, `TypedDict` or alias.
- Comments are seven words or fewer, written as `#:` above the line.
- The issue number is **1038**. Every idempotency key and every
  `source_metadata` value names it.

---

### Task 1: Lift the two shared pieces out of #684

`games/backfill/playthrough_start.py` needs `_append` and needs `Mismatch`, and
#684's `reconcile()` will need to read a fact the new module states. Importing
both ways is a cycle, so the two shared pieces move first. This task changes no
behaviour: every existing test must pass unchanged.

**Files:**

- Create: `games/backfill/appending.py`
- Create: `games/backfill/mismatch.py`
- Modify: `games/backfill/playthrough.py:147-190` (the `_append` definition),
  `games/backfill/playthrough.py:493-517` (the `Mismatch` definition)
- Test: `tests/test_playthrough_conversion.py` (unchanged, must stay green)

**Interfaces:**

- Consumes: nothing.
- Produces: `append_one(library, event, *, actor, idempotency_key,
  command_input, recorded_at, correlation_id, source_metadata) -> bool` in
  `games/backfill/appending.py`; `Mismatch(code, subject, detail)` with
  `as_dict() -> dict[str, str]` in `games/backfill/mismatch.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_conversion.py`:

```python
def test_the_shared_pieces_are_importable_on_their_own():
    from games.backfill.appending import append_one
    from games.backfill.mismatch import Mismatch as SharedMismatch

    #: Re-exported, so every existing import still reads.
    from games.backfill.playthrough import Mismatch as ConversionMismatch

    assert ConversionMismatch is SharedMismatch
    assert callable(append_one)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playthrough_conversion.py -k shared_pieces -x"`

Expected: FAIL with `ModuleNotFoundError: No module named 'games.backfill.appending'`

- [ ] **Step 3: Create `games/backfill/appending.py`**

Move the body of `_append` verbatim, renamed. Keep its whole docstring: it is
the record of why this path does not dispatch.

```python
"""One event, appended rather than dispatched."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from django.contrib.auth.models import User

from games.events.append import AppendResult, LockedStream, SourceMetadata
from games.events.idempotency import idempotent_append
from games.events.vocabulary import NewEvent
from games.models import UserLibrary


def append_one(
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
    """Append one event. True only when it appended.

    One event per call, never one call per row, for two reasons:
    LockedStream.append() stamps one recorded_at across every row
    of a call, and a removed legacy row carries two instants; and
    one key per fact lets the note and each endpoint replay on
    their own.

    No command_input names an identity a pass mints. Such an
    identity is fresh per pass, so a fingerprint holding one
    answers a second pass with IdempotencyKeyMismatch, in place of
    the drift the gate reads. A PlayerGame id is stable and may be
    named.

    dispatch() is not used: its refusals guard what a person
    states next, and this states what the library recorded.
    """

    def build(stream: LockedStream) -> Sequence[NewEvent]:
        #: The contract passes it; nothing reads it.
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
    #: Positive: an UnchangedAppend appended nothing either.
    return isinstance(outcome, AppendResult)
```

- [ ] **Step 4: Create `games/backfill/mismatch.py`**

```python
"""One reason a gated pass must not commit."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One reason the run must not commit.

    The code is each pass's own enumeration, so a pass adds a
    reason without touching another pass's list.
    """

    code: StrEnum
    #: A game, a library, or a table: whatever the code names.
    subject: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "subject": self.subject,
        }
```

- [ ] **Step 5: Rewire `games/backfill/playthrough.py`**

Take out the `_append` function body and the `Mismatch` class body. Add the two
imports beside the existing ones, and keep the old names bound so every caller
and every test reads unchanged:

```python
from games.backfill.appending import append_one as _append
from games.backfill.mismatch import Mismatch
```

Take `AppendResult`, `LockedStream` and `idempotent_append` out of that module's
imports if nothing else there uses them, and take out the now-unused `Any` and
`Sequence` imports if nothing else there uses them either. Run `make lint` to
find out rather than guessing.

- [ ] **Step 6: Run the whole conversion suite**

Run: `make test ARGS="tests/test_playthrough_conversion.py -x"`

Expected: PASS, every test, including the new one.

- [ ] **Step 7: Run lint and types**

Run: `make lint && make typecheck`

Expected: clean. `Mismatch.code` is now `StrEnum` rather than `MismatchCode`;
if mypy reports a narrowing failure at a `mismatch.code is MismatchCode.X`
comparison, change that comparison to `==`, which is what `StrEnum` supports.

- [ ] **Step 8: Commit**

```bash
git add games/backfill/appending.py games/backfill/mismatch.py \
  games/backfill/playthrough.py tests/test_playthrough_conversion.py
git commit -m "Lift the append and the mismatch out of one pass"
```

---

### Task 2: Read the runs in scope

Scope keys on the creation event's own origin. Null markers alone do not select
the default run: `CreatePlaythrough` lets a person create a blank one and #679
states a blank one at track time, and neither is this pass's debt.

**Files:**

- Create: `games/backfill/playthrough_start.py`
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `Mismatch` from Task 1.
- Produces: `START_ISSUE = 1038`, `KEY_PREFIX`, `RunInScope(run_id,
  player_game_id, game_id)`, `default_run_ids(library) -> set[uuid.UUID]`,
  `runs_in_scope(library) -> list[RunInScope]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playthrough_start_repair.py`:

```python
"""What the empty runs come to state. Issue #1038."""

import uuid
from datetime import UTC, date, datetime

import pytest

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import convert_library
from games.backfill.playthrough_start import runs_in_scope
from games.models import Game, PlayerGame, Playthrough, Session
from games.commands.playthrough import ActStatement
from games.removal import remove
from games.writes.playthrough import RunDraft, record_run
from timetracker.temporal import TemporalValue

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _converted(library):
    """The state #684 leaves: tracked, and one empty run each."""
    backfill_library(library)
    convert_library(library)


def test_a_default_run_is_in_scope(owned_library):
    game = _game(owned_library)
    _converted(owned_library)

    scope = runs_in_scope(owned_library)

    assert len(scope) == 1
    assert scope[0].game_id == game.pk


def test_a_blank_run_a_person_created_is_left_alone(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        removed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    record_run(
        owned_library.user,
        game,
        RunDraft(started=None, completed=None, note=""),
        correlation_id=uuid.uuid7(),
    )

    scope = runs_in_scope(owned_library)

    assert scope == []


def test_a_run_stating_either_act_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        start_recorded_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert runs_in_scope(owned_library) == []


def test_a_removed_run_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        removed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert runs_in_scope(owned_library) == []


def test_a_run_at_a_removed_game_is_left_alone(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    remove(game)

    assert runs_in_scope(owned_library) == []
```

The third test writes `start_recorded_at` with `update()` rather than an event
on purpose: this task reads scope and states nothing, so the projection row is
the whole subject. Later tasks state the act properly.

`record_run` at `games/writes/playthrough.py:283` is the one way a person
creates a run, and it takes a `RunDraft(started, completed, note)` whose two
endpoints are `ActStatement | None`. The removal above is what forces it to
create rather than fill the default in: `run_to_adopt` would otherwise hand it
the blank run #684 minted.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: FAIL with
`ModuleNotFoundError: No module named 'games.backfill.playthrough_start'`

- [ ] **Step 3: Write the module**

Create `games/backfill/playthrough_start.py`:

```python
"""A start for the runs #684 left empty. #1038.

#684 states one run per legacy PlayEvent row, and one empty
default for a tracked game holding none. Most tracked games
held none, so most runs state no day at all while a status
change and a session both record when play began. This pass
states that day, and states no completion.
"""

import uuid
from typing import NamedTuple

from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import (
    LibraryEvent,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)

#: Named in every key and every metadata value.
START_ISSUE = 1038
KEY_PREFIX = f"backfill:{START_ISSUE}:playthrough-start"

#: The issue whose defaults this repairs.
CONVERSION_ISSUE = 684


class RunInScope(NamedTuple):
    """One empty default, and what dates it."""

    run_id: uuid.UUID
    player_game_id: uuid.UUID
    game_id: uuid.UUID


def default_run_ids(library: UserLibrary) -> set[uuid.UUID]:
    """Every run #684 minted holding no legacy row.

    The creation event names its origin and the projection row
    names none, so the stream answers this. A creation #684
    made from a row names that row; a default names none, which
    is what the excluded key reads.
    """
    return set(
        LibraryEvent.objects.filter(
            library=library,
            event_type=PLAYTHROUGH_CREATED.event_type,
            source_metadata__origin="backfill",
            source_metadata__issue=CONVERSION_ISSUE,
        )
        .exclude(source_metadata__has_key="play_event_id")
        .values_list("aggregate_id", flat=True)
    )


def runs_in_scope(library: UserLibrary) -> list[RunInScope]:
    """The empty defaults this pass may date.

    Six conditions, and the sixth carries the weight: a person
    may create a blank run and #679 states one at track time.
    Neither is this pass's debt.
    """
    identifiers = default_run_ids(library)
    if not identifiers:
        return []
    rows = (
        Playthrough.objects.filter(
            pk__in=identifiers,
            library=library,
            kind=PlaythroughKind.ORDINARY,
            removed_at__isnull=True,
            start_recorded_at__isnull=True,
            completion_recorded_at__isnull=True,
            player_game__removed_at__isnull=True,
            player_game__game__removed_at__isnull=True,
        )
        .order_by("pk")
        .values_list("pk", "player_game_id", "player_game__game_id")
    )
    return [
        RunInScope(run_id=run_id, player_game_id=player_game_id, game_id=game_id)
        for run_id, player_game_id, game_id in rows
    ]
```

`values_list` rather than model instances on purpose: it pins the columns the
pass reads, the way `_PLAYEVENT_FIELDS` pins #684's, and a migration replaying
this code against a later schema cannot select a column that does not exist.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: PASS, five tests.

- [ ] **Step 5: Commit**

```bash
git add games/backfill/playthrough_start.py tests/test_playthrough_start_repair.py
git commit -m "Read the runs the conversion left empty"
```

---

### Task 3: Read the two evidence days

**Files:**

- Modify: `games/backfill/playthrough_start.py`
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `RunInScope` from Task 2.
- Produces: `StartSource` (`StrEnum`, values `status` and `session`),
  `Evidence(day, source)`, `status_days(library) -> dict[uuid.UUID, date]`
  keyed on `player_game_id`, `session_days(library) -> dict[uuid.UUID, date]`
  keyed on `game_id`, `evidence_for(run, *, status, session) -> Evidence | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_a_session_states_the_viewers_day_not_the_servers(
    owned_user, owned_library, set_user_setting
):
    game = _game(owned_library)
    _converted(owned_library)
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")
    #: Late enough in UTC that Kiritimati reads tomorrow.
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 23, 30, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 6, 0, 30, tzinfo=UTC),
    )

    assert session_days(owned_library)[game.pk] == date(2026, 1, 6)


def test_a_removed_session_states_no_day(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
    )
    remove(session)

    assert session_days(owned_library) == {}


def test_a_session_on_a_removed_game_states_no_day(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
    )
    remove(game)

    assert session_days(owned_library) == {}


def test_the_earliest_session_wins(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    for day in (7, 3, 9):
        Session.objects.create(
            game=game,
            timestamp_start=datetime(2026, 1, day, 10, 0, tzinfo=UTC),
            timestamp_end=datetime(2026, 1, day, 11, 0, tzinfo=UTC),
        )

    assert session_days(owned_library)[game.pk] == date(2026, 1, 3)


def test_a_status_change_states_its_day(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    assert status_days(owned_library)[tracked.pk] == date(2026, 1, 4)


def test_the_earlier_of_the_two_wins_and_names_its_source(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2026, 1, 9, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    run = runs_in_scope(owned_library)[0]

    found = evidence_for(
        run,
        status=status_days(owned_library),
        session=session_days(owned_library),
    )

    assert found == Evidence(date(2026, 1, 4), StartSource.SESSION)


def test_a_run_holding_neither_reads_nothing(owned_library):
    _game(owned_library)
    _converted(owned_library)
    run = runs_in_scope(owned_library)[0]

    assert evidence_for(run, status={}, session={}) is None
```

Add these imports at the top of the test module:

```python
from games.backfill.playthrough_start import (
    Evidence,
    StartSource,
    evidence_for,
    session_days,
    status_days,
)
from games.models import GameStatusChange
```

`set_user_setting` is an existing fixture, the one
`tests/test_playthrough_activity.py:106` uses to state a viewer's zone. Take
its two positional arguments as that file does; write no second helper.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: FAIL with `ImportError: cannot import name 'Evidence'`

- [ ] **Step 3: Write the readers**

Append to `games/backfill/playthrough_start.py`, and add the imports each needs:

```python
def status_days(library: UserLibrary) -> dict[uuid.UUID, date]:
    """The earliest #676 status day, per tracked game.

    candidate_events() reads the whole library in one scan,
    because LibraryEvent indexes neither the type nor the
    payload. A query per run would pay that scan 858 times.

    The four statuses are the whole list: legacy Game.Status
    held u, p, f, r and a, so a #676 event carries no other
    word and shelved cannot appear.
    """
    earliest: dict[uuid.UUID, date] = {}
    candidates, _undated = candidate_events(library)
    for candidate in candidates:
        tracked_id = candidate.key.aggregate_id
        day = candidate.key.day
        if tracked_id not in earliest or day < earliest[tracked_id]:
            earliest[tracked_id] = day
    return earliest


def session_days(library: UserLibrary) -> dict[uuid.UUID, date]:
    """The earliest live session day, per game.

    Read in the viewer's own zone, through the very clock
    games/reads/playthrough_activity.py reads a day with, so
    the day this states and the day the Activity column
    counts from cannot come from two calendars. A game the
    library does not own answers nothing, so a run at a
    shared catalog game reads no session.
    """
    zone = activity_clock(library).zone
    rows = (
        Session.objects.alive()
        .filter(game__library=library, game__removed_at__isnull=True)
        #: Cleared, so the grouping keys on the game alone.
        .order_by()
        .annotate(played_day=TruncDate("timestamp_start", tzinfo=zone))
        .values("game_id")
        .annotate(first_day=Min("played_day"))
        .values_list("game_id", "first_day")
    )
    return {game_id: day for game_id, day in rows if day is not None}


def evidence_for(
    run: RunInScope,
    *,
    status: Mapping[uuid.UUID, date],
    session: Mapping[uuid.UUID, date],
) -> Evidence | None:
    """The day this run's start takes, and what dated it.

    The earlier wins: a status set years after the play must
    not outrank a session that proves the play, and a game
    marked Played with no session still states a day. On an
    equal day the session is named, because it records play.
    """
    status_day = status.get(run.player_game_id)
    session_day = session.get(run.game_id)
    if status_day is None and session_day is None:
        return None
    if status_day is None:
        return Evidence(session_day, StartSource.SESSION)
    if session_day is None:
        return Evidence(status_day, StartSource.STATUS)
    if session_day <= status_day:
        return Evidence(session_day, StartSource.SESSION)
    return Evidence(status_day, StartSource.STATUS)
```

with these two declarations placed above them:

```python
class StartSource(StrEnum):
    """Which record dated the start."""

    STATUS = "status"
    SESSION = "session"


class Evidence(NamedTuple):
    """A day, and the record that states it."""

    day: date
    source: StartSource
```

and these imports added to the module head:

```python
from collections.abc import Mapping
from datetime import date
from enum import StrEnum

from django.db.models import Min
from django.db.models.functions import TruncDate

from games.models import Session
from games.preflight.playthrough import candidate_events
from games.reads.playthrough_activity import activity_clock
```

Add this note under the module docstring, because the mismatch is real and a
reader will otherwise assume the two days share a zone:

```python
#: The two evidence days are read in different zones. A status
#: day was frozen when #676 ran, by transition_effective_time,
#: which reads the server's TIME_ZONE. A session day is read now
#: in the viewer's DISPLAY_TIME_ZONE. The legacy timestamp the
#: status day came from is in a table #771 takes, so the frozen
#: day cannot be read again. The report prints both.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: PASS, twelve tests.

- [ ] **Step 5: Run mypy**

Run: `make typecheck`

Expected: clean. `evidence_for` narrows `session_day` and `status_day` from
`date | None` to `date` through the three guards above; if mypy disagrees on a
branch, add the guard it asks for rather than a `cast`.

- [ ] **Step 6: Commit**

```bash
git add games/backfill/playthrough_start.py tests/test_playthrough_start_repair.py
git commit -m "Read the two days that date a start"
```

---

### Task 4: State the start

**Files:**

- Modify: `games/backfill/playthrough_start.py`
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `append_one` from Task 1, `runs_in_scope`, `status_days`,
  `session_days`, `evidence_for` from Tasks 2 and 3.
- Produces: `StartRepairCounts` with `__add__` and `as_dict()`,
  `NO_START_COUNTS`, `RepairResult(counts, stated, left_alone)`,
  `repair_library(library) -> RepairResult`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_the_pass_states_the_day_a_session_proves(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    result = repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    assert result.counts.events_appended == 1
    assert result.counts.from_session == 1
    assert run.start_recorded_at is not None
    assert run.started_lower == date(2026, 1, 4)
    assert run.started == TemporalValue.from_day(date(2026, 1, 4))
    assert run.start_note == ""


def test_the_pass_states_no_completion_for_an_abandoned_game(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="a",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)

    repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is None


def test_a_run_holding_no_evidence_still_states_no_act(owned_library):
    _game(owned_library)
    _converted(owned_library)

    result = repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    assert result.counts.no_evidence == 1
    assert result.counts.events_appended == 0
    assert run.start_recorded_at is None
    assert run.completion_recorded_at is None


def test_a_second_pass_appends_nothing(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    first = repair_library(owned_library)
    second = repair_library(owned_library)

    assert first.counts.events_appended == 1
    assert second.counts.events_appended == 0
    assert second.counts.runs_in_scope == 0


def test_the_event_names_the_source_that_won(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_library(owned_library)
    event = LibraryEvent.objects.get(
        library=owned_library,
        event_type=PLAYTHROUGH_STARTED.event_type,
    )

    assert event.source_metadata == {
        "origin": "backfill",
        "issue": 1038,
        "source": "session",
    }


def test_the_pass_replays_to_the_same_row(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
```

Add to the test module's imports:

```python
from games.backfill.playthrough_start import repair_library
from games.events.playthrough import PLAYTHROUGH_STARTED
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import LibraryEvent
```

That last test is
`test_a_converted_library_replays_into_the_same_rows` in
`tests/test_playthrough_conversion.py:438`, over a repaired library rather than
a converted one. A row a replay cannot reach states its drift in that list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k repair -x"`

Expected: FAIL with `ImportError: cannot import name 'repair_library'`

- [ ] **Step 3: Write the counts and the pass**

Append to `games/backfill/playthrough_start.py`:

```python
@dataclass(frozen=True, slots=True)
class StartRepairCounts:
    """What one pass did, summable everywhere."""

    libraries: int = 0
    runs_in_scope: int = 0
    #: A run in scope holding neither record.
    no_evidence: int = 0
    status_only: int = 0
    session_only: int = 0
    both: int = 0
    #: Of the runs holding both, the days that match.
    both_agree: int = 0
    from_status: int = 0
    from_session: int = 0
    events_appended: int = 0

    def __add__(self, other: StartRepairCounts) -> StartRepairCounts:
        return StartRepairCounts(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: The value an accumulation starts from.
NO_START_COUNTS = StartRepairCounts()


@dataclass(frozen=True, slots=True)
class RepairResult:
    """What the pass stated, for the gate to read."""

    counts: StartRepairCounts
    #: The day and source each repaired run took.
    stated: Mapping[uuid.UUID, Evidence]
    #: Runs in scope this pass left stating no act.
    left_alone: tuple[uuid.UUID, ...]


def repair_library(library: UserLibrary) -> RepairResult:
    """State a start for every empty default holding evidence.

    recorded_at is now. Nothing recorded this before, and a past
    instant would say something did. #684 could use a row's
    created_at because the row was the record; here the record
    is being made now.
    """
    actor = library.user
    recorded_at = timezone.now()
    status = status_days(library)
    session = session_days(library)
    counts = StartRepairCounts(libraries=1)
    stated: dict[uuid.UUID, Evidence] = {}
    left_alone: list[uuid.UUID] = []

    for run in runs_in_scope(library):
        counts = counts + StartRepairCounts(runs_in_scope=1)
        evidence = evidence_for(run, status=status, session=session)
        counts = counts + _witness_counts(run, evidence, status=status, session=session)
        if evidence is None:
            left_alone.append(run.run_id)
            continue
        stated[run.run_id] = evidence
        #: Its own block, as convert_row's is: lock_stream
        #: refuses the head lock outside a transaction, and
        #: inside a caller's it is only a savepoint.
        with transaction.atomic():
            appended = append_one(
                library,
                playthrough_started(
                    run.run_id,
                    when=TemporalValue.from_day(evidence.day),
                    note="",
                ),
                actor=actor,
                idempotency_key=f"{KEY_PREFIX}:{run.run_id}",
                command_input={
                    "fact": "started",
                    #: Stable, and not minted by this pass.
                    "playthrough_id": str(run.run_id),
                    #: Named, so a changed day is loud.
                    "day": evidence.day,
                },
                recorded_at=recorded_at,
                correlation_id=uuid.uuid7(),
                source_metadata={
                    "origin": "backfill",
                    "issue": START_ISSUE,
                    #: The third key tells an inferred day from
                    #: a recorded one, and reconcile() reads it.
                    "source": evidence.source.value,
                },
            )
        if appended:
            counts = counts + StartRepairCounts(events_appended=1)

    return RepairResult(counts=counts, stated=stated, left_alone=tuple(left_alone))


def _witness_counts(
    run: RunInScope,
    evidence: Evidence | None,
    *,
    status: Mapping[uuid.UUID, date],
    session: Mapping[uuid.UUID, date],
) -> StartRepairCounts:
    """Which records this run held, counted."""
    status_day = status.get(run.player_game_id)
    session_day = session.get(run.game_id)
    if status_day is not None and session_day is not None:
        held = StartRepairCounts(both=1, both_agree=int(status_day == session_day))
    elif status_day is not None:
        held = StartRepairCounts(status_only=1)
    elif session_day is not None:
        held = StartRepairCounts(session_only=1)
    else:
        return StartRepairCounts(no_evidence=1)
    won = (
        StartRepairCounts(from_session=1)
        if evidence is not None and evidence.source is StartSource.SESSION
        else StartRepairCounts(from_status=1)
    )
    return held + won
```

and these imports to the module head:

```python
from dataclasses import dataclass, fields

from django.db import transaction
from django.utils import timezone

from games.backfill.appending import append_one
from games.events.playthrough import playthrough_started
from timetracker.temporal import TemporalValue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: PASS, eighteen tests.

- [ ] **Step 5: Commit**

```bash
git add games/backfill/playthrough_start.py tests/test_playthrough_start_repair.py
git commit -m "State a start for every empty run holding evidence"
```

---

### Task 5: Teach #684's reconcile about a repaired run

Without this, `reconcile()` reports three mismatches for every repaired game
and `make check` goes red. `_rows_for_games` seeds an empty row list for each
live tracked game, so the `rows is None` skip never fires for a game holding no
`PlayEvent`, and `_reconcile_game` compares a repaired run against nothing.

**Files:**

- Modify: `games/backfill/playthrough_start.py` (add `repaired_run_ids`)
- Modify: `games/backfill/playthrough.py:572-670` (`_reconcile_game`) and
  `:673-707` (`reconcile`)
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `START_ISSUE` from Task 2.
- Produces: `repaired_run_ids(library) -> set[uuid.UUID]` in
  `playthrough_start`; `reconcile(library)` in `playthrough` keeps its
  signature and its return type.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_reconcile_is_clean_after_a_repair(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_library(owned_library)

    assert reconcile(owned_library) == []


def test_reconcile_still_reads_a_converted_row_beside_a_repaired_run(owned_library):
    played = _game(owned_library, name="Chrono Trigger")
    recorded = _game(owned_library, name="Terranigma")
    PlayEvent.objects.create(
        game=recorded, started=date(2014, 6, 7), ended=date(2014, 6, 17)
    )
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_library(owned_library)

    assert reconcile(owned_library) == []


def test_reconcile_still_reports_a_second_empty_run(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)
    #: One blank beside the repaired run is one too many:
    #: a repaired run still counts as stating no act.
    record_run(
        owned_library.user,
        game,
        RunDraft(started=None, completed=None, note=""),
        correlation_id=uuid.uuid7(),
    )

    codes = [mismatch.code for mismatch in reconcile(owned_library)]

    assert MismatchCode.SURPLUS_ACTLESS_RUN in codes
```

Add to the test module's imports:

```python
from games.backfill.playthrough import MismatchCode, reconcile
from games.models import PlayEvent
```

The third test is the one that proves the amendment took no teeth out, and it
takes one `record_run` rather than two: `run_to_adopt` hands a blank draft the
blank run a game already holds, so a second call would fill that one in rather
than make a third. The repaired run states an act as far as `run_to_adopt` is
concerned, so this call creates the blank; as far as check 7 is concerned it
states none, so two actless runs stand and "one is allowed" refuses the pair.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k reconcile -x"`

Expected: FAIL on the first two with
`run_disagreement`, `missing_marker` and `display_order_disagreement` in the
returned list.

- [ ] **Step 3: Add the reader**

Append to `games/backfill/playthrough_start.py`:

```python
def repaired_run_ids(library: UserLibrary) -> set[uuid.UUID]:
    """Every run whose only act this pass stated.

    #684's reconcile() compares a run stating an act with the
    legacy row it came from. A run repaired here came from no
    row, so it is read as stating none.
    """
    return set(
        LibraryEvent.objects.filter(
            library=library,
            event_type=PLAYTHROUGH_STARTED.event_type,
            source_metadata__origin="backfill",
            source_metadata__issue=START_ISSUE,
        ).values_list("aggregate_id", flat=True)
    )
```

with `PLAYTHROUGH_STARTED` added to the `games.events.playthrough` import.

- [ ] **Step 4: Amend `_reconcile_game`**

In `games/backfill/playthrough.py`, add the parameter and the local reading:

```text
def _reconcile_game(
    game_id: str,
    rows: Sequence[PlayEvent],
    tracked_id: uuid.UUID,
    repaired: AbstractSet[uuid.UUID],
) -> list[Mismatch]:
    """The row-to-row checks, one game."""

    def states_an_act(run: Playthrough) -> bool:
        #: #1038 stated it, so no legacy row owes it.
        return run.pk not in repaired and _states_an_act(run)
```

Then replace all three uses of `_states_an_act(run)` inside that function with
`states_an_act(run)`: in check 1's `converted` counter, in check 7's `actless`
list, and in check 4's `by_display` list. Give the `MISSING_MARKER` loop the
same exemption:

```text
    for run in live_runs:
        if run.pk in repaired:
            #: One act is all #1038 states, on purpose.
            continue
        markers = (run.start_recorded_at, run.completion_recorded_at)
```

Add `from collections.abc import AbstractSet` to that module's imports, beside
`Mapping` and `Sequence`.

- [ ] **Step 5: Amend `reconcile`**

Read the set once per library and pass it down:

```text
def reconcile(library: UserLibrary) -> list[Mismatch]:
    ...
    mismatches: list[Mismatch] = []
    #: One query, because #1038 states a start no row owes.
    repaired = repaired_run_ids(library)
    tracked = PlayerGame.objects.filter(...)
    ...
            mismatches.extend(
                _reconcile_game(
                    str(tracked_row.game_id), rows, tracked_row.pk, repaired
                )
            )
```

with `from games.backfill.playthrough_start import repaired_run_ids` at the
module head. This import is one-way: `playthrough_start` imports `append_one`
from `games.backfill.appending`, never from `playthrough`, which is why Task 1
moved it.

- [ ] **Step 6: Run both suites**

Run: `make test ARGS="tests/test_playthrough_start_repair.py tests/test_playthrough_conversion.py -x"`

Expected: PASS, every test in both.

- [ ] **Step 7: Commit**

```bash
git add games/backfill/playthrough.py games/backfill/playthrough_start.py \
  tests/test_playthrough_start_repair.py
git commit -m "Read a repaired run as owing no legacy row"
```

---

### Task 6: Gate the pass

**Files:**

- Modify: `games/backfill/playthrough_start.py`
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `RepairResult` from Task 4, `Mismatch` from Task 1.
- Produces: `StartMismatchCode` (`StrEnum`), `StartSnapshot(started,
  completions, actless)`, `snapshot(library) -> StartSnapshot`,
  `gate(library, before, result) -> list[Mismatch]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_the_gate_is_clean_on_a_good_pass(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)

    result = repair_library(owned_library)

    assert gate(owned_library, before, result) == []


def test_the_gate_reads_a_day_that_moved(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    #: The projection now says a day the pass never stated.
    Playthrough.objects.filter(library=owned_library).update(
        started=TemporalValue.from_day(date(1999, 1, 1))
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.START_DAY_DISAGREEMENT in codes


def test_the_gate_reads_a_completion_this_pass_must_not_have_stated(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        completion_recorded_at=datetime(2026, 2, 1, tzinfo=UTC)
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.COMPLETION_DRIFT in codes


def test_the_gate_reads_a_start_that_appeared_outside_the_scope(owned_library):
    played = _game(owned_library, name="Chrono Trigger")
    other = _game(owned_library, name="Terranigma")
    PlayEvent.objects.create(game=other, started=date(2014, 6, 7))
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    #: A converted run's day moves, which the pass never touches.
    Playthrough.objects.filter(library=owned_library, player_game__game=other).update(
        started=TemporalValue.from_day(date(1999, 1, 1))
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.START_MOVED in codes


def test_the_gate_reads_a_run_left_alone_that_gained_an_act(owned_library):
    _game(owned_library)
    _converted(owned_library)
    before = snapshot(owned_library)
    result = repair_library(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        start_recorded_at=datetime(2026, 2, 1, tzinfo=UTC)
    )

    codes = [mismatch.code for mismatch in gate(owned_library, before, result)]

    assert StartMismatchCode.UNEXPECTED_ACT in codes
```

Add to the test module's imports:

```python
from games.backfill.playthrough_start import (
    StartMismatchCode,
    gate,
    snapshot,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k gate -x"`

Expected: FAIL with `ImportError: cannot import name 'StartMismatchCode'`

- [ ] **Step 3: Write the gate**

Append to `games/backfill/playthrough_start.py`:

```python
class StartMismatchCode(StrEnum):
    """Every reason this run refuses to commit."""

    START_DAY_DISAGREEMENT = "start_day_disagreement"
    UNEXPECTED_ACT = "unexpected_act"
    START_MOVED = "start_moved"
    COMPLETION_DRIFT = "completion_drift"
    ACTLESS_DRIFT = "actless_drift"
    COUNT_DRIFT = "count_drift"


class StartSnapshot(NamedTuple):
    """What the library stated before the pass."""

    #: Run id to the day its start states, or None.
    started: Mapping[uuid.UUID, date | None]
    completions: int
    actless: int


def snapshot(library: UserLibrary) -> StartSnapshot:
    """Read the three numbers the gate compares."""
    live = Playthrough.objects.filter(
        library=library,
        kind=PlaythroughKind.ORDINARY,
        removed_at__isnull=True,
    )
    return StartSnapshot(
        started=dict(
            live.filter(start_recorded_at__isnull=False).values_list(
                "pk", "started_lower"
            )
        ),
        completions=live.filter(completion_recorded_at__isnull=False).count(),
        actless=live.filter(
            start_recorded_at__isnull=True,
            completion_recorded_at__isnull=True,
        ).count(),
    )


def gate(
    library: UserLibrary, before: StartSnapshot, result: RepairResult
) -> list[Mismatch]:
    """Every reason this pass must roll back.

    Checks 1, 2, 3, 4 and 6 of the specification. Check 5 is
    the second pass, and check 7 is #684's reconcile and its
    ordering audit; the migration runs all three.
    """
    mismatches: list[Mismatch] = []
    after = snapshot(library)
    days = dict(
        Playthrough.objects.filter(pk__in=result.stated).values_list(
            "pk", "started_lower"
        )
    )
    #: Check 1.
    for run_id, evidence in sorted(
        result.stated.items(), key=lambda pair: str(pair[0])
    ):
        if days.get(run_id) != evidence.day:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.START_DAY_DISAGREEMENT,
                    subject=str(run_id),
                    detail=f"the pass states {evidence.day}, "
                    f"the row says {days.get(run_id)}",
                )
            )
    #: Check 2.
    still_empty = set(
        Playthrough.objects.filter(
            pk__in=result.left_alone,
            start_recorded_at__isnull=True,
            completion_recorded_at__isnull=True,
        ).values_list("pk", flat=True)
    )
    for run_id in sorted(result.left_alone, key=str):
        if run_id not in still_empty:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.UNEXPECTED_ACT,
                    subject=str(run_id),
                    detail="a run holding no evidence states an act",
                )
            )
    #: Check 3.
    expected = set(before.started) | set(result.stated)
    for run_id in sorted(set(after.started) - expected, key=str):
        mismatches.append(
            Mismatch(
                code=StartMismatchCode.START_MOVED,
                subject=str(run_id),
                detail="a run outside the scope states a start",
            )
        )
    for run_id, day in sorted(before.started.items(), key=lambda pair: str(pair[0])):
        #: Membership, not .get(): a run whose start is gone
        #: and a run whose start states no day both answer
        #: None, and only the first is this code's subject.
        if run_id not in after.started:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.START_MOVED,
                    subject=str(run_id),
                    detail=f"a start stated before the pass said {day} "
                    "and now states no act",
                )
            )
        elif after.started[run_id] != day:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.START_MOVED,
                    subject=str(run_id),
                    detail=f"a start stated before the pass said {day} "
                    f"and now says {after.started[run_id]}",
                )
            )
    #: Check 4.
    if after.completions != before.completions:
        mismatches.append(
            Mismatch(
                code=StartMismatchCode.COMPLETION_DRIFT,
                subject=str(library.pk),
                detail=f"completions went from {before.completions} "
                f"to {after.completions}",
            )
        )
    #: Check 6.
    if after.actless != before.actless - len(result.stated):
        mismatches.append(
            Mismatch(
                code=StartMismatchCode.ACTLESS_DRIFT,
                subject=str(library.pk),
                detail=f"{before.actless} runs stated no act, {len(result.stated)} "
                f"were repaired, and {after.actless} state none now",
            )
        )
    return mismatches
```

and `Mismatch`, `PlaythroughKind` and `Playthrough` added to the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: PASS, twenty-six tests.

- [ ] **Step 5: Commit**

```bash
git add games/backfill/playthrough_start.py tests/test_playthrough_start_repair.py
git commit -m "Gate the start repair on six readings"
```

---

### Task 7: The migration

**Files:**

- Create: `games/migrations/0048_playthrough_start_repair.py`
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `repair_library`, `snapshot`, `gate`, `NO_START_COUNTS` from Tasks
  4 and 6; `reconcile` and `ordering_violations` from #684.
- Produces: `MACHINE_PREFIX`, `HUMAN_PREFIX`, `repair_playthrough_starts(apps,
  schema_editor)`.

- [ ] **Step 1: Confirm the number is still free**

Run: `ls games/migrations/`

Expected: the highest number is `0047_playthrough_preset_completed.py`. If #770
or #771 landed first, use the next free number and depend on the highest, not
on `0047`.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_the_migration_states_the_starts_and_reports(owned_library, capsys):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    repair_playthrough_starts(None, None)

    run = Playthrough.objects.get(library=owned_library)
    assert run.started_lower == date(2026, 1, 4)
    machine = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith(MACHINE_PREFIX)
    ]
    payload = json.loads(machine[0][len(MACHINE_PREFIX) :])
    assert payload["summary"]["events_appended"] == 1
    assert payload["summary"]["mismatches"] == 0


def test_the_migration_refuses_a_second_pass_that_appends(owned_library, monkeypatch):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    passes = []

    def drifting(library):
        result = repair_library(library)
        passes.append(1)
        if len(passes) % 2 == 0:
            return RepairResult(
                counts=result.counts + StartRepairCounts(events_appended=1),
                stated=result.stated,
                left_alone=result.left_alone,
            )
        return result

    monkeypatch.setattr("games.backfill.playthrough_start.repair_library", drifting)
    with pytest.raises(RuntimeError, match="count_drift"):
        repair_playthrough_starts(None, None)


def test_the_migration_refuses_a_mismatched_day(owned_library, monkeypatch):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    def lying(library):
        result = repair_library(library)
        return RepairResult(
            counts=result.counts,
            stated={
                run_id: Evidence(date(1999, 1, 1), evidence.source)
                for run_id, evidence in result.stated.items()
            },
            left_alone=result.left_alone,
        )

    monkeypatch.setattr("games.backfill.playthrough_start.repair_library", lying)
    with pytest.raises(RuntimeError, match="start_day_disagreement"):
        repair_playthrough_starts(None, None)
```

Add to the test module's imports:

```python
import importlib
import json

from games.backfill.playthrough_start import RepairResult, StartRepairCounts

_migration = importlib.import_module("games.migrations.0048_playthrough_start_repair")
MACHINE_PREFIX = _migration.MACHINE_PREFIX
repair_playthrough_starts = _migration.repair_playthrough_starts
```

The two `monkeypatch` tests patch the name inside the backfill module, not
inside the migration, so the migration's own function-level import picks the
patched one up. That is the shape `tests/test_playthrough_conversion.py`
already uses; copy how it patches `convert_library` if the call does not take.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k migration -x"`

Expected: FAIL with
`ModuleNotFoundError: No module named 'games.migrations.0048_playthrough_start_repair'`

- [ ] **Step 4: Write the migration**

Create `games/migrations/0048_playthrough_start_repair.py`:

```python
import json
import sys

from django.db import migrations

MACHINE_PREFIX = "PLAYTHROUGH_START_REPAIR_JSON="
HUMAN_PREFIX = "Playthrough start repair:"
SUMMARY_KEYS = (
    "libraries",
    "runs_in_scope",
    "no_evidence",
    "status_only",
    "session_only",
    "both",
    "both_agree",
    "from_status",
    "from_session",
    "events_appended",
    "mismatches",
)

#: Named in the exception, so a lost stdout still says what broke.
NAMED_IN_FAILURE = 3


def _emit(summary, mismatches):
    entries = sorted(
        (mismatch.as_dict() for mismatch in mismatches),
        key=lambda entry: (entry["code"], entry["subject"], entry["detail"]),
    )
    payload = {
        "schema_version": 1,
        "summary": summary,
        "mismatches": entries,
    }
    #: stderr, so the machine line travels with the traceback
    #: rather than on a stream a quiet migrate may discard.
    print(
        MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )
    print(
        HUMAN_PREFIX
        + " "
        + " ".join(f"{key}={summary.get(key, 0)}" for key in SUMMARY_KEYS)
    )
    for entry in entries:
        print(f"  {entry['code']} subject={entry['subject']} {entry['detail']}")
    return entries


def _fail_if_mismatched(mismatches, entries):
    if not mismatches:
        return
    #: The count alone would say nothing on the one occasion
    #: this message is read, and stdout may not have survived.
    named = "; ".join(
        f"{entry['code']} {entry['subject']}: {entry['detail']}"
        for entry in entries[:NAMED_IN_FAILURE]
    )
    remainder = len(entries) - NAMED_IN_FAILURE
    if remainder > 0:
        named += f"; and {remainder} more"
    raise RuntimeError(
        f"Playthrough start repair failed with {len(mismatches)} mismatch(es): {named}"
    )


def repair_playthrough_starts(apps, schema_editor):
    """State a start for the runs #684 left empty.

    The live models and machinery, for the reason 0033 records:
    historical models cannot run a projector or validate a
    payload, so writing events and rows by hand is a second event
    writer. This migration is therefore pinned to the application
    as it stands, and the gate keeps that loud.
    """
    del apps, schema_editor
    from games.backfill import playthrough as conversion
    from games.backfill import playthrough_start as repair
    from games.models import UserLibrary

    counts = repair.NO_START_COUNTS
    mismatches = []
    try:
        for library in UserLibrary.objects.order_by("pk"):
            before = repair.snapshot(library)
            result = repair.repair_library(library)
            counts = counts + result.counts
            mismatches.extend(repair.gate(library, before, result))
            #: Check 5: a second pass appends nothing.
            again = repair.repair_library(library)
            if again.counts.events_appended:
                mismatches.append(
                    repair.Mismatch(
                        code=repair.StartMismatchCode.COUNT_DRIFT,
                        subject=str(library.pk),
                        detail=f"a second pass appended "
                        f"{again.counts.events_appended} event(s)",
                    )
                )
            #: Check 7: #684's own gate still answers clean.
            mismatches.extend(conversion.reconcile(library))
        mismatches.extend(conversion.ordering_violations())
    except Exception:
        #: The rollback takes every event. What is counted so far
        #: says how far the run got, which a traceback does not.
        _emit(
            counts.as_dict() | {"mismatches": len(mismatches), "aborted": 1},
            mismatches,
        )
        raise

    summary = counts.as_dict() | {"mismatches": len(mismatches)}
    entries = _emit(summary, mismatches)
    _fail_if_mismatched(mismatches, entries)


class Migration(migrations.Migration):
    dependencies = [("games", "0047_playthrough_preset_completed")]

    operations = [
        migrations.RunPython(
            repair_playthrough_starts,
            #: Append-only: a rollback cannot take an event back.
            migrations.RunPython.noop,
            elidable=True,
        )
    ]
```

`repair.Mismatch` reads through the backfill module, so add
`from games.backfill.mismatch import Mismatch` to `playthrough_start.py` if
Task 6 did not already, and keep the name bound at that module's top level.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: PASS, twenty-nine tests.

- [ ] **Step 6: Check the migration graph**

Run: `make makemigrations ARGS="--check --dry-run"`

Expected: no model change is pending. This migration adds no schema.

- [ ] **Step 7: Commit**

```bash
git add games/migrations/0048_playthrough_start_repair.py \
  games/backfill/playthrough_start.py tests/test_playthrough_start_repair.py
git commit -m "Gate the start repair behind a migration"
```

---

### Task 8: Run the pass when the sample loads

**Files:**

- Modify: `games/management/commands/load_sample_data.py:158-172`
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `repair_library`, `snapshot`, `gate`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_the_sample_fixture_states_a_start_where_it_holds_one(owned_user):
    call_command("load_sample_data", "--user", owned_user.username, verbosity=0)
    library = UserLibrary.objects.get(user=owned_user)
    live = Playthrough.objects.filter(library=library, removed_at__isnull=True)

    assert live.filter(start_recorded_at__isnull=False).exists()
    assert reconcile(library) == []
    assert runs_in_scope(library) == [] or all(
        evidence_for(
            run,
            status=status_days(library),
            session=session_days(library),
        )
        is None
        for run in runs_in_scope(library)
    )
```

Add to the test module's imports:

```python
from django.core.management import call_command

from games.models import UserLibrary
```

The second assertion is the point: after the load, every run still in scope is
one holding no evidence. A run left in scope that holds evidence would mean the
load ran the pass and the pass skipped it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k sample_fixture -x"`

Expected: FAIL on the first assertion, because nothing states a start yet.

- [ ] **Step 3: Wire the command**

In `games/management/commands/load_sample_data.py`, after the existing
`convert_library` and `reconcile` block, add:

```text
            #: And the days the library's own records prove:
            #: #1038 dates the empty defaults #684 minted.
            #: Gated here as 0048 gates it, so a fixture never
            #: lands holding runs the migration would refuse.
            before = start_snapshot(user.library)
            repaired = repair_library(user.library)
            refusals = start_gate(user.library, before, repaired)
            if refusals:
                raise CommandError(
                    "Sample playthrough starts could not be stated: "
                    + "; ".join(
                        f"{refusal.code} {refusal.subject}: {refusal.detail}"
                        for refusal in refusals[:3]
                    )
                )
```

with the imports at the module head:

```python
from games.backfill.playthrough_start import (
    gate as start_gate,
    repair_library,
    snapshot as start_snapshot,
)
```

The two aliases are there because `gate` and `snapshot` are general words in a
command module that already reads a `reconcile`; the aliased names say which
pass they belong to.

- [ ] **Step 4: Run the test to verify it passes**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k sample_fixture -x"`

Expected: PASS.

- [ ] **Step 5: Run the conversion suite, which loads the same fixture**

Run: `make test ARGS="tests/test_playthrough_conversion.py -x"`

Expected: PASS, including
`test_the_sample_fixture_leaves_every_tracked_game_holding_a_run`, whose
`reconcile(library) == []` now runs against a library holding repaired runs.

- [ ] **Step 6: Commit**

```bash
git add games/management/commands/load_sample_data.py \
  tests/test_playthrough_start_repair.py
git commit -m "State the sample library's starts as the migration does"
```

---

### Task 9: The report

**Files:**

- Create: `games/management/commands/report_playthrough_starts.py`
- Modify: `games/backfill/playthrough_start.py` (add `report_library`)
- Modify: `Makefile` (after the `preflight-playthroughs` target, line 337)
- Modify: `CLAUDE.md` (the commands table)
- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: `runs_in_scope`, `status_days`, `session_days`, `evidence_for`.
- Produces: `DEFAULT_SAMPLE_SIZE`, `StartReportCounts`, `StartSample`,
  `LibraryStartReport(library_id, username, zone, counts, gaps, samples)` with
  `as_dict()`, `report_library(library, *, sample_size) -> LibraryStartReport`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_the_report_states_what_the_pass_would_do(owned_library):
    played = _game(owned_library, name="Chrono Trigger")
    _game(owned_library, name="Terranigma")
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    report = report_library(owned_library, sample_size=20)

    assert report.counts.runs_in_scope == 2
    assert report.counts.session_only == 1
    assert report.counts.no_evidence == 1
    assert report.counts.from_session == 1
    assert len(report.samples) == 1
    assert report.samples[0].game_name == "Chrono Trigger"
    assert report.samples[0].day == date(2026, 1, 4)
    assert report.samples[0].source == "session"


def test_the_report_states_nothing(owned_library):
    played = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=played,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )

    report_library(owned_library, sample_size=20)

    assert Playthrough.objects.get(library=owned_library).start_recorded_at is None


def test_the_report_prints_the_same_bytes_twice(owned_library):
    for name in ("Chrono Trigger", "Terranigma", "Illusion of Gaia"):
        game = _game(owned_library, name=name)
        Session.objects.create(
            game=game,
            timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
            timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
        )
    _converted(owned_library)

    first = _report_output(owned_library.user.username)
    second = _report_output(owned_library.user.username)

    assert first == second


def test_the_report_refuses_a_scope_it_cannot_resolve():
    with pytest.raises(CommandError, match="No user is named"):
        call_command("report_playthrough_starts", "--user", "nobody", verbosity=0)
```

with this helper in the test module, which strips the one line that changes
between two runs:

```python
def _report_output(username):
    """The report's bytes, less the timestamp."""
    buffer = io.StringIO()
    call_command(
        "report_playthrough_starts", "--user", username, stdout=buffer, verbosity=0
    )
    return [
        line
        for line in buffer.getvalue().splitlines()
        if not line.startswith("Generated at ") and '"generated_at"' not in line
    ]
```

The machine line holds `generated_at` inside its JSON, so the filter drops that
whole line too. Read `preflight_playthroughs`'s own test, if it has one, and
reuse its comparison rather than this one.

Add to the test module's imports:

```python
import io

from django.core.management.base import CommandError

from games.backfill.playthrough_start import report_library
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k report -x"`

Expected: FAIL with `ImportError: cannot import name 'report_library'`

- [ ] **Step 3: Write the reader**

Append to `games/backfill/playthrough_start.py`:

```python
#: Runs printed beside each count.
DEFAULT_SAMPLE_SIZE = 20


class StartSample(NamedTuple):
    """One run the report names."""

    run_id: uuid.UUID
    game_name: str
    day: date
    source: str


@dataclass(frozen=True, slots=True)
class LibraryStartReport:
    """One library's whole report."""

    library_id: uuid.UUID
    username: str
    #: The zone the session days were read in.
    zone: str
    counts: StartRepairCounts
    #: The gap in days, counted, for the runs holding both.
    gaps: Mapping[int, int]
    samples: tuple[StartSample, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "library_id": str(self.library_id),
            "username": self.username,
            "zone": self.zone,
            "counts": self.counts.as_dict(),
            "gaps": {str(gap): times for gap, times in sorted(self.gaps.items())},
            "samples": [
                {
                    "run_id": str(sample.run_id),
                    "game_name": sample.game_name,
                    "day": sample.day.isoformat(),
                    "source": sample.source,
                }
                for sample in self.samples
            ],
        }


def report_library(
    library: UserLibrary, *, sample_size: int = DEFAULT_SAMPLE_SIZE
) -> LibraryStartReport:
    """What the pass would state, stating nothing.

    Sorted by identity and never sampled at random, so two
    runs over unchanged data print the same bytes.
    """
    zone = str(activity_clock(library).zone)
    status = status_days(library)
    session = session_days(library)
    runs = runs_in_scope(library)
    names = dict(
        Game.objects.filter(pk__in=[run.game_id for run in runs]).values_list(
            "pk", "name"
        )
    )
    counts = StartRepairCounts(libraries=1)
    gaps: Counter[int] = Counter()
    samples: list[StartSample] = []
    for run in runs:
        counts = counts + StartRepairCounts(runs_in_scope=1)
        evidence = evidence_for(run, status=status, session=session)
        counts = counts + _witness_counts(run, evidence, status=status, session=session)
        status_day = status.get(run.player_game_id)
        session_day = session.get(run.game_id)
        if status_day is not None and session_day is not None:
            gaps[abs((session_day - status_day).days)] += 1
        if evidence is not None and len(samples) < sample_size:
            samples.append(
                StartSample(
                    run_id=run.run_id,
                    game_name=names.get(run.game_id, ""),
                    day=evidence.day,
                    source=evidence.source.value,
                )
            )
    return LibraryStartReport(
        library_id=library.pk,
        username=library.user.username,
        zone=zone,
        counts=counts,
        gaps=dict(gaps),
        samples=tuple(samples),
    )
```

with `from collections import Counter` and `Game` added to the imports.
`runs_in_scope` already orders by identity, so the sample is the first few by
that order and never a random draw.

- [ ] **Step 4: Write the command**

Create `games/management/commands/report_playthrough_starts.py`, in the shape
of `preflight_playthroughs.py`. Copy `_resolve_libraries`, `_library_of_user`
and `_library_by_id` from it verbatim — the three-way group and its two error
sentences are the contract, not an implementation choice:

```python
"""Print what #1038 would state, for a log and a person.

A report states nothing and gates nothing, so what it finds never
fails the run. Only a scope this command cannot resolve is an error.
"""

import json
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from games.backfill.playthrough_start import (
    DEFAULT_SAMPLE_SIZE,
    NO_START_COUNTS,
    LibraryStartReport,
    report_library,
)
from games.models import UserLibrary

MACHINE_PREFIX = "PLAYTHROUGH_START_REPORT_JSON="
GENERATED_PREFIX = "Generated at "


class Command(BaseCommand):
    help = "Report what #1038 would state for the runs #684 left empty."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--user", help="Report the library owned by USERNAME.")
        scope.add_argument(
            "--library", dest="library_id", help="Report one library UUID."
        )
        scope.add_argument(
            "--all-libraries",
            action="store_true",
            help="Explicitly report every library.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=DEFAULT_SAMPLE_SIZE,
            help="Runs printed beside each count. 0 keeps the counts only.",
        )

    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        sample_size = options["sample_size"]
        if sample_size < 0:
            raise CommandError("A sample size counts runs, so it is not negative.")

        reports = [
            report_library(library, sample_size=sample_size) for library in libraries
        ]
        summary = sum((report.counts for report in reports), NO_START_COUNTS)
        generated_at = timezone.now().isoformat()
        payload = {
            "schema_version": 1,
            "generated_at": generated_at,
            "summary": summary.as_dict(),
            "libraries": [report.as_dict() for report in reports],
        }
        self.stdout.write(
            MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
        self.stdout.write(f"{GENERATED_PREFIX}{generated_at}")
        if not reports:
            #: An empty scope reads as an all-zero report.
            self.stdout.write(
                "No library was read, so every count below counts nothing."
            )
        for report in reports:
            self._write_report(report)

    def _write_report(self, report: LibraryStartReport) -> None:
        counts = report.counts
        write = self.stdout.write
        write(
            f"Playthrough start repair - library {report.library_id} "
            f"({report.username})"
        )
        write(f"  runs the pass may date: {counts.runs_in_scope}")
        write(f"    holding a status day only: {counts.status_only}")
        write(f"    holding a session day only: {counts.session_only}")
        write(f"    holding both: {counts.both}")
        write(f"      whose two days agree: {counts.both_agree}")
        write(f"    holding neither, left stating no act: {counts.no_evidence}")
        write(f"  dated by the status: {counts.from_status}")
        write(f"  dated by a session: {counts.from_session}")
        write(f"  session days read in {report.zone}; status days in the")
        write("    server zone #676 froze them in")
        for gap, times in sorted(report.gaps.items()):
            if gap:
                write(f"    days apart {gap}: {times}")
        for sample in report.samples:
            write(
                f"      {sample.run_id} {sample.game_name} "
                f"{sample.day.isoformat()} {sample.source}"
            )
```

Copy the three `_resolve_libraries` helpers in from
`games/management/commands/preflight_playthroughs.py:137-166` unchanged.

- [ ] **Step 5: Add the Makefile target**

After the `preflight-playthroughs` target:

```make
# Read-only: prints what #1038 would state, states nothing.
# Usage: make report-playthrough-starts ARGS="--all-libraries"
report-playthrough-starts: ensure-postgres
	uv run --frozen python manage.py report_playthrough_starts $(ARGS)
```

Add it to `.PHONY` if that Makefile lists targets there — grep `.PHONY` and
follow what the file does.

- [ ] **Step 6: Add the row to the commands table in `CLAUDE.md`**

Under the `preflight-playthroughs` row:

```text
| Report the starts #1038 would state before stating them | `make report-playthrough-starts ARGS="--all-libraries"` (read-only; reports, never gates) |
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -x"`

Expected: PASS, thirty-four tests.

- [ ] **Step 8: Run the report against the sample library by hand**

```bash
make loadsample
make report-playthrough-starts ARGS="--all-libraries"
```

Expected: a machine line, then a per-library block whose counts are not all
zero. Read it: the sentences must say what a person would want to know before
running a migration against their own data.

- [ ] **Step 9: Commit**

```bash
git add games/management/commands/report_playthrough_starts.py \
  games/backfill/playthrough_start.py Makefile CLAUDE.md \
  tests/test_playthrough_start_repair.py
git commit -m "Report the starts before stating them"
```

---

### Task 10: Pin what moves on the screens

The specification names five consequences of stating a start. Three change what
a person sees or presses, and none has a test today.

**Files:**

- Test: `tests/test_playthrough_start_repair.py`

**Interfaces:**

- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Append to `tests/test_playthrough_start_repair.py`:

```python
def test_a_repaired_run_is_no_longer_adopted(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)
    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    #: The blank run is filled in, so a statement makes a second.
    assert run_to_adopt(owned_library, tracked) is None


def test_a_repaired_run_offers_the_completion_press(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    repair_library(owned_library)
    run = Playthrough.objects.get(library=owned_library)

    members = _act_members(run, None, "token")

    assert len(members) == 1
    assert members[0]["title"].startswith("Completed today")


def test_a_repaired_run_dated_long_ago_reads_dormant(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2023, 5, 1, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)

    repair_library(owned_library)
    run = runs_with_condition(owned_library).get()

    assert run.activity == RunActivity.DORMANT
```

Add the imports the three need:

```python
from games.reads.playthrough_activity import RunActivity
from games.reads.playthrough_runs import run_to_adopt, runs_with_condition
from games.views.playthrough_rows import _act_members
```

`_act_members` at `games/views/playthrough_rows.py:185` is the chooser, and it
answers zero or one `ButtonGroupMember`. `runs_with_condition` at
`games/reads/playthrough_runs.py:40` is the clock-bearing read and scopes the
library itself, so no `for_library` sits beside it — `PlaythroughQuerySet`
states none.

- [ ] **Step 2: Run the tests**

Run: `make test ARGS="tests/test_playthrough_start_repair.py -k repaired -x"`

Expected: PASS. These pin behaviour that already follows from the event; a
failure means one of the three consequences is not what the specification says
it is, and that is a finding to report rather than a test to bend.

- [ ] **Step 3: Commit**

```bash
git add tests/test_playthrough_start_repair.py
git commit -m "Pin the three screens a stated start moves"
```

---

### Task 11: The gate, and the documents

**Files:**

- Modify: `CLAUDE.md` (the Playthrough paragraph in Models)
- Modify: `docs/superpowers/plans/2026-09-10-issue-1038-playthrough-start-repair.md`
  (check every box)

- [ ] **Step 1: Run the whole suite**

Run: `make check`

Expected: green. This is the gate: lint, format check, mypy, vale, ts-check,
vitest and the entire pytest suite including `e2e/`. A hand-picked subset is
not the gate.

- [ ] **Step 2: Rehearse the migration against a restored copy**

```bash
make fetch-dump
make report-playthrough-starts ARGS="--all-libraries"
make verify-dump
```

The report comes first and reads the copy before the migration touches it, so
the numbers it prints are the ones to compare the migration's own summary
against. `make verify-dump` restores, migrates and drops the copy; `KEEP=1`
keeps it. If `PROD_SSH_HOST` is not configured in this environment, say so and
run the remaining two against the newest dump already in `.dumps/`.

Expected: the migration's machine line reports `mismatches=0`, and
`events_appended` matches the report's `from_status` plus `from_session`.

- [ ] **Step 3: Update the Playthrough paragraph in `CLAUDE.md`**

The Models section describes what writes a `Playthrough`. Add one sentence
naming #1038 beside the #684 sentence, in the register the rest of that
paragraph uses: a run #684 minted with no acts takes a `started` from the
earlier of the library's own two records, and #684's `reconcile()` reads such a
run as owing no legacy row.

- [ ] **Step 4: Run vale over the changed documents**

Run: `make vale`

Expected: no findings.

- [ ] **Step 5: Commit and push**

```bash
git add CLAUDE.md docs/superpowers/plans/
git commit -m "Record the start repair beside the conversion"
git push -u origin issue-1038-playthrough-start-repair
```

- [ ] **Step 6: Open the pull request**

```bash
gh pr create --title "State a start for the runs the conversion left empty" \
  --body "$(cat <<'BODY'
Closes #1038.

#684 minted one empty default run per tracked game holding no legacy
`PlayEvent` row, and most tracked games hold none: 662 of 858 in the measured
dump. This pass states a `started` for the 542 of those that hold evidence,
dated by the earlier of the earliest #676 status day and the earliest live
session day. No completion is ever stated.

- Scope keys on the creation event's own origin, so a blank run a person made
  and a blank run #679 stated at track time are both left alone.
- #684's `reconcile()` reads a repaired run as owing no legacy row. Without
  that it reports three mismatches for every one of the 542.
- `0048` converts, checks and rolls back on any mismatch.
- `make report-playthrough-starts` prints the same figures, read-only, against
  a restored copy.

Spec:
`docs/superpowers/specs/2026-09-10-issue-1038-playthrough-start-repair-design.md`
Plan: `docs/superpowers/plans/2026-09-10-issue-1038-playthrough-start-repair.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

---

## Notes for whoever executes this

**The three numbers to keep honest.** The measured dump says 858 tracked, 662
holding no legacy row, 542 holding evidence. If a run of the report against
production says something far from that, stop and say so rather than adjusting
the plan: the difference is data that changed, or a reader that reads the wrong
thing, and both are worth knowing before a migration commits.

**Two ways this pass can be wrong and still pass its gate.** The gate proves
the pass stated what its own reader computed. It cannot prove the reader is
right. The two known cases are in the specification: a status day frozen in the
server's zone is compared against a session day in the viewer's, and 14 of 519
rows in the measured dump take a status day that is a bulk status review rather
than play. Neither is repaired here, and `CorrectPlaythroughStart` is the
affordance for both.

**Do not widen the scope.** Repairing a `PlayerGame` status, settling the
`finished()` split between the statistics page and the Purchase list, and
naming the right condition word for a dropped run are each named in the
specification as out, and each belongs to its own issue.
