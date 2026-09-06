# Playthrough endpoints (#681) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A library can state that a Playthrough started and that it completed, each with an optional date at any precision and an optional note, and the pair that cannot be true is refused.

**Architecture:** Two event types, two commands and two projector handlers, over four new columns on the `Playthrough` projection. Each endpoint keeps its stated date in the `TemporalValueField` #679 shipped, and gains a marker column holding the event's `recorded_at` — the marker's null is the act that never happened, which is what a null date cannot say. Nothing renders, nothing corrects, nothing removes.

**Tech Stack:** Django 6 / Python 3.14, PostgreSQL 18, pytest + pytest-xdist, the in-repo event vocabulary (`games/events/`), `timetracker/temporal.py`.

**Spec:** `docs/superpowers/specs/2026-09-06-issue-681-playthrough-endpoints-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `uv run`, `pytest`, `pnpm` or `direnv exec .` directly. Focused runs: `make test ARGS="tests/test_x.py -k name"`.
- **Verification gate is the full `make check`**, and `make check-fast` while iterating. The gate runs `check-migrations`, so a generated migration must leave no drift.
- **Never write to a `GeneratedField`.** On this model: `started_lower`, `started_upper`, `completed_lower`, `completed_upper`.
- **Nothing destroys a record.** No `.delete()` in application code.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest, so a test that dispatches carries `@pytest.mark.django_db(transaction=True)`.
- **A rejection carries two sentences:** `raise CommandRejected(message, sentence=…)`. The first argument may name an id or an issue; `sentence` is the only thing a person is shown.
- **Name variables with complete words** — `event` not `e`, `value` not `v`.
- **Refused words are enforced** by `make vale` over docs *and code comments*: a projector *replays* events and writes a *projection*. See `docs/vocabulary.md`.
- **Comments are `#:` prefixed** in this codebase, short, and say why rather than what.
- **A commit message is normal prose**, and ends with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **The plan document itself is deleted in Task 6**, before the final `make check`.

---

### Task 1: The four endpoint columns

The marker columns are the point of the issue: `TemporalValue.unknown()` serializes to `None`, so the date column reads NULL both for "started on an unknown day" and for "never started". The note columns hold the note the Player Journal renders on the day of the fact.

**Files:**
- Modify: `games/models.py:1639-1673` (the `Playthrough` endpoint block)
- Create: `games/migrations/0044_playthrough_endpoint_columns.py` (generated, then formatted)
- Test: `tests/test_playthrough_projection.py`
- Test: `tests/test_projection_model.py:252-258` (`PINNED_DEFAULTS["games.Playthrough"]`)

**Interfaces:**
- Consumes: nothing.
- Produces: `Playthrough.start_recorded_at`, `Playthrough.completion_recorded_at` (`DateTimeField(null=True, default=None, editable=False)`); `Playthrough.start_note`, `Playthrough.completion_note` (`TextField(blank=True, default="")`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_playthrough_projection.py`, directly below `test_a_playthrough_starts_with_no_endpoints`:

```python
def test_a_playthrough_starts_with_neither_act_recorded():
    """The marker's null is the act that never happened.

    A null date cannot say it: `TemporalValue.unknown()` serializes to
    None, so the date column reads the same for an unknown day.
    """
    row = Playthrough()

    assert row.start_recorded_at is None
    assert row.completion_recorded_at is None


def test_a_playthrough_starts_with_no_endpoint_notes():
    row = Playthrough()

    assert (row.start_note, row.completion_note) == ("", "")


def test_the_endpoint_columns_are_exempt_from_the_required_ones():
    """The creation handler names none of them, and must not.

    Each carries a default, so `_required_columns` exempts it and the
    handler #679 wrote stays as it is.
    """
    required = {name for name, _ in _required_columns(Playthrough)}

    assert required.isdisjoint(
        {
            "started",
            "completed",
            "start_recorded_at",
            "completion_recorded_at",
            "start_note",
            "completion_note",
        }
    )
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_projection.py -k 'recorded or endpoint_notes or exempt' -p no:randomly"
```

Expected: `AttributeError: 'Playthrough' object has no attribute 'start_recorded_at'`.

- [ ] **Step 3: Add the columns**

In `games/models.py`, the `Playthrough` block currently reads `#: #681 states both endpoints.` above `started`. Replace that comment and insert the four columns so each endpoint's three columns sit together — `started`, its two generated bounds, then the marker and the note; then the same for `completed`.

Insert after `started_upper` (before `completed`):

```text
    #: Null is the act that never happened. The date cannot say it: an
    #: unknown day serializes to null too.
    start_recorded_at = models.DateTimeField(null=True, default=None, editable=False)
    #: The note of the act, which the Journal dates. The row's `note`
    #: describes the run and belongs to no day.
    start_note = models.TextField(blank=True, default="")
```

Insert after `completed_upper` (before `created_at`):

```text
    completion_recorded_at = models.DateTimeField(
        null=True, default=None, editable=False
    )
    completion_note = models.TextField(blank=True, default="")
```

Change the comment above `started` from `#: #681 states both endpoints.` to:

```text
    #: The stated date; null is a day nobody knows.
```

- [ ] **Step 4: Generate the migration and format it**

```
make makemigrations ARGS="games --name playthrough_endpoint_columns"
make format
```

Expected: four `AddField` operations and nothing else. `make format` is not optional — Django writes single quotes, ruff wants double, and `make check` runs `format-check`.

Read the generated file and confirm it touches no `GeneratedField` and drops no index.

- [ ] **Step 5: Pin the new defaults**

`tests/test_projection_model.py::test_every_projection_default_is_pinned` compares every defaulted column on every projection against a hand-maintained dict, and nothing else points at it. Replace the `"games.Playthrough"` entry:

```python
PLAYTHROUGH_DEFAULTS = {
    "name": "",
    "note": "",
    "started": None,
    "start_recorded_at": None,
    "start_note": "",
    "completed": None,
    "completion_recorded_at": None,
    "completion_note": "",
    "removed_at": None,
}
```

Do not add the constant above — that block is the literal shape the dict entry takes. Edit `PINNED_DEFAULTS["games.Playthrough"]` in place to hold those nine keys, keeping the `#: No kind: the creation event states it.` comment above it.

- [ ] **Step 6: Run the tests and the drift guard**

```
make test ARGS="tests/test_playthrough_projection.py tests/test_projection_model.py"
make check-migrations
```

Expected: green, and `No changes detected`.

- [ ] **Step 7: Commit**

```bash
git add games/models.py games/migrations/0044_playthrough_endpoint_columns.py tests/test_playthrough_projection.py tests/test_projection_model.py
git commit -m "$(cat <<'EOF'
Give a Playthrough endpoint a marker and a note

A null date says two things at once: the day is unknown, and the act
never happened. `TemporalValue.unknown()` serializes to null, so the
column #679 shipped cannot tell them apart, and "played before" is the
plainest thing #681 has to record.

The marker holds the event's recorded_at, so its null is the act. The
note is the note of the act, which the Journal places on the day the
act names; the row's own note describes the run and belongs to no day.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The two event types and their builders

**Files:**
- Modify: `games/events/playthrough.py`
- Test: `tests/test_playthrough_events.py`

**Interfaces:**
- Consumes: Task 1's columns (not directly — this task writes no row).
- Produces:
  - `PlaythroughEndpointPayload` (`TypedDict` with `note: str`, under `STRICT_SCHEMA`)
  - `PLAYTHROUGH_STARTED` / `PLAYTHROUGH_COMPLETED` (`EventSpec`, aggregate type `"playthrough"`, registered in `DEFAULT_EVENT_TYPES`)
  - `playthrough_started(playthrough_id: uuid.UUID, *, when: TemporalValue | None, note: str) -> NewEvent`
  - `playthrough_completed(playthrough_id: uuid.UUID, *, when: TemporalValue | None, note: str) -> NewEvent`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_events.py`. Note the import line at the top of the file grows to include the four new names, and `TemporalValue` comes from `timetracker.temporal`.

```python
def test_the_endpoint_events_are_in_the_default_vocabulary():
    started = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.started")
    completed = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.completed")

    assert (started, completed) == (PLAYTHROUGH_STARTED, PLAYTHROUGH_COMPLETED)
    assert started.aggregate_type == "playthrough"
    assert completed.aggregate_type == "playthrough"


def test_an_endpoint_payload_carries_a_note_and_nothing_else():
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYTHROUGH_STARTED.event_type, {"note": "blind run"}
    )

    assert validated == {"note": "blind run"}


def test_an_endpoint_payload_takes_the_empty_note():
    """No note is the empty string, never an absent key."""
    assert DEFAULT_EVENT_TYPES.validate(
        PLAYTHROUGH_COMPLETED.event_type, {"note": ""}
    ) == {"note": ""}


def test_an_endpoint_payload_refuses_a_missing_note():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYTHROUGH_STARTED.event_type, {})


def test_an_endpoint_payload_refuses_a_date_of_its_own():
    """The date rides in effective_time, and has one home."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_STARTED.event_type, {"note": "", "when": "2024-03"}
        )


def test_the_builders_name_the_playthrough_they_are_told_about():
    """The aggregate exists, so nothing mints an identity here."""
    identity = uuid.uuid7()
    when = TemporalValue.from_month(2024, 3)

    started = playthrough_started(identity, when=when, note="blind run")
    completed = playthrough_completed(identity, when=None, note="")

    assert (started.aggregate_id, completed.aggregate_id) == (identity, identity)
    assert (started.effective_time, completed.effective_time) == (when, None)
    assert (started.payload, completed.payload) == ({"note": "blind run"}, {"note": ""})
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_events.py"
```

Expected: `ImportError` on `PLAYTHROUGH_STARTED`.

- [ ] **Step 3: Write the specs and the builders**

Append to `games/events/playthrough.py`. `TemporalValue` and `date` are new imports there; `EventSpec`, `NewEvent`, `DEFAULT_EVENT_TYPES` and `STRICT_SCHEMA` are already imported.

```python
@with_config(STRICT_SCHEMA)
class PlaythroughEndpointPayload(TypedDict):
    """The note of one endpoint, and only that.

    The date is `effective_time`, which is where the charter puts what a
    player says happened, and giving it a second home would give every
    later reader a second code path. No note is the empty string: an
    optional key would make a reader ask whether a value is absent or
    empty, and here the two mean one thing.

    One type for both specs. They are two EventSpecs, so an issue that
    gives one of them a field of its own gives it a type of its own.
    """

    note: str


PLAYTHROUGH_STARTED = EventSpec(
    "library.playthrough.started",
    aggregate_type="playthrough",
    payload=PlaythroughEndpointPayload,
)

PLAYTHROUGH_COMPLETED = EventSpec(
    "library.playthrough.completed",
    aggregate_type="playthrough",
    payload=PlaythroughEndpointPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_STARTED)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_COMPLETED)


def playthrough_started(
    playthrough_id: uuid.UUID,
    *,
    when: TemporalValue | None,
    note: str,
) -> NewEvent:
    """The run began, on the day stated or on none."""
    #: The aggregate exists, so the id is given rather than minted.
    return PLAYTHROUGH_STARTED.new(
        aggregate_id=playthrough_id,
        effective_time=when,
        payload={"note": note},
    )


def playthrough_completed(
    playthrough_id: uuid.UUID,
    *,
    when: TemporalValue | None,
    note: str,
) -> NewEvent:
    """The run met its main objective."""
    return PLAYTHROUGH_COMPLETED.new(
        aggregate_id=playthrough_id,
        effective_time=when,
        payload={"note": note},
    )
```

- [ ] **Step 4: Run the tests**

```
make test ARGS="tests/test_playthrough_events.py tests/test_event_wiring.py"
```

Expected: green. `test_event_wiring.py` guards that a projector claims no unregistered type; it does not guard the other direction, which is why Task 5 exists and why its tests read a row back rather than asserting registration.

- [ ] **Step 5: Commit**

```bash
git add games/events/playthrough.py tests/test_playthrough_events.py
git commit -m "$(cat <<'EOF'
Record that a run started and that it completed

Two event types, one payload. The date rides in effective_time, which
is where the charter puts what a player says happened; a date in the
payload would give one value two homes.

The builders take the playthrough's id rather than minting one. The
aggregate already exists, which is the whole difference from the
creation event beside them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The order rule

A pure function, tested as one, because #1010 corrects an endpoint and calls the same rule. It refuses only the certainly-impossible: three guards stand in front of the comparison, and without them a bare `<` raises `TypeError` on five reachable pairs.

**Files:**
- Modify: `games/commands/playthrough.py`
- Test: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `endpoints_certainly_reversed(started: TemporalValue | None, completed: TemporalValue | None) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_command.py`. The table is the test: every row is a pair the rule has to answer, and the crashing inputs are in it on purpose.

```python
@pytest.mark.parametrize(
    ("started", "completed", "reversed_pair"),
    [
        #: Certainly reversed, at every precision.
        ("2024-03-20", "2024-03-10", True),
        ("2024-05", "2024-03", True),
        ("202X", "2019", True),
        ("2024-06/2024-12", "2024-01", True),
        #: Consistent, or imprecise enough to be.
        ("2024-03-10", "2024-03", False),
        ("2024-03-10", "2024-03-10", False),
        ("2024-03", "2024-03-10", False),
        ("2019", "202X", False),
        #: No bound on one side: nothing to prove.
        (None, "2024-03", False),
        ("2024-05", None, False),
        (None, None, False),
        #: A dated endpoint with no bound: an open-ended range.
        ("../2024-06", "2020", False),
        ("2024-05", "2024-01/", False),
        #: A qualifier states no certainty to contradict.
        ("2024-05~", "2024-03", False),
        ("2024-05?", "2024-03", False),
        ("2024-05-10~", "2024-05-09", False),
        ("2024-05", "2024-03~", False),
    ],
)
def test_the_order_rule_refuses_only_the_certainly_impossible(
    started, completed, reversed_pair
):
    """A bare comparison raises TypeError on five of these rows."""
    assert (
        endpoints_certainly_reversed(
            None if started is None else TemporalValue(started),
            None if completed is None else TemporalValue(completed),
        )
        is reversed_pair
    )
```

- [ ] **Step 2: Run it and watch it fail**

```
make test ARGS="tests/test_playthrough_command.py -k order_rule"
```

Expected: `ImportError` on `endpoints_certainly_reversed`.

- [ ] **Step 3: Write the rule**

Add to `games/commands/playthrough.py`, above `CreatePlaythrough`. `TemporalValue` is a new import from `timetracker.temporal`.

```python
def endpoints_certainly_reversed(
    started: TemporalValue | None, completed: TemporalValue | None
) -> bool:
    """Whether a completion cannot follow its start.

    Only the certainly-impossible. Each guard drops a pair the
    comparison cannot judge, and the last two are why a bare `<` is
    wrong rather than merely incomplete:

    A bound is unknown for two reasons. The endpoint carries no date, or
    it is an open-ended range -- `../2024-06` bounds nothing below and
    `2024-01/` nothing above -- and a window with no edge contradicts
    nothing.

    A qualifier leaves the bounds where the bare value put them, so
    `2024-05-10~` bounds to that day exactly. Refusing a completion on
    the 9th would refuse what `~` was written to say.
    """
    if started is None or completed is None:
        return False
    if started.qualifier is not None or completed.qualifier is not None:
        return False
    if started.lower_bound is None or completed.upper_bound is None:
        return False
    return completed.upper_bound < started.lower_bound
```

- [ ] **Step 4: Run the test**

```
make test ARGS="tests/test_playthrough_command.py -k order_rule"
```

Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add games/commands/playthrough.py tests/test_playthrough_command.py
git commit -m "$(cat <<'EOF'
Refuse a completion that cannot follow its start

The rule refuses only what cannot be true, so each guard in front of
the comparison drops a pair nothing can judge.

Two of them are corrections rather than omissions. A dated endpoint can
have no bound, because an open-ended range is grammar a person can
state, and the comparison raises rather than passing there. And a
qualifier leaves the bounds where the bare value put them, so "started
about 10 May, completed 9 May" was refused -- which is the one thing
the tilde was written to prevent.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The two commands and the resolver

**Files:**
- Modify: `games/events/dispatch.py:89` (two `CommandName` members)
- Modify: `games/commands/playthrough.py`
- Test: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: `playthrough_started` / `playthrough_completed` (Task 2), `endpoints_certainly_reversed` (Task 3).
- Produces:
  - `CommandName.PLAYTHROUGH_START = "library.playthrough.start"`, `CommandName.PLAYTHROUGH_COMPLETE = "library.playthrough.complete"`
  - `StartPlaythrough(playthrough_id: uuid.UUID, when: TemporalValue | None, note: str)`
  - `CompletePlaythrough(playthrough_id: uuid.UUID, when: TemporalValue | None, note: str)`
  - `library_playthrough(context: CommandContext, playthrough_id: uuid.UUID) -> Playthrough`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_command.py`. `_track` and the `game` fixture already exist in that file; add a helper that creates a second library's row where needed.

```python
def _start(owned_user, owned_library, playthrough, *, when, note="", key="start"):
    return dispatch(
        StartPlaythrough(playthrough_id=playthrough.pk, when=when, note=note),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_stating_a_start_records_the_date_as_the_effective_time(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()

    result = _start(
        owned_user, owned_library, playthrough, when=TemporalValue.from_month(2024, 3)
    )

    assert result.outcome is CommandOutcome.APPENDED
    event = LibraryEvent.objects.get(event_type="library.playthrough.started")
    assert event.aggregate_id == playthrough.pk
    assert event.effective_time == TemporalValue.from_month(2024, 3)
    assert event.payload == {"note": ""}


@pytest.mark.django_db(transaction=True)
def test_played_before_records_the_act_with_no_date(owned_user, owned_library, game):
    """The headline case: a run happened, and nobody knows when.

    Nothing here is distinguishable by value from a row that never
    started, so a build comparing values would record nothing at all.
    """
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()

    result = _start(owned_user, owned_library, playthrough, when=None)

    assert result.outcome is CommandOutcome.APPENDED
    event = LibraryEvent.objects.get(event_type="library.playthrough.started")
    assert event.effective_time is None


@pytest.mark.django_db(transaction=True)
def test_restating_one_start_exactly_changes_nothing(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    when = TemporalValue.from_day(date(2024, 3, 10))
    _start(owned_user, owned_library, playthrough, when=when, note="blind")

    result = _start(
        owned_user, owned_library, playthrough, when=when, note="blind", key="again"
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.started").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restating_a_start_with_another_date_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(owned_user, owned_library, playthrough, when=TemporalValue.from_year(2024))

    with pytest.raises(CommandRejected) as refusal:
        _start(
            owned_user,
            owned_library,
            playthrough,
            when=TemporalValue.from_year(2025),
            key="moved",
        )

    assert "correct" in refusal.value.sentence.lower()


@pytest.mark.django_db(transaction=True)
def test_restating_a_start_with_another_note_is_refused(
    owned_user, owned_library, game
):
    """The endpoint is the pair, so its note is not a free field."""
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(owned_user, owned_library, playthrough, when=None, note="blind")

    with pytest.raises(CommandRejected):
        _start(owned_user, owned_library, playthrough, when=None, note="", key="wiped")


@pytest.mark.django_db(transaction=True)
def test_a_completion_before_the_start_is_refused(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(
        owned_user, owned_library, playthrough, when=TemporalValue.from_month(2024, 5)
    )

    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            CompletePlaythrough(
                playthrough_id=playthrough.pk,
                when=TemporalValue.from_month(2024, 3),
                note="",
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="reversed",
        )

    assert "before" in refusal.value.sentence.lower()
    assert not LibraryEvent.objects.filter(
        event_type="library.playthrough.completed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_a_start_after_the_completion_is_refused_the_same_way(
    owned_user, owned_library, game
):
    """One rule, whichever endpoint is stated second."""
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    dispatch(
        CompletePlaythrough(
            playthrough_id=playthrough.pk,
            when=TemporalValue.from_month(2024, 3),
            note="",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="done",
    )

    with pytest.raises(CommandRejected):
        _start(
            owned_user,
            owned_library,
            playthrough,
            when=TemporalValue.from_month(2024, 5),
            key="late",
        )


@pytest.mark.django_db(transaction=True)
def test_stating_an_endpoint_of_another_library_is_refused(
    owned_user, owned_library, game, other_library
):
    """A refusal names no id, and leaks no row."""
    elsewhere = Game.objects.create(library=other_library, name="Tunic")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=other_library,
        game=elsewhere,
        tracked_at=timezone.now(),
    )
    hidden = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=other_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(CommandRejected) as refusal:
        _start(owned_user, owned_library, hidden, when=None, key="foreign")

    assert str(hidden.pk) not in refusal.value.sentence


@pytest.mark.django_db(transaction=True)
def test_stating_an_endpoint_for_a_removed_game_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _start(owned_user, owned_library, playthrough, when=None, key="removed")

    assert "Restore it" in refusal.value.sentence


@pytest.mark.django_db(transaction=True)
def test_stating_an_endpoint_for_a_removed_playthrough_is_refused(
    owned_user, owned_library, game
):
    """Inert until #1011 stamps the column, and written here.

    The resolver both commands share is written here, so its answers are
    tested here.
    """
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    Playthrough.objects.filter(pk=playthrough.pk).update(
        removed_at=playthrough.created_at
    )

    with pytest.raises(CommandRejected):
        _start(owned_user, owned_library, playthrough, when=None, key="gone")
```

Check `tests/conftest.py` for the fixture that provides a second library before writing `other_library`; if it has another name, use that name. If none exists, build the library inline in that one test with the same shape as `owned_library`.

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_command.py"
```

Expected: `ImportError` on `StartPlaythrough`.

- [ ] **Step 3: Name the commands**

In `games/events/dispatch.py`, add two members to `CommandName`, below `PLAYTHROUGH_CREATE`:

```text
    PLAYTHROUGH_START = "library.playthrough.start"
    PLAYTHROUGH_COMPLETE = "library.playthrough.complete"
```

- [ ] **Step 4: Write the resolver and the shared refusals**

Add to `games/commands/playthrough.py`, below `endpoints_certainly_reversed`.

```python
def library_playthrough(
    context: CommandContext, playthrough_id: uuid.UUID
) -> Playthrough:
    """The run inside this library, or a refusal that names none.

    A row of another library and a row that does not exist answer alike:
    a refusal is not a place to learn an id. The third library-scoped
    resolver, beside `tracked_game` and `TrackGame._visible_game`, and
    the third caller #909 merges.
    """
    try:
        return Playthrough.objects.select_related("player_game").get(
            library=context.library, pk=playthrough_id
        )
    except Playthrough.DoesNotExist:
        raise CommandRejected(
            f"This library holds no playthrough {playthrough_id}. A stated "
            "endpoint belongs to a run the library records.",
            sentence="That playthrough is not available.",
        ) from None


def _endpoint_subject(
    context: CommandContext, playthrough_id: uuid.UUID
) -> Playthrough:
    """The run, refused if nothing may be stated about it."""
    run = library_playthrough(context, playthrough_id)
    #: Under dispatch's lock: neither mark can move.
    if run.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind playthrough {playthrough_id}, "
            "so it states no further facts about its runs.",
            sentence=(
                "That game was removed from your library. Restore it before "
                "recording this."
            ),
        )
    if run.removed_at is not None:
        raise CommandRejected(
            f"This library removed playthrough {playthrough_id}, so it states "
            "no further facts about it.",
            sentence=(
                "That playthrough was removed from your library. Restore it "
                "before recording this."
            ),
        )
    return run
```

- [ ] **Step 5: Write the two commands**

Append to `games/commands/playthrough.py`.

```python
@dataclass(frozen=True, slots=True)
class StartPlaythrough(Command):
    """State that a run began."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_START
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    #: None is "played before": the act, and no day.
    when: TemporalValue | None
    #: No default. The build compares the whole endpoint, so a caller
    #: who omitted this would be refused for changing it.
    note: str

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _endpoint_subject(context, self.playthrough_id)
        #: The marker, never the date: a null date is also an unknown day.
        if run.start_recorded_at is not None:
            if (self.when, self.note) == (run.started, run.start_note):
                return Unchanged("This run already started on that day.")
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} already states a start, and "
                "a second one would say the run began twice. #1010 corrects a "
                "stated endpoint.",
                sentence=(
                    "This run already has a start. Correct the one it has "
                    "instead of adding another."
                ),
            )
        if endpoints_certainly_reversed(self.when, run.completed):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} completed before the start "
                "being stated, and no run ends before it begins.",
                sentence="This run finished before that date. Check the day.",
            )
        return [
            playthrough_started(run.pk, when=self.when, note=self.note),
        ]


@dataclass(frozen=True, slots=True)
class CompletePlaythrough(Command):
    """State that a run met its main objective."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_COMPLETE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    when: TemporalValue | None
    note: str

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _endpoint_subject(context, self.playthrough_id)
        if run.completion_recorded_at is not None:
            if (self.when, self.note) == (run.completed, run.completion_note):
                return Unchanged("This run already completed on that day.")
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} already states a completion, "
                "and a second one would say the run ended twice. #1010 corrects "
                "a stated endpoint.",
                sentence=(
                    "This run already has a completion. Correct the one it has "
                    "instead of adding another."
                ),
            )
        if endpoints_certainly_reversed(run.started, self.when):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} started after the completion "
                "being stated, and no run ends before it begins.",
                sentence="This run started after that date. Check the day.",
            )
        return [
            playthrough_completed(run.pk, when=self.when, note=self.note),
        ]
```

- [ ] **Step 6: Run the tests**

```
make test ARGS="tests/test_playthrough_command.py tests/test_command_dispatch.py"
```

Expected: green. The commands append events; no row changes yet, because Task 5 wires the handlers.

- [ ] **Step 7: Commit**

```bash
git add games/commands/playthrough.py games/events/dispatch.py tests/test_playthrough_command.py
git commit -m "$(cat <<'EOF'
State a Playthrough start and a Playthrough completion

Both commands resolve the run the same way and answer the same list, so
the resolver and the refusals are shared and the two builds differ only
in the endpoint they read.

The marker decides whether an endpoint is stated. Reading the date
instead would make "played before" -- no day, no note -- compare equal
to a run that never started, and record nothing at all. Only a stated
endpoint compares, and it compares as a pair: a note is part of the
endpoint rather than a field beside it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The projector handlers

**Files:**
- Modify: `games/projectors/playthrough.py`
- Test: `tests/test_playthrough_projection.py`

**Interfaces:**
- Consumes: `PLAYTHROUGH_STARTED` / `PLAYTHROUGH_COMPLETED` (Task 2), the four columns (Task 1), both commands (Task 4).
- Produces: `Playthroughs._started`, `Playthroughs._completed`, both registered in `handles`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_projection.py`. `track` and the `tracked` fixture already exist there.

```python
@pytest.mark.django_db(transaction=True)
def test_a_started_event_writes_the_date_the_marker_and_the_note(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    dispatch(
        StartPlaythrough(
            playthrough_id=run.pk,
            when=TemporalValue.from_month(2024, 3),
            note="blind run",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="start",
    )

    row = Playthrough.objects.get()
    event = LibraryEvent.objects.get(event_type="library.playthrough.started")
    assert row.started == TemporalValue.from_month(2024, 3)
    assert row.start_recorded_at == event.recorded_at
    assert row.start_note == "blind run"
    #: The other endpoint is untouched: two handlers read alike.
    assert (row.completed, row.completion_recorded_at, row.completion_note) == (
        None,
        None,
        "",
    )


@pytest.mark.django_db(transaction=True)
def test_played_before_reads_back_as_an_act_with_no_day(owned_user, owned_library):
    """The marker carries the act; the date carries nothing."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    dispatch(
        StartPlaythrough(playthrough_id=run.pk, when=None, note=""),
        actor=owned_user,
        library=owned_library,
        idempotency_key="start",
    )

    row = Playthrough.objects.get()
    assert row.started is None
    assert row.start_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_a_completed_event_leaves_the_start_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    dispatch(
        StartPlaythrough(
            playthrough_id=run.pk, when=TemporalValue.from_month(2024, 3), note="blind"
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="start",
    )

    dispatch(
        CompletePlaythrough(
            playthrough_id=run.pk,
            when=TemporalValue.from_day(date(2024, 4, 2)),
            note="hard mode",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="done",
    )

    row = Playthrough.objects.get()
    assert (row.started, row.start_note) == (TemporalValue.from_month(2024, 3), "blind")
    assert row.completed == TemporalValue.from_day(date(2024, 4, 2))
    assert row.completion_note == "hard mode"
    assert row.completion_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_an_empty_database_replay_reproduces_both_endpoints(owned_user, owned_library):
    """Every written value comes off the event, so a replay agrees."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    for command, key in (
        (
            StartPlaythrough(
                playthrough_id=run.pk, when=TemporalValue.from_month(2024, 3), note="a"
            ),
            "start",
        ),
        (
            CompletePlaythrough(playthrough_id=run.pk, when=None, note="b"),
            "done",
        ),
    ):
        dispatch(command, actor=owned_user, library=owned_library, idempotency_key=key)
    before = list(Playthrough.objects.order_by("pk").values())
    #: The child first: player_game RESTRICTs.
    Playthrough.objects.all().delete()
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert list(Playthrough.objects.order_by("pk").values()) == before


@pytest.mark.django_db(transaction=True)
def test_re_applying_the_creation_event_leaves_an_endpoint_alone(
    owned_user, owned_library, tracked
):
    """A creation event may not take an endpoint back out."""
    appended = append_playthrough_created(owned_library, owned_user, tracked)
    identity = appended.events[0].aggregate_id
    recorded = timezone.now()
    Playthrough.objects.filter(pk=identity).update(
        started=TemporalValue.from_year(2024),
        start_recorded_at=recorded,
        start_note="blind",
    )

    reapply_creation(identity)

    row = Playthrough.objects.get()
    assert (row.started, row.start_recorded_at, row.start_note) == (
        TemporalValue.from_year(2024),
        recorded,
        "blind",
    )
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_projection.py -k 'started or completed or played_before or endpoints'"
```

Expected: the row reads back with a null marker — the events append, and nothing projects them.

- [ ] **Step 3: Write the handlers**

In `games/projectors/playthrough.py`, add both handlers and extend `handles`. The existing comment block above `handles` says #681's handlers amend rather than project; keep it, and let the new entries sit beside `PLAYTHROUGH_CREATED`.

```python
class Playthroughs(Projector):
    """One row per run at a game."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _started(self, event: RecordedEvent) -> None:
        #: Every value off the event, so a replay agrees.
        self.amend(
            Playthrough,
            event.aggregate_id,
            started=event.effective_time,
            start_recorded_at=event.recorded_at,
            start_note=event.payload["note"],
        )

    def _completed(self, event: RecordedEvent) -> None:
        self.amend(
            Playthrough,
            event.aggregate_id,
            completed=event.effective_time,
            completion_recorded_at=event.recorded_at,
            completion_note=event.payload["note"],
        )
```

Do not paste the class above over the file: it omits `_created` and `handles`. Add the two methods below `_created`, then extend the mapping:

```text
    handles: ClassVar[HandlerMap] = {
        PLAYTHROUGH_CREATED: _created,
        PLAYTHROUGH_STARTED: _started,
        PLAYTHROUGH_COMPLETED: _completed,
    }
```

- [ ] **Step 4: Run the tests**

```
make test ARGS="tests/test_playthrough_projection.py tests/test_event_projectors.py tests/test_playthrough_numbering.py"
```

Expected: green. The numbering reads `started_lower`/`completed_lower`, which the database now fills from a stated date for the first time.

- [ ] **Step 5: Commit**

```bash
git add games/projectors/playthrough.py tests/test_playthrough_projection.py
git commit -m "$(cat <<'EOF'
Project a stated start and a stated completion

Both handlers amend. A creation event knows nothing of an endpoint, and
re-applying it must not take one back out, so the row is changed in
part rather than written whole.

Every value comes off the event -- the date from effective_time, the
marker from recorded_at, the note from the payload -- so a replay from
an empty database writes what the live append wrote.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The docs sweep and the gate

**Files:**
- Modify: `docs/event-retention.md:192-204` (the Naming section)
- Modify: `CLAUDE.md` (the `Playthrough` model bullet)
- Modify: `games/models.py`, `games/projectors/playthrough.py:28-35`, `games/reads/playthrough_numbering.py:19` (comments that say "until #681")
- Delete: `docs/superpowers/plans/2026-09-06-issue-681-playthrough-endpoints.md` (this file)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code reads.

- [ ] **Step 1: Add the naming rule the markers follow**

`docs/event-retention.md` says a column names the act in the past participle, `<act>_at`, because a removal's act and the record of it are one instant. A stated endpoint's are not. Add below that paragraph:

> An act whose own time a person states separately takes two columns. The past
> participle holds the stated time, and the record of the statement takes the
> act's noun with `recorded_at`: `started` beside `start_recorded_at`. Null in
> the record column is still the act that never happened.

- [ ] **Step 2: Update the Playthrough bullet in CLAUDE.md**

The bullet says both endpoints are `TemporalValueField` with generated bounds. Add that each endpoint also carries a marker whose null is the act that never happened, and a note of its own, stated by `StartPlaythrough`/`CompletePlaythrough` in `games/commands/playthrough.py`. Keep it to the two sentences the surrounding bullets run to.

- [ ] **Step 3: Sweep the comments that name #681 as future work**

Three sites say #681 has not happened yet:

- `games/models.py` — the endpoint comments Task 1 rewrote; confirm none still says "#681 states both endpoints".
- `games/projectors/playthrough.py` — the block above `handles` says the endpoint handlers "are never added". They are added now. Rewrite it to say what it still guards: the creation handler names four columns, so an amendment survives a re-applied creation event.
- `games/reads/playthrough_numbering.py:19` — "Until #681 every row has two null bounds". Now some rows have bounds; say so.

Each comment stays at its current length. `make vale` grades code comments too.

- [ ] **Step 4: Delete this plan**

```bash
git rm docs/superpowers/plans/2026-09-06-issue-681-playthrough-endpoints.md
```

The spec stays. The plan is scaffolding, and `make format` reads Python inside Markdown fences, so a plan left behind is a gate failure waiting to happen.

- [ ] **Step 5: Run the whole gate**

```
make check
```

Expected: green, including `check-migrations`, `vale`, and the `e2e/` suite. Never verify with a subset.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
Sweep the docs for the Playthrough endpoints

The naming rule gains the case #681 met: an act whose own time a person
states separately keeps the past participle for that time and gives the
record of the statement the act's noun.

Three comments said #681 was still ahead. The one above the creation
handler is the one that still guards something, so it now says what:
the handler names four columns, and an amendment survives it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Record the verdicts in the issue**

Before closing, edit #681's text so the decisions live where the next reader looks:

1. The endpoint note stays in Scope, and the reason is the Player Journal design, which attaches a note to each lifecycle fact and dates it.
2. The marker columns are `start_recorded_at` / `completion_recorded_at`, not `<act>_at`, and `docs/event-retention.md` now carries the rule.
3. The order rule refuses only the certainly-impossible, and skips a pair where either endpoint carries a qualifier.
4. Correcting or clearing a stated endpoint is #1010, and this issue refuses it.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the four columns and the migration (Task 1), the events and their builders (Task 2), the order rule (Task 3), the commands, the resolver and the five refusals (Task 4), the two handlers and the replay (Task 5), the naming sentence and the comment sweep (Task 6). The spec's "no constraint states the rule" section prescribes an absence, and the plan adds no `CheckConstraint`. The spec's "what this issue does not do" list prescribes absences too: no screen, no form, no API route, no correction, no removal, no status change — the plan touches no view, no form and no router.

**Types.** `when: TemporalValue | None` and `note: str` are the same in the command dataclasses (Task 4), in the builders (Task 2) and in the order rule's parameters (Task 3, which takes the stored value on one side). The projector writes `started`/`start_recorded_at`/`start_note` (Task 5), exactly the column names Task 1 adds and Task 4's build reads back.

**One thing an implementer will hit.** Task 4's foreign-library test needs a second library fixture; the plan says to read `tests/conftest.py` for its real name rather than guessing.
