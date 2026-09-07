# Playthrough write cutover (#687) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every request path that wrote a `PlayEvent` row states a Playthrough
command instead, and the word `playevent` leaves every identifier that does not
derive from the model's own name.

**Architecture:** Two new write modules mirror the `PlayerGame` pair —
`games/writes/playthrough.py` raises, `games/views/playthrough_writes.py` toasts.
`CreatePlaythrough` grows into one build that states a whole new run; an edit
states differences through the three commands #1010 delivered. Reads stay
legacy, so a bridge module maps a legacy row to the run #684 made from it, and
#771 takes that module away with the table.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, Django Ninja, pytest +
pytest-xdist, Playwright, TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-07-issue-687-playthrough-write-cutover-design.md`

## Global Constraints

- Run everything through `make`. Never bare `uv run`, `pytest`, `pnpm`.
  Iterate with `make test ARGS="…"` and `make check-fast`; the gate is the
  full `make check`, including `e2e/`.
- Python 3.14 only. `except A, B:` is PEP 758 syntax, not an `as` binding.
- No dispatch inside a transaction: `run_in_transaction` refuses to nest, so a
  view that dispatches carries no `@transaction.atomic`, and a test that POSTs
  through one needs `@pytest.mark.django_db(transaction=True)`.
- Nothing destroys a record. Never `instance.delete()`.
- Never write a `GeneratedField` (`days_to_finish` here).
- A rejection carries two sentences: `raise CommandRejected(message,
  sentence=…)`. The `message` may name ids; only `sentence` is shown.
- A refused command becomes an answer through `answered(subject)` from
  `games/writes/answers.py`. Never translate one at a call site.
- A command resolves a UUID with `library_row` from `games/commands/scope.py`,
  never a bare `Model.objects.get()`.
- Complete words in identifiers (`element`, not `el`). Compound values get a
  `NamedTuple`/`TypedDict`/alias name.
- Vale refuses `fold`, `heal`, `tombstone`, `archive`, and `delete` next to a
  record noun. `make vale` runs inside `make check`.
- Build UI with `common.components` builders in htpy form, never HTML strings.
- Every mutating link carries `origin=request.get_full_path()`; every mutating
  view ends in `redirect(return_url(request, fallback=…))`; every route is
  classified in `games/views/returns.py`.
- **A test-created game already holds a `PlayerGame` row and no run.** The
  autouse `_track_created_games` fixture (`tests/conftest.py:205-251`) writes
  the row straight through a `post_save` receiver — no `TrackGame`, no events,
  so no `Playthrough`. Every test below that wants the run #679 states carries
  `@pytest.mark.untracked_games` (registered in `pyproject.toml:103`) and calls
  `track_game()` itself. A test that forgets the marker sees `TrackGame` answer
  on a row that already exists and finds no run at all.

**Commit split.** Tasks 1–10 are commit one (the write cutover), task 11 is
commit two (the mechanical rename and the router move), task 12 is commit three
(the saved-preset migration). Task 13 is the gate.

---

### Task 1: The runs a tracked game holds

**Files:**
- Create: `games/reads/playthrough_runs.py`
- Test: `tests/test_playthrough_runs_read.py`

**Interfaces:**
- Consumes: `Playthrough`, `PlayerGame`, `PlaythroughKind`, `UserLibrary` from
  `games.models`; `stated_start`/`stated_completion` from
  `games.reads.playthrough_endpoints`.
- Produces: `live_ordinary_runs(library, player_game) -> QuerySet[Playthrough]`
  and `run_to_adopt(library, player_game) -> Playthrough | None`, both used by
  Task 3.

Background the implementer needs: `Playthrough` declares no manager, so
`Playthrough.objects` is Django's plain default — no `for_library()`, no
`alive()`. Every read states its own four filters. A run may name another
library's `PlayerGame` (the drift `audit_library_ownership` reports), so
`library=` is stated beside `player_game=` rather than inferred from it.

- [ ] **Step 1: Write the failing test**

```python
import uuid

import pytest
from django.utils import timezone

from games.commands.playthrough import CreatePlaythrough
from games.events.dispatch import dispatch
from games.models import PlayerGame, Playthrough, PlaythroughKind
from games.reads.playthrough_runs import live_ordinary_runs, run_to_adopt
from games.writes.playergame import new_correlation_id, track_game

#: Every test here wants the run #679 states, so no test may start
#: from the row the autouse fixture writes without one.
pytestmark = pytest.mark.untracked_games


def a_tracked_game(user, game) -> PlayerGame:
    """Track the game the way a request does, and read its row."""
    track_game(user, game, correlation_id=new_correlation_id())
    return PlayerGame.objects.get(library=user.library, game=game)


def a_second_run(user, game) -> None:
    """One more run at the game, beside the one it was born with."""
    dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )


@pytest.mark.django_db(transaction=True)
def test_a_tracked_game_holds_one_live_ordinary_run(user, game):
    tracked = a_tracked_game(user, game)

    runs = live_ordinary_runs(user.library, tracked)

    assert runs.count() == 1
    assert runs.get().kind == PlaythroughKind.ORDINARY


@pytest.mark.django_db(transaction=True)
def test_the_run_a_tracked_game_is_born_with_is_the_one_adopted(user, game):
    tracked = a_tracked_game(user, game)

    adopted = run_to_adopt(user.library, tracked)

    assert adopted is not None
    assert adopted.start_recorded_at is None
    assert adopted.completion_recorded_at is None


@pytest.mark.django_db(transaction=True)
def test_a_second_run_leaves_nothing_to_adopt(user, game):
    tracked = a_tracked_game(user, game)

    a_second_run(user, game)

    assert run_to_adopt(user.library, tracked) is None


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_is_not_live(user, game):
    tracked = a_tracked_game(user, game)

    #: The projector's own mark, stated here with an UPDATE because
    #: RemovePlaythrough refuses to take the last run off a tracked game.
    Playthrough.objects.filter(player_game=tracked).update(removed_at=timezone.now())

    assert live_ordinary_runs(user.library, tracked).count() == 0
    assert run_to_adopt(user.library, tracked) is None
```

Reuse whatever `user` and `game` fixtures `tests/conftest.py` already offers —
read it first rather than inventing new ones. Check `dispatch`'s keyword names
against `tests/test_playthrough_command.py` before writing `a_second_run`; the
plan quotes them from that file.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_runs_read.py -x"`
Expected: FAIL, `ModuleNotFoundError: games.reads.playthrough_runs`.

- [ ] **Step 3: Write the module**

```python
"""The runs a tracked game holds."""

from django.db.models import QuerySet

from games.models import PlayerGame, Playthrough, PlaythroughKind, UserLibrary
from games.reads.playthrough_endpoints import stated_completion, stated_start


def live_ordinary_runs(
    library: UserLibrary, player_game: PlayerGame
) -> QuerySet[Playthrough]:
    """This tracked game's live ordinary runs, in the order they were made.

    The library is stated beside the parent, not inferred from it: a run
    may name another library's PlayerGame, which is the drift
    `audit_library_ownership` reports, and a count that trusted the
    parent alone would count rows this library does not hold.
    """
    return Playthrough.objects.filter(
        library=library,
        player_game=player_game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).order_by("created_at", "id")


def run_to_adopt(library: UserLibrary, player_game: PlayerGame) -> Playthrough | None:
    """The run a first statement fills in, or nothing.

    A tracked game holds one run from the moment #679 tracks it. Where
    that run is the only one and states neither act, the first
    playthrough a person records is that run rather than a second one
    beside it. Nothing enforces at most one actless run at runtime, so
    this reads the shape rather than trusting it.
    """
    runs = list(live_ordinary_runs(library, player_game)[:2])
    if len(runs) != 1:
        return None
    run = runs[0]
    if stated_start(run) is not None or stated_completion(run) is not None:
        return None
    return run
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playthrough_runs_read.py -x"`
Expected: PASS, four tests.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_runs.py tests/test_playthrough_runs_read.py
git commit -m "Read the runs a tracked game holds"
```

---

### Task 2: One command states a whole new run

**Files:**
- Modify: `games/commands/playthrough.py:81-101` (`CreatePlaythrough`)
- Test: `tests/test_playthrough_command.py` (add cases; update the five
  existing constructions at lines 66, 91, 110, 131, 1425)

**Interfaces:**
- Consumes: `playthrough_created`, `playthrough_note_changed`,
  `playthrough_started`, `playthrough_completed` from `games.events.playthrough`;
  `endpoints_certainly_reversed` from this same module.
- Produces: `ActStatement(when, note)` and
  `CreatePlaythrough(game_id, started, completed, note)`, both used by Task 3.

Why a `NamedTuple` and not a dataclass: `canonical_command_input` is shallow and
hands each field value to `json.dumps(default=_encode_command_value)`, which
knows `datetime`, `date`, `UUID`, `Decimal` and `TemporalValue` and raises
`TypeError` for anything else. A `NamedTuple` **is** a tuple, so json encodes it
as an array and the `TemporalValue` inside reaches the encoder by itself — no new
branch in the fingerprint's wire form.

Why the fields are `ActStatement | None` and not `TemporalValue | None`: under
the act rule a stated act with no day is already `None` for the day, so a bare
`TemporalValue | None` leaves no way to say "this act never happened" — which is
the run `TrackGame` states.

- [ ] **Step 1: Write the failing tests**

```python
class TestCreatePlaythroughStatesBothActs:
    """#687: one build states the run, its note and its two acts."""

    @pytest.mark.django_db(transaction=True)
    def test_it_appends_created_note_started_and_completed(self, user, tracked_game):
        result = dispatch(
            CreatePlaythrough(
                game_id=tracked_game.game_id,
                started=ActStatement(TemporalValue.from_day(date(2026, 1, 2)), ""),
                completed=ActStatement(TemporalValue.from_day(date(2026, 2, 3)), ""),
                note="12h 30m",
            ),
            actor=user,
            library=user.library,
            idempotency_key=str(uuid.uuid7()),
        )

        assert result.outcome is CommandOutcome.APPENDED
        run = Playthrough.objects.get(player_game=tracked_game, note="12h 30m")
        assert run.started == TemporalValue.from_day(date(2026, 1, 2))
        assert run.completed == TemporalValue.from_day(date(2026, 2, 3))
        assert run.start_recorded_at is not None
        assert run.completion_recorded_at is not None

    @pytest.mark.django_db(transaction=True)
    def test_a_dayless_act_is_still_an_act(self, user, tracked_game):
        dispatch(
            CreatePlaythrough(
                game_id=tracked_game.game_id,
                started=ActStatement(None, ""),
                completed=ActStatement(None, ""),
                note="",
            ),
            actor=user,
            library=user.library,
            idempotency_key=str(uuid.uuid7()),
        )

        run = Playthrough.objects.filter(player_game=tracked_game).latest("created_at")
        assert run.started is None
        assert run.start_recorded_at is not None
        assert run.completion_recorded_at is not None

    @pytest.mark.django_db(transaction=True)
    def test_no_act_states_no_endpoint(self, user, tracked_game):
        dispatch(
            CreatePlaythrough(
                game_id=tracked_game.game_id, started=None, completed=None, note=""
            ),
            actor=user,
            library=user.library,
            idempotency_key=str(uuid.uuid7()),
        )

        run = Playthrough.objects.filter(player_game=tracked_game).latest("created_at")
        assert run.start_recorded_at is None
        assert run.completion_recorded_at is None

    @pytest.mark.django_db(transaction=True)
    def test_a_reversed_pair_appends_nothing(self, user, tracked_game):
        before = LibraryEvent.objects.filter(library=user.library).count()

        with pytest.raises(CommandRejected) as refusal:
            dispatch(
                CreatePlaythrough(
                    game_id=tracked_game.game_id,
                    started=ActStatement(TemporalValue.from_day(date(2026, 2, 3)), ""),
                    completed=ActStatement(
                        TemporalValue.from_day(date(2026, 1, 2)), ""
                    ),
                    note="",
                ),
                actor=user,
                library=user.library,
                idempotency_key=str(uuid.uuid7()),
            )

        assert refusal.value.sentence is not None
        assert LibraryEvent.objects.filter(library=user.library).count() == before
```

Match the fixtures and imports the file already uses; `tracked_game` here is
whatever fixture that file already has for a `PlayerGame`.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_command.py -k StatesBothActs -x"`
Expected: FAIL, `TypeError: CreatePlaythrough.__init__() got an unexpected
keyword argument 'started'`.

- [ ] **Step 3: Extend the command**

Replace the `CreatePlaythrough` class (`games/commands/playthrough.py:81-101`)
with this, and put `ActStatement` directly above it:

```python
class ActStatement(NamedTuple):
    """An act that happened, and what was said about it.

    A NamedTuple, so the idempotency fingerprint encodes it as an array
    and the TemporalValue inside reaches the encoder that knows it.
    """

    #: None is "it happened, on a day nobody wrote down".
    when: TemporalValue | None
    note: str = ""


@dataclass(frozen=True, slots=True)
class CreatePlaythrough(Command):
    """State one more run at a game, and what is known of it.

    One build rather than four dispatches: a creation that commits and
    a start that then fails would leave a run with no act, and
    RemovePlaythrough refuses to take the last live ordinary run off a
    tracked game -- a row a person could not get rid of.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_CREATE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: None is an act that never happened, which is the run TrackGame states.
    started: ActStatement | None = None
    completed: ActStatement | None = None
    note: str = ""

    def __post_init__(self) -> None:
        for field_name in ("started", "completed"):
            act = getattr(self, field_name)
            if act is not None:
                #: One spelling of no day and of a blank note, so a
                #: restatement fingerprints alike.
                object.__setattr__(
                    self,
                    field_name,
                    ActStatement(stated_date(act.when), act.note.strip()),
                )
        object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = tracked_game(context, self.game_id)
        #: Under dispatch's lock: the mark cannot move.
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"This library removed game {self.game_id}, so it records no "
                "further runs at it. A removed game is restored first.",
                sentence=(
                    "That game was removed from your library. Restore it "
                    "before adding a playthrough."
                ),
            )
        if endpoints_certainly_reversed(
            started=None if self.started is None else self.started.when,
            completed=None if self.completed is None else self.completed.when,
        ):
            raise CommandRejected(
                f"The run being created at game {self.game_id} would complete "
                "before it began, and no run ends before it begins.",
                sentence="This run finished before it started. Check the days.",
            )
        #: Minted here, so all four events name one run.
        run_id = uuid.uuid7()
        events: list[NewEvent] = [
            playthrough_created(tracked.pk, playthrough_id=run_id)
        ]
        if self.note:
            events.append(playthrough_note_changed(run_id, note=self.note))
        if self.started is not None:
            events.append(
                playthrough_started(
                    run_id, when=self.started.when, note=self.started.note
                )
            )
        if self.completed is not None:
            events.append(
                playthrough_completed(
                    run_id, when=self.completed.when, note=self.completed.note
                )
            )
        return events
```

`NamedTuple` is already imported by this module (`typing`); the four event
factories and `endpoints_certainly_reversed` are already there.

- [ ] **Step 4: Run the new tests, then the whole file**

Run: `make test ARGS="tests/test_playthrough_command.py -x"`
Expected: PASS. The five existing `CreatePlaythrough(...)` constructions (lines
66, 91, 110, 131, 1425) still pass unchanged — every new field defaults — but
read each one and add the acts where the case is about a run that was played.

- [ ] **Step 5: Commit**

```bash
git add games/commands/playthrough.py tests/test_playthrough_command.py
git commit -m "State a whole run in one CreatePlaythrough build"
```

---

### Task 3: The write path

**Files:**
- Create: `games/writes/playthrough.py`
- Test: `tests/test_playthrough_writes.py`

**Interfaces:**
- Consumes: Task 1's `run_to_adopt`; Task 2's `ActStatement` and
  `CreatePlaythrough`; `StartPlaythrough`, `CompletePlaythrough`,
  `CorrectPlaythroughStart`, `CorrectPlaythroughCompletion`,
  `DescribePlaythrough`, `RemovePlaythrough`, `endpoints_certainly_reversed`
  from `games.commands.playthrough`; `PlayerGameNotTracked` from
  `games.commands.playergame`; `track_game`, `new_correlation_id` from
  `games.writes.playergame`; `answered` from `games.writes.answers`.
- Produces: `RunDraft(started, ended, note)`,
  `record_run(actor, game, draft, *, correlation_id)`,
  `restate_run(actor, run, draft, *, correlation_id)`,
  `remove_run(actor, run, *, correlation_id)` — all used by Task 4.

- [ ] **Step 1: Write the failing tests**

Every test in this file wants the run #679 states, so the file opens with
`pytestmark = pytest.mark.untracked_games` and each test tracks the game itself
(see the Global Constraints note on the autouse fixture).

```python
class TestRecordRun:
    """#687: the first run is the one the tracked game already holds."""

    @pytest.mark.django_db(transaction=True)
    def test_the_first_run_states_its_acts_onto_the_run_born_with_the_game(
        self, user, game
    ):
        track_game(user, game, correlation_id=new_correlation_id())
        tracked = PlayerGame.objects.get(library=user.library, game=game)
        born = Playthrough.objects.get(player_game=tracked)

        record_run(
            user,
            game,
            RunDraft(started=date(2026, 1, 2), ended=date(2026, 2, 3), note="12h"),
            correlation_id=new_correlation_id(),
        )

        assert Playthrough.objects.filter(player_game=tracked).count() == 1
        born.refresh_from_db()
        assert born.started == TemporalValue.from_day(date(2026, 1, 2))
        assert born.completed == TemporalValue.from_day(date(2026, 2, 3))
        assert born.note == "12h"

    @pytest.mark.django_db(transaction=True)
    def test_the_second_run_is_a_new_one(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())
        for day in (date(2026, 1, 2), date(2026, 3, 4)):
            record_run(
                user,
                game,
                RunDraft(started=day, ended=day, note=""),
                correlation_id=new_correlation_id(),
            )

        tracked = PlayerGame.objects.get(library=user.library, game=game)
        assert Playthrough.objects.filter(player_game=tracked).count() == 2

    @pytest.mark.django_db(transaction=True)
    def test_an_untracked_game_is_tracked_once_and_left_with_one_run(self, user, game):
        #: No track_game here: the marker leaves the game with no
        #: PlayerGame row, which is what the retry branch is for.
        record_run(
            user,
            game,
            RunDraft(started=None, ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        tracked = PlayerGame.objects.get(library=user.library, game=game)
        assert Playthrough.objects.filter(player_game=tracked).count() == 1

    @pytest.mark.django_db(transaction=True)
    def test_neither_day_still_states_both_acts(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())

        record_run(
            user,
            game,
            RunDraft(started=None, ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        run = Playthrough.objects.get(player_game__game=game)
        assert run.start_recorded_at is not None
        assert run.completion_recorded_at is not None
        assert run.started is None and run.completed is None

    @pytest.mark.django_db(transaction=True)
    def test_a_reversed_pair_is_refused_before_anything_is_appended(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())
        before = LibraryEvent.objects.filter(library=user.library).count()

        with pytest.raises(CommandFailed):
            record_run(
                user,
                game,
                RunDraft(started=date(2026, 2, 3), ended=date(2026, 1, 2), note=""),
                correlation_id=new_correlation_id(),
            )

        assert LibraryEvent.objects.filter(library=user.library).count() == before
```

```python
class TestRestateRun:
    """#687: an edit states differences, and states nothing twice."""

    @pytest.mark.django_db(transaction=True)
    def test_it_states_only_what_changed(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        before = LibraryEvent.objects.filter(library=user.library).count()

        restate_run(
            user,
            run,
            RunDraft(started=date(2026, 1, 3), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        appended = LibraryEvent.objects.filter(library=user.library).count() - before
        assert appended == 1
        run.refresh_from_db()
        assert run.started == TemporalValue.from_day(date(2026, 1, 3))

    @pytest.mark.django_db(transaction=True)
    def test_a_resubmitted_edit_appends_nothing(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        draft = RunDraft(started=date(2026, 1, 2), ended=None, note="")
        restate_run(user, run, draft, correlation_id=new_correlation_id())
        before = LibraryEvent.objects.filter(library=user.library).count()

        restate_run(user, run, draft, correlation_id=new_correlation_id())

        assert LibraryEvent.objects.filter(library=user.library).count() == before

    @pytest.mark.django_db(transaction=True)
    def test_an_unstated_endpoint_is_a_first_statement(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())
        tracked = PlayerGame.objects.get(library=user.library, game=game)
        born = Playthrough.objects.get(player_game=tracked)

        restate_run(
            user,
            born,
            RunDraft(started=date(2026, 1, 2), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        types = list(
            LibraryEvent.objects.filter(aggregate_id=born.pk)
            .order_by("sequence")
            .values_list("event_type", flat=True)
        )
        assert "library.playthrough.started" in types
        assert "library.playthrough.start_corrected" not in types

    @pytest.mark.django_db(transaction=True)
    def test_a_day_only_correction_leaves_the_endpoint_note_alone(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        Playthrough.objects.filter(pk=run.pk).update(start_note="from the box")
        run.refresh_from_db()

        restate_run(
            user,
            run,
            RunDraft(started=date(2026, 1, 5), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        run.refresh_from_db()
        assert run.start_note == "from the box"
```

```python
def a_recorded_run(user, game, *, started, ended) -> Playthrough:
    """Track the game, state one run at it, and read the run back."""
    track_game(user, game, correlation_id=new_correlation_id())
    record_run(
        user,
        game,
        RunDraft(started=started, ended=ended, note=""),
        correlation_id=new_correlation_id(),
    )
    #: The run the tracked game was born with, now stating both acts.
    return Playthrough.objects.get(player_game__game=game)


class TestRemoveRun:
    """#687: a tracked game keeps one run, and gives up any other."""

    @pytest.mark.django_db(transaction=True)
    def test_the_only_run_of_a_tracked_game_is_refused(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)

        with pytest.raises(CommandFailed) as refusal:
            remove_run(user, run, correlation_id=new_correlation_id())

        assert "only playthrough" in refusal.value.message
        run.refresh_from_db()
        assert run.removed_at is None

    @pytest.mark.django_db(transaction=True)
    def test_the_second_run_of_a_tracked_game_is_taken_out(self, user, game):
        a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        record_run(
            user,
            game,
            RunDraft(started=date(2026, 3, 4), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )
        second = Playthrough.objects.filter(player_game__game=game).latest("created_at")

        remove_run(user, second, correlation_id=new_correlation_id())

        second.refresh_from_db()
        assert second.removed_at is not None
        assert (
            Playthrough.objects.filter(
                player_game__game=game, removed_at__isnull=True
            ).count()
            == 1
        )
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_writes.py -x"`
Expected: FAIL, `ModuleNotFoundError: games.writes.playthrough`.

- [ ] **Step 3: Write the module — the values and the dispatch helper**

```python
"""State a run; answer a refused statement.

Takes an actor, not a request. The view half makes it a toast.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from django.contrib.auth.models import User

from games.commands.playergame import PlayerGameNotTracked
from games.commands.playthrough import (
    ActStatement,
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    DescribePlaythrough,
    RemovePlaythrough,
    StartPlaythrough,
    endpoints_certainly_reversed,
)
from games.events.dispatch import Command, CommandRejected, dispatch
from games.models import Game, PlayerGame, Playthrough, UserLibrary
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_runs import run_to_adopt
from games.writes.answers import answered
from games.writes.playergame import track_game
from timetracker.temporal import TemporalValue


@dataclass(frozen=True, slots=True)
class RunDraft:
    """What a person stated about one run.

    Plain dates, because the form states days. The act rule turns them
    into two acts: a day where one was given, and the act with no day
    where none was.
    """

    started: date | None
    ended: date | None
    note: str


def _stated_day(value: date | None) -> TemporalValue | None:
    """The day at day precision, or no day at all."""
    return None if value is None else TemporalValue.from_day(value)


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
        #: Deduplicates nothing; each build absorbs a repeat.
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )
```

- [ ] **Step 4: Write the endpoint statement**

```python
class EndpointStatement(NamedTuple):
    """How one endpoint is stated, the first time and after it."""

    reads: Callable[[Playthrough], StatedEndpoint | None]
    first: type[Command]
    correction: type[Command]


_ENDPOINTS: tuple[EndpointStatement, ...] = (
    EndpointStatement(stated_start, StartPlaythrough, CorrectPlaythroughStart),
    EndpointStatement(
        stated_completion, CompletePlaythrough, CorrectPlaythroughCompletion
    ),
)


def _state_endpoint(
    actor: User,
    run: Playthrough,
    endpoint: EndpointStatement,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State one endpoint, as a first statement or as a correction.

    Which of the two is read before dispatch takes its lock, so a
    second request on the same run can make the choice stale and the
    command refuses it. A refusal re-reads the run and states it once
    more -- one attempt, never a loop, the shape tracking uses.

    A correction carries the note the endpoint already states: #684
    wrote every endpoint note blank and put the row's note on the run,
    so a day-only correction that passed a fresh blank would state a
    note nobody wrote.
    """
    for attempt in (1, 2):
        stated = endpoint.reads(run)
        command_class = endpoint.first if stated is None else endpoint.correction
        note = "" if stated is None else stated.note
        try:
            _dispatch(
                command_class(playthrough_id=run.pk, when=when, note=note),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
            return
        except CommandRejected:
            if attempt == 2:
                raise
            run.refresh_from_db()
```

- [ ] **Step 5: Write the three public acts**

```python
def restate_run(
    actor: User,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State the draft onto a run that exists, differences only.

    Three dispatches rather than one build: each command answers
    Unchanged for state the run already holds, so a submit that fails
    after the first act is finished by submitting again.
    """
    with answered("playthrough"):
        _restate(actor, run, draft, correlation_id=correlation_id)


def _restate(
    actor: User,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """The statements themselves, inside a caller's answer."""
    started = _stated_day(draft.started)
    completed = _stated_day(draft.ended)
    #: Before the first dispatch. On the three-dispatch path a start
    #: commits and only the completion would refuse, and no command
    #: withdraws a stated act.
    if endpoints_certainly_reversed(started=started, completed=completed):
        raise CommandRejected(
            f"The statement about playthrough {run.pk} completes it before it "
            "began, and no run ends before it begins.",
            sentence="This run finished before it started. Check the days.",
        )
    if draft.note.strip() != run.note:
        _dispatch(
            DescribePlaythrough(playthrough_id=run.pk, name=None, note=draft.note),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )
        run.refresh_from_db()
    for endpoint, when in zip(_ENDPOINTS, (started, completed), strict=True):
        _state_endpoint(actor, run, endpoint, when, correlation_id=correlation_id)


def record_run(
    actor: User,
    game: Game,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State one run at a game.

    The first run of a tracked game is the one it already holds: #679
    states a run the moment a library tracks a game, and a second one
    beside it would leave every never-played game with an empty run
    forever.
    """
    with answered("playthrough"):
        try:
            _record_once(actor, game, draft, correlation_id=correlation_id)
        except PlayerGameNotTracked:
            #: One retry, never a loop. TrackGame states a run of its
            #: own, so the branch is read again rather than the command
            #: re-dispatched, which would leave a second run beside it.
            track_game(actor, game, correlation_id=correlation_id)
            _record_once(actor, game, draft, correlation_id=correlation_id)


def _record_once(
    actor: User,
    game: Game,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """Adopt the run the game already holds, or create one."""
    tracked = PlayerGame.objects.filter(library=actor.library, game=game).first()
    adopted = None if tracked is None else run_to_adopt(actor.library, tracked)
    if adopted is not None:
        _restate(actor, adopted, draft, correlation_id=correlation_id)
        return
    #: An untracked game reaches the command, which raises
    #: PlayerGameNotTracked for the retry above to read.
    _dispatch(
        CreatePlaythrough(
            game_id=game.pk,
            #: Both acts, always: a run recorded here happened.
            started=ActStatement(_stated_day(draft.started), ""),
            completed=ActStatement(_stated_day(draft.ended), ""),
            note=draft.note,
        ),
        actor=actor,
        library=actor.library,
        correlation_id=correlation_id,
    )


def remove_run(actor: User, run: Playthrough, *, correlation_id: uuid.UUID) -> None:
    """Take a run out of the lists."""
    with answered("playthrough"):
        _dispatch(
            RemovePlaythrough(playthrough_id=run.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )
```

- [ ] **Step 6: Run the tests**

Run: `make test ARGS="tests/test_playthrough_writes.py -x"`
Expected: PASS. Then `make test ARGS="tests/test_command_scope_guard.py"` —
the guard walks `games/commands/`, so this module is out of its scope, but the
run is cheap and catches a stray manager call moved into a build.

- [ ] **Step 7: Commit**

```bash
git add games/writes/playthrough.py tests/test_playthrough_writes.py
git commit -m "State a run through the Playthrough commands"
```

---

### Task 4: The request-shaped half

**Files:**
- Create: `games/views/playthrough_writes.py`
- Test: covered by Tasks 7–9 through the views; no test file of its own.

**Interfaces:**
- Consumes: Task 3's `record_run`, `restate_run`, `remove_run`, `RunDraft`.
- Produces: `record_run_for_request`, `restate_run_for_request`,
  `remove_run_for_request` — used by Tasks 7, 8 and 9.

- [ ] **Step 1: Write the module**

```python
"""The request-shaped half of the run write path.

games/writes/playthrough.py raises. A view that stays on its page
toasts and answers False; one that stands behind a confirmation
re-raises, so the confirmation states the sentence itself.
"""

import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest

from games.models import Game, Playthrough
from games.writes.answers import CommandFailed
from games.writes.playthrough import RunDraft, record_run, remove_run, restate_run


def record_run_for_request(
    request: HttpRequest, game: Game, draft: RunDraft, *, correlation_id: uuid.UUID
) -> bool:
    """State one run; False on a refusal."""
    try:
        record_run(
            cast("User", request.user), game, draft, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return False
    return True


def restate_run_for_request(
    request: HttpRequest,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> bool:
    """State the draft onto an existing run; False on a refusal."""
    try:
        restate_run(
            cast("User", request.user), run, draft, correlation_id=correlation_id
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
        return False
    return True


def remove_run_for_request(
    request: HttpRequest, run: Playthrough, *, correlation_id: uuid.UUID
) -> None:
    """Take the run out, and let a refusal rise.

    A refused command rises as the CommandFailed it already is, which
    confirm_and_apply reads: the confirmation comes back with the
    sentence and the status the refusal states.
    """
    remove_run(cast("User", request.user), run, correlation_id=correlation_id)
```

- [ ] **Step 2: Check it imports and types**

Run: `make typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add games/views/playthrough_writes.py
git commit -m "Answer a refused run statement onto the request"
```

---

### Task 5: The bridge from a legacy row to its run

**Files:**
- Create: `games/reads/playthrough_provenance.py`
- Test: `tests/test_playthrough_provenance.py`

**Interfaces:**
- Consumes: `LibraryEvent`, `Playthrough`, `UserLibrary` from `games.models`;
  `PLAYTHROUGH_CREATED` from `games.events.playthrough`.
- Produces: `run_for_row(library, row_id) -> Playthrough | None` and
  `runs_for_rows(library, row_ids) -> dict[PlayEventId, PlaythroughId]` — used
  by Tasks 7, 8 and 9 (four call sites, pinned by a test).

Background: #684 wrote no column linking a row to its run. Its conversion
recorded the row id in the creation event's `source_metadata` as
`{"origin": "backfill", "issue": 684, "play_event_id": "<uuid str>"}`
(`games/backfill/playthrough.py:209-215`), and that event's `aggregate_id` is
the run. A default run the conversion minted carries no `play_event_id`, and
neither does a run `TrackGame` states, so the mapping is partial by
construction. `source_metadata` carries no index, so the read scans one
library's events — accepted for four low-traffic paths on a module whose life
#771 ends.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from games.backfill.playthrough import convert_library
from games.models import PlayEvent, Playthrough
from games.reads.playthrough_provenance import run_for_row, runs_for_rows


@pytest.mark.django_db(transaction=True)
def test_a_converted_row_maps_to_its_run(user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library, actor=user)

    run = run_for_row(user.library, row.pk)

    assert run is not None
    assert run.player_game.game_id == game.pk


@pytest.mark.django_db(transaction=True)
def test_a_row_the_conversion_never_saw_maps_to_nothing(user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")

    assert run_for_row(user.library, row.pk) is None
    assert runs_for_rows(user.library, [row.pk]) == {}


@pytest.mark.django_db(transaction=True)
def test_a_default_run_maps_to_no_row(user, game):
    convert_library(user.library, actor=user)

    assert runs_for_rows(user.library, [game.pk]) == {}
```

The test that pins the module's readers lands in Task 9, once every reader
exists; adding it here would fail until then.

Read `games/backfill/playthrough.py` for the real name and signature of the
conversion entry point before writing the fixture; the plan quotes
`convert_library(library, actor=…)` from `load_sample_data`'s use of it.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_provenance.py -x"`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

```python
"""The run a converted legacy row became.

#684 recorded the row's id in the creation event's source_metadata and
wrote no column, so this reads the provenance rather than a join.
#771 removes the legacy table and this module with it.
"""

import uuid
from collections.abc import Iterable

from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import LibraryEvent, Playthrough, UserLibrary

#: The legacy row, and the run #684 made from it.
type PlayEventId = uuid.UUID
type PlaythroughId = uuid.UUID


def runs_for_rows(
    library: UserLibrary, row_ids: Iterable[PlayEventId]
) -> dict[PlayEventId, PlaythroughId]:
    """The run each converted row became.

    Partial by construction: a default run the conversion minted and a
    run TrackGame states carry no row id, because no row became either.
    """
    keys = [str(row_id) for row_id in row_ids]
    if not keys:
        return {}
    recorded = LibraryEvent.objects.filter(
        library=library,
        event_type=PLAYTHROUGH_CREATED.event_type,
        source_metadata__play_event_id__in=keys,
    ).values_list("source_metadata__play_event_id", "aggregate_id")
    return {uuid.UUID(row_id): run_id for row_id, run_id in recorded}


def run_for_row(library: UserLibrary, row_id: PlayEventId) -> Playthrough | None:
    """The run this legacy row became, or nothing.

    The run is read whatever its mark says: a removal answers Unchanged
    for a run already removed, which is a better answer than a refusal
    naming a row the person can still see.
    """
    run_id = runs_for_rows(library, [row_id]).get(row_id)
    if run_id is None:
        return None
    return (
        Playthrough.objects.select_related("player_game")
        .filter(library=library, pk=run_id)
        .first()
    )
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playthrough_provenance.py -x"`
Expected: PASS, three tests.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_provenance.py tests/test_playthrough_provenance.py
git commit -m "Read the run a converted legacy row became"
```

---

### Task 6: The form stops being a ModelForm

**Files:**
- Modify: `games/forms.py:1032-1080` (`PlayEventForm`)
- Test: `tests/test_playevent_form.py` (new), plus whatever
  `tests/test_library_form_isolation.py` already asserts about this form.

**Interfaces:**
- Consumes: `SingleGameChoiceField`, `SearchSelectWidget`, `DatePickerWidget`,
  `PrimitiveWidgetsMixin`, `_game_options` — all already in `games/forms.py`.
- Produces: `PlayEventForm(data, *, library, presentation, locked_game=None)`
  with `cleaned_data` keys `game`, `started`, `ended`, `note`,
  `mark_as_finished`. Task 7 reads them. Task 11 renames the class.

The form writes no row, so `ModelForm` has nothing to save. Its four derived
declarations are restated by hand: `started`/`ended` as
`DateField(required=False)` (the model columns are `null=True, blank=True`) and
`note` as `CharField(max_length=255, required=False)` (the column is
`max_length=255, blank=True`). `game` is already declared explicitly, and
`__init__` already narrows it to `Game.objects.for_library(library)` — a run
belongs to the library's own catalog row, so that read stays exactly as it is.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from django import forms

from games.forms import PlayEventForm


@pytest.mark.django_db
def test_the_form_writes_no_row(user, game, presentation):
    form = PlayEventForm(
        {"game": str(game.pk), "started": "2026-01-02", "ended": "", "note": "12h"},
        library=user.library,
        presentation=presentation,
    )

    assert form.is_valid(), form.errors
    assert not isinstance(form, forms.ModelForm)
    assert not hasattr(form, "save")
    assert form.cleaned_data["note"] == "12h"
    assert form.cleaned_data["ended"] is None


@pytest.mark.django_db
def test_a_locked_game_refuses_a_different_one(user, game, other_game, presentation):
    form = PlayEventForm(
        {"game": str(other_game.pk), "started": "", "ended": "", "note": ""},
        library=user.library,
        presentation=presentation,
        locked_game=game,
    )

    assert not form.is_valid()
    assert "game" in form.errors


@pytest.mark.django_db
def test_a_note_longer_than_the_column_is_refused(user, game, presentation):
    form = PlayEventForm(
        {"game": str(game.pk), "started": "", "ended": "", "note": "x" * 256},
        library=user.library,
        presentation=presentation,
    )

    assert not form.is_valid()
    assert "note" in form.errors
```

`presentation` is `date_time_presentation_for_request`'s value; build one the
way `tests/test_date_time_rendering_paths.py` does, or add a small fixture.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playevent_form.py -x"`
Expected: FAIL — the form is still a `ModelForm` and still has `save`.

- [ ] **Step 3: Rewrite the form**

```python
class PlayEventForm(PrimitiveWidgetsMixin, forms.Form):
    """One run, as a person states it.

    A plain Form: the submit states commands and writes no row, so
    there is nothing for ModelForm to save. The four declarations
    ModelForm derived are restated here against the same columns.
    """

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        locked_game: Game | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        #: An edit states facts about one run, and no command moves a
        #: run between games.
        self.locked_game = locked_game
        cast(
            forms.ModelChoiceField, self.fields["game"]
        ).queryset = Game.objects.for_library(library).order_by("sort_name")
        self.fields["game"].widget.options_resolver = partial(
            _game_options, library=library
        )
        for field_name in ("started", "ended"):
            self.fields[field_name].widget = DatePickerWidget(
                presentation=presentation,
                label=str(self.fields[field_name].label or field_name),
            )

    game = SingleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectWidget(
            search_url="/api/games/search",
            options_resolver=_game_options,
            autofocus=True,
        ),
    )

    started = forms.DateField(required=False)
    ended = forms.DateField(required=False)
    note = forms.CharField(max_length=255, required=False)

    mark_as_finished = forms.BooleanField(
        required=False,
        initial={"mark_as_finished": True},
        label="Set game status to Finished",
    )

    def clean_game(self) -> Game:
        game = self.cleaned_data["game"]
        if self.locked_game is not None and game.pk != self.locked_game.pk:
            raise forms.ValidationError(
                "A playthrough stays with its game. Remove this one and add "
                "it to the other game instead."
            )
        return game
```

`UserLibrary`, `DateTimePresentation`, `Game`, `partial` and `cast` are already
imported by `games/forms.py`.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playevent_form.py tests/test_library_form_isolation.py -x"`
Expected: PASS. The views still call `form.save()` at this point, so
`tests/test_paths_return_200.py` and friends break here — Task 7 fixes them,
and this task's commit is expected to leave that breakage inside the working
tree only if the two tasks land together. Do Task 7 before committing.

- [ ] **Step 5: Hold the commit for Task 7**

The form and its two views are one reviewable change; commit them together at
the end of Task 7.

---

### Task 7: The add and edit views

**Files:**
- Modify: `games/views/playevent.py:240-361` (`add_playevent`,
  `_record_completed`, `edit_playevent`)
- Test: `tests/test_playthrough_view_cutover.py` (new)

**Interfaces:**
- Consumes: Task 4's `record_run_for_request`/`restate_run_for_request`,
  Task 3's `RunDraft`, Task 5's `run_for_row`, Task 6's form.
- Produces: nothing further; Task 11 renames the module and its routes.

Keep, unchanged: the whole prefill block in `add_playevent` (it reads legacy
rows and sessions, which is right until #1012), `render_page`, the two
`ModuleScript` includes, and `return_url`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django.urls import reverse

from games.backfill.playthrough import convert_library
from games.models import LibraryEvent, PlayEvent, Playthrough
from games.reads.playthrough_provenance import run_for_row


@pytest.mark.django_db(transaction=True)
def test_adding_a_playthrough_writes_no_legacy_row(client, user, game):
    client.force_login(user)

    client.post(
        reverse("games:add_playevent"),
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "2026-02-03",
            "note": "12h",
        },
    )

    assert PlayEvent.objects.count() == 0
    run = Playthrough.objects.get(player_game__game=game)
    assert run.note == "12h"
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_marking_finished_states_the_status_under_one_correlation_id(
    client, user, game
):
    client.force_login(user)

    client.post(
        reverse("games:add_playevent"),
        {
            "game": str(game.pk),
            "started": "",
            "ended": "",
            "note": "",
            "mark_as_finished": "on",
        },
    )

    correlations = set(
        LibraryEvent.objects.filter(library=user.library)
        .exclude(event_type__startswith="library.playergame.tracked")
        .values_list("correlation_id", flat=True)
    )
    assert len(correlations) == 1


@pytest.mark.django_db(transaction=True)
def test_editing_a_converted_row_states_the_difference(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library, actor=user)
    client.force_login(user)

    client.post(
        reverse("games:edit_playevent", args=[row.pk]),
        {"game": str(game.pk), "started": "2026-01-02", "ended": "", "note": "read"},
    )

    run = run_for_row(user.library, row.pk)
    run.refresh_from_db()
    assert run.note == "read"
    row.refresh_from_db()
    assert row.note == ""


@pytest.mark.django_db(transaction=True)
def test_a_row_with_no_run_is_refused_on_the_edit_page(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    client.force_login(user)

    response = client.get(reverse("games:edit_playevent", args=[row.pk]), follow=True)

    assert b"was never converted" in response.content
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py -x"`
Expected: FAIL — the add view still writes a row.

- [ ] **Step 3: Rewrite the two views**

The whole of `add_playevent`'s valid branch becomes this (the prefill above it
does not move):

```python
def _draft_from(form: PlayEventForm) -> RunDraft:
    """The run the form states."""
    return RunDraft(
        started=form.cleaned_data["started"],
        ended=form.cleaned_data["ended"],
        note=form.cleaned_data["note"],
    )
```

```text
    if form.is_valid():
        game = form.cleaned_data["game"]
        correlation_id = new_correlation_id()
        if record_run_for_request(
            request, game, _draft_from(form), correlation_id=correlation_id
        ):
            if form.cleaned_data.get("mark_as_finished"):
                _record_completed(request, game, correlation_id)
            return redirect(
                return_url(
                    request,
                    fallback="games:view_game",
                    fallback_args=[game.id, game.url_slug],
                )
            )
```

`_record_completed` takes the game and the request's correlation id, rather than
a row and a fresh one:

```python
def _record_completed(
    request: HttpRequest, game: Game, correlation_id: uuid.UUID
) -> None:
    """State Completed for the game just finished.

    The request's correlation id, not a fresh one: the act and the
    status it implies belong to one submit. No shipped reader groups
    events that way yet -- playergame_history groups on aggregate_id
    and event_type -- so this changes no screen. It is the plumbing
    #683 needs.
    """
    record_facts_for_request(
        request,
        game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=correlation_id,
    )
```

`edit_playevent` reads the legacy row for prefill, maps it to its run, and
states differences:

```python
@login_required
def edit_playevent(request: HttpRequest, playevent_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    run = run_for_row(library, playevent.pk)
    if run is None:
        #: #684 converted the rows of tracked games only, so a row of a
        #: game the library stopped tracking has no run to state facts
        #: about. #771 takes the legacy row and this branch together.
        messages.error(
            request,
            "This play event was never converted into a playthrough, because "
            "your library no longer tracks its game. Track the game again to "
            "record runs at it.",
        )
        return redirect(
            return_url(
                request,
                fallback="games:view_game",
                fallback_args=[playevent.game.id, playevent.game.url_slug],
            )
        )
    form = PlayEventForm(
        request.POST or None,
        initial={
            "game": playevent.game,
            "started": playevent.started,
            "ended": playevent.ended,
            "note": playevent.note,
        },
        library=library,
        presentation=date_time_presentation_for_request(request),
        locked_game=playevent.game,
    )
    if form.is_valid():
        correlation_id = new_correlation_id()
        if restate_run_for_request(
            request, run, _draft_from(form), correlation_id=correlation_id
        ):
            if form.cleaned_data.get("mark_as_finished"):
                _record_completed(request, playevent.game, correlation_id)
            return redirect(
                return_url(
                    request,
                    fallback="games:view_game",
                    fallback_args=[playevent.game.id, playevent.game.url_slug],
                )
            )

    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit playthrough",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-picker.js"),
        ),
    )
```

Import `messages` from `django.contrib`, `uuid`, and the new write helpers;
drop nothing else from the module's imports until Task 11.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py tests/test_playevent_form.py -x"`
Then: `make test ARGS="tests/test_paths_return_200.py tests/test_action_origin_parity.py -x"`
Expected: PASS.

- [ ] **Step 5: Commit the form and the views together**

```bash
git add games/forms.py games/views/playevent.py tests/test_playevent_form.py \
        tests/test_playthrough_view_cutover.py
git commit -m "State a run from the add and edit views"
```

---

### Task 8: The removal view

**Files:**
- Modify: `games/views/playevent.py:364-377` (`remove_playevent`)
- Test: add to `tests/test_playthrough_view_cutover.py`; fix
  `tests/test_removal_confirmation.py`

**Interfaces:**
- Consumes: `confirm_and_apply` from `games/views/removal.py`, Task 4's
  `remove_run_for_request`, Task 5's `run_for_row`.

`tests/test_removal_confirmation.py` needs three changes, not one: its game is
already tracked (the autouse fixture in `tests/conftest.py` tracks every game it
creates), its `PlayEvent.objects.create(...)` mints no conversion event so the
row maps to no run, and its assertions read `PlayEvent.objects.for_library`,
which the removal no longer touches. Build the run through the write path and
read the projection.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db(transaction=True)
def test_removing_the_only_run_is_refused_on_the_confirmation(client, user, game):
    #: No track_game: the autouse fixture wrote the PlayerGame row, and
    #: the conversion turns this row into the game's one run.
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library, actor=user)
    client.force_login(user)

    response = client.post(reverse("games:remove_playevent", args=[row.pk]))

    assert response.status_code == 409
    assert b"only playthrough of that game" in response.content
    assert Playthrough.objects.filter(removed_at__isnull=False).count() == 0


@pytest.mark.django_db(transaction=True)
def test_removing_one_of_two_runs_stamps_the_projection_only(client, user, game):
    first = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    second = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library, actor=user)
    run = run_for_row(user.library, second.pk)
    client.force_login(user)

    response = client.post(reverse("games:remove_playevent", args=[second.pk]))

    assert response.status_code == 302
    run.refresh_from_db()
    assert run.removed_at is not None
    second.refresh_from_db()
    assert second.removed_at is None
    #: The other run is untouched, so the game keeps one.
    other = run_for_row(user.library, first.pk)
    assert other is not None and other.removed_at is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py -k removing -x"`
Expected: FAIL — the view still stamps the legacy row and answers 302.

- [ ] **Step 3: Rewrite the view**

```python
@login_required
def remove_playevent(request: HttpRequest, playevent_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )

    def act() -> None:
        run = run_for_row(library, playevent.pk)
        if run is None:
            raise CommandFailed(
                "This play event was never converted into a playthrough, "
                "because your library no longer tracks its game.",
                CONFLICT_STATUS,
            )
        remove_run_for_request(request, run, correlation_id=new_correlation_id())

    return confirm_and_apply(
        request,
        action=act,
        title="Remove playthrough",
        message=f"Remove this playthrough of {playevent.game}?",
        confirm_label="Remove",
        fallback="games:view_game",
        fallback_args=[playevent.game.id, playevent.game.url_slug],
    )
```

Import `CommandFailed` and `CONFLICT_STATUS` from `games.writes.answers` and
`confirm_and_apply` from `games.views.removal`; drop the `confirm_and_remove`
import if nothing else in the module uses it.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py tests/test_removal_confirmation.py -x"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views/playevent.py tests/test_playthrough_view_cutover.py \
        tests/test_removal_confirmation.py
git commit -m "Remove a run through its command, not the legacy stamp"
```

---

### Task 9: The API write handlers

**Files:**
- Modify: `games/api.py:216-255` (`create_playevent`,
  `partial_update_playevent`, `remove_playevent`)
- Test: `tests/test_playthrough_api_writes.py` (new)

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces: the three handlers. Task 11 moves the prefix to `/api/playthrough`
  and renames the functions.

The GET handlers keep their bodies and their `PlayEventOut` schema; #1015
rewrites them. `AutoPlayEventIn` is unused — check with a grep and take it out
if nothing names it. The POST answers 204: no row is written, so there is
nothing to answer with in the legacy shape, and the projection-backed body
belongs to #1015. `api.exception_handler(CommandFailed)` at `games/api.py:91`
already turns a refusal into its status and a toast, so the handlers call the
raising write module directly.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date

import pytest

from games.backfill.playthrough import convert_library
from games.models import PlayEvent, Playthrough
from games.reads.playthrough_provenance import run_for_row
from timetracker.temporal import TemporalValue


@pytest.mark.django_db(transaction=True)
def test_post_states_a_run_and_writes_no_row(client, user, game):
    client.force_login(user)

    response = client.post(
        "/api/playevent/",
        {"game_id": str(game.pk), "started": "2026-01-02", "ended": None, "note": ""},
        content_type="application/json",
    )

    assert response.status_code == 204
    assert PlayEvent.objects.count() == 0
    assert Playthrough.objects.filter(player_game__game=game).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_reversed_pair_answers_409(client, user, game):
    client.force_login(user)

    response = client.post(
        "/api/playevent/",
        {
            "game_id": str(game.pk),
            "started": "2026-02-03",
            "ended": "2026-01-02",
            "note": "",
        },
        content_type="application/json",
    )

    assert response.status_code == 409


@pytest.mark.django_db(transaction=True)
def test_a_key_the_patch_leaves_out_keeps_the_value_the_row_shows(client, user, game):
    row = PlayEvent.objects.create(
        game=game, started=date(2026, 1, 2), ended=None, note="12h"
    )
    convert_library(user.library, actor=user)
    run = run_for_row(user.library, row.pk)
    client.force_login(user)

    response = client.patch(
        f"/api/playevent/{row.pk}",
        {"note": "12h 30m"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "12h 30m"
    assert run.started == TemporalValue.from_day(date(2026, 1, 2))


@pytest.mark.django_db(transaction=True)
def test_patch_states_the_difference_onto_the_run(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library, actor=user)
    run = run_for_row(user.library, row.pk)
    client.force_login(user)

    response = client.patch(
        f"/api/playevent/{row.pk}",
        {"started": "2026-01-02", "ended": None, "note": "read"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "read"
    row.refresh_from_db()
    assert row.note == ""


@pytest.mark.django_db(transaction=True)
def test_delete_states_the_removal_and_leaves_the_row(client, user, game):
    PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    second = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library, actor=user)
    run = run_for_row(user.library, second.pk)
    client.force_login(user)

    response = client.delete(f"/api/playevent/{second.pk}")

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.removed_at is not None
    second.refresh_from_db()
    assert second.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_a_row_with_no_run_answers_409(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    client.force_login(user)

    response = client.delete(f"/api/playevent/{row.pk}")

    assert response.status_code == 409


def test_only_two_modules_read_the_bridge():
    """#771 takes the bridge away; a third reader is a decision."""
    import pathlib

    readers = sorted(
        path.as_posix()
        for path in pathlib.Path("games").rglob("*.py")
        if "playthrough_provenance" in path.read_text()
        and path.name != "playthrough_provenance.py"
    )
    assert readers == ["games/api.py", "games/views/playevent.py"]
```

The reader test names files, not call counts: the edit and remove views live in
one module and the two API handlers in another. Task 11 renames
`games/views/playevent.py`, so that task updates this list.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_api_writes.py -x"`
Expected: FAIL — POST answers 201 and writes a row.

- [ ] **Step 3: Rewrite the three handlers**

```python
@playevent_router.post("/", response={204: None})
def create_playevent(request, payload: PlayEventIn):
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=payload.game_id)
    record_run(
        cast("User", request.user),
        game,
        RunDraft(started=payload.started, ended=payload.ended, note=payload.note),
        correlation_id=new_correlation_id(),
    )
    messages.success(request, "Playthrough recorded")
    return Status(204, None)
```

```python
@playevent_router.patch("/{playevent_id}", response={204: None})
def partial_update_playevent(request, playevent_id: UUIDv7, payload: UpdatePlayEventIn):
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    run = run_for_row(library, playevent.pk)
    if run is None:
        raise CommandFailed(_NO_RUN_FOR_ROW, CONFLICT_STATUS)
    #: PATCH states some of a run; restate_run states all of one. A key
    #: the payload leaves out keeps the value the legacy row shows,
    #: which is the value this surface read it from. #1015 restates the
    #: whole handler against the projection.
    stated = payload.dict(exclude_unset=True)
    restate_run(
        cast("User", request.user),
        run,
        RunDraft(
            started=stated.get("started", playevent.started),
            ended=stated.get("ended", playevent.ended),
            note=stated.get("note", playevent.note),
        ),
        correlation_id=new_correlation_id(),
    )
    return Status(204, None)
```

```python
#: DELETE is the transport's word, not ours.
@playevent_router.delete("/{playevent_id}", response={204: None})
def remove_playevent(request, playevent_id: UUIDv7):
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    run = run_for_row(library, playevent.pk)
    if run is None:
        raise CommandFailed(_NO_RUN_FOR_ROW, CONFLICT_STATUS)
    remove_run(cast("User", request.user), run, correlation_id=new_correlation_id())
    return Status(204, None)
```

with the shared sentence beside the router declarations:

```python
#: One sentence for the two handlers that need a converted row.
_NO_RUN_FOR_ROW = (
    "This play event was never converted into a playthrough, because your "
    "library no longer tracks its game."
)
```

`PATCH` answered `PlayEventOut` before and answers 204 now, for the same reason
the POST does. Note that in the surface table of the spec.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playthrough_api_writes.py tests/test_library_api_isolation.py -x"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/api.py tests/test_playthrough_api_writes.py
git commit -m "State runs from the API write handlers"
```

---

### Task 10: The "Played +1" action goes away

**Files:**
- Modify: `games/views/game.py:440-485` (`_played_row`), `:976-982` (the
  container's dead htmx trigger)
- Modify: `common/components/custom_elements.py:165-173`, `:209`
- Remove: `ts/elements/play-event-row.ts`
- Regenerate: `ts/generated/props.ts`
- Modify: `tests/test_rendered_pages.py:350-437`,
  `e2e/test_custom_elements_e2e.py:155-200`,
  `e2e/test_played_dropdown_e2e.py`

Why now, in this issue and not in #1024: a click that filled in the run a
tracked game already holds left the game with one run stating both acts, which
#1011 refuses to take off a tracked game — so a misclick was undoable only by
untracking the whole game. #1024 owns the need behind the action. The count and
the "Add playthrough…" item stay.

- [ ] **Step 1: Rewrite the played row**

```python
def _played_row(game: Game, origin: OriginUrl | None) -> Node:
    """'Played N times' split button.

    The '+1' action and the custom element that owned it went with
    #687: a click that filled in the run a tracked game already holds
    left a run only untracking the game could take back. #1024 owns
    stating a count without filling in a form per run.
    """
    from common.components import (
        ControlButton,
        DropdownLinkItem,
        SplitButtonDropdown,
    )

    played = game.playevents.alive().count()

    count_button = ControlButton(
        [("class", "rounded-s-lg")],
        variant="outline",
        href=action_url("games:add_playevent", origin=origin),
    )[
        # One prose phrase = one flex item: the button is inline-flex, and flex
        # layout drops whitespace-only text between items, so the space must
        # live inside a single inline context.
        Span()[Span(data_count="")[str(played)], " times"]
    ]
    dropdown = SplitButtonDropdown(
        primary=count_button,
        id=f"played-{game.id}",
        aria_label="Playthrough actions",
        items=[
            DropdownLinkItem(
                action_url("games:add_playevent_for_game", game.id, origin=origin),
                "Add playthrough...",
            ),
        ],
    )
    return Div(class_="flex gap-2 items-center")[
        Span(class_="uppercase")["Played"], dropdown
    ]
```

The `request` parameter went with `get_token`, so the one call site
(`games/views/game.py:841`) becomes `_played_row(game, origin)`. Then drop the
now-unused `get_token`/`reverse` imports if nothing else in
`games/views/game.py` uses them (grep before removing either).

- [ ] **Step 2: Take the element out**

Remove `PlayEventRowProps`, its `register_element("play-event-row", …)` call and
the `_PlayEventRow = custom_element_builder("play-event-row")` line from
`common/components/custom_elements.py`, then `rm ts/elements/play-event-row.ts`.

Run: `make gen-element-types` (rewrites `ts/generated/props.ts`), then
`make ts-check`.
Expected: clean; `PlayEventRowProps` gone from the generated module.

- [ ] **Step 3: Take the dead htmx trigger off the section**

Nothing fires `play-added` any more. In `games/views/game.py:976-982` the
wrapper keeps its id and loses the four htmx attributes and the stale comment:

```text
    #: #1012 replaces this section with the projection's own.
    return Div(id_="playevents-container")[section]
```

- [ ] **Step 4: Update the Python tests**

In `tests/test_rendered_pages.py`: drop `"<play-event-row"` from the marker
list in `test_view_game`; take out `test_view_game_uses_play_event_row_element`;
re-anchor `test_played_row_count_link_is_a_single_anchor` and
`test_played_row_label_is_one_flex_item_and_count_is_a_prop` on
`html.index('id="played-')` instead of `html.index("<play-event-row")`, and drop
the `count="0"` prop assertion from the second (the prop is gone; the
`<span data-count="">0</span> times` assertion stays, because the prose-phrase
layout is what that test is about).

Run: `make test ARGS="tests/test_rendered_pages.py -x"`
Expected: PASS.

- [ ] **Step 5: Update the browser tests**

In `e2e/test_custom_elements_e2e.py`: take out `test_play_event_row_increments`
entirely (it is the element's own test).

In `e2e/test_played_dropdown_e2e.py`: take out
`test_played_plus_one_fires_when_clicking_row_edge` and
`test_played_plus_one_refreshes_play_events_table`. Retarget the other three at
the "Add playthrough..." row, which is what the menu now holds:

```python
def open_played_menu(page: Page, live_server, game: Game) -> None:
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    page.locator("[id^=played-] [data-toggle]").click()
    expect(page.locator("[id^=played-] [data-menu]")).to_be_visible()


def add_playthrough_row(page: Page):
    """The '<li>' wrapping the 'Add playthrough...' link."""
    return page.locator("[id^=played-] [data-menu] li").filter(
        has_text="Add playthrough"
    )
```

Rename `test_played_plus_one_target_fills_the_row` to
`test_played_menu_link_target_fills_the_row` and assert the element under each
row fraction is an `<a>` or sits inside one, in place of the `[data-add-play]`
check. Update the module docstring: the regression it guards is the row-filling
click target, which is still real.

Run: `make test-e2e ARGS="-k played or custom_elements"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Take the 'Played +1' action out

A click that filled in the run a tracked game already holds left a run
only untracking the game could take back. #1024 owns stating a count
without a form per run."
```

---

### Task 11: The rename and the router move

**Files:**
- Rename: `games/views/playevent.py` → `games/views/playthrough.py`
- Modify: `games/urls.py:10,69-85`, `games/views/returns.py:27,45-62`,
  `games/filters.py:116,131,201-205,727,771,785`, `games/sorting.py:34-35,122-129,155`,
  `games/views/filtering.py:30`, `games/views/stats_links.py` (six
  `playevent_filter` keyword uses), `common/components/custom_elements.py:68`,
  `common/components/quick_filter.py:130`, `games/api.py:357` and the five
  router functions, `games/forms.py` (`PlayEventForm` → `PlaythroughForm`),
  `games/models.py:1441` (`MODE_CHOICES`), `common/criteria.py:1171,1767`
  (comments), `ts/elements/filter-group.test.ts` (the `playevent_filter`
  fixtures)
- Modify: 29 files under `tests/` and `e2e/` that name a renamed route, the
  form, the sorts, the mode key or a criterion key; five of them
  (`tests/test_removal.py`, `tests/test_library_reconciliation.py`,
  `tests/test_catalog_uuid_primary_key.py`,
  `tests/test_session_playhistory_runtime_identity.py`,
  `tests/test_library_api_isolation.py`) name `/api/playevent` as a literal
- Modify: `tests/test_playthrough_api_writes.py` (the reader file list in
  `test_only_two_modules_read_the_bridge`)
- Modify: `docs/superpowers/specs/2026-09-04-playthrough-wave-design.md:238-255`

**What does not move.** Three names are the model's name wearing a suffix and
wait for #771, which renames the model:

- `PlayEventFilter`. `filter_for_model` resolves
  `globals()[f"{model.__name__}Filter"]` by convention and keeps no registry, so
  renaming it is a `KeyError` on the quick bar and the nested builder.
- the singular key `"playevent"`, which is `PlayEvent._meta.model_name` —
  `FILTER_MODE_MODELS`, the builder URL segment `/playevent/filter`,
  `ts/elements/filter-tree/fixtures.json` and `FILTER_FOR_MODEL` in
  `tests/test_filter_tree_contract.py` all read it.
- `related_name="playevents"`, `game.playevents`, and the two
  `Max("playevents__ended")` sort annotations.

- [ ] **Step 1: Move the view module and its routes**

```bash
git mv games/views/playevent.py games/views/playthrough.py
```

Rename the five view functions (`list_playevents` → `list_playthroughs`,
`add_playevent` → `add_playthrough`, `edit_playevent` → `edit_playthrough`,
`remove_playevent` → `remove_playthrough`, and
`create_playevent_tabledata` → `create_playthrough_tabledata`), the five route
names and the five URL paths (`playevent/…` → `playthrough/…`), the `playevent_id`
route argument, and the five entries in `games/views/returns.py`. Update the
`entity="playevent"` argument of `warn_unknown_sort` and the page titles.

- [ ] **Step 2: Rename the free filter and sort names**

`parse_playevent_filter` → `parse_playthrough_filter`; the criterion keys
`playevent_count` → `playthrough_count` and `playevent_filter` →
`playthrough_filter` (the dataclass field names on `GameFilter` and
`PurchaseFilter`, the `AggregateSpec` dict key at `games/filters.py:727` — its
`"playevents"` argument is the relation name and stays); `PLAYEVENT_SORTS` →
`PLAYTHROUGH_SORTS` and `PLAYEVENT_DEFAULT_SORT` → `PLAYTHROUGH_DEFAULT_SORT`
including the two `__all__` entries; the mode key `"playevents"` →
`"playthroughs"` in all seven places (`MODE_PARSERS`, `FILTER_MODE_LIST_URLS`,
`FILTER_MODE_MODELS`, `BUILDER_MODES` in `games/views/filtering.py:30`,
`QUICK_FACETS`, `MODE_SORTS`, and `FilterPreset.MODE_CHOICES` — whose label also
becomes `"Playthroughs"`).

`PlayEventForm` → `PlaythroughForm` in `games/forms.py` and its importers.

- [ ] **Step 3: Move the API router**

`api.add_router("/playevent", playevent_router)` becomes
`api.add_router("/playthrough", playthrough_router)`; rename the router variable
and the five handler functions (`list_playevents`, `create_playevent`,
`get_playevent`, `partial_update_playevent`, `remove_playevent`). Ninja derives
each `url_name` from the function name, so the five reverses move with them; the
one non-test reverse went away with the element in Task 10. Rename the four
schemas to match (`PlayEventIn` → `PlaythroughIn`, and so on) — they are not
model-derived. `PlayEventOut` reads the legacy row and keeps doing so until
#1015; rename it too, and say so in the docstring.

Amend the wave doc's #1015 boundary at
`docs/superpowers/specs/2026-09-04-playthrough-wave-design.md:254-255`: the
router prefix and the row element are done in #687, and #1015 owns the GET
bodies alone.

- [ ] **Step 4: Sweep the tests**

```bash
git grep -ln "add_playevent\|edit_playevent\|remove_playevent\|list_playevents\|PlayEventForm\|parse_playevent_filter\|PLAYEVENT_SORTS\|PLAYEVENT_DEFAULT_SORT\|playevent_count\|playevent_filter\|\"playevents\"\|'playevents'\|/api/playevent" tests e2e
```

Work the list (29 files) one at a time. Leave every use of `PlayEvent`,
`PlayEventFilter`, `game.playevents`, `"playevent"` and `playevents__ended`
alone — those are the model's own name.

- [ ] **Step 5: Update the TypeScript fixtures**

`ts/elements/filter-group.test.ts` names `playevent_filter` as a relation field
in four places; rename them to `playthrough_filter`. The `filter: "PlayEventFilter"`
and `model: "PlayEvent"` values in the same fixtures stay.

Run: `make test-ts`
Expected: PASS.

- [ ] **Step 6: Run the aggregate**

Run: `make check-fast`
Expected: clean. `tests/test_returns_classification.py` is the completeness
guard on the renamed routes; `tests/test_quick_filter_bar.py` and
`tests/test_filter_tree_contract.py` are the two that catch a rename that went
one name too far.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Rename the play event to the playthrough

Every identifier that does not derive from the model's own name. The
filter class, the singular model key and the relation name wait for
#771, which renames the model."
```

---

### Task 12: The saved-preset migration

**Files:**
- Create: `games/migrations/00NN_playthrough_preset_mode.py`
- Test: `tests/test_playthrough_preset_migration.py` (new)

Two stored strings carry the old word: `FilterPreset.mode`, where `playevents`
becomes `playthroughs`, and `object_filter`, where the keys `playevent_count`
and `playevent_filter` are rewritten wherever they appear — `OperatorFilter`
nests, so at any depth, and inside `field_comparisons` too. `find_filter` needs
no pass: it holds only `sort` and `per_page`, and no sort key carries the word.

Changing `MODE_CHOICES` in Task 11 makes Django emit an `AlterField`, so the
schema operation and the data operation travel in one file.

- [ ] **Step 1: Write the failing test**

The two rewrite functions are importable from the migration module, so the
rewrite itself is tested as a function and the schema half is left to
`make migrate`:

```python
import pytest
from django.apps import apps
from django.utils.module_loading import import_string

from games.models import FilterPreset

MIGRATION = "games.migrations.00NN_playthrough_preset_mode"


def test_a_nested_criterion_key_is_rewritten_at_any_depth():
    rewrite = import_string(f"{MIGRATION}._rewrite")

    rewritten = rewrite(
        {
            "AND": [
                {"playevent_count": {"modifier": "GREATER_THAN", "value": 1}},
                {"OR": [{"playevent_filter": {"note": {"value": "x"}}}]},
            ]
        },
        {
            "playevent_count": "playthrough_count",
            "playevent_filter": "playthrough_filter",
        },
    )

    assert rewritten == {
        "AND": [
            {"playthrough_count": {"modifier": "GREATER_THAN", "value": 1}},
            {"OR": [{"playthrough_filter": {"note": {"value": "x"}}}]},
        ]
    }


@pytest.mark.django_db
def test_the_forward_pass_rewrites_the_mode_and_the_stored_filter(user):
    preset = FilterPreset.objects.create(
        user=user,
        name="Long runs",
        mode="playevents",
        find_filter={"sort": "-ended"},
        object_filter={"AND": [{"playevent_count": {"value": 2}}]},
        ui_options={},
    )
    rename_forward = import_string(f"{MIGRATION}.rename_forward")

    rename_forward(apps, None)

    preset.refresh_from_db()
    assert preset.mode == "playthroughs"
    assert preset.object_filter == {"AND": [{"playthrough_count": {"value": 2}}]}


@pytest.mark.django_db
def test_the_backward_pass_is_the_inverse(user):
    preset = FilterPreset.objects.create(
        user=user,
        name="Long runs",
        mode="playthroughs",
        find_filter={},
        object_filter={"AND": [{"playthrough_filter": {"note": {"value": "x"}}}]},
        ui_options={},
    )
    rename_backward = import_string(f"{MIGRATION}.rename_backward")

    rename_backward(apps, None)

    preset.refresh_from_db()
    assert preset.mode == "playevents"
    assert preset.object_filter == {
        "AND": [{"playevent_filter": {"note": {"value": "x"}}}]
    }
```

`apps` here is `django.apps.apps`: both passes read the model through
`apps.get_model("games", "FilterPreset")`, and the live registry answers that
the same way a historical one does for a table this migration does not reshape.
Rename `00NN` to the number `make makemigrations` gives the file. The mode
values are the literal strings, not `FilterPreset.MODE_CHOICES` members, because
Task 11 has already changed that tuple.

- [ ] **Step 2: Generate the migration**

Run: `make makemigrations ARGS="games --name playthrough_preset_mode"`
Expected: an `AlterField` on `filterpreset.mode`. Add the data operation to the
same file:

```python
def _rewrite(value, mapping):
    """Rename criterion keys at every depth of a stored filter."""
    if isinstance(value, dict):
        return {
            mapping.get(key, key): _rewrite(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite(item, mapping) for item in value]
    return value
```

```python
#: The two criterion keys the rename moved, forward.
_KEYS = {
    "playevent_count": "playthrough_count",
    "playevent_filter": "playthrough_filter",
}


def _rename(apps, keys, *, mode_from, mode_to):
    """Rewrite every saved preset that names the old word.

    A plain queryset walk, not `.iterator()`: a server-side cursor is
    refused (`tests/test_iterator_guard.py`), and a preset table holds
    tens of rows.
    """
    preset_model = apps.get_model("games", "FilterPreset")
    for preset in preset_model.objects.all():
        rewritten = _rewrite(preset.object_filter, keys)
        mode = mode_to if preset.mode == mode_from else preset.mode
        if (rewritten, mode) == (preset.object_filter, preset.mode):
            continue
        preset.object_filter = rewritten
        preset.mode = mode
        preset.save(update_fields=["object_filter", "mode"])


def rename_forward(apps, schema_editor):
    """playevents -> playthroughs, in the mode and in the stored filter."""
    _rename(apps, _KEYS, mode_from="playevents", mode_to="playthroughs")


def rename_backward(apps, schema_editor):
    """The inverse, so a downgrade reads its own presets."""
    _rename(
        apps,
        {new: old for old, new in _KEYS.items()},
        mode_from="playthroughs",
        mode_to="playevents",
    )
```

Register it as `migrations.RunPython(rename_forward, rename_backward)`, after
the `AlterField`.

- [ ] **Step 3: Run the tests**

Run: `make test ARGS="tests/test_playthrough_preset_migration.py tests/test_filter_presets.py -x"`
Expected: PASS.

- [ ] **Step 4: Rehearse it on real data**

Run: `make verify-dump`
Expected: the restore migrates clean and the scratch database is dropped.

- [ ] **Step 5: Commit**

```bash
git add games/migrations tests/test_playthrough_preset_migration.py
git commit -m "Rewrite the saved presets that name the play event"
```

---

### Task 13: The gate

- [ ] **Step 1: Count the rows that meet refusal 5**

Run: `make preflight-playthroughs ARGS="--all-libraries"` against a restored
production copy (`make restore-dump` prints its `DATABASE_URL`). The number to
read is the live rows whose game the library no longer tracks: those stay on the
list page and their Edit and Remove buttons now always refuse. A count large
enough to matter turns this from a refusal into a conversion pass, which #684
owns — say the number in the pull request either way.

- [ ] **Step 2: Confirm no request path writes the legacy table**

```bash
git grep -n "PlayEvent.objects.create\|playevent.save()\|PlayEvent(" games/ \
  | grep -v migrations
```
Expected: only the fixture loader and `games/management/commands/`. Nothing
under `games/views/` or in `games/api.py`.

- [ ] **Step 3: Run the full gate**

Run: `make check`
Expected: green, including `e2e/`. Never a hand-picked subset.

- [ ] **Step 4: Sweep the docs**

Drop this plan document (`git rm`), re-read the spec against what landed, and
record on #1013 and #1015 that the naming work moved into #687, add the
provenance module to #771's body, and note the `+1` removal and #1024 in #687
and in the wave doc.

Run: `make check` again after the plan file goes, because
`make format-check` reads Markdown code fences.

- [ ] **Step 5: Open the pull request**

```bash
git push -u origin issue-687-playthrough-write-cutover
gh pr create --title "Switch lifecycle writes to Playthrough commands (#687)" \
             --body-file /tmp/pr-687.md
```
