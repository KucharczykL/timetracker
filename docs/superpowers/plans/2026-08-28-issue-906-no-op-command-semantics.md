# No-op command semantics implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command that finds the state the caller asks for already true succeeds
as `UNCHANGED` instead of raising `CommandRejected`, and claims its idempotency
key so a repeated delivery cannot append after another writer moved the state.

**Architecture:** `build` gains a second thing it can return, `Unchanged(reason)`.
`idempotent_append` recognises it, writes an idempotency record with no sequence
range, and returns a third result class. `dispatch` maps the three result classes
onto a `CommandOutcome` of three members. `LockedStream.append` is untouched, so
an empty event list stays the programming error #662 made it.

**Tech Stack:** Django 6, PostgreSQL 18, pytest + pytest-django, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-08-28-issue-906-no-op-command-semantics-design.md`

## Global Constraints

- Python 3.14. Run everything through `make`; never `uv run` or `pytest`
  directly. Focused runs: `make test ARGS="tests/test_x.py -k name"`.
- `make check` is the gate and must be green before the branch is done.
  `make check-fast` while iterating.
- Never write to a `GeneratedField`.
- Unabbreviated identifiers in Python (`element` not `el`, `event` not `e`).
- Name compound types explicitly — a tuple passed between functions gets a
  `NamedTuple` or a `type` alias.
- Comments use the `#:` prefix that the events modules already use.
- The branch is `claude/issue-906-no-op-command-semantics`, already created, with
  the design doc already committed.
- Commit messages: imperative mood, no `feat:`/`fix:` prefixes — match the
  existing log (`Add commands that archive and restore a tracked game`). End
  every commit message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## File structure

| File | Responsibility | Task |
| --- | --- | --- |
| `games/models.py` | `LibraryIdempotencyRecord` range becomes optional; one constraint replaces two | 1 |
| `games/migrations/0035_idempotency_record_optional_range.py` | The schema change | 1 |
| `games/events/vocabulary.py` | `Unchanged`, beside `NewEvent` | 2 |
| `games/events/idempotency.py` | `UnchangedAppend`; `idempotent_append` recognises `Unchanged` and claims the key | 2 |
| `games/events/dispatch.py` | `CommandOutcome`, `SequenceRange`, the new `CommandResult`, the widened `build` signature | 3 |
| `games/commands/playergame.py` | Six refusals become `Unchanged` | 4 |
| `tests/test_event_idempotency.py` | Constraint and append-layer behaviour | 1, 2 |
| `tests/test_command_dispatch.py` | Outcome mapping, a double that returns `Unchanged` | 3 |
| `tests/test_playergame_command.py` | The six converted behaviours | 4 |
| `docs/superpowers/specs/2026-08-23-issue-664-command-dispatch-design.md` | #906 is answered | 5 |

---

### Task 1: The idempotency record's range becomes optional

**Files:**
- Modify: `games/models.py:1594-1648`
- Create: `games/migrations/0035_idempotency_record_optional_range.py` (generated)
- Test: `tests/test_event_idempotency.py:76-92`

**Interfaces:**
- Consumes: nothing.
- Produces: `LibraryIdempotencyRecord.first_sequence` and `.last_sequence` are
  `int | None`. One check constraint named `library_idempotency_range_whole`
  admits both absent, or both present with `last_sequence >= first_sequence >= 1`.
  The constraints `library_idempotency_first_sequence_positive` and
  `library_idempotency_range_ordered` no longer exist.

- [ ] **Step 1: Write the failing tests**

In `tests/test_event_idempotency.py`, add two params to the existing
`test_rejected_records` — one column present without the other is still refused.
The whole test, with the two new params third and fourth:

```python
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"first_sequence": 0, "last_sequence": 0}, id="sequence-below-one"
        ),
        pytest.param({"first_sequence": 3, "last_sequence": 2}, id="range-inverted"),
        pytest.param({"first_sequence": None}, id="only-the-first-absent"),
        pytest.param({"last_sequence": None}, id="only-the-last-absent"),
        pytest.param({"idempotency_key": ""}, id="empty-key"),
        pytest.param({"request_fingerprint": ""}, id="empty-fingerprint"),
        pytest.param({"fingerprint_version": 0}, id="version-below-one"),
    ],
)
def test_rejected_records(owned_library, overrides: dict[str, Any]):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_record(owned_library, **overrides)
```

Then add this test directly after `test_rejected_records`:

```python
def test_a_record_may_carry_no_range_at_all(owned_library):
    """A command that changed nothing still claims its key."""
    record = make_record(owned_library, first_sequence=None, last_sequence=None)

    record.refresh_from_db()
    assert (record.first_sequence, record.last_sequence) == (None, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_event_idempotency.py -k 'rejected_records or no_range_at_all' -v"`

Expected: `only-the-first-absent` and `only-the-last-absent` FAIL (an
`IntegrityError` is raised for a `NOT NULL` violation rather than for the
constraint — the test passes for the wrong reason, so read the error text and
confirm it names `null value in column`), and
`test_a_record_may_carry_no_range_at_all` FAILs with `IntegrityError: null value
in column "first_sequence"`.

- [ ] **Step 3: Make the columns optional**

In `games/models.py`, replace the two field declarations:

```python
    #: Absent when the command changed nothing: nothing was appended, so there
    #: is no range to replay. #740 removes the nullability along with this
    #: whole model, which it replaces with a record of the request itself.
    first_sequence = models.PositiveBigIntegerField(null=True)
    last_sequence = models.PositiveBigIntegerField(null=True)
```

- [ ] **Step 4: Replace the two constraints with one**

In the same class's `Meta.constraints`, delete the
`library_idempotency_first_sequence_positive` and
`library_idempotency_range_ordered` entries and put this in their place:

```python
#: Both columns, or neither. #740 removes this with the model.
models.CheckConstraint(
    condition=(
        Q(first_sequence__isnull=True, last_sequence__isnull=True)
        | Q(first_sequence__gte=1, last_sequence__gte=F("first_sequence"))
    ),
    name="library_idempotency_range_whole",
)
```

Indent it to sit in the list, and end it with a comma like its neighbours.

`Q` and `F` are already imported in `games/models.py`.

- [ ] **Step 5: Generate the migration**

Run: `make makemigrations ARGS="games --name idempotency_record_optional_range"`

Open the generated `games/migrations/0035_idempotency_record_optional_range.py`
and confirm it contains two `AlterField` operations, two `RemoveConstraint`
operations, and one `AddConstraint`. There must be no `RunPython` step — every
existing row already carries a range, so no data moves.

- [ ] **Step 6: Apply it and run the tests**

Run: `make migrate && make test ARGS="tests/test_event_idempotency.py -v"`

Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 7: Check for drift**

Run: `make check-migrations`

Expected: no pending changes.

- [ ] **Step 8: Commit**

```bash
git add games/models.py games/migrations/0035_idempotency_record_optional_range.py tests/test_event_idempotency.py
git commit -m "$(cat <<'EOF'
Let one idempotency record carry no range

A command that changes nothing appends no event, so it has no range
to record. The two sequence columns become optional and one
constraint takes both or neither.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: An append layer that understands `Unchanged`

**Files:**
- Modify: `games/events/vocabulary.py:84-92`
- Modify: `games/events/idempotency.py:50-58`, `:97-161`
- Test: `tests/test_event_idempotency.py`

**Interfaces:**
- Consumes: Task 1's optional range.
- Produces:
  - `games.events.vocabulary.Unchanged`, a frozen slotted dataclass with one
    field, `reason: str`.
  - `games.events.idempotency.UnchangedAppend`, a frozen slotted dataclass with
    `stream_id: uuid.UUID` and `reason: str | None`.
  - `idempotent_append` takes
    `build: Callable[[LockedStream], Sequence[NewEvent] | Unchanged]` and returns
    `AppendResult | ReplayedAppend | UnchangedAppend`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_event_idempotency.py`, after
`test_a_command_recording_nothing_claims_no_key`:

```python
def test_a_command_that_changes_nothing_records_no_event(owned_library):
    with transaction.atomic():
        result = run_command(
            owned_library, build=lambda _stream: Unchanged("nothing to do")
        )

    assert isinstance(result, UnchangedAppend)
    assert result.reason == "nothing to do"
    assert not LibraryEvent.objects.exists()
    assert LibraryEventStreamHead.objects.get().current_sequence == 0


def test_a_command_that_changes_nothing_still_claims_its_key(owned_library):
    with transaction.atomic():
        run_command(owned_library, build=lambda _stream: Unchanged("nothing to do"))

    record = LibraryIdempotencyRecord.objects.get()
    assert (record.first_sequence, record.last_sequence) == (None, None)
    assert record.request_fingerprint == fingerprint_command_input({"probe": True})
    assert record.fingerprint_version == FINGERPRINT_VERSION


def test_a_claimed_no_op_key_cannot_append_after_the_state_moves(owned_library):
    """The lost update the record exists to close."""
    with transaction.atomic():
        run_command(owned_library, build=lambda _stream: Unchanged("nothing to do"))

    #: The state has moved under the same key, so this build would append.
    with transaction.atomic():
        replay = run_command(owned_library, build=lambda _stream: [make_new_event()])

    assert isinstance(replay, UnchangedAppend)
    #: The build never ran, so there is no sentence to hand back.
    assert replay.reason is None
    assert not LibraryEvent.objects.exists()
    assert LibraryIdempotencyRecord.objects.count() == 1


def test_a_no_op_never_rebuilds_on_a_repeat(owned_library):
    builds: list[str] = []

    def build(_stream) -> Unchanged:
        builds.append("built")
        return Unchanged("nothing to do")

    with transaction.atomic():
        run_command(owned_library, build=build)
    with transaction.atomic():
        run_command(owned_library, build=build)

    assert builds == ["built"]
```

Add `UnchangedAppend` to the `games.events.idempotency` import block at the top
of the file, and `Unchanged` to the `games.events.vocabulary` one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_event_idempotency.py -k 'changes_nothing or claimed_no_op or never_rebuilds' -v"`

Expected: collection FAILS with `ImportError: cannot import name 'Unchanged'`.

- [ ] **Step 3: Add `Unchanged` to the vocabulary**

In `games/events/vocabulary.py`, directly after the `NewEvent` class:

```python
@dataclass(frozen=True, slots=True)
class Unchanged:
    """The state the caller asks for already holds, so there is nothing to
    record. The other thing a command's build may return.

    `reason` is for a log line and for a test that must name which branch
    decided. Nothing user-facing may depend on it: a repeated delivery answers
    from the idempotency record, before the build that writes the sentence runs.
    """

    reason: str
```

- [ ] **Step 4: Add `UnchangedAppend` to the idempotency module**

In `games/events/idempotency.py`, directly after the `ReplayedAppend` class:

```python
@dataclass(frozen=True, slots=True)
class UnchangedAppend:
    """A command that found its work already done. It carries no range, because
    it appended nothing, and no events for the same reason."""

    stream_id: uuid.UUID
    #: None when a claimed key answered, so no build ran to explain itself.
    reason: str | None
```

Add `Unchanged` to the existing
`from games.events.vocabulary import NewEvent` import.

- [ ] **Step 5: Teach `idempotent_append` the third outcome**

In `games/events/idempotency.py`, change the `build` parameter's annotation to
`Callable[[LockedStream], Sequence[NewEvent] | Unchanged]` and the return
annotation to `AppendResult | ReplayedAppend | UnchangedAppend`.

Replace everything from `if record is not None:` to the end of the function
with:

```python
    if record is not None:
        #: A digest from another canonicalizer cannot be compared, so the key
        #: replays unchecked: idempotency outlives a version bump, and only the
        #: mismatch guard lapses for keys predating it.
        if (
            record.fingerprint_version == FINGERPRINT_VERSION
            and record.request_fingerprint != fingerprint
        ):
            raise IdempotencyKeyMismatch(
                f"Idempotency key {idempotency_key!r} already recorded a "
                f"different command for library {library.pk}."
            )
        #: The constraint takes both columns or neither; testing both is what
        #: narrows the pair for the type checker.
        if record.first_sequence is None or record.last_sequence is None:
            return UnchangedAppend(stream_id=stream.stream_id, reason=None)
        return ReplayedAppend(
            stream_id=stream.stream_id,
            first_sequence=record.first_sequence,
            last_sequence=record.last_sequence,
        )

    built = build(stream)
    if isinstance(built, Unchanged):
        #: Claimed, so a repeat of this request cannot append once another
        #: writer has moved the state out from under it.
        _record_range(
            library,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            first_sequence=None,
            last_sequence=None,
        )
        return UnchangedAppend(stream_id=stream.stream_id, reason=built.reason)

    result = stream.append(
        built,
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
        recorded_at=recorded_at,
        wiring=wiring,
    )
    _record_range(
        library,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        first_sequence=result.first_sequence,
        last_sequence=result.last_sequence,
    )
    return result
```

Note that `build(stream)` moved out of the `stream.append(...)` argument list —
the `Unchanged` branch has to see it first.

- [ ] **Step 6: Add the helper the two branches share**

In `games/events/idempotency.py`, above `idempotent_append`:

```python
def _record_range(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    fingerprint: RequestFingerprint,
    first_sequence: int | None,
    last_sequence: int | None,
) -> None:
    """Claim the key. Both sequences, or neither: a command that changed
    nothing claims its key just as firmly as one that appended."""
    LibraryIdempotencyRecord.objects.create(
        library=library,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        fingerprint_version=FINGERPRINT_VERSION,
        first_sequence=first_sequence,
        last_sequence=last_sequence,
    )
```

- [ ] **Step 7: Run the tests**

Run: `make test ARGS="tests/test_event_idempotency.py -v"`

Expected: PASS, including `test_a_command_recording_nothing_claims_no_key`,
which still proves an empty list raises `ValueError` and claims nothing.

- [ ] **Step 8: Type check**

Run: `make typecheck`

Expected: clean. `games/events/dispatch.py` still annotates its inner `build` as
returning `Sequence[NewEvent]`, which is a valid narrower type here, so it does
not error yet.

- [ ] **Step 9: Commit**

```bash
git add games/events/vocabulary.py games/events/idempotency.py tests/test_event_idempotency.py
git commit -m "$(cat <<'EOF'
Let a build say the work is already done

Unchanged is the other thing a build may return. The append layer
claims the key for it and appends nothing, so a repeated delivery
cannot record an event after another writer moved the state.

An empty list still raises: that is a build that forgot its events.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: A dispatch outcome of three members

**Files:**
- Modify: `games/events/dispatch.py:107-123`, `:227-229`, `:280-307`
- Test: `tests/test_command_dispatch.py`

**Interfaces:**
- Consumes: Task 2's `Unchanged` and `UnchangedAppend`.
- Produces:
  - `games.events.dispatch.CommandOutcome`, a `StrEnum` with `APPENDED =
    "appended"`, `REPLAYED = "replayed"`, `UNCHANGED = "unchanged"`.
  - `games.events.dispatch.SequenceRange`, a `NamedTuple` with `first: int` and
    `last: int`.
  - `CommandResult(stream_id, outcome, sequences, reason, correlation_id)`, where
    `sequences: SequenceRange | None` and `reason: str | None`.
  - `Command.build` returns `Sequence[NewEvent] | Unchanged`.
  - `Unchanged` is re-exported from `games.events.dispatch`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_command_dispatch.py`, add `UNCHANGED = "test.command.unchanged"`
to the `DispatchProbeName` enum, and add this double after `RejectingCommand`:

```python
@dataclass(frozen=True, slots=True)
class UnchangedCommand(Command):
    command_name: ClassVar[CommandVocabulary] = DispatchProbeName.UNCHANGED

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        return Unchanged("The state the caller asks for already holds.")
```

Add this test after `test_a_rejected_command_appends_nothing`:

```python
@pytest.mark.django_db(transaction=True)
def test_a_command_that_changes_nothing_reports_it(owned_user, owned_library):
    result = dispatch(
        UnchangedCommand(),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
        wiring=WIRING,
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert result.sequences is None
    assert result.reason == "The state the caller asks for already holds."
    assert not LibraryEvent.objects.filter(library=owned_library).exists()


@pytest.mark.django_db(transaction=True)
def test_a_repeated_no_op_reports_unchanged_without_a_reason(owned_user, owned_library):
    for _ in range(2):
        result = dispatch(
            UnchangedCommand(),
            actor=owned_user,
            library=owned_library,
            idempotency_key="same",
            wiring=WIRING,
        )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert result.sequences is None
    assert result.reason is None


@pytest.mark.django_db(transaction=True)
def test_only_an_unchanged_outcome_has_no_range(owned_user, owned_library):
    appended = dispatch(
        BasicCommand(label="x", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
        wiring=WIRING,
    )
    replayed = dispatch(
        BasicCommand(label="x", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
        wiring=WIRING,
    )
    unchanged = dispatch(
        UnchangedCommand(),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second",
        wiring=WIRING,
    )

    for result in (appended, replayed, unchanged):
        assert (result.sequences is None) == (
            result.outcome is CommandOutcome.UNCHANGED
        )
    assert (appended.reason, replayed.reason) == (None, None)
```

Add `CommandOutcome` and `Unchanged` to the `games.events.dispatch` import block.

Then update every existing assertion in this file that reads `.replayed` or the
two flat sequence fields:

- line 364: `assert result.replayed is False` becomes
  `assert result.outcome is CommandOutcome.APPENDED`
- line 365: `assert (result.first_sequence, result.last_sequence) == (1, 1)`
  becomes `assert result.sequences == (1, 1)`
- line 393: `assert second.replayed is True` becomes
  `assert second.outcome is CommandOutcome.REPLAYED`
- lines 394-397, the four-line tuple comparison, become
  `assert second.sequences == first.sequences`
- line 516: `assert result.replayed is False` becomes
  `assert result.outcome is CommandOutcome.APPENDED`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_command_dispatch.py -v"`

Expected: collection FAILS with `ImportError: cannot import name
'CommandOutcome'`.

- [ ] **Step 3: Add the two new types**

In `games/events/dispatch.py`, add `NamedTuple` to the `typing` import and
`Unchanged` to the `games.events.vocabulary` import, then add above
`CommandResult`:

```python
class CommandOutcome(StrEnum):
    """What one dispatch did.

    Three members rather than two booleans: a boolean pair describes four
    states where three exist.
    """

    APPENDED = "appended"
    REPLAYED = "replayed"
    UNCHANGED = "unchanged"


class SequenceRange(NamedTuple):
    """The stream sequences one append occupied, first and last included."""

    first: int
    last: int
```

- [ ] **Step 4: Reshape `CommandResult`**

Replace the `CommandResult` dataclass body with:

```python
@dataclass(frozen=True, slots=True)
class CommandResult:
    """What one dispatch did, whether or not it was the dispatch that did it.

    `outcome` collapses the append/replay/unchanged union at this boundary, so
    a caller branches on what happened rather than on which class it got. The
    events themselves do not escape: projections run inside the command's
    transaction, and a read taken after the lock is released is a different
    read.
    """

    stream_id: uuid.UUID
    outcome: CommandOutcome
    #: None exactly when the outcome is UNCHANGED: nothing was appended, so
    #: there is no range to name.
    sequences: SequenceRange | None
    #: A sentence only for a build that ran and returned Unchanged. Absent for
    #: an appended outcome, a replayed one, and a no-op whose key was already
    #: claimed. Nothing user-facing may depend on it.
    reason: str | None
    correlation_id: uuid.UUID
```

- [ ] **Step 5: Widen `Command.build` and the dispatch closure**

Change the abstract method's annotation:

```python
    @abstractmethod
    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        """Validate against current state and describe what happened.

        Two questions, in order. Does the state the caller asks for already
        hold? Return `Unchanged`: to do nothing is to reach it. Can it be
        reached from here? A no raises `CommandRejected`.
        """
```

And inside `dispatch`, change the inner closure's annotation to match:

```python
    def build(stream: LockedStream) -> Sequence[NewEvent] | Unchanged:
```

- [ ] **Step 6: Map the three result classes**

Add `UnchangedAppend` to the `games.events.idempotency` import, then replace the
`return CommandResult(...)` at the end of `dispatch` with:

```python
    outcome = run_in_transaction(run, policy=wiring.retry_policy)
    if isinstance(outcome, UnchangedAppend):
        return CommandResult(
            stream_id=outcome.stream_id,
            outcome=CommandOutcome.UNCHANGED,
            sequences=None,
            reason=outcome.reason,
            correlation_id=resolved_correlation_id,
        )
    return CommandResult(
        stream_id=outcome.stream_id,
        outcome=(
            CommandOutcome.REPLAYED
            if isinstance(outcome, ReplayedAppend)
            else CommandOutcome.APPENDED
        ),
        sequences=SequenceRange(outcome.first_sequence, outcome.last_sequence),
        reason=None,
        correlation_id=resolved_correlation_id,
    )
```

- [ ] **Step 7: Run the tests**

Run: `make test ARGS="tests/test_command_dispatch.py -v"`

Expected: PASS. `tests/test_playergame_command.py` is still red — Task 4 fixes it.

- [ ] **Step 8: Type check**

Run: `make typecheck`

Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add games/events/dispatch.py tests/test_command_dispatch.py
git commit -m "$(cat <<'EOF'
Give a dispatch three outcomes and one named range

Unchanged is neither an append nor a replay, so the boolean becomes
an enum of three. The two sequence integers become one range that is
absent exactly when nothing was recorded.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Six PlayerGame refusals become `Unchanged`

**Files:**
- Modify: `games/commands/playergame.py:50-214`
- Test: `tests/test_playergame_command.py`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: no new names. `TrackGame`, `SetPlayerGameStatus`,
  `SetPlayerGameMastered`, `SetPlayerGameExcludedFromUnfinished`,
  `ArchivePlayerGame` and `RestorePlayerGame` each return
  `Sequence[NewEvent] | Unchanged`.

- [ ] **Step 1: Rewrite the seven affected tests**

In `tests/test_playergame_command.py`, add `CommandOutcome` to the
`games.events.dispatch` import block. Then replace each test below wholesale.

`test_tracking_the_same_game_twice_is_refused` (line 125) becomes:

```python
@pytest.mark.django_db(transaction=True)
def test_tracking_the_same_game_twice_changes_nothing(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-first",
    )

    #: A different key: a second intent, not a repeated delivery.
    result = dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert PlayerGame.objects.count() == 1
```

`test_the_status_a_game_already_has_is_refused` (line 269) becomes:

```python
@pytest.mark.django_db(transaction=True)
def test_the_status_a_game_already_has_changes_nothing(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.UNPLAYED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="unplay-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "already gives" in result.reason
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.status_changed"
    ).exists()
```

`test_the_mastery_a_game_already_records_is_refused` (line 387) becomes:

```python
@pytest.mark.django_db(transaction=True)
def test_the_mastery_a_game_already_records_changes_nothing(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=False),
        actor=owned_user,
        library=owned_library,
        idempotency_key="unmaster-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "not mastered" in result.reason
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.mastered_changed"
    ).exists()
```

`test_the_exclusion_a_game_already_records_is_refused` (line 516) becomes:

```python
@pytest.mark.django_db(transaction=True)
def test_the_exclusion_a_game_already_records_changes_nothing(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        SetPlayerGameExcludedFromUnfinished(
            game_id=game.pk, excluded_from_unfinished=False
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="include-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "included in" in result.reason
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.excluded_from_unfinished_changed"
    ).exists()
```

`test_archiving_a_game_the_library_already_archives_is_refused` (line 668)
becomes:

```python
@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_the_library_already_archives_changes_nothing(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    result = dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds-again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playergame.archived").count()
        == 1
    )
```

`test_restoring_a_game_the_library_does_not_archive_is_refused` (line 696)
becomes:

```python
@pytest.mark.django_db(transaction=True)
def test_restoring_a_game_the_library_does_not_archive_changes_nothing(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.restored"
    ).exists()
```

`test_tracking_a_live_game_twice_still_says_the_library_tracks_it` (line 761)
becomes:

```python
@pytest.mark.django_db(transaction=True)
def test_tracking_a_live_game_twice_still_names_the_game(owned_user, owned_library):
    """The rare case may not blunt the common one."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "already tracks Outer Wilds" in result.reason
```

Finally, update the five `.replayed` assertions in this file:

- line 47: `assert result.replayed is False` becomes
  `assert result.outcome is CommandOutcome.APPENDED`
- line 159: `assert second.replayed is True` becomes
  `assert second.outcome is CommandOutcome.REPLAYED`, and the four-line tuple
  comparison below it becomes `assert second.sequences == first.sequences`
- lines 296, 414, 547, 730: each
  `assert (first.replayed, second.replayed) == (False, True)` becomes

```python
    assert (first.outcome, second.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_command.py -v"`

Expected: the seven rewritten tests FAIL with `CommandRejected` raised where a
result was expected. The `.replayed` conversions PASS already, because Task 3
landed the new field.

- [ ] **Step 3: Convert the six refusals**

In `games/commands/playergame.py`, add `Unchanged` to the
`games.events.vocabulary` import, and change all six `build` return annotations
from `Sequence[NewEvent]` to `Sequence[NewEvent] | Unchanged`.

In `TrackGame.build`, replace the second `raise CommandRejected(...)` — the one
reached when `tracked.archived_at is None` — with:

```python
            return Unchanged(f"This library already tracks {game.name}.")
```

Leave the archived branch above it exactly as it is.

In `SetPlayerGameStatus.build`:

```python
        if tracked.status == self.status:
            return Unchanged(
                f"This library already gives game {self.game_id} the status "
                f"{self.status.value!r}."
            )
```

In `SetPlayerGameMastered.build`:

```python
if tracked.mastered == self.mastered:
    recorded = "mastered" if self.mastered else "not mastered"
    return Unchanged(f"This library already records game {self.game_id} as {recorded}.")
```

In `SetPlayerGameExcludedFromUnfinished.build`:

```python
if tracked.excluded_from_unfinished == self.excluded_from_unfinished:
    recorded = "excluded from" if self.excluded_from_unfinished else "included in"
    return Unchanged(
        f"This library already records game {self.game_id} as {recorded} "
        "unfinished lists."
    )
```

In `ArchivePlayerGame.build`:

```python
        if tracked.archived_at is not None:
            return Unchanged(f"This library already archives game {self.game_id}.")
```

In `RestorePlayerGame.build`:

```python
        if tracked.archived_at is None:
            return Unchanged(f"This library does not archive game {self.game_id}.")
```

Every "Whether a repeat should instead succeed as a no-op is EV-23 (#906)"
sentence is now gone. Confirm with `grep -c 906 games/commands/playergame.py`,
which must print `0`.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playergame_command.py -v"`

Expected: PASS. `test_tracking_an_archived_game_names_the_restore` must still
pass — the archived branch is still a rejection.

- [ ] **Step 5: Run the whole non-browser suite**

Run: `make check-fast`

Expected: green. `games/events/benchmark_workload.py` calls `dispatch` and
discards the result, so it needs no edit; if `make typecheck` says otherwise,
fix it here.

- [ ] **Step 6: Commit**

```bash
git add games/commands/playergame.py tests/test_playergame_command.py
git commit -m "$(cat <<'EOF'
Let a repeated PlayerGame command succeed unchanged

Six refusals asked whether a repeat should instead be a no-op. Each
now returns Unchanged: the state the caller asks for already holds,
so to do nothing reaches it.

Tracking a game the library archives is still refused. That state
does not hold, and nothing reaches it by doing nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Close the question in the docs

**Files:**
- Modify: `docs/superpowers/specs/2026-08-23-issue-664-command-dispatch-design.md:260-265`, `:564-565`

**Interfaces:**
- Consumes: Tasks 1 to 4.
- Produces: nothing in code.

- [ ] **Step 1: Answer the question where #664 asked it**

In `docs/superpowers/specs/2026-08-23-issue-664-command-dispatch-design.md:260`,
replace the last two sentences of the "Returning no events is a programming
error" paragraph — from "So a command that finds nothing to do raises" to
"— filed for #671." — with:

```markdown
So a command never returns `[]`. One that finds nothing to do returns
`Unchanged`, which #906 settled: an idempotent no-op ("set status to `f` when
it is already `f`") is a *success*, reported as `CommandOutcome.UNCHANGED` with
no range. `CommandRejected` keeps the precondition nothing satisfies.
```

- [ ] **Step 2: Mark the follow-up delivered**

In the same file's "Follow-up issues" list, replace the `#906` bullet at line
564 with:

```markdown
- #906 — decided: an idempotent no-op is a success with no range, and it claims
  its idempotency key. See
  `docs/superpowers/specs/2026-08-28-issue-906-no-op-command-semantics-design.md`.
```

- [ ] **Step 3: Verify the format gate**

Run: `make format-check`

Expected: `531 files already formatted`. `ruff format` reaches Markdown code
fences, so a fence holding an unformatted Python fragment fails here.

- [ ] **Step 4: Run the full gate**

Run: `make check`

Expected: green, `e2e/` included. This is the verification gate; a hand-picked
subset does not substitute.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-23-issue-664-command-dispatch-design.md
git commit -m "$(cat <<'EOF'
Answer the no-op question where #664 asked it

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Hand the debt to #740**

Ask the human partner before posting — this writes to GitHub.

```bash
gh issue comment 740 --repo KucharczykL/timetracker --body "$(cat <<'EOF'
Note from #906.

`LibraryIdempotencyRecord.first_sequence` and `last_sequence` are now nullable,
and one `library_idempotency_range_whole` constraint takes both or neither. A
command that changes nothing appends no event, so it claims its key with no
range — which is what stops a repeated delivery appending after another writer
moved the state.

That nullability is a patch, and this issue removes it. A record of the request
itself has an outcome column, so "this request changed nothing" is an ordinary
row rather than an absent range. The same record can hold what #906 could not:
the reason a no-op changed nothing, which is unavailable today on a repeated
delivery because the key answers before `build` runs.

Recorded in `docs/superpowers/specs/2026-08-28-issue-906-no-op-command-semantics-design.md`
under "To be removed by #740".
EOF
)"
```

- [ ] **Step 7: Tick the tracker**

Ask the human partner before posting. On #601, tick `#906` in the "First
production evented domain" list and in the "Follow-ups from the dispatch
boundary" list.

---

## Self-review

**Spec coverage.** Every section of the design maps to a task: the rule → Task 4;
what a build returns → Task 2 step 3; what a dispatch returns → Task 3; the
append untouched → asserted by the surviving
`test_a_command_recording_nothing_claims_no_key`; a no-op claims its key →
Tasks 1 and 2; why the record gains nothing else → no task, it is a constraint on
future work stated in the spec; the commands table → Task 4; verification → the
tests across Tasks 1-4 plus `make check` in Task 5; to be removed by #740 → the
model comments in Task 1 and the issue comment in Task 5; out of scope → no task.

**Type consistency.** `Unchanged.reason` is `str`; `UnchangedAppend.reason` and
`CommandResult.reason` are `str | None`, because a claimed key answers before any
build runs. `SequenceRange` is a `NamedTuple`, so `result.sequences == (1, 1)`
compares equal to a plain tuple and the existing assertions convert with almost
no churn. `CommandOutcome` is compared with `is`, which is safe for enum members.

**One thing an executor must not skip.** Task 2 step 5 moves `build(stream)` out
of the `stream.append(...)` argument list. Leaving it inline means the
`Unchanged` branch is never reached and `append` raises a `TypeError` instead.
