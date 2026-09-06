# Remove and restore a Playthrough — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A library states that a run leaves its lists, and states it back, as two
commands over two events, with the refusals the wave commits to.

**Architecture:** `Playthrough.removed_at` already exists and only the
`Playthroughs` projector may write it. Two empty-payload event types carry the
two acts, two handlers amend the column, and two commands decide. The refusal
order puts the no-op first (#906), the last-run rule counts live ordinary rows
and fires only for an ordinary run, and the Session refusal ships as an empty
registry beside its one reader.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pydantic-validated event
payloads, pytest + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-06-issue-1011-playthrough-removal-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a bare
  `uv run` / `pnpm` / `pytest`. Focused runs are `make test ARGS="…"`.
- **The verification gate is the full `make check`**, including `e2e/`. Use
  `make check-fast` while iterating; it is not the gate.
- **Set `PYTEST_WORKERS=0` while debugging one test** — parallel output
  interleaves and `-x` stops only the worker that hit it.
- **No dispatch inside a transaction.** A test that dispatches needs
  `@pytest.mark.django_db(transaction=True)`.
- **A rejection carries two sentences.** `raise CommandRejected(message,
  sentence=…)`. The first argument explains the refusal to whoever reads a log
  and may name an id; `sentence` is the only thing a person is shown. A raise
  site with no `sentence` is answered `REFUSED`.
- **A command asking for state that already holds returns `Unchanged`**, never
  a refusal (#906).
- **Nothing writes a projection column but its projector.** No `remove()`,
  no `restore()`, no `REMOVABLE_MODELS` entry for `Playthrough`.
- **Never write to a `GeneratedField`** (`started_lower`, `started_upper`,
  `completed_lower`, `completed_upper`).
- **Full words in identifiers**, Python and TypeScript.
- **Refused words** are enforced by `make vale` over docs *and code comments*.
  `archive` is an error where it means removal; say `remove`. See
  `docs/vocabulary.md`.
- **Comments explain why, not what**, and match the density of the file
  they land in. The Playthrough modules use `#:` for a field or branch note.
- **No migration.** `removed_at` shipped with #679. If `make check-migrations`
  asks for one, something in the model was touched that should not have been.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| *(none)* | Every file this issue needs already exists. |

**Modified**

| Path | What changes |
|---|---|
| `games/events/playthrough.py` | Two payload types, two `EventSpec`s, two registrations, two builders |
| `games/events/dispatch.py` | Two `CommandName` members |
| `games/projectors/playthrough.py` | `_removed`, `_restored`, two entries in `handles` |
| `games/commands/playthrough.py` | `BlockingReferrer`, `BLOCKING_REFERRERS`, `blocking_referrer()`, `_refuse_under_a_removed_game()`, `RemovePlaythrough`, `RestorePlaythrough` |
| `games/reads/playthrough_numbering.py` | `display_name(…, *, fallback=None)` |
| `games/models.py` | The `removed_at` comment names the two commands |
| `games/removal.py` | The comment naming the projections outside `REMOVABLE_MODELS` |
| `CLAUDE.md` | The `Playthrough` bullet |
| `docs/superpowers/specs/2026-09-04-playthrough-wave-design.md` | The `#1011` section records what shipped |
| `tests/test_playthrough_events.py` | Vocabulary and payload strictness for both types |
| `tests/test_playthrough_projection.py` | Handlers, replay, rebuild |
| `tests/test_playthrough_command.py` | Every refusal, every `Unchanged`, idempotency, the blocking referrer |
| `tests/test_playthrough_numbering.py` | The `fallback`, and a removed row built by the real command |

---

### Task 1: The two events

**Files:**
- Modify: `games/events/playthrough.py` (append after `PLAYTHROUGH_NOTE_CHANGED`, currently ending at line 208)
- Test: `tests/test_playthrough_events.py`

**Interfaces:**
- Consumes: `EventSpec`, `DEFAULT_EVENT_TYPES`, `NewEvent`, `STRICT_SCHEMA`, `with_config` — all already imported by the module.
- Produces: `PLAYTHROUGH_REMOVED`, `PLAYTHROUGH_RESTORED` (both `EventSpec`),
  `playthrough_removed(playthrough_id: uuid.UUID) -> NewEvent`,
  `playthrough_restored(playthrough_id: uuid.UUID) -> NewEvent`.

- [ ] **Step 1: Confirm the two type names are free**

No test fixture may already claim these strings. `tests/test_event_vocabulary.py`
asserts every invented type is absent from `DEFAULT_EVENT_TYPES`, and #681 broke
that guard by registering a name a fixture had taken.

Run: `grep -rn "playthrough.removed\|playthrough.restored" tests/ games/`
Expected: no hit outside `docs/`. If there is one, rename the fixture first.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_playthrough_events.py`:

```
def test_the_lifecycle_events_are_in_the_default_vocabulary():
    removed = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.removed")
    restored = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.restored")

    assert (removed, restored) == (PLAYTHROUGH_REMOVED, PLAYTHROUGH_RESTORED)
    assert removed.aggregate_type == "playthrough"
    assert restored.aggregate_type == "playthrough"


def test_a_lifecycle_payload_states_nothing_but_its_type():
    """The type is the fact, so no key can disagree with it."""
    assert DEFAULT_EVENT_TYPES.validate(PLAYTHROUGH_REMOVED.event_type, {}) == {}
    assert DEFAULT_EVENT_TYPES.validate(PLAYTHROUGH_RESTORED.event_type, {}) == {}


def test_a_lifecycle_payload_refuses_a_direction_of_its_own():
    """A later fact takes a later type, not a key nobody declared."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_REMOVED.event_type, {"removed": True}
        )


def test_a_lifecycle_payload_refuses_a_time_of_its_own():
    """`recorded_at` carries it, so a replay writes what was recorded."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_RESTORED.event_type, {"at": "2026-09-06T00:00:00Z"}
        )


def test_the_lifecycle_builders_name_the_playthrough_they_are_told_about():
    """The aggregate exists, so nothing mints an identity here."""
    identity = uuid.uuid7()

    removed = playthrough_removed(identity)
    restored = playthrough_restored(identity)

    assert (removed.aggregate_id, restored.aggregate_id) == (identity, identity)
    assert (removed.payload, restored.payload) == ({}, {})
    assert (removed.effective_time, restored.effective_time) == (None, None)
```

Extend the module's existing import of `games.events.playthrough` with
`PLAYTHROUGH_REMOVED`, `PLAYTHROUGH_RESTORED`, `playthrough_removed` and
`playthrough_restored`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_events.py -k lifecycle"`
Expected: collection error — `ImportError: cannot import name 'PLAYTHROUGH_REMOVED'`.

- [ ] **Step 4: Write the implementation**

Append to `games/events/playthrough.py`:

```
@with_config(STRICT_SCHEMA)
class PlaythroughRemovedPayload(TypedDict):
    """The library takes the run out of its lists.

    Empty, because the type is the fact. A key stating a direction
    could disagree with the type it rides on, and Audit History reads
    the name.
    """


@with_config(STRICT_SCHEMA)
class PlaythroughRestoredPayload(TypedDict):
    """The library puts the run back."""


PLAYTHROUGH_REMOVED = EventSpec(
    "library.playthrough.removed",
    aggregate_type="playthrough",
    payload=PlaythroughRemovedPayload,
)

PLAYTHROUGH_RESTORED = EventSpec(
    "library.playthrough.restored",
    aggregate_type="playthrough",
    payload=PlaythroughRestoredPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_REMOVED)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_RESTORED)


def playthrough_removed(playthrough_id: uuid.UUID) -> NewEvent:
    """The run leaves the lists. `recorded_at` states when."""
    return PLAYTHROUGH_REMOVED.new(aggregate_id=playthrough_id, payload={})


def playthrough_restored(playthrough_id: uuid.UUID) -> NewEvent:
    """The run is back, with every fact it had."""
    return PLAYTHROUGH_RESTORED.new(aggregate_id=playthrough_id, payload={})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_events.py"`
Expected: PASS, whole file.

- [ ] **Step 6: Commit**

```bash
git add games/events/playthrough.py tests/test_playthrough_events.py
git commit -m "Record that a run left the lists, and that it is back"
```

---

### Task 2: The two projector handlers

**Files:**
- Modify: `games/projectors/playthrough.py`
- Test: `tests/test_playthrough_projection.py`

**Interfaces:**
- Consumes: `playthrough_removed` / `playthrough_restored` and their specs from Task 1.
- Produces: `Playthroughs._removed`, `Playthroughs._restored`, both registered in
  `handles`. After this task, appending either event amends
  `Playthrough.removed_at`.

- [ ] **Step 1: Write the failing tests**

`tests/test_playthrough_projection.py` already has `append_about_run(library,
actor, event, *, key=…)` and `track(...)`; reuse them. Add:

```
@pytest.mark.django_db(transaction=True)
def test_the_removal_event_writes_its_own_time(owned_user, owned_library):
    """Off the event, so a replay agrees with the live path."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    append_about_run(
        owned_library, owned_user, playthrough_removed(run.pk), key="remove"
    )

    stamped = LibraryEvent.objects.get(
        event_type="library.playthrough.removed"
    ).recorded_at
    run.refresh_from_db()
    assert run.removed_at == stamped


@pytest.mark.django_db(transaction=True)
def test_the_restore_event_states_the_way_back(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    append_about_run(
        owned_library, owned_user, playthrough_removed(run.pk), key="remove"
    )

    append_about_run(
        owned_library, owned_user, playthrough_restored(run.pk), key="restore"
    )

    run.refresh_from_db()
    assert run.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_a_removal_and_its_undoing(owned_user, owned_library):
    """Removed, back, and removed again reach one state."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    for index, event in enumerate(
        (
            playthrough_removed(run.pk),
            playthrough_restored(run.pk),
            playthrough_removed(run.pk),
        )
    ):
        append_about_run(owned_library, owned_user, event, key=f"lifecycle-{index}")
    last = (
        LibraryEvent.objects.filter(event_type="library.playthrough.removed")
        .order_by("sequence")
        .last()
        .recorded_at
    )
    #: The child first: player_game RESTRICTs.
    Playthrough.objects.all().delete()
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert Playthrough.objects.get().removed_at == last


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_of_a_removed_run_swaps_with_an_empty_diff(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    append_about_run(
        owned_library, owned_user, playthrough_removed(run.pk), key="remove"
    )

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

Add `playthrough_removed` and `playthrough_restored` to the module's import from
`games.events.playthrough`.

Check the existing helper's exact name before writing: if the module calls it
`append_about_run`, use that; #1010 added it for the correction events.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_projection.py -k 'removal or restore or removed'"`
Expected: FAIL — the events append but no handler runs, so `removed_at` stays
`None` and the first assertion compares `None` to a timestamp.

- [ ] **Step 3: Write the implementation**

In `games/projectors/playthrough.py`, add the two imports to the existing
`games.events.playthrough` import block, then the handlers after
`_completion_corrected`:

```
    def _removed(self, event: RecordedEvent) -> None:
        #: The event's instant, so a replay writes what was recorded.
        self.amend(Playthrough, event.aggregate_id, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(Playthrough, event.aggregate_id, removed_at=None)
```

and the two entries at the end of `handles`:

```
        PLAYTHROUGH_REMOVED: _removed,
        PLAYTHROUGH_RESTORED: _restored,
```

Do **not** name `removed_at` in `_created`. The creation handler names four
columns on purpose, and `tests/test_playthrough_projection.py` already pins that
re-applying it leaves an amended `removed_at` alone.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_projection.py"`
Expected: PASS, whole file — including the pre-existing
`test_re_applying_the_creation_event_leaves_an_amendment_alone`.

- [ ] **Step 5: Commit**

```bash
git add games/projectors/playthrough.py tests/test_playthrough_projection.py
git commit -m "Project a removed run and its way back"
```

---

### Task 3: The two commands, without the two extra refusals

**Files:**
- Modify: `games/events/dispatch.py:90-95` (the `CommandName` block)
- Modify: `games/commands/playthrough.py` (append after `CorrectPlaythroughCompletion`)
- Test: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: `playthrough_removed` / `playthrough_restored` (Task 1), the handlers
  (Task 2), and the existing `library_playthrough(context, playthrough_id)`.
- Produces: `CommandName.PLAYTHROUGH_REMOVE`, `CommandName.PLAYTHROUGH_RESTORE`,
  `RemovePlaythrough(playthrough_id: uuid.UUID)`,
  `RestorePlaythrough(playthrough_id: uuid.UUID)`, and the module-level helper
  `_refuse_under_a_removed_game(run: Playthrough, playthrough_id: uuid.UUID) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_command.py`:

```
def _remove(owned_user, owned_library, playthrough, key="remove"):
    return dispatch(
        RemovePlaythrough(playthrough_id=playthrough.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


def _restore(owned_user, owned_library, playthrough, key="restore"):
    return dispatch(
        RestorePlaythrough(playthrough_id=playthrough.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_stamps_the_column(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)

    result = _remove(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.APPENDED
    run.refresh_from_db()
    assert run.removed_at is not None


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_a_second_time_changes_nothing(
    owned_user, owned_library, game
):
    """A no-op is a success recording no event, per #906."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)

    result = _remove(owned_user, owned_library, run, key="remove-again")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert LibraryEvent.objects.filter(
        event_type="library.playthrough.removed"
    ).count() == 1


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_removal(owned_user, owned_library, game):
    """The key names the request, so a repeat replays the record."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run, key="once")

    result = _remove(owned_user, owned_library, run, key="once")

    assert result.outcome is CommandOutcome.REPLAYED
    assert LibraryEvent.objects.filter(
        event_type="library.playthrough.removed"
    ).count() == 1


@pytest.mark.django_db(transaction=True)
def test_restoring_a_run_clears_the_column(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)

    result = _restore(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.APPENDED
    run.refresh_from_db()
    assert run.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_restoring_a_live_run_changes_nothing(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    result = _restore(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not LibraryEvent.objects.filter(
        event_type="library.playthrough.restored"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_of_another_library_is_refused(
    owned_user, owned_library, django_user_model
):
    """A refusal is not a place to learn an id.

    Built by hand, the way
    `test_stating_an_endpoint_of_another_library_is_refused` builds it:
    there is no second-library fixture, and a stranger's rows are not
    reachable through a command.
    """
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    elsewhere = Game.objects.create(library=stranger.library, name="Tunic")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        game=elsewhere,
        tracked_at=timezone.now(),
    )
    hidden = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, hidden, key="foreign")

    assert refusal.value.sentence == "That playthrough is not available."
    assert str(hidden.pk) not in refusal.value.sentence


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_of_a_removed_game_is_refused(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="parent-gone")

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before changing "
        "its playthroughs."
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_run_of_a_removed_game_is_refused(owned_user, owned_library, game):
    """The way out is always open: restore the game, then the run."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _restore(owned_user, owned_library, run, key="parent-gone")

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before changing "
        "its playthroughs."
    )
```

Add one helper beside the existing `_imported_run`, because almost every test
here needs a run that is *not* the game's only ordinary one:

```
def _second_run(owned_user, owned_library, key="second-run"):
    """A run the last-ordinary-run rule does not protect."""
    game = Game.objects.get()
    #: CommandResult carries no events on purpose, so the new row is
    #: the one that was not there before.
    before = set(Playthrough.objects.values_list("pk", flat=True))
    dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )
    return Playthrough.objects.exclude(pk__in=before).get()
```

Extend the module's import from `games.commands.playthrough` with
`RemovePlaythrough` and `RestorePlaythrough`.

Check `other_library` against `tests/conftest.py` before use — if the fixture is
named differently, use the name the suite already has for a second library.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_command.py -k 'removing or restoring or removal'"`
Expected: collection error — `ImportError: cannot import name 'RemovePlaythrough'`.

- [ ] **Step 3: Add the two command names**

In `games/events/dispatch.py`, after `PLAYTHROUGH_CORRECT_COMPLETION` (line 95):

```
    PLAYTHROUGH_REMOVE = "library.playthrough.remove"
    PLAYTHROUGH_RESTORE = "library.playthrough.restore"
```

- [ ] **Step 4: Write the two commands**

In `games/commands/playthrough.py`, add `playthrough_removed` and
`playthrough_restored` to the `games.events.playthrough` import, then append:

```
def _refuse_under_a_removed_game(run: Playthrough, playthrough_id: uuid.UUID) -> None:
    """Refuse a lifecycle act on a run whose game is gone.

    A sentence of its own, and not `_live_run`'s: "before recording
    this" names an act that neither of these two performs.
    """
    #: Under dispatch's lock: the mark cannot move.
    if run.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind playthrough {playthrough_id}, "
            "so its runs neither leave the lists nor come back.",
            sentence=(
                "That game was removed from your library. Restore it before "
                "changing its playthroughs."
            ),
        )


@dataclass(frozen=True, slots=True)
class RemovePlaythrough(Command):
    """Take a run out of the library's lists."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_REMOVE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = library_playthrough(context, self.playthrough_id)
        #: The no-op first, and not the parent, which is the order
        #: `_live_run` reads them in. #906: a command asking for state
        #: that already holds is a success, so a repeat still answers
        #: one after the game itself was removed.
        if run.removed_at is not None:
            return Unchanged(
                f"This library already removed playthrough {self.playthrough_id}."
            )
        _refuse_under_a_removed_game(run, self.playthrough_id)
        return [playthrough_removed(run.pk)]


@dataclass(frozen=True, slots=True)
class RestorePlaythrough(Command):
    """Put a removed run back.

    `RestorePlayerGame` consults nothing above it, because a removed
    catalog Game cannot be restored from the library and a refusal
    would strand the row. Here the thing above is a PlayerGame,
    `RestorePlayerGame` never refuses, so the way out is always open
    and the refusal states the order rather than hiding the row.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_RESTORE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = library_playthrough(context, self.playthrough_id)
        #: The no-op first, for the reason RemovePlaythrough states.
        if run.removed_at is None:
            return Unchanged(
                f"This library did not remove playthrough {self.playthrough_id}."
            )
        _refuse_under_a_removed_game(run, self.playthrough_id)
        return [playthrough_restored(run.pk)]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_command.py"`
Expected: PASS, whole file.

- [ ] **Step 6: Commit**

```bash
git add games/events/dispatch.py games/commands/playthrough.py tests/test_playthrough_command.py
git commit -m "State that a run leaves the lists, and that it comes back"
```

---

### Task 4: A tracked game keeps one ordinary run

**Files:**
- Modify: `games/commands/playthrough.py` (`RemovePlaythrough.build`)
- Test: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: `RemovePlaythrough` (Task 3), `PlaythroughKind`, `_second_run`,
  `_imported_run` (both already in the test module).
- Produces: the module-level helper
  `_other_live_ordinary_runs(context: CommandContext, run: Playthrough) -> QuerySet[Playthrough]`.

- [ ] **Step 1: Write the failing tests**

```
@pytest.mark.django_db(transaction=True)
def test_removing_the_only_ordinary_run_is_refused(owned_user, owned_library, game):
    """Every tracked game keeps a Playthrough 1."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="last")

    assert refusal.value.sentence == (
        "This is the only playthrough of that game, and a tracked game keeps "
        "one. Remove the game itself instead."
    )


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_beside_a_live_sibling_is_allowed(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)

    result = _remove(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.APPENDED


@pytest.mark.django_db(transaction=True)
def test_a_removed_sibling_does_not_keep_the_last_run_removable(
    owned_user, owned_library, game
):
    """The rule counts live rows, so the second removal is refused."""
    _track(owned_user, owned_library, game)
    second = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, second, key="first-removal")
    first = Playthrough.objects.get(removed_at__isnull=True)

    with pytest.raises(CommandRejected):
        _remove(owned_user, owned_library, first, key="second-removal")


@pytest.mark.django_db(transaction=True)
def test_a_bucket_does_not_keep_an_ordinary_run_removable(
    owned_user, owned_library, game
):
    """No display number is counted across a bucket."""
    _track(owned_user, owned_library, game)
    _imported_run(owned_user, owned_library)
    ordinary = Playthrough.objects.get(kind=PlaythroughKind.ORDINARY)

    with pytest.raises(CommandRejected):
        _remove(owned_user, owned_library, ordinary, key="last-ordinary")


@pytest.mark.django_db(transaction=True)
def test_a_bucket_is_removable_from_a_game_with_no_ordinary_run(
    owned_user, owned_library, game
):
    """The rule fires for an ordinary run, and only for one.

    Removing a bucket takes no ordinary run away, and gating the count
    alone would leave the bucket #700 creates unremovable forever.
    """
    _track(owned_user, owned_library, game)
    bucket = _imported_run(owned_user, owned_library)
    Playthrough.objects.filter(kind=PlaythroughKind.ORDINARY).update(
        removed_at=timezone.now()
    )

    result = _remove(owned_user, owned_library, bucket, key="bucket")

    assert result.outcome is CommandOutcome.APPENDED
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_command.py -k 'only_ordinary or bucket or sibling'"`
Expected: FAIL — `test_removing_the_only_ordinary_run_is_refused` raises no
`CommandRejected`, because nothing counts siblings yet.

- [ ] **Step 3: Write the implementation**

Add the helper beside `_refuse_under_a_removed_game`:

```
def _other_live_ordinary_runs(
    context: CommandContext, run: Playthrough
) -> QuerySet[Playthrough]:
    """The live ordinary runs of this game, besides this one.

    Scoped on the library explicitly. `library_playthrough` scopes on
    `Playthrough.library`, and a run may name another library's
    PlayerGame -- which is the drift `cross_library_violations`
    reports -- so a query keyed on the parent alone counts rows this
    library does not hold.
    """
    return Playthrough.objects.filter(
        library=context.library,
        player_game=run.player_game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).exclude(pk=run.pk)
```

Import `QuerySet` from `django.db.models` at the top of the module.

Then, in `RemovePlaythrough.build`, after `_refuse_under_a_removed_game(...)`:

```
        #: Only for an ordinary run. Removing a bucket takes no
        #: ordinary run away, and refusing there would defend nothing
        #: and leave the bucket #700 creates unremovable.
        if (
            run.kind == PlaythroughKind.ORDINARY
            and not _other_live_ordinary_runs(context, run).exists()
        ):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} is the last live ordinary "
                f"run of player game {run.player_game_id}, and every tracked "
                "game holds one.",
                sentence=(
                    "This is the only playthrough of that game, and a tracked "
                    "game keeps one. Remove the game itself instead."
                ),
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_command.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/commands/playthrough.py tests/test_playthrough_command.py
git commit -m "Keep one ordinary run on every tracked game"
```

---

### Task 5: The refusal the Sessions wave will need

**Files:**
- Modify: `games/commands/playthrough.py`
- Test: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: `RemovePlaythrough` (Task 3).
- Produces: `BlockingReferrer` (a `NamedTuple` of `model`, `field_name`,
  `sentence`), `BLOCKING_REFERRERS: tuple[BlockingReferrer, ...]` (empty), and
  `blocking_referrer(run: Playthrough) -> BlockingReferrer | None`.

**Why an empty tuple and not a system check:** the wave states #701 makes
`Session` a projection, so `Session.playthrough` is a reference *out of* a
projection and `games.E009` already refuses `manage.py check` until it is
registered. A second registry would duplicate that, and would bless what
`ProjectionModel`'s docstring refuses. See the spec.

- [ ] **Step 1: Write the failing tests**

A referrer needs a model with a foreign key to `Playthrough`, and none exists.
Declare one under `isolate_apps` and give it a table, the way
`tests/test_uuidv7.py:169` and `tests/test_temporal_field.py:155` do:

```
@pytest.mark.django_db(transaction=True)
def test_a_registered_referrer_keeps_a_run_in_place(
    owned_user, owned_library, game, monkeypatch
):
    """Inert on delivery: #700 and #701 supply the first entry."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)

    with isolate_apps("games"):

        class Assignment(models.Model):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            playthrough = models.ForeignKey(Playthrough, on_delete=models.RESTRICT)
            removed_at = models.DateTimeField(null=True, default=None)

            class Meta:
                app_label = "games"
                db_table = "test_playthrough_assignment"

        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(Assignment)
        try:
            Assignment.objects.create(playthrough=run)
            monkeypatch.setattr(
                playthrough_commands,
                "BLOCKING_REFERRERS",
                (
                    BlockingReferrer(
                        model=Assignment,
                        field_name="playthrough",
                        sentence=(
                            "Sessions are assigned to this playthrough. Move "
                            "them before removing it."
                        ),
                    ),
                ),
            )

            with pytest.raises(CommandRejected) as refusal:
                _remove(owned_user, owned_library, run, key="blocked")

            assert refusal.value.sentence == (
                "Sessions are assigned to this playthrough. Move them before "
                "removing it."
            )
        finally:
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(Assignment)


@pytest.mark.django_db(transaction=True)
def test_a_removed_referring_row_keeps_nothing_in_place(
    owned_user, owned_library, game, monkeypatch
):
    """A referrer's own mark decides, so a removed row blocks nothing."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)

    with isolate_apps("games"):

        class Assignment(models.Model):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            playthrough = models.ForeignKey(Playthrough, on_delete=models.RESTRICT)
            removed_at = models.DateTimeField(null=True, default=None)

            class Meta:
                app_label = "games"
                db_table = "test_playthrough_assignment"

        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(Assignment)
        try:
            Assignment.objects.create(playthrough=run, removed_at=timezone.now())
            monkeypatch.setattr(
                playthrough_commands,
                "BLOCKING_REFERRERS",
                (
                    BlockingReferrer(
                        model=Assignment,
                        field_name="playthrough",
                        sentence="unused",
                    ),
                ),
            )

            result = _remove(owned_user, owned_library, run, key="not-blocked")

            assert result.outcome is CommandOutcome.APPENDED
        finally:
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(Assignment)


def test_the_delivered_registry_refuses_nothing():
    """Nothing names a run yet; #700 and #701 give the first thing that does."""
    assert playthrough_commands.BLOCKING_REFERRERS == ()
```

Add to the test module's imports:

```
from django.db import connection, models
from django.test.utils import isolate_apps

from games.commands import playthrough as playthrough_commands
from games.commands.playthrough import BlockingReferrer
```

`monkeypatch.setattr` targets the module object, not the imported name, because
`build()` reads the module global at call time.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_command.py -k referr"`
Expected: collection error — `ImportError: cannot import name 'BlockingReferrer'`.

- [ ] **Step 3: Write the implementation**

In `games/commands/playthrough.py`, above `RemovePlaythrough`:

```
class BlockingReferrer(NamedTuple):
    """One thing whose existence keeps a run in place.

    The model must carry `removed_at`: what a person removed states
    nothing about a run, so only a live row blocks.
    """

    model: type[models.Model]
    #: The alias games/projections.py states for a field's name.
    field_name: FieldName
    #: The one thing a person is shown. Each entry writes its own,
    #: because "move the sessions" is advice only its own referrer
    #: can give.
    sentence: str


#: Empty until #700 and #701 give a Session its reference to a run.
#: Written now so a shipped command need not grow the rule, and kept
#: beside its one reader: an incoming-reference registry in
#: games/projections.py would duplicate games.E009, which already
#: refuses an unregistered reference out of a projection.
BLOCKING_REFERRERS: tuple[BlockingReferrer, ...] = ()


def blocking_referrer(run: Playthrough) -> BlockingReferrer | None:
    """The first registered thing naming this run, or none."""
    for referrer in BLOCKING_REFERRERS:
        named = referrer.model._default_manager.filter(
            **{referrer.field_name: run}, removed_at__isnull=True
        )
        if named.exists():
            return referrer
    return None
```

Import `NamedTuple` from `typing`, `models` from `django.db`, and `FieldName`
from `games.projections`. If importing `games.projections` into
`games.commands.playthrough` makes a cycle, declare `type FieldName = str`
locally with a comment naming the alias it mirrors — run the tests to find out
rather than guessing.

In `RemovePlaythrough.build`, between `_refuse_under_a_removed_game(...)` and
the last-run rule:

```
        blocker = blocking_referrer(run)
        if blocker is not None:
            raise CommandRejected(
                f"{blocker.model.__name__} rows name playthrough "
                f"{self.playthrough_id}, so the run stays where they can "
                "find it.",
                sentence=blocker.sentence,
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_command.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Verify the checks still pass with a fabricated model in the suite**

Run: `make typecheck && make test ARGS="tests/test_projection_references.py tests/test_projection_rebuild.py"`
Expected: PASS. The fabricated `Assignment` lives inside one test and its table
is removed in a `finally`, so no projection walk sees it.

- [ ] **Step 6: Commit**

```bash
git add games/commands/playthrough.py tests/test_playthrough_command.py
git commit -m "Refuse a removal while something still names the run"
```

---

### Task 6: A name for a run no number is counted across

**Files:**
- Modify: `games/reads/playthrough_numbering.py:41-53`
- Test: `tests/test_playthrough_numbering.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `display_name(playthrough: Playthrough, *, fallback: str | None = None) -> str`.
  Existing callers pass one positional argument and are unaffected.

- [ ] **Step 1: Write the failing tests**

```
def test_a_fallback_answers_for_a_row_with_no_number():
    """A removed row and a bucket are both unnumbered."""
    run = Playthrough(name="")

    assert display_name(run, fallback="Removed playthrough") == (
        "Removed playthrough"
    )


def test_a_fallback_does_not_displace_a_stated_name():
    run = Playthrough(name="Blind run")

    assert display_name(run, fallback="Removed playthrough") == "Blind run"


def test_no_fallback_still_refuses_an_unnumbered_row():
    """A screen that forgot to number its rows hears about it."""
    with pytest.raises(UnnumberedPlaythrough):
        display_name(Playthrough(name=""))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playthrough_numbering.py -k fallback"`
Expected: FAIL — `TypeError: display_name() got an unexpected keyword argument`.

- [ ] **Step 3: Write the implementation**

Replace `display_name` in `games/reads/playthrough_numbering.py`:

```
def display_name(playthrough: Playthrough, *, fallback: str | None = None) -> str:
    """What a screen calls this run.

    `fallback` is for a caller that means to render a row no number is
    counted across -- a removed one, or one whose kind is not ordinary.
    With none, the refusal stands, so a screen that simply forgot to
    number its rows still hears about it.
    """
    if playthrough.name:
        return playthrough.name
    number = getattr(playthrough, "display_number", None)
    if number is None:
        if fallback is not None:
            return fallback
        raise UnnumberedPlaythrough(
            f"Playthrough {playthrough.pk} has no name and no display "
            "number. A blank name is displayed as its number, which only "
            "with_display_number() states, and only over the live ordinary "
            "rows a number is counted across. A caller that means to render "
            "such a row states a fallback."
        )
    return f"Playthrough {number}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playthrough_numbering.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_numbering.py tests/test_playthrough_numbering.py
git commit -m "Answer for a run no display number is counted across"
```

---

### Task 7: Move the faked column onto the command, and sweep the comments

**Files:**
- Modify: `tests/test_playthrough_command.py:566-568`, `:889`, `:1298`
- Modify: `tests/test_playthrough_numbering.py:70`
- Modify: `games/models.py` (the `removed_at` comment on `Playthrough`)
- Modify: `games/removal.py:28-30`
- Modify: `CLAUDE.md` (the `Playthrough` bullet)
- Modify: `docs/superpowers/specs/2026-09-04-playthrough-wave-design.md` (the `#1011` section)

**Interfaces:**
- Consumes: `RemovePlaythrough` (Task 3).
- Produces: nothing new. This task removes the last raw `update(removed_at=…)`
  from the tests that assert command behaviour.

- [ ] **Step 1: Move the three command tests onto a dispatch**

Each of these three stamps the column by hand with a docstring saying it is
inert until this issue. Replace the `update()` with a real removal — and note
each needs a run the last-ordinary-run rule does not protect, so build it with
`_second_run` before removing it:

```
    _track(owned_user, owned_library, game)
    playthrough = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, playthrough, key="gone")
```

Then delete the "Inert until #1011 stamps the column" sentence from
`test_stating_an_endpoint_for_a_removed_playthrough_is_refused`, keeping the
rest of the docstring. The two others are
`test_describing_a_removed_run_is_refused` and
`test_correcting_an_endpoint_of_a_removed_run_is_refused` — the third states a
start before removing the run, so keep that `_start(...)` line and give it the
second run:

```
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    _remove(owned_user, owned_library, run, key="gone")
```

All three keep asserting `_live_run`'s sentence, which the removal pair does not
share:

```
    assert refusal.value.sentence == (
        "That playthrough was removed from your library. Restore it before "
        "recording this."
    )
```

Leave `tests/test_playthrough_projection.py:255` alone. Its direct write is the
point: it proves the creation handler leaves an amendment alone, which is about
the handler and not about the command.

- [ ] **Step 2: Move the numbering test onto a dispatch**

`tests/test_playthrough_numbering.py:70` builds a removed row with
`make_run(tracked, removed_at=timezone.now())`. That module builds rows directly
rather than dispatching, so switching it pulls a whole command harness into a
read-layer test. Keep the direct write, and add a comment naming
`RemovePlaythrough` as what states the column in production:

```
    #: Stamped directly: this module tests the read, and
    #: RemovePlaythrough is what states the column in production.
```

- [ ] **Step 3: Run the whole family**

Run: `make test ARGS="tests/test_playthrough_command.py tests/test_playthrough_numbering.py tests/test_playthrough_projection.py tests/test_playthrough_events.py"`
Expected: PASS.

- [ ] **Step 4: Sweep the four comments**

`games/models.py`, on `Playthrough.removed_at`:

```
    #: Null means live. RemovePlaythrough states it; RestorePlaythrough
    #: clears it. Only the projector writes either.
```

`games/removal.py`, the comment naming the projections that stay out of
`REMOVABLE_MODELS`: it currently names `PlayerGame` alone. Name both, and give
the reason once — a projection is written only by its projector, and `remove()`
issues an `UPDATE` the next replay would overwrite.

`CLAUDE.md`, the `Playthrough` bullet. Replace the sentence reading "Its
`removed_at` is the projector's, stated by the command #1011 adds, which is why
it is absent from `REMOVABLE_MODELS`" with:

```
Its `removed_at` is the projector's, so it is absent from
`REMOVABLE_MODELS`: #1011 states it with `RemovePlaythrough` and
clears it with `RestorePlaythrough`, which refuse a lifecycle act
under a removed `PlayerGame`, refuse taking the last live ordinary
run off a tracked game, and read `BLOCKING_REFERRERS` -- empty until
#700 and #701 give a Session its reference to a run
```

Keep the bullet's surrounding sentences, and keep the clause about a blank name
reading as `Playthrough N`; `display_name()` now takes a `fallback` for a row no
number is counted across.

`docs/superpowers/specs/2026-09-04-playthrough-wave-design.md`, the `### #1011`
section: it says the refusal "is inert until the Sessions wave creates the
reference". Record what shipped — the empty registry, why it is not a system
check, and that the last-run rule counts live ordinary rows.

- [ ] **Step 5: Lint the prose**

Run: `make vale`
Expected: no errors, and no new warnings. `archive` where it means removal is a
build-failing error.

- [ ] **Step 6: Commit**

```bash
git add tests/ games/models.py games/removal.py CLAUDE.md docs/superpowers/specs/2026-09-04-playthrough-wave-design.md
git commit -m "State the removed column through its command"
```

---

### Task 8: The gate

**Files:** none.

- [ ] **Step 1: Confirm no migration is owed**

Run: `make makemigrations ARGS="--check --dry-run"`
Expected: no changes detected. If it wants a migration, revert whatever touched
the model — `removed_at` shipped with #679.

- [ ] **Step 2: Run the full gate**

Run: `make check`
Expected: green — lint, format check, mypy, vale, ts-check, vitest, and the
entire pytest suite including `e2e/`. Never verify with a subset.

- [ ] **Step 3: Fix and re-run**

If anything is red, fix it and run the full `make check` again. `ARGS` is for
iterating, never for the gate.

- [ ] **Step 4: Push and open the pull request**

```bash
git push -u origin claude/issue-1011-playthrough-removal
```

The pull request body states the four decisions the spec records, links
`docs/superpowers/specs/2026-09-06-issue-1011-playthrough-removal-design.md`,
and says `Closes #1011`.

---

## After the merge

The docs sweep is a separate act, per the repo's convention: drop
`docs/superpowers/plans/2026-09-06-issue-1011-playthrough-removal.md` and trim
the spec to what outlives the issue. #684 supplies the default run for every
game the #676 backfill tracked, at which point the last-ordinary-run rule
defends a property that actually holds. #700 and #701 fill `BLOCKING_REFERRERS`
with the Session reference, and #1012 is the first screen to call
`display_name(..., fallback=…)`.
