# HistoricalPlaytime aggregate implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `HistoricalPlaytime` and `HistoricalPlaytimeRun` projection tables, the four events, the four commands, the projector, the referrer and audit registrations, and the replay-gate legs — tables nothing writes and nothing reads yet.

**Architecture:** Fourth projection family after `PlayerGame`, `Playthrough` and `PlayerSession`, copying their topology: identity is the creation event's `aggregate_id`, the projector is the only writer, `removed_at` is the projector's mark. A record is one fact, so `created` and `restated` share one whole-statement payload; the runs it names are a join projection whose row ids the command mints and the payload carries, so a replay reproduces them. `when` rides on the envelope's `effective_time`, as a playthrough endpoint's date does.

**Tech Stack:** Django 6 / Python 3.14 / PostgreSQL 18, pydantic `TypeAdapter` payload validation, pytest + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-17-issue-705-historical-playtime-aggregate-design.md` — read it first; every "why" lives there and is not repeated here. The wave it belongs to: `docs/superpowers/specs/2026-09-17-historical-playtime-wave-design.md`.

## Global Constraints

- Run everything through `make`. Never `direnv exec .`, never bare `uv run` / `pytest`.
- Iterate with `make check-fast`; the gate before "done" is the full `make check`, e2e included.
- Focused runs: `make test ARGS="tests/test_historical_playtime_projection.py -x"`.
- Python 3.14 only. `except A, B:` (PEP 758) is valid here; ruff formats to it.
- Never write to a `GeneratedField`.
- Name variables with complete words. Name compound types (`TypedDict`, `NamedTuple`, PEP 695 alias) rather than repeating structural annotations.
- Every `CommandRejected` carries two sentences: `raise CommandRejected(message, sentence=…)`.
- No command resolves a row with a bare manager `.get()`; use `library_row` from `games/commands/scope.py`. `tests/test_command_scope_guard.py` enforces it.
- Comments explain intent, never history; no issue or PR references in code comments.
- The recorded vocabulary is frozen on merge: event type names, aggregate type, payload keys and their spellings cannot be changed afterwards.
- `make vale` refuses `delete`, `fold`, and the projector/projection confusions in docs and comments. Say `remove` for the mark and `take out` for a row that leaves a table.

---

### Task 1: The two tables and their registrations

**Files:**
- Modify: `games/models.py` (after `LibraryCalendar`, before `UserLibraryPreferences`)
- Modify: `games/projections.py:109-114` (`AUDITED_PROJECTION_REFERENCES`)
- Create: `games/migrations/0002_historical_playtime.py` (generated)
- Test: `tests/test_historical_playtime_projection.py`

**Interfaces produced:**
- `HistoricalPlaytimeProvenance(models.TextChoices)` — `ESTIMATED = "estimated"`, `MANUALLY_ENTERED = "manually_entered"`, `EXTERNALLY_MEASURED = "externally_measured"`
- `HistoricalPlaytimeQuerySet(RemovableMixin, models.QuerySet["HistoricalPlaytime"])` with `ancestor_marks = ("player_game",)`
- `HistoricalPlaytime(ProjectionModel)` — columns per the spec's §"The projections"
- `HistoricalPlaytimeRunQuerySet(models.QuerySet["HistoricalPlaytimeRun"])` with `alive()`
- `HistoricalPlaytimeRun(ProjectionModel)` — `record`, `playthrough`
- Reverse accessors: `HistoricalPlaytime.runs`, `Playthrough.historical_playtime_runs`, `PlayerGame.historical_playtime`

- [ ] **Step 1: Write the failing tests**

`tests/test_historical_playtime_projection.py`, module docstring `"""One row per historical playtime record a library states."""`. Build rows with `HistoricalPlaytime.objects.create(...)` directly here — the projector arrives in Task 3, and these tests are about the schema. Copy the `game`, `tracked` and `run` fixtures from `tests/test_playersession_projection.py:53-79` verbatim, and add:

```python
import uuid
from datetime import date, timedelta

import pytest
from django.apps import apps as global_apps
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    unaudited_projection_references,
)

pytestmark = pytest.mark.untracked_games


def a_record(tracked, **stated) -> HistoricalPlaytime:
    columns = {
        "id": uuid.uuid7(),
        "library": tracked.library,
        "player_game": tracked,
        "duration": timedelta(hours=100),
        "when": "2005",
        "provenance": HistoricalPlaytimeProvenance.ESTIMATED,
        "device": None,
        "emulated": False,
        "note": "",
        "created_at": timezone.now(),
    } | stated
    return HistoricalPlaytime.objects.create(**columns)


def a_join(record, run) -> HistoricalPlaytimeRun:
    return HistoricalPlaytimeRun.objects.create(
        id=uuid.uuid7(), library=record.library, record=record, playthrough=run
    )
```

Constraint tests, each wrapping the write in `pytest.raises(IntegrityError)` inside `transaction.atomic()`:

| test | row | expected |
|---|---|---|
| `test_a_zero_duration_is_refused` | `duration=timedelta(0)` | IntegrityError |
| `test_a_negative_duration_is_refused` | `duration=timedelta(hours=-1)` | IntegrityError |
| `test_an_unknown_provenance_is_refused` | `provenance="guessed"` | IntegrityError |
| `test_a_run_is_named_once_per_record` | two `a_join(record, run)` | IntegrityError |
| `test_an_unknown_when_is_admitted` | `when=None` | row exists, `when_lower is None`, `when_upper is None` |

Generated-column tests (`refresh_from_db()` after each write):

```python
@pytest.mark.django_db
def test_a_year_bounds_to_its_first_and_last_day(tracked):
    record = a_record(tracked, when="2005")
    record.refresh_from_db()
    assert record.when_lower == date(2005, 1, 1)
    assert record.when_upper == date(2005, 12, 31)


@pytest.mark.django_db
def test_an_open_range_has_no_upper_bound(tracked):
    record = a_record(tracked, when="2005/")
    record.refresh_from_db()
    assert record.when_lower == date(2005, 1, 1)
    assert record.when_upper is None
```

Structure tests:

```python
def test_the_model_passes_the_projection_checks():
    assert check_projection_models(apps=global_apps) == []


def test_the_four_references_are_registered():
    keys = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}
    assert ("games.HistoricalPlaytime", "player_game") in keys
    assert ("games.HistoricalPlaytime", "device") in keys
    assert ("games.HistoricalPlaytimeRun", "record") in keys
    assert ("games.HistoricalPlaytimeRun", "playthrough") in keys
    assert unaudited_projection_references() == ()


def test_both_managers_state_alive():
    assert hasattr(HistoricalPlaytime._default_manager, "alive")
    assert hasattr(HistoricalPlaytimeRun._default_manager, "alive")


@pytest.mark.django_db
def test_a_removed_record_hides_its_join_rows(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    HistoricalPlaytime.objects.filter(pk=record.pk).update(removed_at=timezone.now())
    assert not HistoricalPlaytimeRun.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_tracked_game_hides_the_record(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())
    assert not HistoricalPlaytime.objects.alive().exists()
    assert not HistoricalPlaytimeRun.objects.alive().exists()


def test_the_record_reaches_the_game_in_one_hop():
    assert HistoricalPlaytime.comparison_through == (("player_game__game", "Game"),)
```

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_historical_playtime_projection.py -x"` → ImportError, no `HistoricalPlaytime`.

- [ ] **Step 3: Add the models**

In `games/models.py`, after `LibraryCalendar`:

```python
class HistoricalPlaytimeProvenance(models.TextChoices):
    """Where a stated duration came from.

    Full words: a recorded payload is never upcast.
    """

    ESTIMATED = "estimated", "Estimated"
    MANUALLY_ENTERED = "manually_entered", "Manually entered"
    EXTERNALLY_MEASURED = "externally_measured", "Externally measured"


class HistoricalPlaytimeQuerySet(RemovableMixin, models.QuerySet["HistoricalPlaytime"]):
    """The marks that hide a record: its own and its tracked game's."""

    ancestor_marks = ("player_game",)


class HistoricalPlaytime(ProjectionModel):
    """Playtime a library states without sittings, projected from its events."""

    objects = HistoricalPlaytimeQuerySet.as_manager()

    #: The game is one parent away; the filter compares against it.
    comparison_through = (("player_game__game", "Game"),)

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The creation event's aggregate_id, evaluated once.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    player_game = models.ForeignKey(
        PlayerGame,
        #: No cascade may destroy a projection row.
        on_delete=models.RESTRICT,
        related_name="historical_playtime",
    )
    #: Every column below is stated by the event and carries no default.
    duration = models.DurationField()
    #: Null is a when nobody knows, as on a run's start.
    when = TemporalValueField()
    when_lower = models.GeneratedField(
        expression=TemporalLowerBound("when"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    when_upper = models.GeneratedField(
        expression=TemporalUpperBound("when"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    provenance = models.CharField(max_length=19, choices=HistoricalPlaytimeProvenance)
    #: RESTRICT: only the projector changes rows.
    device = models.ForeignKey(
        "Device",
        on_delete=models.RESTRICT,
        null=True,
        related_name="historical_playtime",
    )
    emulated = models.BooleanField()
    note = models.TextField()
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null means live.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    class Meta:
        indexes = (
            #: The containment reads: a year or a month, then the key.
            models.Index(
                fields=("library", "when_lower", "id"),
                name="historicalplaytime_when_order",
            ),
        )
        constraints = (
            library_identity_constraint(),
            models.CheckConstraint(
                condition=Q(duration__gt=timedelta(0)),
                name="historicalplaytime_duration_positive",
            ),
            models.CheckConstraint(
                condition=Q(provenance__in=HistoricalPlaytimeProvenance.values),
                name="historicalplaytime_provenance_known",
            ),
        )


class HistoricalPlaytimeRunQuerySet(models.QuerySet["HistoricalPlaytimeRun"]):
    """A join row is live while its record is."""

    def alive(self):
        return self.filter(
            record__removed_at__isnull=True,
            record__player_game__removed_at__isnull=True,
        )


class HistoricalPlaytimeRun(ProjectionModel):
    """One run a historical playtime record names."""

    objects = HistoricalPlaytimeRunQuerySet.as_manager()

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The statement's own id for this pair, evaluated once.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    record = models.ForeignKey(
        HistoricalPlaytime, on_delete=models.RESTRICT, related_name="runs"
    )
    playthrough = models.ForeignKey(
        Playthrough,
        on_delete=models.RESTRICT,
        related_name="historical_playtime_runs",
    )

    class Meta:
        constraints = (
            library_identity_constraint(),
            models.UniqueConstraint(
                fields=("record", "playthrough"),
                name="historicalplaytimerun_once_per_record",
            ),
        )
```

`TemporalLowerBound` and `TemporalUpperBound` are already imported from `timetracker.temporal` for `Playthrough`. Index and constraint names must stay ≤ 30 characters; the ones above are.

- [ ] **Step 4: Register the four references**

`games/projections.py`: append to `AUDITED_PROJECTION_REFERENCES`, importing both models beside the other three:

```python
AUDITED_PROJECTION_REFERENCES: tuple[ProjectionReference, ...] = (
    ProjectionReference.on(PlayerGame, "game"),
    ProjectionReference.on(PlayerSession, "device"),
    ProjectionReference.on(PlayerSession, "playthrough"),
    ProjectionReference.on(Playthrough, "player_game"),
    ProjectionReference.on(HistoricalPlaytime, "player_game"),
    ProjectionReference.on(HistoricalPlaytime, "device"),
    ProjectionReference.on(HistoricalPlaytimeRun, "record"),
    ProjectionReference.on(HistoricalPlaytimeRun, "playthrough"),
)
```

Leaving any out fails `manage.py check` with `games.E009`.

- [ ] **Step 5: Make and apply the migration**

```bash
make makemigrations ARGS="games --name historical_playtime"
make migrate
```

Read the generated `games/migrations/0002_historical_playtime.py` before moving on: two `CreateModel`s, two `CheckConstraint`s and one index on the record, one `UniqueConstraint` on the join, and no `AlterField` on anything else. Then `make check-migrations`.

- [ ] **Step 6: Run the tests**

`make test ARGS="tests/test_historical_playtime_projection.py"` → all pass. Then `make check-fast`.

- [ ] **Step 7: Commit**

```bash
git add games/models.py games/projections.py games/migrations tests/test_historical_playtime_projection.py
git commit -m "feat: state what a historical playtime record holds"
```

---

### Task 2: The events and their payload

**Files:**
- Create: `games/events/historical_playtime.py`
- Test: `tests/test_historical_playtime_events.py`

**Interfaces consumed:** `HistoricalPlaytimeProvenance` (Task 1); `ReferenceId`, `Reference`, `STRICT_SCHEMA` from `games/events/references.py`; `NoteText` from `games/events/playersession.py`; `EventSpec`, `NewEvent`, `DEFAULT_EVENT_TYPES` from `games/events/vocabulary.py`.

**Interfaces produced:**
- `type ProvenanceValue = Literal["estimated", "manually_entered", "externally_measured"]`
- `HistoricalPlaytimeRunPayload(TypedDict)` — `id: ReferenceId`, `playthrough: ReferenceId`
- `HistoricalPlaytimeStatementPayload(TypedDict)` — the spec's shape
- `HISTORICALPLAYTIME_CREATED`, `HISTORICALPLAYTIME_RESTATED`, `HISTORICALPLAYTIME_REMOVED`, `HISTORICALPLAYTIME_RESTORED: EventSpec`
- `sorted_runs(members: Iterable[HistoricalPlaytimeRunPayload]) -> list[HistoricalPlaytimeRunPayload]` — the canonical order, by `playthrough` text
- `historicalplaytime_created(*, player_game_id, runs, duration, when, provenance, device, emulated, note, record_id=None) -> NewEvent`
- `historicalplaytime_restated(record_id, *, player_game_id, runs, duration, when, provenance, device, emulated, note) -> NewEvent`
- `historicalplaytime_removed(record_id) -> NewEvent`, `historicalplaytime_restored(record_id) -> NewEvent`

- [ ] **Step 1: Write the failing tests**

`tests/test_historical_playtime_events.py`, following `tests/test_playersession_events.py`:

```python
"""What a library states about playtime it did not track."""

import uuid
from datetime import timedelta

import pytest

from games.events.historical_playtime import (
    HISTORICALPLAYTIME_CREATED,
    HISTORICALPLAYTIME_REMOVED,
    HISTORICALPLAYTIME_RESTATED,
    HISTORICALPLAYTIME_RESTORED,
    historicalplaytime_created,
    historicalplaytime_removed,
    historicalplaytime_restated,
    historicalplaytime_restored,
    sorted_runs,
)
from games.events.references import ReferenceArity
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid
from timetracker.temporal import TemporalValue

PLAYER_GAME = uuid.uuid7()
RUN_A = uuid.uuid7()
RUN_B = uuid.uuid7()
DEVICE = {
    "kind": "device",
    "id": str(uuid.uuid7()),
    "label": "Steam Deck",
    "detail": "",
}


def a_member(run: uuid.UUID) -> dict:
    return {"id": str(uuid.uuid7()), "playthrough": str(run)}


def a_statement(**stated) -> dict:
    return {
        "player_game": str(PLAYER_GAME),
        "playthroughs": sorted_runs([a_member(RUN_A)]),
        "duration_seconds": 360000,
        "provenance": "estimated",
        "device": None,
        "emulated": False,
        "note": "",
        "release": None,
        "source": None,
    } | stated


def test_the_event_types_are_spelled_once_and_forever():
    assert HISTORICALPLAYTIME_CREATED.event_type == "library.historicalplaytime.created"
    assert (
        HISTORICALPLAYTIME_RESTATED.event_type == "library.historicalplaytime.restated"
    )
    assert HISTORICALPLAYTIME_REMOVED.event_type == "library.historicalplaytime.removed"
    assert (
        HISTORICALPLAYTIME_RESTORED.event_type == "library.historicalplaytime.restored"
    )
    for spec in (
        HISTORICALPLAYTIME_CREATED,
        HISTORICALPLAYTIME_RESTATED,
        HISTORICALPLAYTIME_REMOVED,
        HISTORICALPLAYTIME_RESTORED,
    ):
        assert spec.aggregate_type == "historicalplaytime"


def test_a_statement_round_trips():
    payload = a_statement(device=DEVICE)
    assert DEFAULT_EVENT_TYPES.validate(HISTORICALPLAYTIME_CREATED, payload) == payload


@pytest.mark.parametrize(
    "broken",
    [
        {"playthroughs": []},
        {"playthroughs": [a_member(RUN_A), a_member(RUN_A)]},
        {"playthroughs": sorted_runs([a_member(RUN_A), a_member(RUN_B)])[::-1]},
        {"duration_seconds": 0},
        {"duration_seconds": -1},
        {"duration_seconds": "360000"},
        {"provenance": "guessed"},
        {"release": DEVICE},
        {"source": {"provider": "steam"}},
        {"extra": True},
    ],
    ids=[
        "no-runs",
        "repeated-run",
        "unsorted-runs",
        "zero-duration",
        "negative-duration",
        "lax-integer",
        "unknown-provenance",
        "release-stated",
        "source-stated",
        "extra-key",
    ],
)
def test_a_broken_statement_is_refused(broken):
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(HISTORICALPLAYTIME_CREATED, a_statement(**broken))


def test_a_missing_key_is_refused():
    payload = a_statement()
    del payload["note"]
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(HISTORICALPLAYTIME_CREATED, payload)


def test_the_restatement_shares_the_statement_payload():
    assert HISTORICALPLAYTIME_RESTATED.payload is HISTORICALPLAYTIME_CREATED.payload


def test_the_references_are_enumerated():
    assert DEFAULT_EVENT_TYPES.reference_fields_for(HISTORICALPLAYTIME_CREATED) == {
        "device": ReferenceArity.OPTIONAL,
    }


def test_the_runs_sort_by_run_text():
    members = [a_member(RUN_B), a_member(RUN_A)]
    assert [m["playthrough"] for m in sorted_runs(members)] == sorted(
        [str(RUN_B), str(RUN_A)]
    )


def test_the_when_rides_on_the_envelope():
    event = historicalplaytime_created(
        player_game_id=PLAYER_GAME,
        runs=[a_member(RUN_A)],
        duration=timedelta(hours=100),
        when=TemporalValue.parse("2005~"),
        provenance="estimated",
        device=None,
        emulated=False,
        note="",
    )
    assert event.effective_time.canonical == "2005~"
    assert "when" not in event.payload


def test_an_unknown_when_is_a_null_effective_time():
    event = historicalplaytime_created(
        player_game_id=PLAYER_GAME,
        runs=[a_member(RUN_A)],
        duration=timedelta(hours=1),
        when=TemporalValue.unknown(),
        provenance="estimated",
        device=None,
        emulated=False,
        note="",
    )
    assert event.effective_time is None


def test_the_identity_may_be_stated():
    stated = uuid.uuid7()
    event = historicalplaytime_created(
        player_game_id=PLAYER_GAME,
        runs=[a_member(RUN_A)],
        duration=timedelta(hours=1),
        when=TemporalValue.unknown(),
        provenance="estimated",
        device=None,
        emulated=False,
        note="",
        record_id=stated,
    )
    assert event.aggregate_id == stated


def test_a_duration_is_whole_seconds():
    event = historicalplaytime_created(
        player_game_id=PLAYER_GAME,
        runs=[a_member(RUN_A)],
        duration=timedelta(hours=1, seconds=30),
        when=TemporalValue.unknown(),
        provenance="estimated",
        device=None,
        emulated=False,
        note="",
    )
    assert event.payload["duration_seconds"] == 3630


def test_the_mark_events_carry_nothing():
    record = uuid.uuid7()
    assert historicalplaytime_removed(record).payload == {}
    assert historicalplaytime_restored(record).payload == {}
```

Check how `DEFAULT_EVENT_TYPES.validate` and `reference_fields_for` are called in `tests/test_playersession_events.py` and match their exact signatures; `ReferenceArity.OPTIONAL` is the arity a `Reference | None` field reports there.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_historical_playtime_events.py -x"` → ImportError.

- [ ] **Step 3: Write the module**

`games/events/historical_playtime.py`, following `games/events/playersession.py`'s shape:

```python
"""Events about playtime a library states without sittings."""

import uuid
from collections.abc import Iterable
from datetime import timedelta
from typing import Annotated, Literal, TypedDict

from pydantic import AfterValidator, Field, with_config

from games.events.playersession import NoteText
from games.events.references import STRICT_SCHEMA, Reference, ReferenceId
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent
from timetracker.temporal import TemporalValue

#: The recorded spelling; the model's TextChoices is not it.
type ProvenanceValue = Literal["estimated", "manually_entered", "externally_measured"]


@with_config(STRICT_SCHEMA)
class HistoricalPlaytimeRunPayload(TypedDict):
    """One run the record names, and the join row's own identity.

    Both bare ids, as a session's run is: a required ReferenceKind on
    a projection row would make replay's check read the live table
    before the first row.
    """

    id: ReferenceId
    playthrough: ReferenceId


def sorted_runs(
    members: Iterable[HistoricalPlaytimeRunPayload],
) -> list[HistoricalPlaytimeRunPayload]:
    """The one order a statement's runs are recorded in."""
    return sorted(members, key=lambda member: member["playthrough"])


def _canonical_runs(
    members: list[HistoricalPlaytimeRunPayload],
) -> list[HistoricalPlaytimeRunPayload]:
    """Refuse an empty, repeated or unsorted list."""
    if not members:
        raise ValueError("A record names at least one playthrough.")
    runs = [member["playthrough"] for member in members]
    if len(set(runs)) != len(runs):
        raise ValueError("A record names each playthrough once.")
    if members != sorted_runs(members):
        raise ValueError("A record's playthroughs are sorted by id.")
    return members


type RunMembers = Annotated[
    list[HistoricalPlaytimeRunPayload], AfterValidator(_canonical_runs)
]


@with_config(STRICT_SCHEMA)
class HistoricalPlaytimeStatementPayload(TypedDict):
    """The whole of one record; created and restated share it.

    `when` is not here: it is the envelope's effective_time, where a
    playthrough endpoint's date already rides.

    `release` and `source` are reserved and typed None: the validator
    refuses a value until the issue that defines one widens the type.
    A key holding None rather than an absent one, because under
    extra="forbid" the two would be two spellings of one fact.
    """

    player_game: ReferenceId
    playthroughs: RunMembers
    duration_seconds: Annotated[int, Field(gt=0)]
    provenance: ProvenanceValue
    device: Reference | None
    emulated: bool
    note: NoteText
    release: None
    source: None


@with_config(STRICT_SCHEMA)
class HistoricalPlaytimeMarkPayload(TypedDict):
    """Removed and restored state nothing beyond the act."""


HISTORICALPLAYTIME_CREATED = EventSpec(
    "library.historicalplaytime.created",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeStatementPayload,
)
HISTORICALPLAYTIME_RESTATED = EventSpec(
    "library.historicalplaytime.restated",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeStatementPayload,
)
HISTORICALPLAYTIME_REMOVED = EventSpec(
    "library.historicalplaytime.removed",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeMarkPayload,
)
HISTORICALPLAYTIME_RESTORED = EventSpec(
    "library.historicalplaytime.restored",
    aggregate_type="historicalplaytime",
    payload=HistoricalPlaytimeMarkPayload,
)
for _spec in (
    HISTORICALPLAYTIME_CREATED,
    HISTORICALPLAYTIME_RESTATED,
    HISTORICALPLAYTIME_REMOVED,
    HISTORICALPLAYTIME_RESTORED,
):
    DEFAULT_EVENT_TYPES.register(_spec)


def _statement(
    *,
    player_game_id: uuid.UUID,
    runs: Iterable[HistoricalPlaytimeRunPayload],
    duration: timedelta,
    provenance: ProvenanceValue,
    device: Reference | None,
    emulated: bool,
    note: str,
) -> HistoricalPlaytimeStatementPayload:
    return {
        "player_game": str(player_game_id),
        "playthroughs": sorted_runs(runs),
        #: Whole seconds: the command truncates, this only spells.
        "duration_seconds": duration // timedelta(seconds=1),
        "provenance": provenance,
        "device": device,
        "emulated": emulated,
        "note": note,
        "release": None,
        "source": None,
    }


def _effective(when: TemporalValue) -> TemporalValue | None:
    return None if when.is_unknown else when


def historicalplaytime_created(
    *,
    player_game_id: uuid.UUID,
    runs: Iterable[HistoricalPlaytimeRunPayload],
    duration: timedelta,
    when: TemporalValue,
    provenance: ProvenanceValue,
    device: Reference | None,
    emulated: bool,
    note: str,
    record_id: uuid.UUID | None = None,
) -> NewEvent:
    """The library stated playtime it did not track."""
    return HISTORICALPLAYTIME_CREATED.new(
        aggregate_id=uuid.uuid7() if record_id is None else record_id,
        effective_time=_effective(when),
        payload=_statement(
            player_game_id=player_game_id,
            runs=runs,
            duration=duration,
            provenance=provenance,
            device=device,
            emulated=emulated,
            note=note,
        ),
    )


def historicalplaytime_restated(
    record_id: uuid.UUID,
    *,
    player_game_id: uuid.UUID,
    runs: Iterable[HistoricalPlaytimeRunPayload],
    duration: timedelta,
    when: TemporalValue,
    provenance: ProvenanceValue,
    device: Reference | None,
    emulated: bool,
    note: str,
) -> NewEvent:
    """The library stated the whole record again."""
    return HISTORICALPLAYTIME_RESTATED.new(
        aggregate_id=record_id,
        effective_time=_effective(when),
        payload=_statement(
            player_game_id=player_game_id,
            runs=runs,
            duration=duration,
            provenance=provenance,
            device=device,
            emulated=emulated,
            note=note,
        ),
    )


def historicalplaytime_removed(record_id: uuid.UUID) -> NewEvent:
    return HISTORICALPLAYTIME_REMOVED.new(aggregate_id=record_id, payload={})


def historicalplaytime_restored(record_id: uuid.UUID) -> NewEvent:
    return HISTORICALPLAYTIME_RESTORED.new(aggregate_id=record_id, payload={})
```

`TemporalValue.is_unknown` is a property (`timetracker/temporal.py:216`). If the registry's `_check_names` refuses a `None`-typed field or the `Annotated` list validator, read `games/events/vocabulary.py`'s `register` and adjust the spelling, never the shape: the payload keys and their meaning are the spec's.

- [ ] **Step 4: Run the tests, then the suite**

`make test ARGS="tests/test_historical_playtime_events.py"`, then `make test ARGS="tests/test_event_vocabulary.py"` (the registry's own tests walk every registered type), then `make check-fast`.

- [ ] **Step 5: Commit**

```bash
git add games/events/historical_playtime.py tests/test_historical_playtime_events.py
git commit -m "feat: record what one historical playtime statement says"
```

---

### Task 3: The projector

**Files:**
- Create: `games/projectors/historical_playtime.py`
- Modify: `games/projectors/__init__.py`
- Test: `tests/test_historical_playtime_projection.py` (append)

**Interfaces consumed:** Task 1's models, Task 2's specs and payload types, `RecordedEvent` from `games/events/envelope.py`, `Projector`, `HandlerMap`, `ProjectorFamily` from `games/events/projection.py`.

**Interfaces produced:**
- `class StatementColumns(TypedDict)` — `player_game_id: uuid.UUID`, `duration: timedelta`, `when: str | None`, `provenance: HistoricalPlaytimeProvenance`, `device_id: uuid.UUID | None`, `emulated: bool`, `note: str`
- `columns_for_statement(payload: HistoricalPlaytimeStatementPayload, effective_time: TemporalValue | None) -> StatementColumns` — always seven keys
- `HistoricalPlaytimes(Projector)`, family `ProjectorFamily.CURRENT_STATE`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_historical_playtime_projection.py`. These append events directly, as `tests/test_playersession_projection.py` does around line 600 with `lock_stream` and the append path; copy its `append_session` helper's mechanics into:

```python
def append(library, actor, event, *, key: str) -> None:
    """Append one built event under a key, through the ordinary path."""
    # Copy the body of tests/test_playersession_projection.py::append_session,
    # which locks the stream and appends with DEFAULT_REGISTRY projecting.
```

Read that helper and reproduce it here rather than importing it across test modules. Then:

```python
def a_created(tracked, runs, **stated):
    return historicalplaytime_created(
        player_game_id=tracked.pk,
        runs=[{"id": str(uuid.uuid7()), "playthrough": str(run.pk)} for run in runs],
        duration=stated.get("duration", timedelta(hours=100)),
        when=stated.get("when", TemporalValue.parse("2005")),
        provenance=stated.get("provenance", "estimated"),
        device=stated.get("device"),
        emulated=stated.get("emulated", False),
        note=stated.get("note", ""),
    )


def test_the_mapper_names_every_statement_column():
    payload = {
        "player_game": str(uuid.uuid7()),
        "playthroughs": [{"id": str(uuid.uuid7()), "playthrough": str(uuid.uuid7())}],
        "duration_seconds": 3600,
        "provenance": "manually_entered",
        "device": None,
        "emulated": True,
        "note": "read off Steam",
        "release": None,
        "source": None,
    }
    columns = columns_for_statement(payload, TemporalValue.parse("2005"))
    assert set(columns) == {
        "player_game_id",
        "duration",
        "when",
        "provenance",
        "device_id",
        "emulated",
        "note",
    }
    assert columns["when"] == "2005"
    assert columns["duration"] == timedelta(hours=1)
    assert columns["provenance"] is HistoricalPlaytimeProvenance.MANUALLY_ENTERED
    assert columns_for_statement(payload, None)["when"] is None


@pytest.mark.django_db(transaction=True)
def test_the_creation_writes_the_record_and_its_runs(
    owned_user, owned_library, tracked, run
):
    second = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    event = a_created(tracked, [run, second])
    append(owned_library, owned_user, event, key="create")

    record = HistoricalPlaytime.objects.get()
    assert record.pk == event.aggregate_id
    assert record.library_id == owned_library.pk
    assert record.player_game_id == tracked.pk
    assert record.when == "2005"
    assert set(record.runs.values_list("playthrough_id", flat=True)) == {
        run.pk,
        second.pk,
    }
    assert set(record.runs.values_list("id", flat=True)) == {
        uuid.UUID(member["id"]) for member in event.payload["playthroughs"]
    }


@pytest.mark.django_db(transaction=True)
def test_a_restatement_replaces_the_runs_and_keeps_a_kept_id(
    owned_user, owned_library, tracked, run
):
    second = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    created = a_created(tracked, [run, second])
    append(owned_library, owned_user, created, key="create")
    kept = next(
        m for m in created.payload["playthroughs"] if m["playthrough"] == str(run.pk)
    )

    restated = historicalplaytime_restated(
        created.aggregate_id,
        player_game_id=tracked.pk,
        runs=[kept],
        duration=timedelta(hours=50),
        when=TemporalValue.parse("2006~"),
        provenance="manually_entered",
        device=None,
        emulated=True,
        note="halved",
    )
    append(owned_library, owned_user, restated, key="restate")

    record = HistoricalPlaytime.objects.get()
    assert record.duration == timedelta(hours=50)
    assert record.when == "2006~"
    assert record.provenance == HistoricalPlaytimeProvenance.MANUALLY_ENTERED
    assert record.emulated is True
    assert record.note == "halved"
    assert list(record.runs.values_list("id", "playthrough_id")) == [
        (uuid.UUID(kept["id"]), run.pk)
    ]


@pytest.mark.django_db(transaction=True)
def test_removed_and_restored_move_the_mark(owned_user, owned_library, tracked, run):
    created = a_created(tracked, [run])
    append(owned_library, owned_user, created, key="create")
    append(
        owned_library,
        owned_user,
        historicalplaytime_removed(created.aggregate_id),
        key="remove",
    )
    assert HistoricalPlaytime.objects.get().removed_at is not None
    assert not HistoricalPlaytimeRun.objects.alive().exists()
    append(
        owned_library,
        owned_user,
        historicalplaytime_restored(created.aggregate_id),
        key="restore",
    )
    assert HistoricalPlaytime.objects.get().removed_at is None
    assert HistoricalPlaytimeRun.objects.alive().count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_projection_replays_from_an_empty_stream(
    owned_user, owned_library, tracked, run
):
    created = a_created(tracked, [run])
    append(owned_library, owned_user, created, key="create")
    append(
        owned_library,
        owned_user,
        historicalplaytime_restated(
            created.aggregate_id,
            player_game_id=tracked.pk,
            runs=created.payload["playthroughs"],
            duration=timedelta(hours=2),
            when=TemporalValue.unknown(),
            provenance="estimated",
            device=None,
            emulated=False,
            note="",
        ),
        key="restate",
    )
    before_records = list(HistoricalPlaytime.objects.order_by("pk").values())
    before_runs = list(HistoricalPlaytimeRun.objects.order_by("pk").values())

    HistoricalPlaytimeRun.objects.all().delete()
    HistoricalPlaytime.objects.all().delete()
    replay(owned_library)

    assert list(HistoricalPlaytime.objects.order_by("pk").values()) == before_records
    assert list(HistoricalPlaytimeRun.objects.order_by("pk").values()) == before_runs


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_swaps_both_tables_with_an_empty_diff(
    owned_user, owned_library, game
):
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked_run = Playthrough.objects.get(player_game__game=game)
    append(
        owned_library,
        owned_user,
        a_created(tracked_run.player_game, [tracked_run]),
        key="create",
    )

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert all(table.differing == 0 for table in report.tables)
```

For the rebuild assertion, read `RebuildReport` in `games/events/rebuild.py` and match its attribute names; `tests/test_playersession_projection.py::test_a_rebuild_swaps_the_table_with_an_empty_diff` shows the exact assertions to copy.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_historical_playtime_projection.py -k 'mapper or creation or restatement or mark or replay or rebuild' -x"` → ImportError on `columns_for_statement`.

- [ ] **Step 3: Write the projector**

`games/projectors/historical_playtime.py`:

```python
"""Current-state rows for the playtime a library states without sittings."""

import uuid
from datetime import timedelta
from typing import ClassVar, TypedDict

from games.events.envelope import RecordedEvent
from games.events.historical_playtime import (
    HISTORICALPLAYTIME_CREATED,
    HISTORICALPLAYTIME_REMOVED,
    HISTORICALPLAYTIME_RESTATED,
    HISTORICALPLAYTIME_RESTORED,
    HistoricalPlaytimeStatementPayload,
)
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
)
from timetracker.temporal import TemporalValue


class StatementColumns(TypedDict):
    """The seven columns one statement decides.

    A TypedDict so a dropped key is the type checker's finding, not
    `project()`'s at append time.
    """

    player_game_id: uuid.UUID
    duration: timedelta
    when: str | None
    provenance: HistoricalPlaytimeProvenance
    device_id: uuid.UUID | None
    emulated: bool
    note: str


def columns_for_statement(
    payload: HistoricalPlaytimeStatementPayload, effective_time: TemporalValue | None
) -> StatementColumns:
    """Every column, every time: a restatement overwrites the whole row."""
    device = payload["device"]
    return {
        "player_game_id": uuid.UUID(payload["player_game"]),
        "duration": timedelta(seconds=payload["duration_seconds"]),
        "when": None if effective_time is None else effective_time.canonical,
        "provenance": HistoricalPlaytimeProvenance(payload["provenance"]),
        "device_id": None if device is None else uuid.UUID(device["id"]),
        "emulated": payload["emulated"],
        "note": payload["note"],
    }


class HistoricalPlaytimes(Projector):
    """One row per record, and one join row per run it names."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _write_runs(self, event: RecordedEvent) -> None:
        """The record's runs, replaced whole.

        A derived set is never patched: the rows of this record in the
        event's library are taken out and written again from the payload,
        each with the id the statement carries, so a kept run keeps its
        row and a replay reproduces every id.
        """
        rows = self.library_rows(HistoricalPlaytimeRun, event)
        rows.filter(record_id=event.aggregate_id).delete()
        projected = self.target.model(HistoricalPlaytimeRun)
        rows.bulk_create(
            [
                projected(
                    id=uuid.UUID(member["id"]),
                    library_id=event.library_id,
                    record_id=event.aggregate_id,
                    playthrough_id=uuid.UUID(member["playthrough"]),
                )
                for member in event.payload["playthroughs"]
            ]
        )

    def _created(self, event: RecordedEvent) -> None:
        #: Never names the mark, so a removal survives a replayed restate.
        self.project(
            HistoricalPlaytime,
            event,
            created_at=event.recorded_at,
            **columns_for_statement(event.payload, event.effective_time),
        )
        self._write_runs(event)

    def _restated(self, event: RecordedEvent) -> None:
        self.amend(
            HistoricalPlaytime,
            event,
            **columns_for_statement(event.payload, event.effective_time),
        )
        self._write_runs(event)

    def _removed(self, event: RecordedEvent) -> None:
        #: The event's instant, so a replay agrees.
        self.amend(HistoricalPlaytime, event, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(HistoricalPlaytime, event, removed_at=None)

    handles: ClassVar[HandlerMap] = {
        HISTORICALPLAYTIME_CREATED: _created,
        HISTORICALPLAYTIME_RESTATED: _restated,
        HISTORICALPLAYTIME_REMOVED: _removed,
        HISTORICALPLAYTIME_RESTORED: _restored,
    }
```

`rows.bulk_create` on a filtered queryset: Django's `bulk_create` ignores the filter, so the `library_rows` call only serves to pick the redirected (shadow or live) model; keep the explicit `library_id` on each row. If `library_rows` returns a queryset whose manager refuses `bulk_create` on a `.filter()` result, call `projected._default_manager.bulk_create(...)` instead, with `projected = self.target.model(HistoricalPlaytimeRun)`.

Add `historical_playtime` to the import in `games/projectors/__init__.py`, keeping the alphabetical order.

- [ ] **Step 4: Run the tests**

`make test ARGS="tests/test_historical_playtime_projection.py"`, then `make test ARGS="tests/test_event_projectors.py tests/test_projection_rebuild.py"`, then `make check-fast`.

- [ ] **Step 5: Commit**

```bash
git add games/projectors tests/test_historical_playtime_projection.py
git commit -m "feat: project the playtime a library states without sittings"
```

---

### Task 4: The four commands

**Files:**
- Create: `games/commands/historical_playtime.py`
- Modify: `games/events/dispatch.py:83-107` (`CommandName`)
- Modify: `games/commands/scope.py` (receives `library_device`)
- Modify: `games/commands/playersession.py:395-423` (`_library_device` becomes an import)
- Test: `tests/test_historical_playtime_command.py`

**Interfaces consumed:** Task 2's builders; `library_playthrough`, `refuse_unless_live` from `games/commands/playthrough.py`; `library_row`, `Refusal` from `games/commands/scope.py`; `check_note`, `DURATION_RESOLUTION` from `games/commands/playersession.py`; Task 3's `columns_for_statement`.

**Interfaces produced:**
- `CommandName.HISTORICALPLAYTIME_RECORD = "library.historicalplaytime.record"`, `_RESTATE = "library.historicalplaytime.restate"`, `_REMOVE = "library.historicalplaytime.remove"`, `_RESTORE = "library.historicalplaytime.restore"`
- `library_device(context, device_id) -> Device | None` in `games/commands/scope.py` (the moved `_library_device`)
- `HistoricalPlaytimeStatement(NamedTuple)` — `duration: timedelta`, `when: str | None`, `provenance: HistoricalPlaytimeProvenance`, `playthrough_ids: tuple[uuid.UUID, ...]`, `device_id: uuid.UUID | None`, `emulated: bool`, `note: str`
- `RecordHistoricalPlaytime(statement)`, `RestateHistoricalPlaytime(record_id, statement)`, `RemoveHistoricalPlaytime(record_id)`, `RestoreHistoricalPlaytime(record_id)`
- `ONE_GAME`, `INTO_THE_BUCKET_HISTORICAL`: the two module-level sentences

- [ ] **Step 1: Write the failing tests**

`tests/test_historical_playtime_command.py`. Copy the module header, `pytestmark`, and the `game`, `run`, `second_library` fixtures from `tests/test_playersession_command.py:1-93`, then:

```python
from games.commands.historical_playtime import (
    INTO_THE_BUCKET_HISTORICAL,
    ONE_GAME,
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RemoveHistoricalPlaytime,
    RestateHistoricalPlaytime,
    RestoreHistoricalPlaytime,
)
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
)

A_STATEMENT = HistoricalPlaytimeStatement(
    duration=timedelta(hours=100),
    when="2005",
    provenance=HistoricalPlaytimeProvenance.ESTIMATED,
    playthrough_ids=(),
    device_id=None,
    emulated=False,
    note="",
)


def stated(run, **changes) -> HistoricalPlaytimeStatement:
    return A_STATEMENT._replace(playthrough_ids=(run.pk,))._replace(**changes)


def record(library, actor, statement, *, key=None) -> HistoricalPlaytime:
    dispatch(
        RecordHistoricalPlaytime(statement=statement),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )
    return HistoricalPlaytime.objects.get()


@pytest.fixture
def second_run(owned_user, owned_library, run) -> Playthrough:
    dispatch(
        CreatePlaythrough(game_id=run.player_game.game_id),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second",
    )
    return Playthrough.objects.exclude(pk=run.pk).get()


def test_it_records_the_statement(owned_user, owned_library, run, second_run):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk, run.pk))
    )
    assert stored.duration == timedelta(hours=100)
    assert stored.when == "2005"
    assert stored.player_game_id == run.player_game_id
    assert set(stored.runs.values_list("playthrough_id", flat=True)) == {
        run.pk,
        second_run.pk,
    }
    assert (
        LibraryEvent.objects.filter(
            library=owned_library, event_type="library.historicalplaytime.created"
        ).count()
        == 1
    )


def test_an_unknown_when_is_admitted(owned_user, owned_library, run):
    assert record(owned_library, owned_user, stated(run, when=None)).when is None


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"playthrough_ids": ()}, "at least one"),
        ({"duration": timedelta(0)}, "at least a second"),
        ({"duration": timedelta(seconds=-1)}, "at least a second"),
        ({"when": "not a date"}, ""),
    ],
    ids=["no-runs", "zero", "negative", "unparseable-when"],
)
def test_a_statement_is_refused_before_the_fingerprint(run, changes, fragment):
    with pytest.raises(CommandRejected) as refused:
        RecordHistoricalPlaytime(statement=stated(run, **changes))
    assert refused.value.sentence
    assert fragment in refused.value.sentence


def test_a_duration_is_truncated_to_whole_seconds(run):
    command = RecordHistoricalPlaytime(
        statement=stated(run, duration=timedelta(seconds=90, microseconds=500))
    )
    assert command.statement.duration == timedelta(seconds=90)


def test_a_repeated_run_is_named_once(run):
    command = RecordHistoricalPlaytime(
        statement=stated(run, playthrough_ids=(run.pk, run.pk))
    )
    assert command.statement.playthrough_ids == (run.pk,)


def test_the_note_is_stripped(run):
    command = RecordHistoricalPlaytime(statement=stated(run, note="  read off Steam  "))
    assert command.statement.note == "read off Steam"


def _refused(library, actor, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refused:
        dispatch(
            command, actor=actor, library=library, idempotency_key=str(uuid.uuid7())
        )
    assert refused.value.sentence
    return refused.value


def test_it_refuses_runs_of_two_games(owned_user, owned_library, run):
    other = Game.objects.create(library=owned_library, name="Elden Ring")
    dispatch(
        TrackGame(game_id=other.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-other",
    )
    other_run = Playthrough.objects.get(player_game__game=other)
    refused = _refused(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(
            statement=stated(run, playthrough_ids=(run.pk, other_run.pk))
        ),
    )
    assert refused.sentence == ONE_GAME


def test_it_refuses_the_bucket(owned_user, owned_library, run):
    bucket = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    refused = _refused(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(statement=stated(run, playthrough_ids=(bucket.pk,))),
    )
    assert refused.sentence == INTO_THE_BUCKET_HISTORICAL


def test_it_refuses_a_run_another_library_holds(
    owned_user, owned_library, run, second_library
):
    Playthrough.objects.filter(pk=run.pk).update(library=second_library)
    _refused(owned_library, owned_user, RecordHistoricalPlaytime(statement=stated(run)))


def test_it_refuses_a_removed_run(owned_user, owned_library, run):
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())
    _refused(owned_library, owned_user, RecordHistoricalPlaytime(statement=stated(run)))


def test_it_refuses_a_run_under_a_removed_game(owned_user, owned_library, run):
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())
    _refused(owned_library, owned_user, RecordHistoricalPlaytime(statement=stated(run)))


def test_it_refuses_a_removed_device(owned_user, owned_library, run):
    device = Device.objects.create(
        library=owned_library, name="Deck", removed_at=timezone.now()
    )
    _refused(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(statement=stated(run, device_id=device.pk)),
    )


def test_it_refuses_a_device_another_library_holds(
    owned_user, owned_library, run, second_library
):
    device = Device.objects.create(library=second_library, name="Deck")
    _refused(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(statement=stated(run, device_id=device.pk)),
    )


def test_it_admits_every_provenance(owned_user, owned_library, run):
    for index, provenance in enumerate(HistoricalPlaytimeProvenance):
        dispatch(
            RecordHistoricalPlaytime(statement=stated(run, provenance=provenance)),
            actor=owned_user,
            library=owned_library,
            idempotency_key=f"p{index}",
        )
    assert HistoricalPlaytime.objects.count() == 3


def test_a_retry_of_one_statement_appends_nothing_more(owned_user, owned_library, run):
    command = RecordHistoricalPlaytime(statement=stated(run))
    dispatch(command, actor=owned_user, library=owned_library, idempotency_key="k")
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="k"
    )
    assert second.outcome is CommandOutcome.REPLAYED
    assert HistoricalPlaytime.objects.count() == 1


def test_the_same_runs_in_another_order_fingerprint_alike(run, second_run):
    one = RecordHistoricalPlaytime(
        statement=stated(run, playthrough_ids=(run.pk, second_run.pk))
    )
    other = RecordHistoricalPlaytime(
        statement=stated(run, playthrough_ids=(second_run.pk, run.pk))
    )
    assert one.statement == other.statement


def test_a_restatement_overwrites_and_keeps_a_kept_join_id(
    owned_user, owned_library, run, second_run
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(run.pk, second_run.pk))
    )
    kept_id = stored.runs.get(playthrough=run).pk
    dispatch(
        RestateHistoricalPlaytime(
            record_id=stored.pk,
            statement=stated(run, duration=timedelta(hours=50), when="2006~"),
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restate",
    )
    stored.refresh_from_db()
    assert stored.duration == timedelta(hours=50)
    assert stored.when == "2006~"
    assert list(stored.runs.values_list("pk", "playthrough_id")) == [(kept_id, run.pk)]


def test_an_equal_restatement_appends_nothing(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    before = LibraryEvent.objects.count()
    result = dispatch(
        RestateHistoricalPlaytime(record_id=stored.pk, statement=stated(run)),
        actor=owned_user,
        library=owned_library,
        idempotency_key="same",
    )
    assert result.outcome is CommandOutcome.UNCHANGED
    assert LibraryEvent.objects.count() == before


def test_a_restatement_of_a_removed_record_is_refused(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    _refused(
        owned_library,
        owned_user,
        RestateHistoricalPlaytime(record_id=stored.pk, statement=stated(run, note="x")),
    )


def test_remove_and_restore_move_the_mark_and_repeat_as_no_ops(
    owned_user, owned_library, run
):
    stored = record(owned_library, owned_user, stated(run))
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    stored.refresh_from_db()
    assert stored.removed_at is not None
    again = dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm2",
    )
    assert again.outcome is CommandOutcome.UNCHANGED
    dispatch(
        RestoreHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rs",
    )
    stored.refresh_from_db()
    assert stored.removed_at is None
    again = dispatch(
        RestoreHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rs2",
    )
    assert again.outcome is CommandOutcome.UNCHANGED


def test_a_record_another_library_holds_is_refused(
    owned_user, owned_library, run, second_library
):
    stored = record(owned_library, owned_user, stated(run))
    HistoricalPlaytime.objects.filter(pk=stored.pk).update(library=second_library)
    _refused(owned_library, owned_user, RemoveHistoricalPlaytime(record_id=stored.pk))
```

Confirm `CommandOutcome.UNCHANGED` is the member name in `games/events/dispatch.py`; `tests/test_playersession_command.py` uses it for `Unchanged` answers.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_historical_playtime_command.py -x"` → ImportError.

- [ ] **Step 3: Move the device resolver**

Cut `_library_device` from `games/commands/playersession.py:395-423` into `games/commands/scope.py` as `library_device`, importing `Device` and `CommandRejected` there (`scope.py` already imports `CommandRejected`). Generalise its two sentences from "a session" to "a record" wording: message `"This library holds no device {device_id}. A stated fact names a device the library records."`, sentence unchanged (`"That device is not available."`); the removed-device sentence becomes `"That device was removed from your library. Restore it before choosing it."`. In `playersession.py`, `from games.commands.scope import Refusal, library_device, library_row` and replace the three call sites of `_library_device` with `library_device`. Run `make test ARGS="tests/test_playersession_command.py -k device"` and fix any test that pinned the old sentence.

- [ ] **Step 4: Write the commands**

`CommandName` in `games/events/dispatch.py`, after `CALENDAR_SET_DAY_ZONE`:

```python
    HISTORICALPLAYTIME_RECORD = "library.historicalplaytime.record"
    HISTORICALPLAYTIME_RESTATE = "library.historicalplaytime.restate"
    HISTORICALPLAYTIME_REMOVE = "library.historicalplaytime.remove"
    HISTORICALPLAYTIME_RESTORE = "library.historicalplaytime.restore"
```

`games/commands/historical_playtime.py`:

```python
"""Commands about the playtime a library states without sittings."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, NamedTuple

from games.commands.playersession import DURATION_RESOLUTION, check_note
from games.commands.playthrough import library_playthrough, refuse_unless_live
from games.commands.scope import Refusal, library_device, library_row
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.historical_playtime import (
    HistoricalPlaytimeRunPayload,
    historicalplaytime_created,
    historicalplaytime_removed,
    historicalplaytime_restated,
    historicalplaytime_restored,
)
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent, Unchanged
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    Playthrough,
    PlaythroughKind,
)
from games.projectors.historical_playtime import columns_for_statement
from timetracker.temporal import TemporalValue, TemporalValueParseError

ONE_GAME = (
    "Historical playtime belongs to one game. Choose playthroughs of the same game."
)
INTO_THE_BUCKET_HISTORICAL = (
    "That is the imported-history bucket. Record historical playtime on one of "
    "the game's playthroughs instead."
)
AT_LEAST_ONE_RUN = "Choose at least one playthrough."
AT_LEAST_A_SECOND = "Historical playtime is at least a second."


class HistoricalPlaytimeStatement(NamedTuple):
    """The whole of one record, as a person states it.

    A NamedTuple, so the idempotency fingerprint encodes it as an
    array; a dataclass reaches the encoder's fallback and raises.
    Positional, so the fields are named here once and left alone.
    """

    duration: timedelta
    #: Canonical temporal text; None is a when nobody knows.
    when: str | None
    provenance: HistoricalPlaytimeProvenance
    playthrough_ids: tuple[uuid.UUID, ...]
    device_id: uuid.UUID | None
    emulated: bool
    note: str


def normalized_statement(
    statement: HistoricalPlaytimeStatement,
) -> HistoricalPlaytimeStatement:
    """One spelling, so restatements fingerprint alike; refusals first."""
    note = statement.note.strip()
    check_note(note)
    runs = tuple(sorted(set(statement.playthrough_ids), key=str))
    if not runs:
        raise CommandRejected(
            "A historical playtime statement names no playthrough.",
            sentence=AT_LEAST_ONE_RUN,
        )
    duration = statement.duration - (statement.duration % DURATION_RESOLUTION)
    if duration < DURATION_RESOLUTION:
        raise CommandRejected(
            f"A historical playtime of {statement.duration} states no time.",
            sentence=AT_LEAST_A_SECOND,
        )
    try:
        when = TemporalValue.parse(statement.when).canonical
    except TemporalValueParseError as error:
        raise CommandRejected(
            f"{statement.when!r} is not a temporal value: {error}",
            sentence=str(error),
        ) from None
    return statement._replace(
        note=note, playthrough_ids=runs, duration=duration, when=when
    )


def _live_runs(
    context: CommandContext, statement: HistoricalPlaytimeStatement
) -> list[Playthrough]:
    """Every named run, live, of one game, none the bucket."""
    runs = [
        refuse_unless_live(library_playthrough(context, run_id))
        for run_id in statement.playthrough_ids
    ]
    if len({run.player_game_id for run in runs}) != 1:
        raise CommandRejected(
            "A historical playtime statement names playthroughs of two games.",
            sentence=ONE_GAME,
        )
    for run in runs:
        if run.kind == PlaythroughKind.IMPORTED_HISTORY:
            raise CommandRejected(
                f"Playthrough {run.pk} is the imported-history bucket, which "
                "takes no stated playtime.",
                sentence=INTO_THE_BUCKET_HISTORICAL,
            )
    return runs


def _members(
    runs: Sequence[Playthrough], kept: dict[uuid.UUID, uuid.UUID]
) -> list[HistoricalPlaytimeRunPayload]:
    """A join id per run: the one it has, or a fresh one."""
    return [
        {"id": str(kept.get(run.pk, uuid.uuid7())), "playthrough": str(run.pk)}
        for run in runs
    ]


def library_record(context: CommandContext, record_id: uuid.UUID) -> HistoricalPlaytime:
    return library_row(
        context,
        HistoricalPlaytime.objects.select_related("player_game"),
        Refusal(
            message=f"This library holds no historical playtime record {record_id}.",
            sentence="That record is not available.",
        ),
        pk=record_id,
    )


def _live_record(context: CommandContext, record_id: uuid.UUID) -> HistoricalPlaytime:
    record = library_record(context, record_id)
    #: Under dispatch's lock: neither mark can move.
    if record.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind record {record_id}.",
            sentence="That game was removed from your library. Restore it before changing this.",
        )
    if record.removed_at is not None:
        raise CommandRejected(
            f"This library removed record {record_id}, so it states nothing further.",
            sentence="That record was removed. Restore it before changing it.",
        )
    return record


@dataclass(frozen=True, slots=True)
class RecordHistoricalPlaytime(Command):
    """State playtime the library did not track."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_RECORD
    statement: HistoricalPlaytimeStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized_statement(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        runs = _live_runs(context, self.statement)
        device = library_device(context, self.statement.device_id)
        return [
            historicalplaytime_created(
                player_game_id=runs[0].player_game_id,
                runs=_members(runs, {}),
                duration=self.statement.duration,
                when=TemporalValue.parse(self.statement.when),
                provenance=self.statement.provenance.value,
                device=None if device is None else capture_reference(device),
                emulated=self.statement.emulated,
                note=self.statement.note,
            )
        ]


@dataclass(frozen=True, slots=True)
class RestateHistoricalPlaytime(Command):
    """State the whole record again."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_RESTATE
    record_id: uuid.UUID
    statement: HistoricalPlaytimeStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized_statement(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        record = _live_record(context, self.record_id)
        runs = _live_runs(context, self.statement)
        device = library_device(context, self.statement.device_id)
        kept = dict(
            HistoricalPlaytimeRun.objects.filter(
                record=record, library=context.library
            ).values_list("playthrough_id", "id")
        )
        event = historicalplaytime_restated(
            record.pk,
            player_game_id=runs[0].player_game_id,
            runs=_members(runs, kept),
            duration=self.statement.duration,
            when=TemporalValue.parse(self.statement.when),
            provenance=self.statement.provenance.value,
            device=None if device is None else capture_reference(device),
            emulated=self.statement.emulated,
            note=self.statement.note,
        )
        #: The projector's mapping; never a copy of it.
        stated = columns_for_statement(event.payload, event.effective_time)
        held = {column: getattr(record, column) for column in stated}
        same_runs = set(kept) == {run.pk for run in runs}
        if stated == held and same_runs:
            return Unchanged("This record already states that.")
        return [event]


@dataclass(frozen=True, slots=True)
class RemoveHistoricalPlaytime(Command):
    """Take a record out of every total."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_REMOVE
    record_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        record = library_record(context, self.record_id)
        #: No-op first: a repeat succeeds regardless.
        if record.removed_at is not None:
            return Unchanged(f"This library already removed record {self.record_id}.")
        return [historicalplaytime_removed(record.pk)]


@dataclass(frozen=True, slots=True)
class RestoreHistoricalPlaytime(Command):
    """Put a removed record back."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_RESTORE
    record_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        record = library_record(context, self.record_id)
        if record.removed_at is None:
            return Unchanged(f"This library did not remove record {self.record_id}.")
        return [historicalplaytime_restored(record.pk)]
```

`HistoricalPlaytimeRun.objects.filter(record=…, library=context.library)` inside `Restate` is a read of a projection under dispatch's lock, as `_timed_start` reads the session row; it is not a `.get()`, so the scope guard admits it. `held["when"]` is the column's canonical text and `stated["when"]` the same, so the comparison holds without parsing. `held["provenance"]` is a plain string off the row and `stated["provenance"]` a `TextChoices` member; `str` enums compare equal to their value, so no coercion is needed.

If `HistoricalPlaytimeProvenance` fails to fingerprint (the encoder may not know a `TextChoices` member), carry `provenance` in the statement as its `str` value and construct the enum in `build`; `tests/test_event_idempotency.py` shows what the encoder knows.

- [ ] **Step 5: Run the tests**

`make test ARGS="tests/test_historical_playtime_command.py"`, then
`make test ARGS="tests/test_command_scope_guard.py tests/test_command_answers.py tests/test_command_dispatch.py tests/test_playersession_command.py"`.

- [ ] **Step 6: Commit**

```bash
git add games/commands/historical_playtime.py games/commands/scope.py games/commands/playersession.py games/events/dispatch.py tests/test_historical_playtime_command.py tests/test_playersession_command.py
git commit -m "feat: state, restate, remove and restore historical playtime"
```

---

### Task 5: A record keeps its run in place

**Files:**
- Modify: `games/commands/playthrough.py:520-529` (`BLOCKING_REFERRERS`)
- Test: `tests/test_historical_playtime_command.py` (append)

**Interfaces consumed:** Task 1's `HistoricalPlaytimeRun`; `BlockingReferrer`, `RemovePlaythrough` from `games/commands/playthrough.py`.

**Interfaces produced:** the second `BLOCKING_REFERRERS` entry and its sentence, `HISTORICAL_PLAYTIME_RECORDED`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_historical_playtime_command.py`:

```python
from games.commands.playthrough import HISTORICAL_PLAYTIME_RECORDED, RemovePlaythrough


def test_a_live_record_keeps_its_run_in_place(
    owned_user, owned_library, run, second_run
):
    record(owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,)))
    refused = _refused(
        owned_library, owned_user, RemovePlaythrough(playthrough_id=second_run.pk)
    )
    assert refused.sentence == HISTORICAL_PLAYTIME_RECORDED


def test_a_removed_record_keeps_nothing_in_place(
    owned_user, owned_library, run, second_run
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,))
    )
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    dispatch(
        RemovePlaythrough(playthrough_id=second_run.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm-run",
    )
    second_run.refresh_from_db()
    assert second_run.removed_at is not None


def test_a_restated_away_record_keeps_nothing_in_place(
    owned_user, owned_library, run, second_run
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,))
    )
    dispatch(
        RestateHistoricalPlaytime(record_id=stored.pk, statement=stated(run)),
        actor=owned_user,
        library=owned_library,
        idempotency_key="move",
    )
    dispatch(
        RemovePlaythrough(playthrough_id=second_run.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm-run",
    )
    second_run.refresh_from_db()
    assert second_run.removed_at is not None


def test_a_foreign_record_is_refused_as_a_defect(
    owned_user, owned_library, run, second_run, second_library
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,))
    )
    HistoricalPlaytime.objects.filter(pk=stored.pk).update(library=second_library)
    HistoricalPlaytimeRun.objects.filter(record=stored).update(library=second_library)
    with pytest.raises(CommandRejected) as refused:
        dispatch(
            RemovePlaythrough(playthrough_id=second_run.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="rm-run",
        )
    assert str(second_library.pk) in str(refused.value)
```

Read `tests/test_playthrough_command.py::test_a_foreign_referring_row_is_refused_as_a_defect` (line 2062) for the exact assertion on a foreign referrer and match it.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_historical_playtime_command.py -k 'in_place or foreign_record' -x"` → the removal is admitted, or ImportError on the sentence.

- [ ] **Step 3: Register the referrer**

In `games/commands/playthrough.py`, beside the session entry:

```python
HISTORICAL_PLAYTIME_RECORDED = (
    "Historical playtime is recorded on this playthrough. Restate it onto "
    "another playthrough, or remove it, before removing this one."
)

BLOCKING_REFERRERS: tuple[BlockingReferrer, ...] = (
    BlockingReferrer.on(PlayerSession, "playthrough", sentence=...),  # as today
    BlockingReferrer.on(
        HistoricalPlaytimeRun,
        "playthrough",
        sentence=HISTORICAL_PLAYTIME_RECORDED,
    ),
)
```

Import `HistoricalPlaytimeRun` from `games.models`. `on()` checks the manager states `alive()` at import; Task 1's queryset does.

- [ ] **Step 4: Run the tests**

`make test ARGS="tests/test_historical_playtime_command.py tests/test_playthrough_command.py"`.

- [ ] **Step 5: Commit**

```bash
git add games/commands/playthrough.py tests/test_historical_playtime_command.py
git commit -m "feat: a historical playtime record keeps its run in place"
```

---

### Task 6: The replay gate has a record in every leg

**Files:**
- Modify: `tests/test_projection_replay_gate.py`

**Interfaces consumed:** Task 4's commands, Task 3's projector.

- [ ] **Step 1: Read the gate**

Read `tests/test_projection_replay_gate.py` whole. `build_stream` (line 91) dispatches every command through `run(command, key)`; `registered_event_types` (line 313) walks the three projectors' `handles`; `rows_of` (line 410) snapshots three tables; `build_neighbour` (line 363) gives a second library its own rows.

- [ ] **Step 2: Extend the stream**

In `build_stream`, after the session commands, add four dispatches: a record naming two runs of one game, a restatement onto one run, a second record removed, a third removed and restored. Use `HistoricalPlaytimeStatement` from Task 4 with the run ids the stream already created. In `build_neighbour`, add one record so the neighbour's tables are non-empty.

- [ ] **Step 3: Extend the coverage guard and the snapshots**

Add `HistoricalPlaytimes.handles` to the `for handles in (...)` in `registered_event_types`. Add both tables to `rows_of` and to whatever tuple type it returns, and to `empty_projections`; the assertion helpers compare the tuple, so widen the type alias they share.

- [ ] **Step 4: Run the gate**

`make test ARGS="tests/test_projection_replay_gate.py"`. `test_the_stream_carries_every_registered_event_type` fails until all four new types are dispatched; `test_a_rebuild_swaps_every_table_with_an_empty_diff` fails if a join id is minted twice.

- [ ] **Step 5: Commit**

```bash
git add tests/test_projection_replay_gate.py
git commit -m "test: replay a historical playtime record in every leg"
```

---

### Task 7: Documentation and the gate

**Files:**
- Modify: `CLAUDE.md` (the Models list, after the `PlayerSession` entry at line 257)
- Test: the whole suite

- [ ] **Step 1: Document the model**

Add a `HistoricalPlaytime` entry to `CLAUDE.md`'s Models section in the voice of the entries around it: the fourth projection, playtime stated without sittings, whole-statement events, `when` on the envelope with generated bounds, one or more runs of one game through `HistoricalPlaytimeRun` whose ids the payload carries, three provenances, `alive()`'s one ancestor mark and the join's derived one, and that the database admits a superset of what the command admits. Name the spec.

- [ ] **Step 2: Run the prose linter**

`make vale`.

- [ ] **Step 3: Run the full gate**

`make check` — lint, format check, mypy, vale, ts-check, vitest, and the entire pytest suite including `e2e/`. Never a hand-picked subset. Do not run it while `make dev` is up.

- [ ] **Step 4: Verify the replay parity target**

`make verify-replay-parity` — read-only, replays every library and fails on a differing row.

- [ ] **Step 5: Commit and open the PR**

```bash
git add CLAUDE.md
git commit -m "docs: name what a HistoricalPlaytime record holds"
```

Open the PR against `main` with `gh pr create`, naming #705 and the spec. Merge with `gh pr merge --merge` — never squash, never rebase.

---

## Follow-up notes

- #706 posts a `HistoricalPlaytimeStatement` from its form and offers `ESTIMATED` and `MANUALLY_ENTERED` only.
- #709 reads `when_lower`/`when_upper` and the `historicalplaytime_when_order` index.
- #1098 appends `created` from a session's columns beside `library.playersession.reclassified`; `RestoreSession`'s refusal lives there.
- `library_device` in `scope.py` is now the one device resolver; #1098's reclassification uses it too.
