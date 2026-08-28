# Switch PlayerGame writes to commands — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every place that writes `Game.status` or `Game.mastered` states the fact as a command instead, and copies the folded projection back onto the catalog column.

**Architecture:** A new `games/writes/playergame.py` dispatches the command and mirrors the result; a new `games/views/playergame_writes.py` adapts that to a request and a toast. A rebuild refuses to write a live table, so the mirror cannot be a projector — it is a dual write at the call site, and the mirror reads the projection rather than what the caller asked for, so it cannot disagree with the fold. #678 deletes both modules when the reads move.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, Django Ninja, pytest / pytest-django / pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-08-28-issue-677-playergame-write-cutover-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never raw `uv run` / `pytest` / `pnpm`. Focused runs: `make test ARGS="tests/test_x.py -k name -x"`. Set `PYTEST_WORKERS=0` when debugging, because parallel output interleaves and `-x` stops only one worker.
- **The verification gate is the full `make check`** (lint + format-check + mypy + ts-check + vitest + the whole pytest suite including `e2e/`). `make check-fast` is for iterating only.
- **Python 3.14 is required.** A `SyntaxError` in an `except A, B:` line means the wrong interpreter, not broken code.
- **Never write to a `GeneratedField`**: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`.
- **Name variables with complete words** — `element` not `el`, `event` not `e`, `removeButton` not `removeBtn`. Applies to code you touch as well as code you add.
- **Name compound and primitive roles** — a `tuple`/`dict` passed between functions gets a `TypedDict`/`NamedTuple`/alias; a bare `str` standing for a domain concept gets a PEP 695 alias (`type LegacyStatus = str`).
- **One act, one verb** — an event type, its command and its projection column share one verb.
- **`run_in_transaction` refuses to run inside a transaction.** Every `dispatch()` this plan adds must be outside any `transaction.atomic()` block. `games/catalog_compat.py:18` `save_legacy_game_form` is atomic — dispatch after it returns, never inside it.
- **A test that drives a switched view must be transactional.** pytest-django wraps each test in a rolled-back transaction by default, and a dispatch cannot open one inside it, so every such test fails with `NestedTransactionNotSupported`. Two remedies, and which one applies depends on the file:
  - A pytest function or module: `pytest.mark.django_db(transaction=True)`, per test or as a module-level `pytestmark`.
  - A method of a `django.test.TestCase`: **move that method out of the class** to a module-level marked function. Do not switch the class to `TransactionTestCase` — that truncates the database between every test in it to serve one.

  Each task below names the files known to break. Any *other* file that fails this way takes the same treatment; `make check` in Task 9 is what finds the ones no task predicted.
- **Comments are short.** Match the surrounding density; the codebase uses `#:` for a note attached to the line below.
- Commit at the end of every task. Do not push and do not open a PR.

---

### Task 1: One map between the two status vocabularies

The catalog stores a letter (`Game.Status`) and the events store a word (`PlayerGameStatus`). #676 wrote the letter-to-word direction inside the backfill. The write path needs both directions, so both move to a module of their own that #678 can delete whole.

**Files:**
- Create: `games/playergame_status.py`
- Modify: `games/backfill/playergame.py:41-69` (the map, the exception and `player_status_for` move out; the module re-exports them)
- Test: `tests/test_playergame_status_map.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `type LegacyStatus = str`
  - `UnmappedLegacyStatus(ValueError)`, `UnmappedPlayerStatus(ValueError)`
  - `player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus`
  - `legacy_status_for(player_status: PlayerGameStatus) -> LegacyStatus`
  - `LEGACY_STATUS_TO_PLAYER_STATUS`, `PLAYER_STATUS_TO_LEGACY_STATUS`

- [ ] **Step 1: Write the failing test**

Create `tests/test_playergame_status_map.py`:

```python
"""Both directions of the map between Game.Status and PlayerGameStatus."""

import pytest

from games.models import Game, PlayerGameStatus
from games.playergame_status import (
    UnmappedLegacyStatus,
    UnmappedPlayerStatus,
    legacy_status_for,
    player_status_for,
)


@pytest.mark.parametrize("legacy_status", [member.value for member in Game.Status])
def test_every_legacy_status_maps_and_round_trips(legacy_status):
    player_status = player_status_for(legacy_status)
    assert legacy_status_for(player_status) == legacy_status


def test_shelved_has_no_legacy_status():
    #: Game.Status holds five members and PlayerGameStatus holds six. The
    #: catalog cannot store the sixth, so the mirror must raise rather than
    #: invent a letter.
    with pytest.raises(UnmappedPlayerStatus, match="shelved"):
        legacy_status_for(PlayerGameStatus.SHELVED)


def test_an_unknown_letter_is_refused():
    with pytest.raises(UnmappedLegacyStatus, match="'z'"):
        player_status_for("z")


def test_finished_is_completed():
    #: The two vocabularies disagree on the word for this one state, which is
    #: the reason the map exists at all.
    assert player_status_for(Game.Status.FINISHED) is PlayerGameStatus.COMPLETED
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `make test ARGS="tests/test_playergame_status_map.py -x"`
Expected: FAIL — `ModuleNotFoundError: No module named 'games.playergame_status'`

- [ ] **Step 3: Write the module**

Create `games/playergame_status.py`:

```python
"""Both directions of the map between the catalog's status letter and the
event vocabulary's word.

Issue #677. #676 needed one direction and kept it inside the backfill. The
write path holds both vocabularies at once, so both directions live here and
#678 deletes this module with the mirror that needs it.
"""

from collections.abc import Mapping

from games.models import Game, PlayerGameStatus

#: One letter of Game.Status.
type LegacyStatus = str  # "f"


class UnmappedLegacyStatus(ValueError):
    """Raised for a legacy letter the map does not know."""


class UnmappedPlayerStatus(ValueError):
    """Raised for a player status the catalog column cannot hold."""


#: A recorded payload cannot be upcast, so the letters become words here and
#: never reach an event. SHELVED is absent: no legacy column states it.
LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus] = {
    Game.Status.UNPLAYED: PlayerGameStatus.UNPLAYED,
    Game.Status.PLAYED: PlayerGameStatus.PLAYED,
    Game.Status.FINISHED: PlayerGameStatus.COMPLETED,
    Game.Status.RETIRED: PlayerGameStatus.RETIRED,
    Game.Status.ABANDONED: PlayerGameStatus.ABANDONED,
}

#: Inverted rather than written twice, so the two cannot fall out of step.
PLAYER_STATUS_TO_LEGACY_STATUS: Mapping[PlayerGameStatus, LegacyStatus] = {
    player_status: legacy_status
    for legacy_status, player_status in LEGACY_STATUS_TO_PLAYER_STATUS.items()
}


def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus:
    """The word a recorded payload carries for one legacy letter."""
    try:
        return LEGACY_STATUS_TO_PLAYER_STATUS[legacy_status]
    except KeyError:
        raise UnmappedLegacyStatus(
            f"{legacy_status!r} is not a legacy status this map knows. "
            "Every member of Game.Status names a PlayerGameStatus."
        ) from None


def legacy_status_for(player_status: PlayerGameStatus) -> LegacyStatus:
    """The letter the catalog column holds for one recorded word."""
    try:
        return PLAYER_STATUS_TO_LEGACY_STATUS[player_status]
    except KeyError:
        raise UnmappedPlayerStatus(
            f"{player_status!r} has no member of Game.Status. Nothing emits "
            "it while the catalog is the read source; #678 moves the reads "
            "and takes this guard with them."
        ) from None
```

- [ ] **Step 4: Point the backfill at it**

In `games/backfill/playergame.py`, delete the `LegacyStatus` alias, the
`LEGACY_STATUS_TO_PLAYER_STATUS` mapping, `UnmappedLegacyStatus` and
`player_status_for` (lines 43-69), and re-export them so
`tests/test_playergame_backfill.py`'s existing import keeps working:

```python
#: Re-exported: #677 moved the map out and this module's callers, including
#: its tests, still name it here.
from games.playergame_status import (
    LEGACY_STATUS_TO_PLAYER_STATUS as LEGACY_STATUS_TO_PLAYER_STATUS,
)
from games.playergame_status import LegacyStatus as LegacyStatus
from games.playergame_status import UnmappedLegacyStatus as UnmappedLegacyStatus
from games.playergame_status import player_status_for as player_status_for
```

The `X as X` form is what tells ruff the import is a deliberate re-export
rather than dead code. Drop the now-unused `Mapping` from the module's
`collections.abc` import if nothing else uses it.

- [ ] **Step 5: Run both test files**

Run: `make test ARGS="tests/test_playergame_status_map.py tests/test_playergame_backfill.py"`
Expected: PASS

- [ ] **Step 6: Lint, format and type check**

Run: `make lint && make format && make typecheck`
Expected: all clean

- [ ] **Step 7: Commit**

```bash
git add games/playergame_status.py games/backfill/playergame.py tests/test_playergame_status_map.py
git commit -m "Give the status map both directions and a module

#676 needed a letter to become a word and kept the map inside the
backfill. #677 needs the word to become a letter again, in a mirror that
#678 deletes, so the map moves where the deletion can reach it.

The second direction is the inversion of the first rather than a second
table, so the two cannot disagree. Shelved has no letter and raises."
```

---

### Task 2: A command that states both facts at once

The game form states a status and a mastery in one save. Two dispatches would be two acts for one act, and would make the form's second dispatch land after the first already committed. One composite command emits the events for the facts that differ.

`_tracked_game()` currently raises a bare `CommandRejected` for an untracked game. Task 3's heal has to recognise exactly that case, so it becomes its own class rather than something matched on a message.

**Files:**
- Modify: `games/events/dispatch.py:81-88` (one new `CommandName` member)
- Modify: `games/commands/playergame.py:30-39` (the new exception class) and the end of the file (the new command)
- Test: `tests/test_playergame_command.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `CommandName.PLAYERGAME_RECORD_FACTS = "library.playergame.record_facts"`
  - `PlayerGameNotTracked(CommandRejected)`
  - `RecordPlayerGameFacts(game_id: uuid.UUID, status: PlayerGameStatus | None, mastered: bool | None)` — both keyword fields are required at the call site; constructing one with neither stated raises `ValueError`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_command.py`. Add `RecordPlayerGameFacts` and
`PlayerGameNotTracked` to the existing import from `games.commands.playergame`,
and add `LibraryEvent` if it is not already imported.

```python
@pytest.mark.django_db(transaction=True)
def test_recording_both_facts_appends_two_events(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    result = dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.COMPLETED, mastered=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="facts",
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert result.sequences is not None
    assert result.sequences.last - result.sequences.first == 1
    row = PlayerGame.objects.get()
    assert (row.status, row.mastered) == (PlayerGameStatus.COMPLETED, True)


@pytest.mark.django_db(transaction=True)
def test_recording_one_fact_appends_one_event(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="facts",
    )

    types = list(
        LibraryEvent.objects.filter(library=owned_library)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )
    assert types == ["library.playergame.created", "library.playergame.status_changed"]
    assert PlayerGame.objects.get().mastered is False


@pytest.mark.django_db(transaction=True)
def test_recording_only_the_fact_that_differs(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
    )

    #: Same status, new mastery: the status event must not be repeated.
    dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second",
    )

    assert (
        LibraryEvent.objects.filter(
            library=owned_library, event_type="library.playergame.status_changed"
        ).count()
        == 1
    )
    assert PlayerGame.objects.get().mastered is True


@pytest.mark.django_db(transaction=True)
def test_recording_facts_that_already_hold_is_unchanged(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    before = LibraryEvent.objects.filter(library=owned_library).count()

    result = dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.UNPLAYED, mastered=False
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="facts",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert result.sequences is None
    assert LibraryEvent.objects.filter(library=owned_library).count() == before


def test_a_command_that_states_no_fact_cannot_be_built():
    with pytest.raises(ValueError, match="states no fact"):
        RecordPlayerGameFacts(game_id=uuid.uuid7(), status=None, mastered=None)


@pytest.mark.django_db(transaction=True)
def test_recording_facts_for_an_untracked_game_is_its_own_rejection(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    #: PlayerGameNotTracked rather than CommandRejected, because the write
    #: path heals this one case and must not match on a message to find it.
    with pytest.raises(PlayerGameNotTracked):
        dispatch(
            RecordPlayerGameFacts(
                game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="facts",
        )
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `make test ARGS="tests/test_playergame_command.py -k 'record or untracked' -x"`
Expected: FAIL — `ImportError: cannot import name 'RecordPlayerGameFacts'`

- [ ] **Step 3: Add the command name**

In `games/events/dispatch.py`, add the member to `CommandName` after
`PLAYERGAME_RESTORE`:

```python
    PLAYERGAME_RECORD_FACTS = "library.playergame.record_facts"
```

- [ ] **Step 4: Give the untracked rejection its own class**

In `games/commands/playergame.py`, replace `_tracked_game` (lines 30-39) with:

```python
class PlayerGameNotTracked(CommandRejected):
    """This library has no projection row for the game.

    Its own class because the write path heals exactly this case, by
    tracking the game and dispatching again. Matching on a message is the
    alternative and it is not one.
    """


def _tracked_game(context: CommandContext, game_id: uuid.UUID) -> PlayerGame:
    """The projection row, never the catalog."""
    try:
        return PlayerGame.objects.get(library=context.library, game_id=game_id)
    except PlayerGame.DoesNotExist:
        raise PlayerGameNotTracked(
            f"This library tracks no game {game_id}. A recorded fact belongs "
            "to a tracked game, and #676 backfills one for every game a "
            "library has."
        ) from None
```

- [ ] **Step 5: Add the composite command**

Append to `games/commands/playergame.py`:

```python
@dataclass(frozen=True, slots=True)
class RecordPlayerGameFacts(Command):
    """State the status, the mastery, or both, as one act.

    The game form states both facts on every save whether or not the player
    touched either, so the two travel as one command rather than two. Which
    of them already holds is decided in `build`, under the stream-head lock,
    rather than from a form's `changed_data`, where a stale `initial` reaches
    it.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_RECORD_FACTS
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: None means this act does not state the fact, and is a field value like
    #: any other, so it enters the fingerprint.
    status: PlayerGameStatus | None
    mastered: bool | None

    def __post_init__(self) -> None:
        if self.status is None and self.mastered is None:
            raise ValueError(
                "RecordPlayerGameFacts states no fact. A command that asks "
                "for nothing would still claim an idempotency key and write "
                "a record for a request that expressed no intent."
            )

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        events: list[NewEvent] = []
        if self.status is not None and tracked.status != self.status:
            events.append(
                PLAYERGAME_STATUS_CHANGED.new(
                    aggregate_id=tracked.pk,
                    #: A test pins Literal and choices equal.
                    payload={"status": cast("StatusValue", self.status.value)},
                )
            )
        if self.mastered is not None and tracked.mastered != self.mastered:
            events.append(
                PLAYERGAME_MASTERED_CHANGED.new(
                    aggregate_id=tracked.pk,
                    payload={"mastered": self.mastered},
                )
            )
        if not events:
            return Unchanged(
                f"This library already records the stated facts for game "
                f"{self.game_id}."
            )
        return events
```

- [ ] **Step 6: Run the whole command suite**

Run: `make test ARGS="tests/test_playergame_command.py tests/test_command_dispatch.py"`
Expected: PASS. `tests/test_command_dispatch.py:649` asserts no `CommandName`
member starts with `test.`, which the new member satisfies.

- [ ] **Step 7: Confirm a rebuild still agrees**

Run: `make test ARGS="tests/test_playergame_projection.py tests/test_projection_rebuild.py"`
Expected: PASS. The composite reuses #672's and #673's event types, so the
projector, the replay and every rebuild are untouched — this run proves it.

- [ ] **Step 8: Lint, format, type check and commit**

```bash
make lint && make format && make typecheck
git add games/events/dispatch.py games/commands/playergame.py tests/test_playergame_command.py
git commit -m "Let one command state a status and a mastery

The game form states both facts on every save. Two dispatches would make
one act two, and the second would land after the first committed. The
composite emits an event per fact that differs and is Unchanged when
neither does, reusing the two event types rather than adding a third.

A command that states neither fact refuses to be constructed: it would
claim an idempotency key for a request that asked for nothing.

The untracked rejection takes its own class, because the write path heals
that one case and cannot find it by reading a message."
```

---

### Task 3: The write path

One module holds both vocabularies, dispatches, heals a game with no row, mirrors the fold onto the catalog, and turns each failure into something a view can answer with.

**Files:**
- Create: `games/writes/__init__.py`
- Create: `games/writes/playergame.py`
- Test: `tests/test_playergame_write_path.py` (create)

**Interfaces:**
- Consumes: `legacy_status_for` and `player_status_for` from Task 1; `RecordPlayerGameFacts`, `PlayerGameNotTracked` from Task 2.
- Produces:
  - `PlayerGameWriteFailed(Exception)` with `.message: str` and `.status_code: int`
  - `new_correlation_id() -> uuid.UUID`
  - `track_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None`
  - `record_facts(actor: User, game: Game, *, status: LegacyStatus | None = None, mastered: bool | None = None, correlation_id: uuid.UUID) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playergame_write_path.py`:

```python
"""The dual write: state the fact as a command, mirror the fold back."""

import uuid

import pytest
from django.http import Http404

from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus
from games.writes.playergame import (
    PlayerGameWriteFailed,
    new_correlation_id,
    record_facts,
    track_game,
)


@pytest.fixture
def tracked_game(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game


@pytest.mark.django_db(transaction=True)
def test_a_status_reaches_the_event_the_projection_and_the_catalog(
    owned_user, owned_library, tracked_game
):
    record_facts(
        owned_user,
        tracked_game,
        status=Game.Status.FINISHED,
        correlation_id=new_correlation_id(),
    )

    event = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playergame.status_changed"
    )
    assert event.payload == {"status": "completed"}
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
    tracked_game.refresh_from_db()
    assert tracked_game.status == Game.Status.FINISHED


@pytest.mark.django_db(transaction=True)
def test_the_mirror_writes_the_fold_and_not_the_request(
    owned_user, owned_library, tracked_game
):
    #: A catalog column moved behind the projection's back is corrected to
    #: what the events fold to, not to what this call asked for. The command
    #: finds the projection already Played, returns Unchanged, and the mirror
    #: still repairs the catalog.
    record_facts(
        owned_user,
        tracked_game,
        status=Game.Status.PLAYED,
        correlation_id=new_correlation_id(),
    )
    Game.objects.filter(pk=tracked_game.pk).update(status=Game.Status.RETIRED)

    record_facts(
        owned_user,
        tracked_game,
        status=Game.Status.PLAYED,
        correlation_id=new_correlation_id(),
    )

    tracked_game.refresh_from_db()
    assert tracked_game.status == Game.Status.PLAYED


@pytest.mark.django_db(transaction=True)
def test_an_untracked_game_heals_and_records(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic")

    record_facts(
        owned_user,
        game,
        status=Game.Status.PLAYED,
        correlation_id=new_correlation_id(),
    )

    types = list(
        LibraryEvent.objects.filter(library=owned_library)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )
    assert types == ["library.playergame.created", "library.playergame.status_changed"]
    game.refresh_from_db()
    assert game.status == Game.Status.PLAYED


@pytest.mark.django_db(transaction=True)
def test_one_act_shares_one_correlation_id(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic")
    correlation_id = new_correlation_id()

    record_facts(
        owned_user, game, status=Game.Status.PLAYED, correlation_id=correlation_id
    )

    #: The heal's TrackGame and the retried facts are one act, so the stream
    #: says so rather than recording two coincidences.
    recorded = set(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "correlation_id", flat=True
        )
    )
    assert recorded == {correlation_id}


@pytest.mark.django_db(transaction=True)
def test_the_heal_does_not_loop(owned_user, owned_library, monkeypatch):
    game = Game.objects.create(library=owned_library, name="Tunic")

    #: A TrackGame that records nothing leaves the row still missing. The
    #: heal must give up on the second rejection rather than recurse.
    monkeypatch.setattr(
        "games.writes.playergame.track_game", lambda *args, **kwargs: None
    )
    with pytest.raises(PlayerGameWriteFailed) as failure:
        record_facts(
            owned_user,
            game,
            status=Game.Status.PLAYED,
            correlation_id=new_correlation_id(),
        )
    assert failure.value.status_code == 409


@pytest.mark.django_db(transaction=True)
def test_another_librarys_game_is_not_found(other_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    #: The actor names the library, so an actor who does not own this one is
    #: refused. A 404 rather than a 403: the charter says another library's
    #: object is absent, not forbidden.
    with pytest.raises(Http404):
        track_game(other_user, game, correlation_id=new_correlation_id())


@pytest.mark.django_db(transaction=True)
def test_an_exhausted_retry_budget_asks_the_player_to_try_again(
    owned_user, tracked_game, monkeypatch
):
    def exhausted(*args, **kwargs):
        raise RetryBudgetExhausted(3)

    monkeypatch.setattr("games.writes.playergame.dispatch", exhausted)
    with pytest.raises(PlayerGameWriteFailed) as failure:
        record_facts(
            owned_user,
            tracked_game,
            status=Game.Status.PLAYED,
            correlation_id=new_correlation_id(),
        )
    assert failure.value.status_code == 409
    assert "try again" in failure.value.message


@pytest.mark.django_db(transaction=True)
def test_a_reused_key_over_different_input_says_it_will_never_work(
    owned_user, tracked_game, monkeypatch
):
    def mismatched(*args, **kwargs):
        raise IdempotencyKeyMismatch("that key belongs to another request")

    monkeypatch.setattr("games.writes.playergame.dispatch", mismatched)
    with pytest.raises(PlayerGameWriteFailed) as failure:
        record_facts(
            owned_user,
            tracked_game,
            status=Game.Status.PLAYED,
            correlation_id=new_correlation_id(),
        )
    assert failure.value.status_code == 409
    assert "cannot be retried" in failure.value.message
```

`other_user` is defined as a fixture in `tests/test_playergame_command.py`.
Copy it and `other_library` into this file rather than importing across test
modules:

```python
@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")
```

- [ ] **Step 2: Run and confirm the failure**

Run: `make test ARGS="tests/test_playergame_write_path.py -x"`
Expected: FAIL — `ModuleNotFoundError: No module named 'games.writes'`

- [ ] **Step 3: Create the package**

Create `games/writes/__init__.py`:

```python
"""Dual writes: a fact stated as a command, then mirrored onto the catalog.

Issue #677. Every module here exists because a read has not moved yet, so
each one is deleted by the issue that moves its reads.
"""
```

- [ ] **Step 4: Write the write path**

Create `games/writes/playergame.py`:

```python
"""State a PlayerGame fact as a command, then mirror the fold onto the catalog.

Issue #677. A projector folding these events into `Game.status` would be one
write path rather than two, and cannot be built: `only_shadow_writes()`
refuses every statement a rebuild makes against a live table. So the mirror
is a dual write at the call site, and it copies the *projection* rather than
what the caller asked for — a mirror that reads the fold cannot disagree
with it, and #906 made a declined request an ordinary outcome.

This module takes an actor rather than a request, because `authorize()`
checks `library.user_id == actor.pk` and the actor therefore already names
the library. `games/views/playergame_writes.py` is the half that knows about
requests and toasts. #678 deletes both.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from django.contrib.auth.models import User
from django.http import Http404

from games.commands.playergame import (
    PlayerGameNotTracked,
    RecordPlayerGameFacts,
    TrackGame,
)
from games.events.dispatch import (
    Command,
    CommandNotPermitted,
    CommandRejected,
    dispatch,
)
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.models import Game, PlayerGame, PlayerGameStatus, UserLibrary
from games.playergame_status import (
    LegacyStatus,
    legacy_status_for,
    player_status_for,
)


class PlayerGameWriteFailed(Exception):
    """A fact the player stated could not be recorded.

    It carries the status code as well as the sentence, because the two
    conflict leaves disagree about what to do next and the API answers with
    the number while a page answers with the words.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def new_correlation_id() -> uuid.UUID:
    """One per request.

    A refund dispatches once per game of the purchase and a heal dispatches
    three times. Without a shared id the stream records each as its own act.
    """
    return uuid.uuid7()


@contextmanager
def _translated() -> Iterator[None]:
    """Turn every command failure into something a view can answer with."""
    try:
        yield
    except CommandNotPermitted as error:
        #: The charter: another library's object is absent, not forbidden.
        raise Http404("No such game.") from error
    except RetryBudgetExhausted as error:
        raise PlayerGameWriteFailed(
            "Another change reached this game first. Nothing was recorded; try again.",
            409,
        ) from error
    except IdempotencyKeyMismatch as error:
        #: Unreachable while every key is minted per request. Handled anyway,
        #: so a future keyed caller meets a 409 rather than a 500.
        raise PlayerGameWriteFailed(
            "This request cannot be retried, because its key already belongs "
            "to a different one.",
            409,
        ) from error
    except CommandRejected as error:
        raise PlayerGameWriteFailed(str(error), 409) from error


def _dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    correlation_id: uuid.UUID,
) -> None:
    dispatch(
        command,
        actor=actor,
        library=library,
        #: Per request, thus it deduplicates nothing; #906's state comparison
        #: is what absorbs a repeat. See the design's key section.
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )


def track_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None:
    """Track one catalog game in the actor's library."""
    with _translated():
        _dispatch(
            TrackGame(game_id=game.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def record_facts(
    actor: User,
    game: Game,
    *,
    status: LegacyStatus | None = None,
    mastered: bool | None = None,
    correlation_id: uuid.UUID,
) -> None:
    """State one fact or two, then mirror the fold onto the catalog.

    `status` is a letter of `Game.Status`, because every caller holds one.
    A `None` means this act does not state that fact.
    """
    library = actor.library
    command = RecordPlayerGameFacts(
        game_id=game.pk,
        status=None if status is None else player_status_for(status),
        mastered=mastered,
    )
    with _translated():
        try:
            _dispatch(
                command, actor=actor, library=library, correlation_id=correlation_id
            )
        except PlayerGameNotTracked:
            #: #676 backfilled a row for every game a library held and
            #: add_game tracks each new one, so this means the two fell out
            #: of step: a TrackGame that did not commit, a restored dump, a
            #: game the sample loader made. Creating the catalog row and
            #: tracking it are two commits, because run_in_transaction
            #: refuses a nested transaction, so the gap is reachable.
            #: One retry, never a loop: a second rejection is a real one.
            track_game(actor, game, correlation_id=correlation_id)
            _dispatch(
                command, actor=actor, library=library, correlation_id=correlation_id
            )
    _mirror(game, library)


def _mirror(game: Game, library: UserLibrary) -> None:
    """Copy the folded row onto the catalog columns #678 has not moved yet."""
    row = PlayerGame.objects.get(library=library, game=game)
    status = legacy_status_for(PlayerGameStatus(row.status))
    if (game.status, game.mastered) == (status, row.mastered):
        return
    game.status = status
    game.mastered = row.mastered
    #: A full field save, so the pre_save audit signal fires and legacy
    #: GameStatusChange history continues exactly as today.
    game.save(update_fields=["status", "mastered"])
```

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_playergame_write_path.py"`
Expected: PASS

If `test_the_heal_does_not_loop` fails with a `RecursionError`, the heal is
calling itself; it must call `track_game` and then `_dispatch`, never
`record_facts`.

- [ ] **Step 6: Lint, format, type check and commit**

```bash
make lint && make format && make typecheck
git add games/writes tests/test_playergame_write_path.py
git commit -m "Add the one place that states a PlayerGame fact

A projector folding these events onto Game.status cannot exist: a rebuild
refuses every statement against a live table, and the catalog column is
old storage rather than a projection. So the mirror is a dual write, and
it copies the projection rather than the request — a mirror that reads
the fold cannot disagree with it, and a declined request is ordinary now.

An untracked game heals once and never loops. Creating a catalog row and
tracking it are two commits, so the gap between them is reachable and a
game caught in it would otherwise be unwritable forever.

One correlation id per act, because a refund dispatches once per game."
```

---

### Task 4: Refuse a transaction the dispatcher cannot nest in

`run_in_transaction` opens the transaction it retries, so it refuses to run inside one and offers no escape. Every dispatch this issue adds depends on that, and nothing today states the dependency. `ATOMIC_REQUESTS` is the one that can be turned on from outside the code.

**Files:**
- Modify: `games/checks.py` (append)
- Modify: `games/views/purchase.py:303`, `games/views/purchase.py:620` (one comment each)
- Test: `tests/test_atomic_requests_check.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `check_atomic_requests(...) -> list[CheckMessage]`, error id `games.E008`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_atomic_requests_check.py`:

```python
"""ATOMIC_REQUESTS is what makes every command dispatch legal."""

from django.test import override_settings

from games.checks import check_atomic_requests


def test_no_error_when_no_alias_wraps_a_request():
    assert check_atomic_requests() == []


def test_a_wrapped_alias_is_refused(settings):
    wrapped = {
        alias: {**config, "ATOMIC_REQUESTS": True}
        for alias, config in settings.DATABASES.items()
    }
    with override_settings(DATABASES=wrapped):
        errors = check_atomic_requests()

    assert [error.id for error in errors] == ["games.E008"]
    assert "default" in errors[0].msg
```

- [ ] **Step 2: Run and confirm the failure**

Run: `make test ARGS="tests/test_atomic_requests_check.py -x"`
Expected: FAIL — `ImportError: cannot import name 'check_atomic_requests'`

- [ ] **Step 3: Add the check**

Append to `games/checks.py`, and add `from django.conf import settings` to its
imports:

```python
@register()
def check_atomic_requests(
    *,
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[CheckMessage]:
    """Refuse a wrapping transaction the command dispatcher cannot nest in."""
    wrapped = sorted(
        alias
        for alias, config in settings.DATABASES.items()
        if config.get("ATOMIC_REQUESTS")
    )
    if not wrapped:
        return []
    return [
        Error(
            f"ATOMIC_REQUESTS is on for {', '.join(wrapped)}.",
            hint=(
                "run_in_transaction opens the transaction it retries, so it "
                "refuses to run inside one: every view that dispatches a "
                "command would raise NestedTransactionNotSupported at "
                "request time. Wrap the work that needs a transaction, not "
                "the request."
            ),
            id="games.E008",
        )
    ]
```

Registered with no tag rather than `Tags.database`, because database-tagged
checks are skipped unless a database is requested and this one reads only
settings.

- [ ] **Step 4: Comment the two atomic helpers that survive**

`_create_separate_purchases` (`games/views/purchase.py:303`) and
`split_purchase` (`games/views/purchase.py:620`) keep their
`@transaction.atomic` and are unaffected, because neither dispatches. They
are the shape of the next mistake. Add above each decorator:

```python
#: No command may be dispatched inside this block: run_in_transaction
#: refuses to nest, so a dispatch here raises at request time.
```

`games/catalog_compat.py:18` `save_legacy_game_form` is atomic for the same
reason and gets the same comment.

- [ ] **Step 5: Run the test and commit**

```bash
make test ARGS="tests/test_atomic_requests_check.py"
make lint && make format && make typecheck
git add games/checks.py games/views/purchase.py games/catalog_compat.py tests/test_atomic_requests_check.py
git commit -m "Say out loud what makes a dispatch legal

Every command this wave adds to a view depends on nothing above it having
opened a transaction, and nothing says so. ATOMIC_REQUESTS is the one
that can be turned on from outside the code, and turning it on breaks
every write path at request time rather than at check time.

The three atomic blocks that survive take a comment, because they are the
shape of the next mistake rather than an instance of it."
```

---

### Task 5: The game form and its two views

`GameForm` stops writing the two columns; `add_game` and `edit_game` state them as facts. This is the task that breaks the existing suite, so it migrates the tests it breaks.

**Files:**
- Create: `games/views/playergame_writes.py`
- Modify: `games/forms.py:852-865` (`GameForm.Meta.fields`, plus declared fields, `field_order`, `__init__` and `save`)
- Modify: `games/views/game.py:225-244` (`add_game`), `games/views/game.py:300-305` (`edit_game`)
- Modify: `tests/test_rendered_pages.py:267-280`, `tests/test_catalog_write_views.py`, `tests/test_returns_views.py`, `tests/test_library_form_isolation.py`
- Test: `tests/test_playergame_view_cutover.py` (create)

**Interfaces:**
- Consumes: `record_facts`, `track_game`, `new_correlation_id`, `PlayerGameWriteFailed` from Task 3.
- Produces:
  - `record_facts_for_request(request, game, *, status=None, mastered=None, correlation_id) -> bool`
  - `track_game_for_request(request, game, *, correlation_id) -> bool`

  Both return `True` on success. On a `PlayerGameWriteFailed` they add a
  `messages.error` and return `False`; an `Http404` propagates.

- [ ] **Step 1: Write the view-layer adapter**

Create `games/views/playergame_writes.py`:

```python
"""The request-shaped half of the PlayerGame write path.

Issue #677. `games/writes/playergame.py` takes an actor and raises; this
takes a request, shows the failure as a toast, and says whether the view
should carry on. #678 deletes both.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game
from games.playergame_status import LegacyStatus
from games.writes.playergame import (
    PlayerGameWriteFailed,
    record_facts,
    track_game,
)


def track_game_for_request(
    request: HttpRequest, game: Game, *, correlation_id: uuid.UUID
) -> bool:
    """Track the game. Message the player and answer False on a failure."""
    try:
        track_game(cast(User, request.user), game, correlation_id=correlation_id)
    except PlayerGameWriteFailed as failure:
        messages.error(request, failure.message)
        return False
    return True


def record_facts_for_request(
    request: HttpRequest,
    game: Game,
    *,
    status: LegacyStatus | None = None,
    mastered: bool | None = None,
    correlation_id: uuid.UUID,
) -> bool:
    """State the facts. Message the player and answer False on a failure."""
    try:
        record_facts(
            cast(User, request.user),
            game,
            status=status,
            mastered=mastered,
            correlation_id=correlation_id,
        )
    except PlayerGameWriteFailed as failure:
        messages.error(request, failure.message)
        return False
    return True
```

- [ ] **Step 2: Write the failing view tests**

Create `tests/test_playergame_view_cutover.py`:

```python
"""Every switched view states its fact as a command."""

import pytest
from django.urls import reverse

from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
)

GAME_PAYLOAD = {"name": "Outer Wilds", "status": "u", "wikidata": ""}


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.mark.django_db(transaction=True)
def test_adding_a_game_tracks_it_and_records_its_facts(logged_in, owned_library):
    response = logged_in.post(
        reverse("games:add_game"), {**GAME_PAYLOAD, "status": "f", "mastered": "on"}
    )

    assert response.status_code == 302
    game = Game.objects.get(name="Outer Wilds")
    assert (game.status, game.mastered) == ("f", True)
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert (row.status, row.mastered) == (PlayerGameStatus.COMPLETED, True)


@pytest.mark.django_db(transaction=True)
def test_a_game_created_as_finished_records_no_status_change(logged_in):
    #: The pre_save audit signal returns early when no previous row exists,
    #: so a game created at a non-default status records no transition today.
    #: Assigning the two values before the first save keeps that exactly true.
    logged_in.post(reverse("games:add_game"), {**GAME_PAYLOAD, "status": "f"})

    assert GameStatusChange.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_adding_a_game_records_one_creation_event(logged_in, owned_library):
    logged_in.post(reverse("games:add_game"), {**GAME_PAYLOAD, "status": "u"})

    types = list(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "event_type", flat=True
        )
    )
    #: The row is created at the state the form states, so the composite
    #: finds both facts already holding and appends nothing.
    assert types == ["library.playergame.created"]


@pytest.mark.django_db(transaction=True)
def test_editing_a_games_status_records_the_event_and_the_audit_row(
    logged_in, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    logged_in.post(
        reverse("games:edit_game", args=[game.id]),
        {**GAME_PAYLOAD, "status": "p"},
    )

    game.refresh_from_db()
    assert game.status == "p"
    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED
    #: Legacy history is unchanged by the cutover.
    assert GameStatusChange.objects.filter(game=game, new_status="p").count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_edit_form_shows_the_games_current_status(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="f")

    response = logged_in.get(reverse("games:edit_game", args=[game.id]))

    #: status and mastered left Meta.fields, so ModelForm no longer seeds
    #: their initial from the instance and the form must do it. Asserted on
    #: the HTML rather than a form object: the view renders through
    #: render_page(), which returns no template context to read.
    assert '<option value="f" selected>' in response.content.decode()
```

- [ ] **Step 3: Run and confirm they fail**

Run: `make test ARGS="tests/test_playergame_view_cutover.py -x"`
Expected: FAIL — no `PlayerGame` row is created, because nothing dispatches yet.

- [ ] **Step 4: Take the two columns off the form**

In `games/forms.py`, inside `GameForm`:

Remove `"status"` and `"mastered"` from `Meta.fields`, leaving:

```python
        fields = (
            "name",
            "sort_name",
            "platform",
            "year_released",
            "original_year_released",
            "wikidata",
        )
```

Declare them as plain form fields beside `platform`:

```python
    #: Plain form fields rather than model fields: form.save() must not write
    #: either column. The write path is the single writer, and #678 deletes
    #: these two when the reads move to the projection.
    status = forms.ChoiceField(choices=Game.Status.choices, required=True)
    mastered = forms.BooleanField(required=False)
```

Pin the rendered order, because a declared field that names no model field is
appended after the model fields and these two would drop to the bottom of the
form:

```python
    field_order = (
        "name",
        "sort_name",
        "platform",
        "year_released",
        "original_year_released",
        "status",
        "mastered",
        "wikidata",
    )
```

Seed their initial from the instance at the end of `__init__`, because
`model_to_dict` no longer covers them:

```python
        if self.instance.pk is not None:
            self.initial.setdefault("status", self.instance.status)
            self.initial.setdefault("mastered", self.instance.mastered)
```

Add a `save` that assigns them only for a new row:

```python
    def save(self, commit=True):
        game = super().save(commit=False)
        #: A new row starts at the state the form states, so the mirror finds
        #: the catalog and the projection already equal. Creating it at the
        #: column default and letting the mirror move it would append a
        #: GameStatusChange that does not exist today: the pre_save audit
        #: signal returns early when no previous row exists.
        if game._state.adding:
            game.status = self.cleaned_data["status"]
            game.mastered = self.cleaned_data["mastered"]
        if commit:
            game.save()
            self.save_m2m()
        return game
```

An edit takes no such assignment: the instance keeps the persisted values
through `save_legacy_game_form`, and the mirror moves them afterwards, which
is what fires the audit signal exactly once.

- [ ] **Step 5: Switch `add_game`**

In `games/views/game.py`, add the imports:

```python
from games.views.playergame_writes import (
    record_facts_for_request,
    track_game_for_request,
)
from games.writes.playergame import new_correlation_id
```

Replace lines 224-244 — the decorator through the last `return redirect(...)`
of the `if game is not None:` branch. The `return render_page(...)` tail at
lines 246-269 is untouched.

```python
@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    form = GameForm(request.POST or None, library=library)
    if form.is_valid():
        game = _save_game_form_or_add_wikidata_error(form)
        if game is not None:
            correlation_id = new_correlation_id()
            recorded = track_game_for_request(
                request, game, correlation_id=correlation_id
            ) and record_facts_for_request(
                request,
                game,
                status=form.cleaned_data["status"],
                mastered=form.cleaned_data["mastered"],
                correlation_id=correlation_id,
            )
            if not recorded:
                #: The catalog row stands and the facts do not. Re-rendering
                #: the form would invite a resubmit that creates a second
                #: game, and chaining onward would hide the error, so the
                #: player lands on the list with the toast.
                return redirect(return_url(request, fallback="games:list_games"))
            origin = origin_from(request)
            if "submit_and_redirect" in request.POST:
                return redirect(
                    action_url(
                        "games:add_purchase_for_game", game_id=game.id, origin=origin
                    )
                )
            elif "submit_and_create_session" in request.POST:
                return redirect(
                    action_url(
                        "games:add_session_for_game", game_id=game.id, origin=origin
                    )
                )
            return redirect(return_url(request, fallback="games:list_games"))
```

- [ ] **Step 6: Switch `edit_game`**

Replace lines 299-311 — the whole function. `game` is already bound at line
302, so the helper's return value keeps being tested only for `None`, exactly
as the line being replaced does.

```python
@login_required
def edit_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    form = GameForm(request.POST or None, instance=game, library=library)
    if form.is_valid() and _save_game_form_or_add_wikidata_error(form) is not None:
        #: Both outcomes land in the same place, so a failure needs no branch
        #: of its own: the toast the helper adds carries the difference.
        record_facts_for_request(
            request,
            game,
            status=form.cleaned_data["status"],
            mastered=form.cleaned_data["mastered"],
            correlation_id=new_correlation_id(),
        )
        return redirect(return_url(request, fallback="games:list_games"))
    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit Game",
        scripts=ModuleScript("dist/elements/search-select.js"),
    )
```

- [ ] **Step 7: Run the new tests**

Run: `make test ARGS="tests/test_playergame_view_cutover.py"`
Expected: PASS

- [ ] **Step 8: Migrate the existing tests these views break**

Each of these drives a successful POST through a switched view. pytest-django's
default rolls the test back inside a transaction, and `run_in_transaction`
refuses to open one inside another, so each fails with
`NestedTransactionNotSupported` until it becomes transactional.

Run them first to see the failure:

Run: `make test ARGS="tests/test_catalog_write_views.py tests/test_returns_views.py tests/test_library_form_isolation.py tests/test_rendered_pages.py" PYTEST_WORKERS=0`
Expected: FAIL with `NestedTransactionNotSupported`

Then:

- `tests/test_catalog_write_views.py:11` — change
  `pytestmark = pytest.mark.django_db` to
  `pytestmark = pytest.mark.django_db(transaction=True)`.
- `tests/test_library_form_isolation.py:32` — the same change.
- `tests/test_returns_views.py` — has no `pytestmark`; its database access
  comes from the `owned_library`/`owned_user` fixtures and one explicit `db`.
  Add `pytestmark = pytest.mark.django_db(transaction=True)` below the
  `GAME_FORM` constant. pytest-django's `db` fixture defers to
  `transactional_db` when both are requested, so no fixture needs an edit.
- `tests/test_rendered_pages.py:267` — this one is not a marker edit.
  `test_add_game_submit_and_create_session_redirects` is a method of
  `RenderedPagesTest`, a `django.test.TestCase`. Move that single method out
  of the class, to the end of the file, as a module-level pytest function:

```python
@pytest.mark.django_db(transaction=True)
def test_add_game_submit_and_create_session_redirects(client, owned_user):
    #: Moved out of RenderedPagesTest by #677: the POST now dispatches a
    #: command, and run_in_transaction refuses to open a transaction inside
    #: the one a TestCase wraps every test in. Making the whole class
    #: transactional would truncate between each of its tests to serve one.
    client.force_login(owned_user)

    response = client.post(
        reverse("games:add_game"),
        {"name": "New Session Game", "status": "u", "submit_and_create_session": ""},
    )

    game = Game.objects.get(name="New Session Game")
    assertRedirects(
        response,
        reverse("games:add_session_for_game", kwargs={"game_id": game.id}),
    )
```

  Add `import pytest` and
  `from pytest_django.asserts import assertRedirects` to the file's imports if
  absent. `test_form_errors_render_with_component_class` stays where it is:
  it POSTs an invalid payload, so it never saves and never dispatches.

- [ ] **Step 9: Re-run the migrated files**

Run: `make test ARGS="tests/test_catalog_write_views.py tests/test_returns_views.py tests/test_library_form_isolation.py tests/test_rendered_pages.py"`
Expected: PASS

- [ ] **Step 10: Confirm the projection and the catalog still agree**

Run: `make test ARGS="tests/test_playergame_backfill.py tests/test_playergame_projection.py"`
Expected: PASS

- [ ] **Step 11: Lint, format, type check and commit**

```bash
make lint && make format && make typecheck
git add games/views/playergame_writes.py games/forms.py games/views/game.py tests/
git commit -m "Let the game form state its two facts

GameForm stops writing status and mastered, and the two views state them
instead. A new row is the exception: the values are assigned before the
first save, because the audit signal records no transition for a game
that has no previous row and moving it afterwards would invent one.

Both columns leave Meta.fields, so the form seeds their initial from the
instance itself and pins the field order a declared field would lose.

Four test files drove these POSTs under a rolled-back transaction, which
a dispatch cannot open inside. Three take a marker; the fourth is a
TestCase method and moves out of its class rather than making eighty
tests truncate to serve one."
```

---

### Task 6: The status dropdown's API

**Files:**
- Modify: `games/api.py:95-96` (`GameStatusUpdate`), `games/api.py:179-186` (`partial_update_game`), and near `games/api.py:84` (the exception handler)
- Test: `tests/test_playergame_view_cutover.py` (append)

**Interfaces:**
- Consumes: `record_facts`, `new_correlation_id`, `PlayerGameWriteFailed` from Task 3.
- Produces: nothing later tasks read.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_view_cutover.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_the_status_api_records_the_fact(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "f"},
        content_type="application/json",
    )

    assert response.status_code == 204
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
    game.refresh_from_db()
    assert game.status == "f"


@pytest.mark.django_db(transaction=True)
def test_the_status_api_refuses_a_status_that_is_not_one(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "zzz"},
        content_type="application/json",
    )

    #: Today the value reaches the column: Game.save() calls clean() and not
    #: full_clean(), and neither checks choices. Typing the schema field is
    #: what makes Ninja refuse it before the view runs.
    assert response.status_code == 422
    game.refresh_from_db()
    assert game.status == "u"


@pytest.mark.django_db(transaction=True)
def test_a_failed_status_write_answers_409_with_a_toast(
    logged_in, owned_library, monkeypatch
):
    from games.writes.playergame import PlayerGameWriteFailed

    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    def refuse(*args, **kwargs):
        raise PlayerGameWriteFailed("Nothing was recorded; try again.", 409)

    monkeypatch.setattr("games.api.record_facts", refuse)
    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "f"},
        content_type="application/json",
    )

    assert response.status_code == 409
    #: The dropdown reverts itself on any non-ok response and shows whatever
    #: the trigger header carries, so the sentence must ride along.
    assert "show-toast" in response.headers["HX-Trigger"]
```

- [ ] **Step 2: Run and confirm they fail**

Run: `make test ARGS="tests/test_playergame_view_cutover.py -k status -x"`
Expected: FAIL — no `PlayerGame` row, and the unknown status returns 204.

- [ ] **Step 3: Type the schema field**

In `games/api.py`, replace `GameStatusUpdate`:

```python
class GameStatusUpdate(Schema):
    #: The enum rather than str: Ninja refuses an unknown member with a 422
    #: before the view runs. Game.save() calls clean() and not full_clean(),
    #: so nothing downstream checks choices.
    status: Game.Status
```

- [ ] **Step 4: Switch the view and register the handler**

Add the imports to `games/api.py`:

```python
from games.writes.playergame import (
    PlayerGameWriteFailed,
    new_correlation_id,
    record_facts,
)
```

Replace `partial_update_game`:

```python
@game_router.patch("/{game_id}/status", response={204: None})
def partial_update_game(request, game_id: UUIDv7, payload: GameStatusUpdate):
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    record_facts(
        cast(User, request.user),
        game,
        status=payload.status,
        correlation_id=new_correlation_id(),
    )
    messages.success(request, "Status updated")
    return Status(204, None)
```

Add the handler just below `api = NinjaAPI(auth=django_auth)`:

```python
@api.exception_handler(PlayerGameWriteFailed)
def _playergame_write_failed(request, failure: PlayerGameWriteFailed):
    #: The message goes through Django messages, so the htmx middleware turns
    #: it into the HX-Trigger the toast store reads. The status code is what
    #: makes the dropdown revert its optimistic label.
    messages.error(request, failure.message)
    return api.create_response(
        request, {"detail": failure.message}, status=failure.status_code
    )
```

- [ ] **Step 5: Run the API tests**

Run: `make test ARGS="tests/test_playergame_view_cutover.py -k status"`
Expected: PASS

- [ ] **Step 6: Run every test that touches the API**

Run: `make test ARGS="tests/test_api.py tests/test_library_api_isolation.py tests/test_custom_elements.py"`
Expected: PASS. Any failure with `NestedTransactionNotSupported` means that
file drives the status PATCH and needs
`@pytest.mark.django_db(transaction=True)`; apply it the same way as Task 5
Step 8.

- [ ] **Step 7: Lint, format, type check and commit**

```bash
make lint && make format && make typecheck
git add games/api.py tests/test_playergame_view_cutover.py
git commit -m "Let the status dropdown state a fact

The endpoint wrote the column and validated nothing: Game.save() calls
clean() rather than full_clean(), so an unknown letter reached the
database. Typing the schema field makes Ninja refuse it with a 422.

A failure answers 409 with the sentence in a toast. The dropdown already
snapshots its label and reverts on any non-ok response, so this needs no
client change — only the status code and the words."
```

---

### Task 7: The session and play-event views

The two flips live inside `SessionForm.save` and `PlayEventForm.save`, where they cover every caller for free. A form has no actor, so they move to the four views that have one: two adds and two edits. The edits are not trimmable — both bind their checkbox and re-apply the flip today.

**Files:**
- Modify: `games/forms.py:635-645` (`SessionForm.save`), `games/forms.py:941-951` (`PlayEventForm.save`)
- Modify: `games/views/session.py:200-202`, `games/views/session.py:259-261`
- Modify: `games/views/playevent.py:293-302`, `games/views/playevent.py:327-335`
- Test: `tests/test_playergame_view_cutover.py` (append)

**Interfaces:**
- Consumes: `record_facts_for_request`, `new_correlation_id`.
- Produces: nothing later tasks read.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_view_cutover.py`. Add `Session`, `PlayEvent`
and `timezone` to the imports.

```python
def _session_payload(game, **overrides):
    started = timezone.now().replace(microsecond=0)
    return {
        "game": str(game.id),
        "timestamp_start": started.strftime("%Y-%m-%d %H:%M"),
        "timestamp_start_timezone": "",
        "timestamp_end": "",
        "timestamp_end_timezone": "",
        "duration_manual": "",
        "note": "",
        "mark_as_played": "on",
        **overrides,
    }


@pytest.mark.django_db(transaction=True)
def test_adding_a_session_records_played(logged_in, owned_library, tracked_game):
    logged_in.post(reverse("games:add_session"), _session_payload(tracked_game))

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED
    tracked_game.refresh_from_db()
    assert tracked_game.status == "p"


@pytest.mark.django_db(transaction=True)
def test_editing_a_session_records_played_too(logged_in, owned_library, tracked_game):
    #: The checkbox is a field of the form and an edit binds it, so an edit
    #: re-applies the flip today. Covering only the add view would be a
    #: silent regression rather than a smaller change.
    session = Session.objects.create(
        library=owned_library, game=tracked_game, timestamp_start=timezone.now()
    )
    Game.objects.filter(pk=tracked_game.pk).update(status="u")

    logged_in.post(
        reverse("games:edit_session", args=[session.id]),
        _session_payload(tracked_game),
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_session_leaves_a_finished_game_alone(logged_in, owned_library, tracked_game):
    Game.objects.filter(pk=tracked_game.pk).update(status="f")

    logged_in.post(reverse("games:add_session"), _session_payload(tracked_game))

    #: The guard reads the catalog, because every read reads the catalog
    #: until #678. Without it a completed game falls back to played.
    tracked_game.refresh_from_db()
    assert tracked_game.status == "f"


@pytest.mark.django_db(transaction=True)
def test_adding_a_play_event_records_completed(logged_in, owned_library, tracked_game):
    logged_in.post(
        reverse("games:add_playevent"),
        {
            "game": str(tracked_game.id),
            "started": "",
            "ended": "",
            "note": "",
            "mark_as_finished": "on",
        },
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
    tracked_game.refresh_from_db()
    assert tracked_game.status == "f"


@pytest.mark.django_db(transaction=True)
def test_editing_a_play_event_records_completed_too(
    logged_in, owned_library, tracked_game
):
    play_event = PlayEvent.objects.create(library=owned_library, game=tracked_game)
    Game.objects.filter(pk=tracked_game.pk).update(status="u")

    logged_in.post(
        reverse("games:edit_playevent", args=[play_event.id]),
        {
            "game": str(tracked_game.id),
            "started": "",
            "ended": "",
            "note": "",
            "mark_as_finished": "on",
        },
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
```

Add the `tracked_game` fixture near the top of the file:

```python
@pytest.fixture
def tracked_game(owned_user, owned_library):
    from games.writes.playergame import new_correlation_id, track_game

    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game
```

If a POST comes back 200 rather than 302 the form did not validate; print
`response.context["form"].errors` to see which field the payload is missing,
and fix the payload rather than the view.

- [ ] **Step 2: Run and confirm they fail**

Run: `make test ARGS="tests/test_playergame_view_cutover.py -k 'session or play_event' -x"`
Expected: FAIL — the catalog moves but no event is recorded, so `PlayerGame`
still reads `unplayed`.

- [ ] **Step 3: Take the flip out of `SessionForm.save`**

Replace `SessionForm.save` in `games/forms.py`:

```python
    def save(self, commit=True):
        #: The mark_as_played flip moved to the views in #677: a fact is
        #: stated as a command, and a form has no actor to state it as.
        session = super().save(commit=False)
        if commit:
            session.save()
        return session
```

- [ ] **Step 4: Take the flip out of `PlayEventForm.save`**

Replace `PlayEventForm.save`:

```python
    def save(self, commit=True):
        #: The mark_as_finished flip moved to the views in #677, and the
        #: transaction.atomic() that wrapped the two saves went with it: a
        #: dispatch inside it would raise NestedTransactionNotSupported, and
        #: one remaining save needs no block.
        play_event = super().save(commit=False)
        if commit:
            play_event.save()
        return play_event
```

- [ ] **Step 5: State the fact in the two session views**

Add to `games/views/session.py`:

```python
from games.views.playergame_writes import record_facts_for_request
from games.writes.playergame import new_correlation_id
```

Add a helper beside the two views, so the same four lines are not written
twice:

```python
def _record_played(request: HttpRequest, session: Session) -> None:
    """State Played for a game the session says was unplayed."""
    #: The guard reads the catalog, because every read reads the catalog
    #: until #678. Without it a completed game falls back to played.
    if session.game.status != Game.Status.UNPLAYED:
        return
    record_facts_for_request(
        request,
        session.game,
        status=Game.Status.PLAYED,
        correlation_id=new_correlation_id(),
    )
```

In `add_session`, replace lines 200-202:

```python
        if form.is_valid():
            session = form.save()
            if form.cleaned_data.get("mark_as_played"):
                _record_played(request, session)
            return redirect(return_url(request, fallback="games:list_sessions"))
```

In `edit_session`, replace lines 259-261 the same way.

- [ ] **Step 6: State the fact in the two play-event views**

Add to `games/views/playevent.py`:

```python
from games.views.playergame_writes import record_facts_for_request
from games.writes.playergame import new_correlation_id
```

Add the helper:

```python
def _record_completed(request: HttpRequest, play_event: PlayEvent) -> None:
    """State Completed for the game this playthrough finished."""
    record_facts_for_request(
        request,
        play_event.game,
        status=Game.Status.FINISHED,
        correlation_id=new_correlation_id(),
    )
```

In `add_playevent`, replace the `form.save()` at line 294:

```python
    if form.is_valid():
        play_event = form.save()
        if form.cleaned_data.get("mark_as_finished"):
            _record_completed(request, play_event)
        game = play_event.game
        return redirect(
            return_url(
                request,
                fallback="games:view_game",
                fallback_args=[game.id, game.url_slug],
            )
        )
```

In `edit_playevent`, replace the `form.save()` at line 328 the same way,
keeping that view's existing redirect.

Import `Game` in both view modules if it is not already imported.

- [ ] **Step 7: Run the new tests**

Run: `make test ARGS="tests/test_playergame_view_cutover.py"`
Expected: PASS

- [ ] **Step 8: Run everything these forms and views touch**

Run: `make test ARGS="tests/test_forms.py tests/test_signals.py tests/test_user_preference_consumers.py tests/test_session_fk_uuid.py tests/test_library_form_isolation.py"`
Expected: PASS. Anything failing with `NestedTransactionNotSupported` takes
`@pytest.mark.django_db(transaction=True)`.

- [ ] **Step 9: Lint, format, type check and commit**

```bash
make lint && make format && make typecheck
git add games/forms.py games/views/session.py games/views/playevent.py tests/test_playergame_view_cutover.py
git commit -m "Move the two checkbox flips to the views that have an actor

A fact is stated as a command and a command needs an actor, which a form
does not have. The flips leave SessionForm.save and PlayEventForm.save,
and the transaction.atomic() around the second goes with them: a dispatch
inside it cannot open the transaction it retries.

Four views take them, not two. Both edit views bind their checkbox and
re-apply the flip today, so covering only the adds would have been a
silent regression.

The unplayed guard keeps reading the catalog, because every read does
until #678."
```

---

### Task 8: The refund

`refund_purchase` abandons every game of the purchase, then refunds. It answers a table row plus an out-of-band template that closes the modal, so a failure cannot redirect.

**Files:**
- Modify: `games/views/purchase.py:552-566`
- Modify: `tests/test_purchase_runtime_identity.py:12`,
  `tests/test_origin_partials.py`, `tests/test_middleware_integration.py:76`,
  and `tests/test_table_width_policy.py:150` if it breaks
- Test: `tests/test_playergame_view_cutover.py` (append)

**Interfaces:**
- Consumes: `record_facts_for_request`, `new_correlation_id`.
- Produces: nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_view_cutover.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_refunding_abandons_every_game_under_one_correlation_id(
    logged_in, owned_user, owned_library
):
    from games.models import LibraryEvent, Purchase
    from games.writes.playergame import new_correlation_id, track_game

    games = []
    for name in ("Outer Wilds", "Tunic"):
        game = Game.objects.create(library=owned_library, name=name, status="p")
        track_game(owned_user, game, correlation_id=new_correlation_id())
        games.append(game)
    purchase = Purchase.objects.create(library=owned_library, price=0)
    purchase.games.set(games)

    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    assert response.status_code == 200
    assert set(PlayerGame.objects.values_list("status", flat=True)) == {
        PlayerGameStatus.ABANDONED
    }
    correlation_ids = set(
        LibraryEvent.objects.filter(
            event_type="library.playergame.status_changed"
        ).values_list("correlation_id", flat=True)
    )
    #: One button press is one act, whatever number of games it moves.
    assert len(correlation_ids) == 1


@pytest.mark.django_db(transaction=True)
def test_a_failed_refund_answers_409_and_swaps_nothing(
    logged_in, owned_user, owned_library, monkeypatch
):
    from games.models import Purchase
    from games.writes.playergame import PlayerGameWriteFailed, new_correlation_id
    from games.writes.playergame import track_game

    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="p")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    purchase = Purchase.objects.create(library=owned_library, price=0)
    purchase.games.set([game])

    def refuse(*args, **kwargs):
        raise PlayerGameWriteFailed("Nothing was recorded; try again.", 409)

    monkeypatch.setattr("games.views.purchase.record_facts", refuse)
    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    #: htmx swaps nothing outside 2xx, so the row keeps what it shows and
    #: the modal stays open. A redirect would swap a whole page into a cell.
    assert response.status_code == 409
    assert response.content == b""
    assert "show-toast" in response.headers["HX-Trigger"]
    purchase.refresh_from_db()
    assert purchase.date_refunded is None
```

Check the refund field's real name before writing that last assertion — read
`Purchase.refund()` in `games/models.py` and assert on whatever it sets.

- [ ] **Step 2: Run and confirm they fail**

Run: `make test ARGS="tests/test_playergame_view_cutover.py -k refund -x"`
Expected: FAIL — no events recorded; the failure case returns 200.

- [ ] **Step 3: Switch the view**

In `games/views/purchase.py`, add:

```python
from games.views.playergame_writes import record_facts_for_request
from games.writes.playergame import (
    PlayerGameWriteFailed,
    new_correlation_id,
    record_facts,
)
```

Replace the loop at lines 552-556:

```python
    correlation_id = new_correlation_id()
    for game in purchase.games.all():
        if not record_facts_for_request(
            request,
            game,
            status=Game.Status.ABANDONED,
            correlation_id=correlation_id,
        ):
            #: No redirect: this answers a table row and an out-of-band
            #: modal close, so a whole page would be swapped into a cell.
            #: htmx swaps nothing outside 2xx, and the toast rides the
            #: HX-Trigger header the middleware sets from the message.
            return HttpResponse(status=409)
```

The dispatches share no transaction, so a failure part-way abandons some
games and refunds nothing — the same failure shape the loop of `game.save()`
calls has today.

`record_facts` is imported so the test can monkeypatch
`games.views.purchase.record_facts`; if ruff flags it as unused, patch
`games.views.playergame_writes.record_facts` in the test instead and drop the
import.

- [ ] **Step 4: Run the new tests**

Run: `make test ARGS="tests/test_playergame_view_cutover.py -k refund"`
Expected: PASS

- [ ] **Step 5: Migrate the purchase tests**

Five test files POST to `games:refund_purchase`. The loop is unconditional
over `purchase.games.all()`, so each one that refunds a purchase holding at
least one game now dispatches and needs a transaction it cannot open.

Run: `make test ARGS="tests/test_purchase_runtime_identity.py tests/test_origin_partials.py tests/test_middleware_integration.py tests/test_table_width_policy.py tests/test_library_page_isolation.py" PYTEST_WORKERS=0`
Expected: FAIL with `NestedTransactionNotSupported` on the refund POSTs.

- `tests/test_purchase_runtime_identity.py:12` — change
  `pytestmark = pytest.mark.django_db` to
  `pytestmark = pytest.mark.django_db(transaction=True)`.
- `tests/test_origin_partials.py` — has no `pytestmark`; its database access
  comes from the `owned_library` fixture. Add
  `pytestmark = pytest.mark.django_db(transaction=True)` below the `ORIGIN`
  constant. pytest-django's `db` fixture defers to `transactional_db` when
  both are requested, so the fixtures need no edit.
- `tests/test_middleware_integration.py:76` —
  `test_refund_purchase_returns_updated_row_with_hx_trigger` is a method of
  `MiddlewareIntegrationTest(TestCase)` and refunds a one-game purchase, so it
  breaks. Move it out of the class to the end of the file as a module-level
  `@pytest.mark.django_db(transaction=True)` function, converting `self.client`
  to the `client` fixture, `self.user`/`self.game`/`self.platform` to locally
  created objects, and each `self.assertX` to a plain `assert`. Making the
  whole class transactional instead would truncate between every test in it to
  serve one.
- `tests/test_table_width_policy.py:150` —
  `test_refunded_row_fragment_keeps_the_tables_policy` refunds
  `Purchase.objects.first()`, which breaks only if that purchase holds a game.
  Move it out of `DataTableGateTest(TestCase)` the same way if it fails, and
  leave it alone if it does not.
- `tests/test_library_page_isolation.py:360` —
  `test_foreign_purchase_action_posts_return_404_without_mutation` expects a
  404, which `owned_or_404` raises before the loop, so nothing dispatches and
  this file needs no change. Confirm that rather than assuming it.

Run: `make test ARGS="tests/test_purchase_runtime_identity.py tests/test_origin_partials.py tests/test_middleware_integration.py tests/test_table_width_policy.py tests/test_library_page_isolation.py"`
Expected: PASS

- [ ] **Step 6: Lint, format, type check and commit**

```bash
make lint && make format && make typecheck
git add games/views/purchase.py tests/
git commit -m "Let a refund state Abandoned for every game it covers

The last of the six writes. One correlation id for the whole button
press, so a three-game bundle reads as one refund rather than three
coincidences.

A failure answers 409 with an empty body rather than a redirect. The view
returns a table row and an out-of-band modal close, so a redirect would
swap a whole page into a cell; htmx swaps nothing outside 2xx, and the
toast rides the trigger header instead.

The dispatches share no transaction, so a part-way failure abandons some
games and refunds nothing — the shape the loop of saves already had."
```

---

### Task 9: The gate, the documentation and the two hand-offs

**Files:**
- Modify: `CLAUDE.md` (the Conventions list)
- Modify: `docs/event-retention.md` or the events documentation, if it lists which writes are evented
- Delete: `docs/superpowers/plans/2026-08-28-issue-677-playergame-write-cutover.md` (this plan)

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: green. This is the only run that counts — it includes `e2e/`, which
is where a removed form field or a changed response code surfaces.

If an e2e test fails on the status dropdown, the add/edit form, mark-as-played,
mark-as-finished or a refund, fix the code rather than the test: those are the
five flows this issue changed and the e2e suite is the only place they are
driven end to end.

- [ ] **Step 2: Confirm no drift between the events and the catalog**

Run: `make test ARGS="tests/test_playergame_backfill.py -k reconcile"`
Expected: PASS. #676's reconciler compares every live game against the row its
events folded to, which is exactly the invariant the mirror maintains.

- [ ] **Step 3: Run the benchmark**

Run: `make bench`
Expected: completes. It is not part of `make check` and takes about 1.7
minutes. Note the per-command cost in the commit message if it moved: a
refund of an N-game bundle is now N dispatches rather than N saves.

- [ ] **Step 4: Update CLAUDE.md**

Add to the "Conventions for AI assistants" list:

```markdown
- **A PlayerGame fact is stated as a command** — never assign `Game.status` or
  `Game.mastered` directly. Call `record_facts()` / `track_game()` from
  `games/writes/playergame.py`, or their request-shaped wrappers in
  `games/views/playergame_writes.py`. The catalog columns are a mirror of the
  projection until #678 moves the reads.
- **No dispatch inside a transaction** — `run_in_transaction` opens the
  transaction it retries and refuses to nest, so a view that dispatches carries
  no `@transaction.atomic` and calls no helper that does. `games.E008` refuses
  `ATOMIC_REQUESTS`. A test that POSTs through such a view needs
  `@pytest.mark.django_db(transaction=True)`.
```

Also update the `games/` line of the directory listing to mention `writes/`.

- [ ] **Step 5: Commit the documentation**

```bash
git add CLAUDE.md docs/
git commit -m "Write down the two rules this issue introduced

A status is stated, not assigned, and nothing may open a transaction
above a dispatch. Both are invisible in the code that obeys them and
loud in the code that does not, which is what a convention list is for."
```

- [x] **Step 6: Post the two hand-offs** — already done

Two things this issue deliberately does not do had no owner on the tracker,
only in the spec. Both were commented before implementation started, so do not
post them again:

- **#678** takes archive/restore's first caller, the lists that give an
  archived game a visible effect, and the unreachable `PlayerGameStatus.SHELVED`
  — plus the deletion of all three modules this issue adds.
  <https://github.com/KucharczykL/timetracker/issues/678#issuecomment-5452481005>
- **#736** (PUR-12, not the #601 epic) takes `Purchase.infinite`, the seventh
  legacy write, and with it the only one of #673's six commands that still has
  no caller.
  <https://github.com/KucharczykL/timetracker/issues/736#issuecomment-5452482424>

- [ ] **Step 7: Delete this plan and commit**

```bash
git rm docs/superpowers/plans/2026-08-28-issue-677-playergame-write-cutover.md
git commit -m "Drop the plan for #677

The design document is the record that outlives the work; a plan that
described how to reach a state the code is now in describes nothing."
```

---

## Coverage against the spec

| Spec section | Task |
|---|---|
| The six writes | 5, 6, 7, 8 |
| The write path | 3 |
| Why the mirror is not a projector | 3 (docstring), no code |
| The mirror reads the fold | 3 |
| The composite command | 2 |
| A game with no row | 2 (the exception), 3 (the heal) |
| Nothing may open the transaction first | 4 |
| The keys name the request | 3 (`_dispatch`) |
| One correlation id per request | 3, and every call site in 5–8 |
| The form | 5 |
| The call sites | 5, 6, 7, 8 |
| Failures at the view boundary | 3 (`_translated`), 5 (the adapter), 6 (the Ninja handler), 8 (the 409) |
| What an archived game accepts | no code; #678 hand-off in 9 |
| Two legacy writes this does not switch | no code; both hand-offs in 9 |
| The tests that already drive these writes | 5 (four files), 7 and 8 (the rest) |
| Verification | every task's test steps, and 9 Step 1 |
| Reversibility | no code — no migration, so a revert is the commits |
