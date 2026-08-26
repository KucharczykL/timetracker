# PlayerGame Current-State Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first real projection — one `PlayerGame` row per catalog game a library tracks, written only by a projector folding one event that one command appends.

**Architecture:** A `ProjectionModel` subclass whose primary key is the creation event's `aggregate_id`; an `EventSpec` whose payload carries a `catalog.game` `Reference`; a `CURRENT_STATE` `Projector` that upserts on that key; a `Command` reached only through `dispatch()`. Nothing renders, and no existing read path changes.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pydantic `TypedDict` payload schemas, pytest / pytest-django.

**Spec:** `docs/superpowers/specs/2026-08-26-issue-671-playergame-projection-design.md`

## Global Constraints

- **Drive everything through `make`.** Never run `uv run`, `pytest`, `pnpm`, or
  `direnv exec .` directly. Focused runs:
  `make test ARGS="tests/test_playergame_projection.py -x"`.
- **Iterate with `make check-fast`; the gate is the full `make check`** (which
  includes `e2e/`). Only the full gate counts as verification.
- **Python 3.14 and PostgreSQL 18 are hard prerequisites.** A `SyntaxError` in an
  `except A, B:` line means the wrong interpreter, not broken code.
- **Never write to a `GeneratedField`** (`duration_calculated`, `duration_total`,
  `price_per_game`, `days_to_finish`). None of them appear in this work.
- **Unabbreviated identifiers** in Python and TypeScript (`element` not `el`).
- **Comment style:** this codebase marks explanatory notes with `#:`. Follow the
  surrounding density — the event modules comment the *why*, never the *what*.
- **A projection row is a pure function of the events.** No field may be minted,
  defaulted in the database, or stamped from the clock; `games/checks.py`
  enforces it as `games.E001`–`games.E006`.
- **Dispatch opens its own transaction.** Every test that calls `dispatch()`,
  `lock_stream()`, or `rebuild_projections()` must be marked
  `@pytest.mark.django_db(transaction=True)`; the plain `db` fixture wraps the
  test in an atomic block and `run_in_transaction` refuses to nest.

---

### Task 1: The PlayerGame table

**Files:**
- Modify: `games/models.py` (immediately after `ProjectionModel`, which ends at line 1269)
- Create: `games/migrations/0028_playergame.py` (generated, not hand-written)
- Create: `tests/test_playergame_projection.py`
- Modify: `tests/test_projection_rebuild.py:130-132`
- Modify: `tests/test_uuid_identity_audit.py:29-63` (the pinned relation set)
- Modify: `CLAUDE.md:152`

**Interfaces:**
- Consumes: `ProjectionModel` and `Game` from `games/models.py`; `UUIDv7Field`
  from `timetracker/uuidv7.py`.
- Produces: `games.models.PlayerGame`, with fields `id` (UUID, no default),
  `library` (FK, inherited), `game` (FK to `Game`), `tracked_at` (datetime, no
  default), and a unique constraint named `unique_library_player_game` over
  `("library", "game")`. Every later task imports this model.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playergame_projection.py`:

```python
"""The first projection: one row per catalog game a library tracks."""

import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.models import Game, PlayerGame


@pytest.fixture
def tracked_game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def other_library(django_user_model, db):
    other = django_user_model.objects.create_user(username="other-owner", password="p")
    return other.library


def test_playergame_is_a_pure_projection():
    """Nothing in the row may come from anywhere but the event."""
    complaints = [
        str(message.id)
        for message in check_projection_models()
        if message.obj is PlayerGame
    ]

    assert complaints == []


def test_the_identity_has_no_default():
    #: UUIDv7Field mints one unless told not to. A projection key is the
    #: event's aggregate_id, so a rebuild reproduces the identity it had.
    assert PlayerGame().id is None


def test_a_library_tracks_one_game_once(owned_library, tracked_game):
    PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=tracked_game,
        tracked_at=timezone.now(),
    )

    #: The savepoint is not decoration: an IntegrityError marks the test's
    #: surrounding atomic block for rollback, and every later query in the
    #: test would raise TransactionManagementError instead of running.
    with transaction.atomic(), pytest.raises(IntegrityError):
        PlayerGame.objects.create(
            id=uuid.uuid7(),
            library=owned_library,
            game=tracked_game,
            tracked_at=timezone.now(),
        )


def test_two_libraries_track_one_shared_game_independently(
    owned_library, other_library
):
    #: No library: the shared catalog.
    shared = Game.objects.create(name="Outer Wilds")

    for library in (owned_library, other_library):
        PlayerGame.objects.create(
            id=uuid.uuid7(),
            library=library,
            game=shared,
            tracked_at=timezone.now(),
        )

    assert PlayerGame.objects.filter(game=shared).count() == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_projection.py -x"`
Expected: FAIL at import with `ImportError: cannot import name 'PlayerGame' from 'games.models'`.

- [ ] **Step 3: Add the model**

In `games/models.py`, directly below the `ProjectionModel` class (before
`class UserLibraryPreferences`):

```python
class PlayerGame(ProjectionModel):
    """One catalog game a library tracks, projected from its events."""

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The creation event's aggregate_id. UUIDv7Field supplies both a minted
        #: default and a database default; `games.checks` refuses each on a
        #: projection, because a rebuild would evaluate them again.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    game = models.ForeignKey(
        Game,
        #: Never collateral: a replay owns these rows, so nothing else may
        #: cascade them away.
        on_delete=models.RESTRICT,
        related_name="player_games",
    )
    #: The creation event's recorded_at.
    tracked_at = models.DateTimeField(editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("library", "game"),
                name="unique_library_player_game",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.game} tracked by library {self.library_id}"
```

- [ ] **Step 4: Generate the migration**

Run: `make makemigrations`
Expected: `games/migrations/0028_playergame.py` created, containing a single
`CreateModel` whose `options={"constraints": [...]}` carries the unique
constraint inline — the autodetector only splits constraints into a separate
`AddConstraint` when a circular dependency forces it, and
`games/migrations/0026_libraryeventreference.py:67` is the precedent. Read the
file and confirm the `id` column has no `default` and no `db_default`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_projection.py -x"`
Expected: PASS, 4 tests.

- [ ] **Step 6: Retire the assertion that no projection table exists**

`tests/test_projection_rebuild.py:130-132` currently reads:

```python
def test_the_application_declares_no_projection_table_yet():
    #: The foundation before the first family.
    assert projection_models() == ()
```

Replace it with:

```python
def test_the_application_declares_the_playergame_projection():
    #: The first family's table, and so far the only one.
    assert projection_models() == (PlayerGame,)
```

Add `PlayerGame` to the `from games.models import (...)` block at the top of
that file, keeping the names alphabetical.

- [ ] **Step 7: Register the two new relation columns with the identity audit**

`games/identity_audit.py` derives its expectations from model metadata, but
`tests/test_uuid_identity_audit.py` pins the derivation against a hand-written
set so that a wrong derivation cannot agree with itself. Two foreign keys arrive
with this model, so two pairs join `EXPECTED_RELATION_COLUMNS`, in the set's
existing alphabetical order — after the `games_platform` entry:

```python
    ("games_platform", "library_id"),
    ("games_playergame", "game_id"),
    ("games_playergame", "library_id"),
    ("games_playevent", "game_id"),
```

Nothing else in that file changes: both columns are `uuid_v7`, so neither
`RESIDUAL_INTEGER_RELATIONS` nor `RESIDUAL_INTEGER_PRIMARY_KEYS` gains an entry.

Run: `make test ARGS="tests/test_uuid_identity_audit.py"`
Expected: PASS. Skipping this step fails
`test_relation_columns_cover_every_games_relation`, and
`tests/test_projection_rebuild.py:1236` too — its leak detector imports the same
constant.

- [ ] **Step 8: Record the model in CLAUDE.md**

After the `FilterPreset` bullet at `CLAUDE.md:152`, add:

```markdown
- **PlayerGame** — the first event-sourced projection: one row per catalog `Game` a library tracks. `id` is the creation event's `aggregate_id`, `tracked_at` its `recorded_at`, unique per `(library, game)`. Written only by the `CURRENT_STATE` projector; never by a view
```

- [ ] **Step 9: Run the neighbouring suites**

Run: `make test ARGS="tests/test_projection_rebuild.py tests/test_projection_model.py tests/test_playergame_projection.py tests/test_uuid_identity_audit.py"`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add games/models.py games/migrations/0028_playergame.py tests/test_playergame_projection.py tests/test_projection_rebuild.py tests/test_uuid_identity_audit.py CLAUDE.md
git commit -m "Give the projections their first table"
```

---

### Task 2: The creation event type

**Files:**
- Create: `games/events/playergame.py`
- Create: `tests/test_playergame_events.py`

**Interfaces:**
- Consumes: `Reference` and `STRICT_SCHEMA` from `games/events/references.py`;
  `EventSpec` and `DEFAULT_EVENT_TYPES` from `games/events/vocabulary.py`.
- Produces: `PlayerGameCreatedPayload` (a `TypedDict` with the single key
  `game: Reference`) and `PLAYERGAME_CREATED`, an `EventSpec` over event type
  `"library.playergame.created"`, aggregate type `"playergame"`, registered into
  `DEFAULT_EVENT_TYPES` at import. Tasks 3 and 4 import `PLAYERGAME_CREATED`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playergame_events.py`:

```python
"""The vocabulary a library uses to say it tracks a game."""

import uuid

import pytest

from games.events.playergame import PLAYERGAME_CREATED
from games.events.references import Reference, ReferenceArity
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid


def a_game_reference() -> Reference:
    return Reference(
        kind="catalog.game",
        id=str(uuid.uuid7()),
        label="Outer Wilds",
        detail="2019",
    )


def test_the_creation_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.created")

    assert registered is PLAYERGAME_CREATED
    assert registered.aggregate_type == "playergame"


def test_the_payload_declares_its_catalog_reference():
    #: This declaration is the whole integration with the reference index: it
    #: writes the LibraryEventReference row, protects the game from deletion,
    #: and is checked before every fold.
    assert DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERGAME_CREATED.event_type) == {
        "game": ReferenceArity.SINGLE
    }


def test_a_payload_repeating_what_the_envelope_records_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_CREATED.event_type,
            {"game": a_game_reference(), "library": str(uuid.uuid7())},
        )


def test_a_payload_naming_no_game_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_CREATED.event_type, {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_events.py -x"`
Expected: FAIL with `ModuleNotFoundError: No module named 'games.events.playergame'`.

- [ ] **Step 3: Write the event module**

Create `games/events/playergame.py`:

```python
"""What a library records about the catalog games it tracks.

The first production vocabulary. Until now `DEFAULT_EVENT_TYPES` was empty by
design; registering happens at import, and `games/projectors/playergame.py`
imports this module, which `GamesConfig.ready()` reaches through the projector
package.
"""

from typing import TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA, Reference
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec


@with_config(STRICT_SCHEMA)
class PlayerGameCreatedPayload(TypedDict):
    """The catalog game this library began tracking.

    One key. The library is on the envelope, the identity is the aggregate_id,
    and the time is recorded_at; repeating any of them here would be a second
    copy of a fact the event already carries.
    """

    game: Reference


PLAYERGAME_CREATED = EventSpec(
    "library.playergame.created",
    aggregate_type="playergame",
    payload=PlayerGameCreatedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_CREATED)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_events.py -x"`
Expected: PASS, 4 tests.

- [ ] **Step 5: Type-check**

Run: `make typecheck`
Expected: no new errors. `EventSpec` is a frozen dataclass whose fields are
`(event_type, aggregate_type, payload, version=1)`, so the call above matches it
positionally-then-by-keyword; the registry checks `is_typeddict(spec.payload)` at
runtime and refuses anything else.

- [ ] **Step 6: Commit**

```bash
git add games/events/playergame.py tests/test_playergame_events.py
git commit -m "Say in events that a library tracks a game"
```

---

### Task 3: The current-state projector

**Files:**
- Create: `games/projectors/playergame.py`
- Modify: `games/projectors/__init__.py`
- Modify: `tests/test_playergame_projection.py`

**Interfaces:**
- Consumes: `PLAYERGAME_CREATED` (Task 2), `PlayerGame` (Task 1),
  `Projector` / `ProjectorFamily` / `HandlerMap` from
  `games/events/projection.py`, `RecordedEvent` from `games/events/envelope.py`.
- Produces: `games.projectors.playergame.PlayerGames`, registered into
  `DEFAULT_REGISTRY` under `ProjectorFamily.CURRENT_STATE` at import. After this
  task, appending a `library.playergame.created` event writes a row with no
  further wiring.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_projection.py` (and extend its imports):

```python
from games.events.append import lock_stream
from games.events.playergame import PLAYERGAME_CREATED
from games.events.references import capture_reference
from games.events.replay import replay


def append_created(library, actor, game, *, identity, key="track"):
    """Append one creation event the way a command would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                PLAYERGAME_CREATED.new(
                    aggregate_id=identity,
                    payload={"game": capture_reference(game)},
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


@pytest.mark.django_db(transaction=True)
def test_the_creation_event_writes_the_tracked_row(
    owned_user, owned_library, tracked_game
):
    identity = uuid.uuid7()

    appended = append_created(
        owned_library, owned_user, tracked_game, identity=identity
    )

    row = PlayerGame.objects.get(pk=identity)
    assert row.library_id == owned_library.pk
    assert row.game_id == tracked_game.pk
    assert row.tracked_at == appended.events[0].recorded_at


@pytest.mark.django_db(transaction=True)
def test_folding_the_stream_again_writes_no_second_row(
    owned_user, owned_library, tracked_game
):
    #: A replay folds every event a second time. Keying the write on the
    #: event's own identity is what makes that a no-op instead of a duplicate.
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)

    replay(owned_library)

    assert PlayerGame.objects.count() == 1
    assert PlayerGame.objects.get().pk == identity
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_projection.py -x -k creation_event"`
Expected: FAIL with `PlayerGame.DoesNotExist` — the event appends, and nothing
projects it.

- [ ] **Step 3: Write the projector**

Create `games/projectors/playergame.py`:

```python
"""The current-state family for the games a library tracks."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.playergame import PLAYERGAME_CREATED
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import PlayerGame


class PlayerGames(Projector):
    """One row per tracked game, from the events that track it."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        #: `self.target.model`, never the imported model: a shadow rebuild
        #: points the same family at its temp table.
        projected = self.target.model(PlayerGame)
        projected.objects.update_or_create(
            id=event.aggregate_id,
            defaults={
                #: From the event, never from a command's context. That is why
                #: a replay reproduces the same ownership.
                "library_id": event.library_id,
                "game_id": uuid.UUID(event.payload["game"]["id"]),
                "tracked_at": event.recorded_at,
            },
        )

    handles: ClassVar[HandlerMap] = {PLAYERGAME_CREATED: _created}
```

- [ ] **Step 4: Register the family**

Replace the last paragraph of the `games/projectors/__init__.py` docstring and
add the import:

```python
"""The projection families the append path folds every event through.

One module per family, each defining a `Projector` subclass that registers
itself on import. `GamesConfig.ready()` imports this package, so a family is
live once its module is imported here.

The machinery each family builds on is `games.events.projection`.
"""

from games.projectors import playergame  # noqa: F401
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_projection.py -x"`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add games/projectors/playergame.py games/projectors/__init__.py tests/test_playergame_projection.py
git commit -m "Fold the creation event into a tracked row"
```

---

### Task 4: The TrackGame command

**Files:**
- Modify: `games/events/dispatch.py:55-70` (the `CommandName` enum)
- Create: `games/commands/__init__.py`
- Create: `games/commands/playergame.py`
- Create: `tests/test_playergame_command.py`

**Interfaces:**
- Consumes: `PLAYERGAME_CREATED` (Task 2), `PlayerGame` (Task 1),
  `Command` / `CommandContext` / `CommandName` / `CommandRejected` from
  `games/events/dispatch.py`, `capture_reference` from
  `games/events/references.py`.
- Produces: `CommandName.PLAYERGAME_TRACK` (value
  `"library.playergame.track"`) and
  `games.commands.playergame.TrackGame(game_id: uuid.UUID)`, dispatched as
  `dispatch(TrackGame(game_id=...), actor=..., library=..., idempotency_key=...)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playergame_command.py`:

```python
"""Tracking a game: the first command that is not a placeholder."""

import uuid

import pytest

from games.commands.playergame import TrackGame
from games.events.dispatch import CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame
from games.retention import purging_library


@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")


@pytest.fixture
def other_library(other_user):
    return other_user.library


@pytest.fixture
def shared_game(db):
    #: No library: the shared catalog.
    return Game.objects.create(name="Outer Wilds")


@pytest.mark.django_db(transaction=True)
def test_tracking_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    result = dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-outer-wilds",
    )

    assert result.replayed is False
    event = LibraryEvent.objects.get(library=owned_library)
    assert event.event_type == "library.playergame.created"
    assert event.payload["game"]["id"] == str(game.pk)

    row = PlayerGame.objects.get()
    assert (row.pk, row.game_id, row.library_id) == (
        event.aggregate_id,
        game.pk,
        owned_library.pk,
    )


@pytest.mark.django_db(transaction=True)
def test_two_libraries_track_one_shared_game_independently(
    owned_user, owned_library, other_user, other_library, shared_game
):
    for actor, library in ((owned_user, owned_library), (other_user, other_library)):
        dispatch(
            TrackGame(game_id=shared_game.pk),
            actor=actor,
            library=library,
            idempotency_key="track-shared",
        )

    assert PlayerGame.objects.filter(game=shared_game).count() == 2
    assert PlayerGame.objects.filter(library=owned_library).count() == 1
    #: One shared row, two private facts about it.
    assert Game.objects.filter(pk=shared_game.pk).count() == 1


@pytest.mark.django_db(transaction=True)
def test_another_librarys_private_game_cannot_be_tracked(
    owned_user, owned_library, other_library
):
    theirs = Game.objects.create(library=other_library, name="Their Secret")

    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=theirs.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-theirs",
        )

    assert not PlayerGame.objects.exists()
    assert not LibraryEvent.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_an_archived_game_cannot_be_tracked(owned_user, owned_library):
    from django.utils import timezone

    game = Game.objects.create(
        library=owned_library, name="Retired", archived_at=timezone.now()
    )

    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-retired",
        )


@pytest.mark.django_db(transaction=True)
def test_a_game_nobody_has_cannot_be_tracked(owned_user, owned_library):
    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=uuid.uuid7()),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-nothing",
        )


@pytest.mark.django_db(transaction=True)
def test_tracking_the_same_game_twice_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-first",
    )

    #: A different key, so this is a second intent rather than a repeat.
    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-again",
        )

    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_repeating_the_key_replays_rather_than_tracking_twice(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    command = TrackGame(game_id=game.pk)
    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="once"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="once"
    )

    assert second.replayed is True
    assert (second.first_sequence, second.last_sequence) == (
        first.first_sequence,
        first.last_sequence,
    )
    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_purging_the_library_takes_the_tracked_row_with_it(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    #: RESTRICT refuses collateral, not a purge: the library, its games and its
    #: projections are collected in one cascade.
    with purging_library():
        owned_user.delete()

    assert not PlayerGame.objects.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_command.py -x"`
Expected: FAIL with `ModuleNotFoundError: No module named 'games.commands'`.

- [ ] **Step 3: Open the command-name vocabulary, then add the command name**

`tests/test_command_dispatch.py::test_placeholders_do_not_outlive_the_first_real_command`
fires the moment a real member joins `CommandName`, on the premise that the six
`TEST_COMMAND_*` members are then undeleted scaffolding. They are not: they back
five test doubles for behaviour `TrackGame` cannot exercise. The vocabulary opens
instead, exactly as the spec's "What this changes elsewhere" section describes.

In `games/events/dispatch.py`, above `class CommandName`:

```python
class CommandVocabulary(StrEnum):
    """A closed set of command names, of which there is more than one.

    Members are stable domain symbols rather than Python paths, so moving or
    renaming a class cannot invalidate idempotency keys already issued under it.
    Requiring a member of *some* vocabulary still refuses a bare string typo,
    while leaving the production allowlist free of names only a test uses.
    """
```

Then reduce `CommandName` to real commands only, and give it the new base:

```python
class CommandName(CommandVocabulary):
    """Every command the application can run.

    The readable inventory: one grep, and no entry that is not a thing the
    system does. A test double names itself from its own vocabulary.
    """

    PLAYERGAME_TRACK = "library.playergame.track"
```

Key the registry on the name rather than the member, so two vocabularies cannot
both claim one string:

```python
_COMMAND_REGISTRY: dict[CommandNameValue, DefinitionSite] = {}
```

with the alias beside `DefinitionSite`:

```python
#: A command's stable domain symbol.
type CommandNameValue = str  # "library.playergame.track"
```

and widen the check in `Command.__init_subclass__`:

```python
        name = getattr(cls, "command_name", None)
        if not isinstance(name, CommandVocabulary):
            raise TypeError(
                f"{cls.__qualname__} declares no command_name. Every concrete "
                "command names itself with a member of a CommandVocabulary."
            )

        definition_site = (cls.__module__, cls.__qualname__)
        registered = _COMMAND_REGISTRY.get(name.value)
        #: dataclass(slots=True) cannot add slots in place, so it rebuilds the
        #: class and fires this a second time. One definition site registering
        #: twice is that rebuild; a second site is a real collision.
        if registered is not None and registered != definition_site:
            raise TypeError(
                f"{cls.__qualname__} claims {name.value!r}, already owned by "
                f"{registered[0]}.{registered[1]}."
            )
        _COMMAND_REGISTRY[name.value] = definition_site
```

with `command_name: ClassVar[CommandVocabulary]` on `Command`.

In `tests/test_command_dispatch.py`, declare the doubles' own vocabulary and
repoint the six classes at it:

```python
class DispatchProbeName(CommandVocabulary):
    """Names for the doubles that exercise dispatch itself.

    Not in `CommandName`, because nothing here is a thing the application does.
    """

    BASIC = "test.command.basic"
    TWIN = "test.command.twin"
    TEMPORAL = "test.command.temporal"
    UNSHAPED = "test.command.unshaped"
    REJECTING = "test.command.rejecting"
    FLAKY = "test.command.flaky"
```

Replace the tripwire with the assertion it was reaching for:

```python
def test_the_allowlist_holds_real_commands_only():
    #: The inventory is only readable if everything in it is a thing the
    #: system does. Doubles name themselves from DispatchProbeName.
    assert not [name for name in CommandName if name.name.startswith("TEST_")]


def test_two_vocabularies_cannot_claim_one_name():
    class Borrowed(CommandVocabulary):
        TRACK = CommandName.PLAYERGAME_TRACK.value

    with pytest.raises(TypeError, match="already owned by"):

        @dataclass(frozen=True, slots=True)
        class Impostor(Command):
            command_name: ClassVar[CommandVocabulary] = Borrowed.TRACK

            def build(self, context: CommandContext) -> Sequence[NewEvent]:
                return []
```

- [ ] **Step 4: Write the command package**

Create `games/commands/__init__.py`:

```python
"""The commands a library issues, one module per aggregate.

A command is a frozen dataclass whose fields are its canonical input; nothing
here appends. `games.events.dispatch` is the only entry point that runs one.
"""
```

Create `games/commands/playergame.py`:

```python
"""Commands about the catalog games a library tracks."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from django.db.models import Q

from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.playergame import PLAYERGAME_CREATED
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent
from games.models import Game, PlayerGame


@dataclass(frozen=True, slots=True)
class TrackGame(Command):
    """Begin tracking one catalog game in this library."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_TRACK
    #: A UUID rather than a Game: a model instance has no canonical form to
    #: fingerprint, so the row is re-read here, scoped to the library.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        game = self._visible_game(context)
        #: Both reads happen under the stream-head lock dispatch already took,
        #: so no concurrent TrackGame can land between them and the append.
        if PlayerGame.objects.filter(library=context.library, game=game).exists():
            raise CommandRejected(
                f"This library already tracks {game.name}. Whether a repeat "
                "should instead succeed as a no-op is EV-23 (#906)."
            )
        return [
            PLAYERGAME_CREATED.new(
                aggregate_id=uuid.uuid7(),
                payload={"game": capture_reference(game)},
            )
        ]

    def _visible_game(self, context: CommandContext) -> Game:
        """This library's own game, or one from the shared catalog."""
        try:
            return Game.objects.filter(
                Q(library=context.library) | Q(library__isnull=True),
                archived_at__isnull=True,
            ).get(pk=self.game_id)
        except Game.DoesNotExist:
            #: Says nothing about whose it is. A refusal is not a place to
            #: learn what another library holds.
            raise CommandRejected(
                f"No game {self.game_id} this library can track. A library "
                "tracks its own games and the shared catalog, and neither "
                "offers an archived row."
            ) from None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_command.py -x"`
Expected: PASS, 8 tests.

- [ ] **Step 6: Run the dispatch suite for collisions**

Run: `make test ARGS="tests/test_command_dispatch.py"`
Expected: PASS. A `TypeError` about a claimed command name here would mean the
new member duplicates a definition site; it does not, but the registry is the
thing that would say so.

- [ ] **Step 7: Commit**

```bash
git add games/events/dispatch.py games/commands tests/test_playergame_command.py
git commit -m "Let a library say it tracks a game"
```

---

### Task 5: Retirement and rebuild parity

**Files:**
- Modify: `games/retention.py:137-138` (inside `_delete_everything_but`)
- Modify: `tests/test_retention.py`
- Modify: `tests/test_playergame_projection.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: no new names. `archive_or_delete()` keeps its signature and gains
  the rule that a `RESTRICT`ed row is left alone rather than raising.

- [ ] **Step 1: Write the failing archive test**

In `tests/test_retention.py`, in the "a referenced row is retained" section
after `test_a_referenced_game_is_archived`:

```python
@pytest.mark.django_db(transaction=True)
def test_a_tracked_game_archives_and_keeps_its_projection_row(
    owned_user, owned_library
):
    """A projection row is not collateral: a replay owns it."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    assert archive_or_delete(game) is Retirement.ARCHIVED

    assert Game.objects.get(pk=game.pk).archived_at is not None
    assert PlayerGame.objects.filter(game=game).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_tracked_game_refuses_a_hard_delete(owned_user, owned_library):
    """#653's rule, checked over the first payload that exercises it.

    Two refusals now guard the same row, and the foreign key gets there first:
    `Model.delete()` collects before it sends `pre_delete`, so RESTRICT raises
    while `refuse_to_delete_a_referenced_row` is still unreached. Pinned as it
    behaves rather than as it reads best, so that changing the order is a
    visible decision.
    """
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    with pytest.raises(RestrictedError):
        game.delete()

    assert Game.objects.filter(pk=game.pk).exists()
```

`RestrictedError` comes from `django.db.models.deletion`. The pre-existing
`ReferencedRowDeletion` tests in this file cover games no projection tracks, and
keep passing unchanged.

Extend that file's imports with `from django.db.models.deletion import
RestrictedError`, `from games.commands.playergame import TrackGame`, `from
games.events.dispatch import dispatch`, and `PlayerGame` in the `games.models`
import block.

- [ ] **Step 2: Run both to see which one fails**

Run: `make test ARGS="tests/test_retention.py -k tracked_game"`
Expected: exactly one failure. `test_a_tracked_game_refuses_a_hard_delete`
already passes — the foreign key is doing its job before any change here.
`test_a_tracked_game_archives_and_keeps_its_projection_row` FAILs with
`RestrictedError: Cannot delete some instances of model 'Game' because they are
referenced through restricted foreign keys: 'PlayerGame.game'.` — the same
mechanism firing where it should not. No `-x`: the point of this step is seeing
both outcomes.

- [ ] **Step 3: Stop the retirement cascade collecting projections**

In `games/retention.py`, in `_delete_everything_but`, change:

```python
    collector = Collector(using=router.db_for_write(model, instance=instance))
    collector.collect([instance])
```

to:

```python
    collector = Collector(using=router.db_for_write(model, instance=instance))
    #: A RESTRICT row is not collateral of a retirement. Failing here would
    #: refuse to archive a game a library tracks; deleting it would be worse,
    #: because a replay writes it back and the live table would then disagree
    #: with the rebuilt one for good.
    collector.collect([instance], fail_on_restricted=False)
```

- [ ] **Step 4: Run the retention suite**

Run: `make test ARGS="tests/test_retention.py"`
Expected: PASS, including the pre-existing archive and delete tests.

- [ ] **Step 5: Write the failing parity test**

Append to `tests/test_playergame_projection.py` (extending its imports with
`from games.commands.playergame import TrackGame`, `from games.events.dispatch
import dispatch`, and `from games.events.rebuild import RebuildMode,
rebuild_projections`):

```python
@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_the_tracked_rows(
    owned_user, owned_library, tracked_game
):
    """Replay parity, stated as a test: the rebuild changes nothing."""
    dispatch(
        TrackGame(game_id=tracked_game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    before = PlayerGame.objects.get()

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [(0, 0, 0)]

    rebuilt = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert rebuilt.swapped is True
    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.library_id, after.tracked_at) == (
        before.pk,
        before.game_id,
        before.library_id,
        before.tracked_at,
    )
```

- [ ] **Step 6: Run it**

Run: `make test ARGS="tests/test_playergame_projection.py -x -k rebuild"`
Expected: PASS. This is the first rebuild over a real table, so a failure here
is information, not noise — read the `TableDiff` in the report before changing
anything.

- [ ] **Step 7: Commit**

```bash
git add games/retention.py tests/test_retention.py tests/test_playergame_projection.py
git commit -m "Keep a projection row out of a catalog retirement"
```

---

### Task 6: The verification gate

**Files:** none created; fixes land wherever the gate points.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: a green `make check` and a clean identity audit.

- [ ] **Step 1: Run the migration drift guard and the audit**

Run: `make check-migrations`
Expected: "No changes detected".

Run: `make audit-uuid-identity`
Expected: exit 0, with `games_playergame` carrying the ordering note
`skipped: the model has no creation timestamp to order by`. That is a Note, not
a violation: `identity_audit.DEFAULT_ORDER_SOURCE` is `"created_at"`, this model
names its timestamp `tracked_at`, and nothing maps the table in
`IDENTITY_ORDER_SOURCE`.

**Leave it skipped, deliberately.** Mapping `"games_playergame": "tracked_at"`
would restore the check, and the invariant it asserts does not reliably hold
here: the aggregate id is minted inside `build()` while `recorded_at` is stamped
at append, so two dispatches racing across libraries can order the two columns
differently and red the audit for no defect. `games_libraryevent` accepts that
same race against `recorded_at`; this table has no backfilled identities to
protect, so it buys nothing for the flakiness.

- [ ] **Step 2: Run the fast aggregate**

Run: `make check-fast`
Expected: PASS. The three suites a new model reaches —
`tests/test_projection_rebuild.py`, `tests/test_uuid_identity_audit.py`, and
`tests/test_retention.py` — were all updated in Tasks 1 and 5. A failure here is
a fourth one nobody predicted; read what it names rather than assuming.

- [ ] **Step 3: Run the full gate**

Run: `make check`
Expected: PASS, including `e2e/`. Nothing in this issue renders, but a new model
and a new startup import can break pages that mention neither, which is why the
subset run in Step 2 is not the gate.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "Settle the suite around the first projection"
```

- [ ] **Step 5: Report, do not push**

Report the gate's result. Pushing the branch and opening the pull request are
the user's call, not this plan's.

---

## Notes for the reviewer

- **Nothing calls `TrackGame` outside tests.** That is the boundary, not an
  omission: #677 switches the write path.
- **`update_or_create` keyed on `aggregate_id`** is what makes a re-fold a no-op.
  A plain `create` would pass every test in Task 3 except
  `test_folding_the_stream_again_writes_no_second_row`.
- **The duplicate-track refusal is a decision with an open issue behind it**
  (#906). If that issue lands first and chooses "succeed as a no-op", the change
  here is one branch in `TrackGame.build`.
- **`fail_on_restricted=False` widens one function's tolerance.** Today the only
  `RESTRICT` relations in the app are `LibraryEvent.stream` and
  `PlayerGame.game`, neither of which a catalog retirement should ever delete.
- **A tracked game's hard delete now fails with the wrong message.** Both
  refusals are correct, but `RESTRICT` fires during `collect()` and the
  tombstone's `pre_delete` never runs, so the operator sees a foreign-key error
  instead of "retire it with `archive_or_delete`". Nothing in this issue calls
  `Game.delete()` on a tracked game outside that test. Reordering the guard is a
  follow-up worth filing, not a change to make here.
- **`fail_on_restricted=False` still puts `PlayerGame` in `collector.data`.**
  Django's `RESTRICT` handler calls `add_dependency`, which seeds an empty bucket
  for the restricted model. Empty means `delete_batch` runs no query and no
  `pre_delete`/`post_delete` fires, so no row is touched — but a reader of
  `collector.data` should not be surprised to find the key there.
- **The E001–E006 regression guard lives in `tests/test_playergame_projection.py`,**
  not in `tests/test_projection_model.py` as the spec suggests. That file builds
  throwaway models under `@isolate_apps`; a real model's check belongs beside the
  real model's other tests.
