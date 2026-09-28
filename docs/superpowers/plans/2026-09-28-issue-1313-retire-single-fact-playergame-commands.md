# Retire single-fact PlayerGame commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `SetPlayerGameStatus` and `SetPlayerGameMastered`, leaving `RecordPlayerGameFacts` as the one command that states status or mastery, and refuse any future command that claims a retired name.

**Architecture:** First move every test off the two commands onto `RecordPlayerGameFacts` (green refactor). Then delete the commands and their `CommandName` members, and add `RETIRED_COMMAND_NAMES` with a guard in `Command.__init_subclass__`.

**Tech Stack:** Django, pytest (pytest-django, xdist), `make` targets.

**Spec:** `docs/superpowers/specs/2026-09-28-issue-1313-retire-single-fact-playergame-commands-design.md`

## Global Constraints

- Run tests only through `make`: `make test-fast ARGS="<path> -k <expr> -x"`. Never raw `pytest` / `uv run`.
- Wrap each pytest target in the shared lock: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make …`.
- Refusal tests call `dispatch`, never `record_facts` (it tracks an untracked game and retries).
- Comments follow the repo idiom: `#:` prefix, terse, state intent.
- Retired values: exactly `"library.playergame.set_status"` and `"library.playergame.set_mastered"`.

---

### Task 1: Move tests onto RecordPlayerGameFacts

**Files:**
- Modify: `tests/test_playergame_command.py` (imports lines 8-17; tests lines 200-490; setup at ~523 and ~684-695)
- Modify: `tests/test_projection_replay_gate.py` (imports 27-34; `build_stream` ~139-152; `build_neighbour` ~531-536)

**Interfaces:**
- Consumes: `RecordPlayerGameFacts(game_id: uuid.UUID, status: PlayerGameStatus | None, mastered: bool | None)` from `games.commands.playergame`.
- Produces: no production names. After this task no test imports `SetPlayerGameStatus` or `SetPlayerGameMastered`.

- [ ] **Step 1: Add the fact cases beside `track()`**

In `tests/test_playergame_command.py`, add `from typing import Any, NamedTuple` to the imports, and insert after `def track(...)`:

```python
class StatedFact(NamedTuple):
    """One fact RecordPlayerGameFacts states alone."""

    stated: dict[str, Any]
    #: What a freshly tracked row already holds.
    held: dict[str, Any]
    #: The other fact, changed first so it is no default.
    other: dict[str, Any]
    event_type: str
    payload: dict[str, Any]
    column: str
    value: Any
    default: Any


FACTS = [
    pytest.param(
        StatedFact(
            stated={"status": PlayerGameStatus.COMPLETED, "mastered": None},
            held={"status": PlayerGameStatus.UNPLAYED, "mastered": None},
            other={"status": None, "mastered": True},
            event_type="library.playergame.status_changed",
            payload={"status": "completed"},
            column="status",
            value=PlayerGameStatus.COMPLETED,
            default=PlayerGameStatus.UNPLAYED,
        ),
        id="status",
    ),
    pytest.param(
        StatedFact(
            stated={"status": None, "mastered": True},
            held={"status": None, "mastered": False},
            other={"status": PlayerGameStatus.COMPLETED, "mastered": None},
            event_type="library.playergame.mastered_changed",
            payload={"mastered": True},
            column="mastered",
            value=True,
            default=False,
        ),
        id="mastery",
    ),
]


def state(actor, library, game, facts: dict[str, Any], key: str):
    return dispatch(
        RecordPlayerGameFacts(game_id=game.pk, **facts),
        actor=actor,
        library=library,
        idempotency_key=key,
    )
```

- [ ] **Step 2: Replace the status and mastery twins (lines 200-490)**

Delete `test_setting_a_status_records_it_and_projects_it`, `test_a_live_status_change_states_the_day_it_happened`, `test_a_status_leaves_the_rest_of_the_row_alone`, `test_a_status_for_an_untracked_game_is_refused`, `test_a_status_for_a_game_another_library_tracks_is_refused`, `test_the_status_a_game_already_has_changes_nothing`, `test_one_idempotency_key_records_one_status_change`, and the five `mastery`/`mastering` twins through `test_one_idempotency_key_records_one_mastery_change`.

Keep `test_a_recorded_status_fact_states_the_day_too` and `test_a_mastery_fact_still_states_no_time` unchanged. Put in place of the deleted tests:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_stated_fact_records_it_and_projects_it(owned_user, owned_library, fact):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    state(owned_user, owned_library, game, fact.stated, "state")

    event = LibraryEvent.objects.get(event_type=fact.event_type)
    assert event.payload == fact.payload
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert getattr(row, fact.column) == fact.value


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_stated_fact_leaves_the_rest_of_the_row_alone(
    owned_user, owned_library, fact
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    state(owned_user, owned_library, game, fact.other, "other")
    untouched = [
        column
        for column in ("pk", "game_id", "tracked_at", "status", "mastered")
        if column != fact.column
    ]
    before = PlayerGame.objects.get()

    state(owned_user, owned_library, game, fact.stated, "state")

    after = PlayerGame.objects.get()
    assert [getattr(after, c) for c in untouched] == [
        getattr(before, c) for c in untouched
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_fact_for_an_untracked_game_is_refused(owned_user, owned_library, fact):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        state(owned_user, owned_library, game, fact.stated, "state")

    assert not LibraryEvent.objects.filter(event_type=fact.event_type).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_fact_for_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game, fact
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        state(owned_user, owned_library, shared_game, fact.stated, "state")

    assert getattr(PlayerGame.objects.get(), fact.column) == fact.default


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_fact_that_already_holds_changes_nothing(owned_user, owned_library, fact):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = state(owned_user, owned_library, game, fact.held, "hold")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "already records" in result.reason
    assert not LibraryEvent.objects.filter(event_type=fact.event_type).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_one_idempotency_key_records_one_fact_change(
    owned_user, owned_library, fact
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    first = state(owned_user, owned_library, game, fact.stated, "state")
    second = state(owned_user, owned_library, game, fact.stated, "state")

    assert (first.outcome, second.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
    assert LibraryEvent.objects.filter(event_type=fact.event_type).count() == 1
```

- [ ] **Step 3: Replace the setup dispatches**

In `test_an_exclusion_leaves_the_rest_of_the_row_alone`, replace the `SetPlayerGameMastered` dispatch with:

```python
    state(owned_user, owned_library, game, {"status": None, "mastered": True}, "master")
```

In `test_removing_a_game_leaves_the_rest_of_the_row_alone`, replace both setup dispatches with one:

```python
    state(
        owned_user,
        owned_library,
        game,
        {"status": PlayerGameStatus.PLAYED, "mastered": True},
        "play-and-master",
    )
```

Remove `SetPlayerGameMastered` and `SetPlayerGameStatus` from the import block. Remove `timezone` / `TemporalValue` imports only if no remaining test uses them (the kept `states_the_day_too` test uses both).

- [ ] **Step 4: Swap the replay gate dispatches**

In `tests/test_projection_replay_gate.py` `build_stream`, replace lines ~139-152 with:

```python
    run(
        RecordPlayerGameFacts(
            game_id=first.pk, status=PlayerGameStatus.PLAYED, mastered=None
        ),
        "status-first",
    )
    #: A second word, so the column is no constant.
    run(
        RecordPlayerGameFacts(
            game_id=second.pk, status=PlayerGameStatus.ABANDONED, mastered=None
        ),
        "status-second",
    )
    run(
        RecordPlayerGameFacts(game_id=first.pk, status=None, mastered=True),
        "mastered-first",
    )
    #: On, then off: the false is stated, not defaulted.
    run(
        RecordPlayerGameFacts(game_id=second.pk, status=None, mastered=True),
        "mastered-second-on",
    )
    run(
        RecordPlayerGameFacts(game_id=second.pk, status=None, mastered=False),
        "mastered-second-off",
    )
```

In `build_neighbour`, replace the `SetPlayerGameStatus(...)` tuple entry with:

```python
        (
            RecordPlayerGameFacts(
                game_id=game.pk, status=PlayerGameStatus.COMPLETED, mastered=None
            ),
            "neighbour-status",
        ),
```

In the import block, delete `SetPlayerGameMastered,` and `SetPlayerGameStatus,` and add `RecordPlayerGameFacts,` before `RemovePlayerGame,`.

- [ ] **Step 5: Run the moved tests**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_playergame_command.py tests/test_projection_replay_gate.py"`
Expected: PASS. `grep -n "SetPlayerGame\(Status\|Mastered\)" tests/` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add tests/test_playergame_command.py tests/test_projection_replay_gate.py
git commit -m "test(playergame): state status and mastery through RecordPlayerGameFacts (#1313)"
```

---

### Task 2: Delete the commands and guard retired names

**Files:**
- Modify: `games/events/dispatch.py` (enum lines 76-85; after `_COMMAND_REGISTRY` line 264; `__init_subclass__` ~287-303)
- Modify: `games/commands/playergame.py` (delete lines 123-172; `RecordPlayerGameFacts` docstring)
- Test: `tests/test_command_dispatch.py` (beside `test_the_allowlist_holds_real_commands_only`, ~698)

**Interfaces:**
- Consumes: Task 1 (no test imports the retired classes).
- Produces: `RETIRED_COMMAND_NAMES: frozenset[CommandNameValue]` in `games.events.dispatch`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_command_dispatch.py`, add `RETIRED_COMMAND_NAMES` to the `from games.events.dispatch import (...)` block, then after `test_the_allowlist_holds_real_commands_only`:

```python
def test_the_allowlist_holds_no_retired_name():
    #: A member no command claims never reaches __init_subclass__.
    assert not {name.value for name in CommandName} & RETIRED_COMMAND_NAMES


@pytest.mark.parametrize("retired", sorted(RETIRED_COMMAND_NAMES))
def test_a_command_cannot_claim_a_retired_name(retired):
    Revived = CommandVocabulary("Revived", {"ONLY": retired})

    with pytest.raises(TypeError, match="retired"):

        @dataclass(frozen=True, slots=True)
        class Reviver(Command):
            command_name: ClassVar[CommandVocabulary] = Revived.ONLY

            def build(self, context: CommandContext) -> Sequence[NewEvent]:
                return []
```

- [ ] **Step 2: Run to verify failure**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_command_dispatch.py -k retired"`
Expected: collection error, `ImportError: cannot import name 'RETIRED_COMMAND_NAMES'`.

- [ ] **Step 3: Add the set and the guard**

In `games/events/dispatch.py`, after `_COMMAND_REGISTRY: dict[...] = {}`:

```python
#: Removed from CommandName, never reused: an equal name over equal
#: fields is an equal digest, so an old key would replay as the new
#: command.
RETIRED_COMMAND_NAMES: frozenset[CommandNameValue] = frozenset(
    {
        "library.playergame.set_status",
        "library.playergame.set_mastered",
    }
)
```

In `Command.__init_subclass__`, directly after the `if not isinstance(name, CommandVocabulary): raise TypeError(...)` block and before the `#: The rebuilt class carries a bare __qualname__.` comment:

```python
        if name.value in RETIRED_COMMAND_NAMES:
            raise TypeError(
                f"{cls.__qualname__} claims {name.value!r}, a retired command "
                "name. A retired name is never reused."
            )
```

- [ ] **Step 4: Delete the enum members and the commands**

In `CommandName`, delete:

```python
    PLAYERGAME_SET_STATUS = "library.playergame.set_status"
    PLAYERGAME_SET_MASTERED = "library.playergame.set_mastered"
```

Append to the `CommandName` docstring:

```
    A retired member is deleted and its value joins
    RETIRED_COMMAND_NAMES; it is never renamed or reused.
```

In `games/commands/playergame.py`, delete the `SetPlayerGameStatus` and `SetPlayerGameMastered` classes with their decorators. Change the `RecordPlayerGameFacts` docstring first line to:

```python
    """State a status, a mastery, or both.

    The one command that states either fact. The game form states both
    at every save, so the two travel as one command. build() decides
    which already holds, under the lock, where a form's stale initial
    cannot reach it.
    """
```

- [ ] **Step 5: Run the tests**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="tests/test_command_dispatch.py tests/test_playergame_command.py tests/test_projection_replay_gate.py"`
Expected: PASS.

Run: `git grep -nE 'SetPlayerGame(Status|Mastered)|PLAYERGAME_SET_(STATUS|MASTERED)' -- ':!docs/superpowers'`
Expected: no output.

- [ ] **Step 6: Full check and commit**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
Expected: PASS (lint, format, mypy, ts-check, vitest, pytest incl. e2e).

```bash
git add games/events/dispatch.py games/commands/playergame.py tests/test_command_dispatch.py
git commit -m "refactor(playergame): retire SetPlayerGameStatus and SetPlayerGameMastered (#1313)"
```
