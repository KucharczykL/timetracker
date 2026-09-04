# Playthrough aggregate and its mandatory default — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `Playthrough` as the second projection table, with a creation
event, a projector in the `CURRENT_STATE` family, a standalone command, the
`TrackGame` edit that states a default playthrough for every newly tracked game,
and the read-time display-number rule.

**Architecture:** Relax `ProjectorRegistry` so a family holds many projectors
keyed on definition site, with the ownership guard moved to the
`(family, event type)` pair. Then add the model and its migration, the
`library.playthrough.created` event, the `Playthroughs` projector, the
`CreatePlaythrough` command, the two-event `TrackGame`, and
`games/reads/playthrough_numbering.py`. Every value the projector writes comes
off the event, so a replay reproduces the row.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pydantic TypedDict
payloads, pytest + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-04-issue-679-playthrough-aggregate-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a raw
  `uv run` / `pnpm` / `pytest`. Focused runs are
  `make test ARGS="tests/test_x.py -k name -x"`.
- **Iterate with `make check-fast`; the gate is the full `make check`,**
  including `e2e/`. Never verify with a hand-picked subset before declaring
  done.
- **Python 3.14 is required.** A `SyntaxError` in an `except A, B:` clause means
  the wrong interpreter, not broken code.
- **Nothing destroys a record.** Never `instance.delete()`.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest, so
  a test that dispatches needs `@pytest.mark.django_db(transaction=True)`.
- **Never write to a `GeneratedField`.**
- **Refused words**, enforced by `make vale` over docs *and code comments*: a
  projector *replays*; the row it leaves is the *projection*. Do not write
  fold, tombstone, archive, delete, or heal in prose or comments. `delete` is
  Django's word, not the library's.
- **Complete words in identifiers.** `template` not `tpl`, `event` not `e`.
- **A rejection carries two sentences:** `raise CommandRejected(message,
  sentence=…)`. The first explains the refusal in a log; `sentence` is the only
  thing a person sees.
- **One act, one verb.** For this aggregate the verb is `create`:
  `CommandName.PLAYTHROUGH_CREATE` / `library.playthrough.create`, the event
  `library.playthrough.created`, the column `created_at`.
- **Commit after every task.** Small commits, imperative subject.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `games/events/projection.py` | Registry holds many projectors per family; guard on `(family, event type)` | 1 |
| `games/projectors/__init__.py` | Docstring correction; imports the new module | 1, 4 |
| `tests/test_event_projectors.py` | Registry behaviour, including two classes in one family | 1 |
| `games/models.py` | `PlaythroughKind`, `Playthrough`, `ProjectionModel` docstring | 2, 8 |
| `games/migrations/0043_playthrough.py` | The table | 2 |
| `tests/test_projection_rebuild.py` | Pinned `projection_models()` and relation columns | 2 |
| `tests/test_projection_model.py` | Pinned projection defaults | 2 |
| `tests/test_uuid_identity_audit.py` | Pinned relation columns and identity tables | 2 |
| `tests/test_playthrough_projection.py` | Model shape, projector, replay, rebuild | 2, 4, 9 |
| `games/events/playthrough.py` | The event spec, its payload, the shared builder | 3 |
| `tests/test_playthrough_events.py` | Payload strictness, `Literal`/choices parity | 3 |
| `games/projectors/playthrough.py` | The `Playthroughs` projector | 4 |
| `games/commands/playthrough.py` | `CreatePlaythrough` | 5 |
| `games/events/dispatch.py` | `CommandName.PLAYTHROUGH_CREATE` | 5 |
| `games/commands/playergame.py` | `tracked_game` public; `TrackGame` returns two events | 5, 6 |
| `tests/test_playthrough_command.py` | Command refusals, two-event `TrackGame` | 5, 6 |
| `games/reads/playthrough_numbering.py` | `with_display_number`, `display_name` | 7 |
| `tests/test_playthrough_numbering.py` | Order, exclusions, rebuild stability | 7, 9 |
| `games/management/commands/audit_library_ownership.py` | Cross-library pair | 8 |
| `tests/test_library_commands.py` | The audit reports a cross-library row | 8 |
| `tests/test_retention.py` | The purge still empties a library | 10 |
| `CLAUDE.md`, `docs/vocabulary.md`, `docs/event-benchmarks.md` | Documentation | 11 |

---

## Task 1: A family holds many projectors

**Files:**
- Modify: `games/events/projection.py:55-165` (docstrings, `__init__`,
  `register`, `for_target`, `_rebuild_handlers`)
- Modify: `games/projectors/__init__.py:1`
- Test: `tests/test_event_projectors.py:203-240`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProjectorRegistry` accepts two `Projector` subclasses declaring the
  same `family_name`, provided no event type is claimed twice inside that
  family. `register(projector_class, *, target=LIVE_TARGET) -> None` and
  `for_target(target) -> ProjectorRegistry` keep their signatures.

- [ ] **Step 1: Rename the collision test and add the one that must now pass**

In `tests/test_event_projectors.py`, rename
`test_two_families_cannot_claim_one_member` to
`test_two_classes_cannot_claim_one_event_type_in_one_family` — its body is
unchanged, because both classes already claim `PROBE_RECORDED` inside `STATS`
from two definition sites.

Add these two tests after it. `PROBE_RECORDED`/`RECORDED` already exist in the
module; `OTHER` is the second event type it already imports.

```python
#: A local sink, because the module's CALLS is typed
#: list[tuple[ProjectorFamily, str]] and these tests record which class ran.
type ClassCall = tuple[str, str]


def test_two_classes_share_one_family_when_they_claim_different_event_types():
    """The thing that was impossible before #679."""
    seen: list[ClassCall] = []
    registry = ProjectorRegistry()

    class First(Projector, registry=registry):
        family_name = ProjectorFamily.CURRENT_STATE

        def _recorded(self, event: RecordedEvent) -> None:
            seen.append(("first", event.event_type))

        handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}

    class Second(Projector, registry=registry):
        family_name = ProjectorFamily.CURRENT_STATE

        def _other(self, event: RecordedEvent) -> None:
            seen.append(("second", event.event_type))

        handles: ClassVar[HandlerMap] = {PROBE_OTHER: _other}

    registry.apply(make_event())
    registry.apply(make_event(event_type=OTHER))

    assert seen == [("first", RECORDED), ("second", OTHER)]


def test_a_refused_claim_leaves_the_family_as_it_was():
    """Every claim is checked before any is taken."""
    seen: list[ClassCall] = []
    registry = ProjectorRegistry()

    class Incumbent(Projector, registry=registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: RecordedEvent) -> None:
            seen.append(("incumbent", event.event_type))

        handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}

    with pytest.raises(TypeError, match="already owned by"):

        class Greedy(Projector, registry=registry):
            family_name = ProjectorFamily.STATS

            def _other(self, event: RecordedEvent) -> None: ...

            def _recorded(self, event: RecordedEvent) -> None: ...

            handles: ClassVar[HandlerMap] = {
                PROBE_OTHER: _other,
                PROBE_RECORDED: _recorded,
            }

    #: The uncontested claim did not survive the refusal.
    assert registry.handlers_for(OTHER) == ()
    registry.apply(make_event())
    assert seen == [("incumbent", RECORDED)]
```

Everything else these tests name already exists in the file: `RECORDED` and
`OTHER` at lines 41-42, `PROBE_RECORDED` and `PROBE_OTHER` at 108-109, and
`make_event(**overrides)` at 74, whose defaults include `event_type=RECORDED`.

Note the `handles` dict in `Greedy`: Python evaluates it top to bottom, so the
uncontested `PROBE_OTHER` claim comes first and is the one a
mutate-as-you-go loop would have left behind.

- [ ] **Step 2: Run the tests and watch them fail**

```
make test ARGS="tests/test_event_projectors.py -x -p no:randomly"
```

Expected: `test_two_classes_share_one_family_when_they_claim_different_event_types`
fails with `TypeError: Second claims 'current_state', already owned by …`.

- [ ] **Step 3: Rewrite the registry's three mappings**

In `games/events/projection.py`, replace `ProjectorRegistry.__init__`:

```python
class ProjectorRegistry:
    def __init__(self) -> None:
        #: Many projectors per family, keyed on where each was defined, so
        #: re-registering one site replaces it rather than adding a copy.
        self._families: dict[ProjectorFamily, dict[DefinitionSite, Projector]] = {}
        #: Kept so `for_target` rebuilds from the classes.
        self._classes: dict[ProjectorFamily, dict[DefinitionSite, type[Projector]]] = {}
        #: One owner per act, not per family: two projectors share a family
        #: only while they claim different event types.
        self._claims: dict[tuple[ProjectorFamily, EventType], DefinitionSite] = {}
        #: The string a RecordedEvent carries.
        self._handlers: dict[EventType, tuple[FamilyHandler, ...]] = {}
```

- [ ] **Step 4: Move the ownership guard onto the pair**

Replace the guard block in `register` (currently
`games/events/projection.py:129-141`) with the tail of this `register`. Its
signature and its four preceding validation blocks are unchanged — only what
follows them, from `definition_site` to `_rebuild_handlers`, is new:

```python
class ProjectorRegistry:
    def register(
        self,
        projector_class: type[Projector],
        *,
        target: ProjectionTarget = LIVE_TARGET,
    ) -> None:
        ...  # family_name, handles, and their validation, unchanged

        definition_site = (projector_class.__module__, projector_class.__qualname__)
        #: Every claim is checked before any is taken, so a refusal leaves
        #: nothing half-registered behind it.
        for spec in handles:
            claimed_by = self._claims.get((family_name, spec.event_type))
            if claimed_by is not None and claimed_by != definition_site:
                raise TypeError(
                    f"{projector_class.__qualname__} claims "
                    f"{spec.event_type!r} in {family_name.value!r}, "
                    f"already owned by {claimed_by[0]}.{claimed_by[1]}."
                )
        for spec in handles:
            self._claims[(family_name, spec.event_type)] = definition_site

        #: A family takes its target, nothing else.
        self._families.setdefault(family_name, {})[definition_site] = projector_class(
            target
        )
        self._classes.setdefault(family_name, {})[definition_site] = projector_class
        self._rebuild_handlers()
```

- [ ] **Step 5: Follow the nesting into `for_target` and `_rebuild_handlers`**

```python
class ProjectorRegistry:
    def for_target(self, target: ProjectionTarget) -> ProjectorRegistry:
        """The same families, writing where `target` points."""
        sibling = ProjectorRegistry()
        sibling._classes = {
            family_name: dict(sites) for family_name, sites in self._classes.items()
        }
        sibling._claims = dict(self._claims)
        sibling._families = {
            family_name: {
                site: projector_class(target) for site, projector_class in sites.items()
            }
            for family_name, sites in self._classes.items()
        }
        sibling._rebuild_handlers()
        return sibling

    def _rebuild_handlers(self) -> None:
        handlers: dict[EventType, list[FamilyHandler]] = {}
        for family_name in sorted(self._families, key=_RUN_ORDER.__getitem__):
            for family in self._families[family_name].values():
                for spec, handler in family.handles.items():
                    handlers.setdefault(spec.event_type, []).append(
                        (family_name, handler.__get__(family))
                    )
        self._handlers = {
            event_type: tuple(found) for event_type, found in handlers.items()
        }
```

- [ ] **Step 6: Correct the two docstrings the change falsifies**

`ProjectorFamily`'s docstring currently ends its second paragraph with "and must
not depend on which module Python imported first". Replace that paragraph:

```
    **Member order is run order.** Journal and statistics families read the
    current-state rows written earlier in the same transaction, so the order
    between families is load-bearing and is this enum, never an import order.
    Within one family the order is registration order, which is an import
    order -- and does not matter, because one event type has one owner inside
    a family, so no two same-family handlers ever see one event.
```

`games/projectors/__init__.py:1` currently reads
`"""One module per family; importing registers it."""`. Replace with:

```python
"""One module per projection concern; importing registers it.

A family may hold more than one, so this is not one module per family:
`CURRENT_STATE` holds both PlayerGames and Playthroughs.
"""
```

- [ ] **Step 7: Run the tests and the type checker**

```
make test ARGS="tests/test_event_projectors.py tests/test_projection_targets.py tests/test_projection_rebuild.py tests/test_event_wiring.py -p no:randomly"
make typecheck
make vale
```

Expected: all pass. `make vale` reports only the seven pre-existing warnings
(four `folds`, three `archive`) and no errors.

- [ ] **Step 8: Commit**

```bash
git add games/events/projection.py games/projectors/__init__.py tests/test_event_projectors.py
git commit -m "Let one projection family hold more than one projector

The ownership guard moves from the family to the (family, event type)
pair, so PlayerGames and Playthroughs can both be current-state. Every
claim is checked before any is taken, so a refused registration leaves
nothing behind.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: The Playthrough table

**Files:**
- Modify: `games/models.py` (after `PlayerGame`, which ends around line 1592)
- Create: `games/migrations/0043_playthrough.py` (generated)
- Modify: `tests/test_projection_rebuild.py:134-136`
- Modify: `tests/test_projection_model.py:243-250`
- Modify: `tests/test_uuid_identity_audit.py:32-…` and `:238-…`
- Create: `tests/test_playthrough_projection.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `games.models.PlaythroughKind` (`TextChoices`, members `ORDINARY =
  "ordinary"` and `IMPORTED_HISTORY = "imported_history"`) and
  `games.models.Playthrough`, a `ProjectionModel` with fields `id`,
  `library`, `player_game`, `kind`, `name`, `note`, `started`,
  `started_lower`, `started_upper`, `completed`, `completed_lower`,
  `completed_upper`, `created_at`, `removed_at`. The reverse accessor on
  `PlayerGame` is `playthroughs`.

- [ ] **Step 1: Write the failing model tests**

Create `tests/test_playthrough_projection.py`:

```python
"""One row per run at a game a library tracks."""

import pytest

from games.checks import check_projection_models
from games.models import Playthrough, PlaythroughKind

pytestmark = pytest.mark.untracked_games


def test_playthrough_is_a_pure_projection():
    """Nothing in the row predates the event."""
    complaints = [
        str(message.id)
        for message in check_projection_models()
        if message.obj is Playthrough
    ]

    assert complaints == []


def test_the_identity_has_no_default():
    #: The key is the event's aggregate_id.
    assert Playthrough().id is None


def test_a_playthrough_starts_ordinary():
    assert Playthrough().kind == PlaythroughKind.ORDINARY


def test_a_playthrough_starts_unnamed():
    """A blank name is what the display number is for."""
    assert Playthrough().name == ""
    assert Playthrough().note == ""


def test_a_playthrough_starts_with_no_endpoints():
    """#681 states them."""
    assert Playthrough().started is None
    assert Playthrough().completed is None


def test_a_playthrough_starts_live():
    assert Playthrough().removed_at is None


def test_the_bound_columns_are_generated():
    """Never written from application code."""
    generated = {
        field.name for field in Playthrough._meta.concrete_fields if field.generated
    }

    assert generated == {
        "started_lower",
        "started_upper",
        "completed_lower",
        "completed_upper",
    }


def test_the_display_order_index_covers_every_sort_key():
    """The read-time numbering has an index behind it."""
    covering = [
        index
        for index in Playthrough._meta.indexes
        if index.fields
        == [
            "player_game",
            "started_lower",
            "completed_lower",
            "created_at",
            "id",
        ]
    ]

    assert len(covering) == 1
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_projection.py -x -p no:randomly"
```

Expected: `ImportError: cannot import name 'Playthrough' from 'games.models'`.

- [ ] **Step 3: Add the enum and the model**

In `games/models.py`, directly after the `PlayerGame` class (its `__str__`
returns `f"{self.game} tracked by library {self.library_id}"`), add:

```python
class PlaythroughKind(models.TextChoices):
    """Whether a run is a person's or the importer's.

    Full words, not letters: a recorded payload cannot be upcast, so an
    event recording `i` would mean imported history forever.
    """

    ORDINARY = "ordinary", "Ordinary"
    IMPORTED_HISTORY = "imported_history", "Imported history"


class Playthrough(ProjectionModel):
    """One run at a game a library tracks, projected from its events."""

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The creation event's aggregate_id, evaluated once.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    player_game = models.ForeignKey(
        PlayerGame,
        #: No cascade may remove a projection row.
        on_delete=models.RESTRICT,
        related_name="playthroughs",
    )
    #: Stated by the creation event, and never restated.
    kind = models.CharField(
        max_length=16,
        choices=PlaythroughKind,
        default=PlaythroughKind.ORDINARY,
    )
    #: #1010 states it. Blank displays as "Playthrough N".
    name = models.CharField(max_length=255, blank=True, default="")
    #: #1010 states it.
    note = models.TextField(blank=True, default="")
    #: #681 states both endpoints.
    started = TemporalValueField()
    started_lower = models.GeneratedField(
        expression=TemporalLowerBound("started"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    started_upper = models.GeneratedField(
        expression=TemporalUpperBound("started"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    completed = TemporalValueField()
    completed_lower = models.GeneratedField(
        expression=TemporalLowerBound("completed"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    completed_upper = models.GeneratedField(
        expression=TemporalUpperBound("completed"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null means live. #1011 states it.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    class Meta:
        indexes = (
            #: The display-number order, ending on the key so it is total.
            models.Index(
                fields=(
                    "player_game",
                    "started_lower",
                    "completed_lower",
                    "created_at",
                    "id",
                ),
                name="playthrough_display_order",
            ),
        )

    def __str__(self) -> str:
        return f"Playthrough {self.pk} of tracked game {self.player_game_id}"
```

`TemporalValueField`, `TemporalLowerBound` and `TemporalUpperBound` are already
imported at the top of `games/models.py` for `Game` and `Release`. If any is
missing, add it to the existing `from timetracker.temporal import …`.

- [ ] **Step 4: Generate the migration and read it**

```
make makemigrations ARGS="games --name playthrough"
```

Expected: `games/migrations/0043_playthrough.py`, depending on
`0042_external_reference_choices`. Read it and confirm it creates one table and
alters nothing else. If Django numbered it differently, the head of
`games/migrations/` moved — take the number it gives.

- [ ] **Step 5: Run the model tests**

```
make test ARGS="tests/test_playthrough_projection.py -p no:randomly"
```

Expected: PASS.

- [ ] **Step 6: Update the four pinned inventories, one at a time**

Run each pinned test, read what it reports, and make the literal match.

`tests/test_projection_rebuild.py:134-136` — `projection_models()` is sorted by
`db_table`, and `games_playergame` sorts before `games_playthrough`:

```python
def test_the_application_declares_its_projections():
    """Two projection tables so far."""
    assert projection_models() == (PlayerGame, Playthrough)
```

Import `Playthrough` beside `PlayerGame` at the top of that file.

`tests/test_projection_model.py:243-250` — add the second entry to
`PINNED_DEFAULTS`. `started` and `completed` appear because
`TemporalValueField.__init__` does `kwargs.setdefault("default", None)`:

```python
    "games.Playthrough": {
        "kind": "ordinary",
        "name": "",
        "note": "",
        "started": None,
        "completed": None,
        "removed_at": None,
    },
```

`tests/test_uuid_identity_audit.py:32` `EXPECTED_RELATION_COLUMNS` — add these
two members, in the collection's existing alphabetical position:

```text
("games_playthrough", "library_id"),
("games_playthrough", "player_game_id"),
```

`tests/test_uuid_identity_audit.py:238` `EXPECTED_IDENTITY_TABLES` — add
`"games_playthrough"` in alphabetical position.

The same `EXPECTED_RELATION_COLUMNS` set is re-asserted from
`tests/test_projection_rebuild.py:1274`, which imports it — no second edit.

- [ ] **Step 7: Run every pinned suite and the identity audit**

```
make test ARGS="tests/test_projection_rebuild.py tests/test_projection_model.py tests/test_uuid_identity_audit.py tests/test_projection_targets.py -p no:randomly"
make audit-uuid-identity
```

Expected: all pass, and the audit reports no violation.

- [ ] **Step 8: Commit**

```bash
git add games/models.py games/migrations/0043_playthrough.py tests/
git commit -m "Add the Playthrough projection table

Two endpoints as TemporalValueField with generated lower and upper
bound columns beside each, and an index over the display-number order
ending on the key so the order is total.

Four pinned test inventories name the new table: projection_models,
the projection defaults, and both halves of the UUID identity audit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: The creation event

**Files:**
- Create: `games/events/playthrough.py`
- Create: `tests/test_playthrough_events.py`

**Interfaces:**
- Consumes: `games.models.PlaythroughKind` (Task 2).
- Produces:
  - `PlaythroughKindValue` — `Literal["ordinary", "imported_history"]`
  - `PlaythroughCreatedPayload` — TypedDict with `player_game: ReferenceId` and
    `kind: PlaythroughKindValue`
  - `PLAYTHROUGH_CREATED` — `EventSpec`, event type
    `"library.playthrough.created"`, aggregate type `"playthrough"`
  - `playthrough_created(player_game_id: uuid.UUID, *, kind:
    PlaythroughKindValue = "ordinary") -> NewEvent` — mints a fresh
    `aggregate_id`

- [ ] **Step 1: Write the failing event tests**

Create `tests/test_playthrough_events.py`:

```python
"""What a library records about a run at a game."""

import uuid

import pytest
from pydantic import ValidationError

from games.events.playthrough import (
    PLAYTHROUGH_CREATED,
    PlaythroughKindValue,
    playthrough_created,
)
from games.events.vocabulary import DEFAULT_EVENT_TYPES
from games.models import PlaythroughKind


def test_the_creation_event_is_in_the_default_vocabulary():
    assert "library.playthrough.created" in DEFAULT_EVENT_TYPES


def test_the_kind_literal_matches_the_choices():
    """A payload is read back as a plain string."""
    from typing import get_args

    assert set(get_args(PlaythroughKindValue.__value__)) == set(PlaythroughKind.values)


def test_the_payload_refuses_an_unknown_key():
    with pytest.raises(ValidationError):
        PLAYTHROUGH_CREATED.validate(
            {
                "player_game": str(uuid.uuid7()),
                "kind": "ordinary",
                "note": "",
            }
        )


def test_the_payload_refuses_a_kind_nobody_defined():
    with pytest.raises(ValidationError):
        PLAYTHROUGH_CREATED.validate(
            {"player_game": str(uuid.uuid7()), "kind": "speedrun"}
        )


def test_the_payload_refuses_a_reference_that_is_not_canonical_uuidv7():
    with pytest.raises(ValidationError):
        PLAYTHROUGH_CREATED.validate(
            {"player_game": str(uuid.uuid4()), "kind": "ordinary"}
        )


def test_the_builder_mints_a_fresh_identity_each_call():
    tracked_id = uuid.uuid7()

    first = playthrough_created(tracked_id)
    second = playthrough_created(tracked_id)

    assert first.aggregate_id != second.aggregate_id
    assert first.payload == {"player_game": str(tracked_id), "kind": "ordinary"}
```

`EventSpec`'s validation entry point may not be spelled `validate`. Read
`games/events/vocabulary.py` and use whatever `EventSpec` exposes — the
`TypeAdapter` call the append path uses. `tests/test_event_vocabulary.py` shows
the idiom.

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_events.py -x -p no:randomly"
```

Expected: `ModuleNotFoundError: No module named 'games.events.playthrough'`.

- [ ] **Step 3: Write the event module**

Create `games/events/playthrough.py`:

```python
"""What a library records about a run at a game."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA, ReferenceId
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent

#: A Literal, not PlaythroughKind, on purpose.
#: Strict validation refuses a plain string for an enum field, and a recorded
#: payload is read back as one. A test pins these arguments to the choices.
type PlaythroughKindValue = Literal["ordinary", "imported_history"]


@with_config(STRICT_SCHEMA)
class PlaythroughCreatedPayload(TypedDict):
    """The tracked game this run belongs to, and what kind of run it is.

    `player_game` is a bare ReferenceId rather than a Reference for two
    reasons. TrackGame cannot capture one: the PlayerGame row does not
    exist while its build composes this event. And a ReferenceKind for
    PlayerGame would make replay's resolvable-references check read the
    live table before the first row, so a rebuild of a library that has
    lost rows would refuse to run -- which is the drift a rebuild is for.
    """

    player_game: ReferenceId
    kind: PlaythroughKindValue


PLAYTHROUGH_CREATED = EventSpec(
    "library.playthrough.created",
    aggregate_type="playthrough",
    payload=PlaythroughCreatedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_CREATED)


def playthrough_created(
    player_game_id: uuid.UUID,
    *,
    kind: PlaythroughKindValue = "ordinary",
) -> NewEvent:
    """The one creation event, for both commands that state one.

    It lives beside the spec rather than in games.commands.playthrough,
    because that module and games.commands.playergame would otherwise
    import each other.
    """
    return PLAYTHROUGH_CREATED.new(
        aggregate_id=uuid.uuid7(),
        payload={"player_game": str(player_game_id), "kind": kind},
    )
```

- [ ] **Step 4: Run the tests**

```
make test ARGS="tests/test_playthrough_events.py tests/test_event_vocabulary.py tests/test_event_wiring.py -p no:randomly"
make typecheck
```

Expected: PASS. If `test_event_wiring` complains that no projector claims the
spec, that is Task 4 — note it and move on only if the failure names exactly
that. Otherwise fix it here.

- [ ] **Step 5: Commit**

```bash
git add games/events/playthrough.py tests/test_playthrough_events.py
git commit -m "Record library.playthrough.created

The payload names the tracked game by bare ReferenceId, not Reference:
TrackGame has no row to capture when it composes the event, and a
ReferenceKind would make a rebuild refuse the drift it exists to repair.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: The Playthroughs projector

**Files:**
- Create: `games/projectors/playthrough.py`
- Modify: `games/projectors/__init__.py`
- Test: `tests/test_playthrough_projection.py` (append to Task 2's file)

**Interfaces:**
- Consumes: `PLAYTHROUGH_CREATED` (Task 3), `Playthrough` (Task 2), the relaxed
  registry (Task 1).
- Produces: `games.projectors.playthrough.Playthroughs`, a `Projector` with
  `family_name = ProjectorFamily.CURRENT_STATE`.

- [ ] **Step 1: Write the failing projector test**

Append to `tests/test_playthrough_projection.py`. Add these imports at the top
of the file:

```python
import uuid

from django.db import transaction
from django.utils import timezone

from games.events.append import lock_stream
from games.events.envelope import RecordedEvent
from games.events.playthrough import PLAYTHROUGH_CREATED, playthrough_created
from games.events.projection import DEFAULT_REGISTRY
from games.models import Game, LibraryEvent, PlayerGame
```

And this helper, in the shape `append_created` in
`tests/test_playergame_projection.py:114` already uses:

```python
def append_playthrough_created(library, actor, tracked, *, key="create"):
    """Append one creation event, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [playthrough_created(tracked.pk)],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )
```

And these tests:

```python
def test_the_creation_event_has_a_current_state_handler():
    handlers = DEFAULT_REGISTRY.handlers_for("library.playthrough.created")

    assert len(handlers) == 1


def test_playergames_still_owns_its_own_events():
    """Two projectors in one family, each with its own act."""
    assert len(DEFAULT_REGISTRY.handlers_for("library.playergame.created")) == 1


@pytest.fixture
def tracked(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    return PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_the_creation_event_writes_the_row(owned_user, owned_library, tracked):
    appended = append_playthrough_created(owned_library, owned_user, tracked)

    row = Playthrough.objects.get()
    assert (row.player_game_id, row.library_id) == (tracked.pk, owned_library.pk)
    assert row.pk == appended.events[0].aggregate_id
    assert row.kind == PlaythroughKind.ORDINARY
    assert row.created_at == appended.events[0].recorded_at
    #: The model defaults, which no amendment has replaced yet.
    assert (row.name, row.note, row.started, row.completed, row.removed_at) == (
        "",
        "",
        None,
        None,
        None,
    )


@pytest.mark.django_db(transaction=True)
def test_applying_the_creation_event_twice_writes_one_row(
    owned_user, owned_library, tracked
):
    """The write is keyed on aggregate_id."""
    appended = append_playthrough_created(owned_library, owned_user, tracked)
    event = RecordedEvent.from_row(
        LibraryEvent.objects.get(aggregate_id=appended.events[0].aggregate_id)
    )

    with transaction.atomic():
        DEFAULT_REGISTRY.apply(event)

    assert Playthrough.objects.count() == 1
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_projection.py -x -p no:randomly"
```

Expected: `test_the_creation_event_has_a_current_state_handler` fails,
`len(handlers) == 0`.

- [ ] **Step 3: Write the projector**

Create `games/projectors/playthrough.py`:

```python
"""The current-state family for runs at a tracked game."""

import uuid
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.playthrough import PLAYTHROUGH_CREATED
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import Playthrough


class Playthroughs(Projector):
    """One row per run at a tracked game."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        self.project(
            Playthrough,
            event.aggregate_id,
            #: From the event, never a command's context.
            library_id=event.library_id,
            player_game_id=uuid.UUID(event.payload["player_game"]),
            kind=event.payload["kind"],
            created_at=event.recorded_at,
        )

    #: Only these four. A rebuild inserts the model defaults for the rest and
    #: the amendment events that follow set the real values, so naming a
    #: column here would let a re-applied creation event overwrite one.
    #:
    #: #681's endpoint handlers use amend, never project, and are never added
    #: to this list: `started` and `completed` carry a default, so
    #: `_required_columns` exempts them and would not catch the mistake.
    handles: ClassVar[HandlerMap] = {PLAYTHROUGH_CREATED: _created}
```

- [ ] **Step 4: Register it by importing it**

`games/projectors/__init__.py`, after the `playergame` import:

```python
from games.projectors import playergame, playthrough  # noqa: F401
```

Keep whatever import style the file already uses; only add the module.

- [ ] **Step 5: Run the tests**

```
make test ARGS="tests/test_playthrough_projection.py tests/test_playergame_projection.py tests/test_event_wiring.py tests/test_event_projectors.py -p no:randomly"
make typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add games/projectors/playthrough.py games/projectors/__init__.py tests/test_playthrough_projection.py
git commit -m "Project library.playthrough.created

The second current-state projector, which the registry change made
possible. Every value comes off the event, so a replay writes the row
it wrote before.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: The CreatePlaythrough command

**Files:**
- Modify: `games/events/dispatch.py:81-89` (`CommandName`)
- Modify: `games/commands/playergame.py:46` (`_tracked_game` → `tracked_game`,
  and its six call sites at lines 118, 145, 172, 199, 220, 252)
- Create: `games/commands/playthrough.py`
- Create: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: `playthrough_created` (Task 3), `Playthrough` (Task 2).
- Produces:
  - `CommandName.PLAYTHROUGH_CREATE = "library.playthrough.create"`
  - `games.commands.playergame.tracked_game(context: CommandContext, game_id:
    uuid.UUID) -> PlayerGame` — the same function, now public
  - `games.commands.playthrough.CreatePlaythrough(game_id: uuid.UUID)` — a
    frozen dataclass `Command`

- [ ] **Step 1: Write the failing command tests**

Create `tests/test_playthrough_command.py`:

```python
"""Dispatching the command that states a run at a game."""

import pytest

from games.commands.playergame import PlayerGameNotTracked, TrackGame
from games.commands.playthrough import CreatePlaythrough
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame, Playthrough, PlaythroughKind

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def _track(owned_user, owned_library, game, key="track"):
    return dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_records_it_and_projects_it(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)

    result = dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second-run",
    )

    assert result.outcome is CommandOutcome.APPENDED
    events = LibraryEvent.objects.filter(
        event_type="library.playthrough.created"
    ).order_by("sequence")
    assert events.count() == 2
    tracked = PlayerGame.objects.get()
    assert events.last().payload == {
        "player_game": str(tracked.pk),
        "kind": "ordinary",
    }
    assert Playthrough.objects.filter(player_game=tracked).count() == 2


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_for_an_untracked_game_is_refused(
    owned_user, owned_library, game
):
    with pytest.raises(PlayerGameNotTracked):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="untracked",
        )

    assert Playthrough.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_for_a_removed_game_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="removed",
        )

    assert "Restore it" in refusal.value.sentence
    #: Only the default, from TrackGame.
    assert Playthrough.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_repeat_under_one_key_records_nothing_further(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    for _ in range(2):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="second-run",
        )

    assert Playthrough.objects.count() == 2
```

Check `CommandRejected`'s attribute name for the person-facing sentence — read
`games/events/dispatch.py` and use whatever it stores (`sentence`, per the
project convention). Adjust the assertion if the attribute differs.

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_command.py -x -p no:randomly"
```

Expected: `ModuleNotFoundError: No module named 'games.commands.playthrough'`.

- [ ] **Step 3: Add the command name**

In `games/events/dispatch.py`, after `PLAYERGAME_RECORD_FACTS`:

```python
    PLAYTHROUGH_CREATE = "library.playthrough.create"
```

- [ ] **Step 4: Make the resolver public**

In `games/commands/playergame.py`, rename `_tracked_game` to `tracked_game` and
give it the comment that names its successor:

```python
def tracked_game(context: CommandContext, game_id: uuid.UUID) -> PlayerGame:
    """The projection row, never the catalog.

    Public since #679, so games.commands.playthrough can call it.
    #909 replaces it with the shared library-scoped resolver.
    """
```

Update its six call sites in the same file — lines 118, 145, 172, 199, 220 and
252 in the pre-change file. Confirm none is left:

```
grep -rn "_tracked_game" games/ tests/
```

Expected: no output.

- [ ] **Step 5: Write the command**

Create `games/commands/playthrough.py`:

```python
"""Commands about the runs a library records at a game."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from games.commands.playergame import tracked_game
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.playthrough import playthrough_created
from games.events.vocabulary import NewEvent, Unchanged


@dataclass(frozen=True, slots=True)
class CreatePlaythrough(Command):
    """State one more run at a game this library tracks.

    It takes no name: #1010 owns naming, and a blank name is what the
    display number is for.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_CREATE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"This library removed game {self.game_id}, so it records no "
                "further runs at it. A removed game is restored first.",
                sentence=(
                    "That game was removed from your library. Restore it "
                    "before adding a playthrough."
                ),
            )
        return [playthrough_created(tracked.pk)]
```

The refusal for an untracked game is `PlayerGameNotTracked`, raised by
`tracked_game` with its own sentence — this command adds nothing there.

- [ ] **Step 6: Run the tests**

```
make test ARGS="tests/test_playthrough_command.py tests/test_playergame_command.py tests/test_command_dispatch.py tests/test_command_answers.py -p no:randomly"
make typecheck
```

Expected: PASS. `test_playthrough_command` will still fail its
`events.count() == 2` and `Playthrough…count() == 2` assertions, because
`TrackGame` does not yet state a default — that is Task 6. If only those two
assertions fail, note it and continue; fix anything else here.

- [ ] **Step 7: Commit**

```bash
git add games/events/dispatch.py games/commands/playergame.py games/commands/playthrough.py tests/test_playthrough_command.py
git commit -m "Add CreatePlaythrough

One verb for the act: library.playthrough.create, the event
library.playthrough.created, the column created_at.

_tracked_game becomes public so the new module can resolve a tracked
game; #909 replaces it with the shared resolver.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: TrackGame states the default

**Files:**
- Modify: `games/commands/playergame.py:82-87` (`TrackGame.build`'s return)
- Modify: `tests/test_playergame_command.py:55`
- Test: `tests/test_playthrough_command.py` (Task 5's assertions go green)

**Interfaces:**
- Consumes: `playthrough_created` (Task 3).
- Produces: `TrackGame.build` returns two `NewEvent`s —
  `library.playergame.created` then `library.playthrough.created` — under one
  minted PlayerGame identity.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_command.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_tracking_a_game_states_its_first_playthrough(owned_user, owned_library, game):
    """The library's first act on a game states both facts."""
    _track(owned_user, owned_library, game)

    events = list(LibraryEvent.objects.order_by("sequence"))
    assert [event.event_type for event in events] == [
        "library.playergame.created",
        "library.playthrough.created",
    ]
    #: One dispatch, one correlation_id.
    assert len({event.correlation_id for event in events}) == 1
    assert events[1].sequence == events[0].sequence + 1

    tracked = PlayerGame.objects.get()
    run = Playthrough.objects.get()
    assert events[1].payload == {
        "player_game": str(tracked.pk),
        "kind": "ordinary",
    }
    assert (run.player_game_id, run.kind, run.library_id) == (
        tracked.pk,
        PlaythroughKind.ORDINARY,
        owned_library.pk,
    )


@pytest.mark.django_db(transaction=True)
def test_a_repeated_track_under_one_key_states_one_playthrough(
    owned_user, owned_library, game
):
    """A repeat answers from the idempotency record."""
    _track(owned_user, owned_library, game)
    _track(owned_user, owned_library, game)

    assert Playthrough.objects.count() == 1
    assert LibraryEvent.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_tracking_an_already_tracked_game_states_no_second_default(
    owned_user, owned_library, game
):
    """#684 supplies a missing default; TrackGame does not."""
    _track(owned_user, owned_library, game, key="first")
    result = _track(owned_user, owned_library, game, key="second")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert Playthrough.objects.count() == 1
```

`CommandOutcome.UNCHANGED` may be spelled differently — read
`games/events/dispatch.py` for the member name and use it.

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_command.py -x -p no:randomly"
```

Expected: `test_tracking_a_game_states_its_first_playthrough` fails, because
only one event was recorded.

- [ ] **Step 3: Return two events**

In `games/commands/playergame.py`, replace `TrackGame.build`'s return statement:

```python
        #: The library's first act on a game states both facts, which is
        #: what a mandatory default means. dispatch resolves one
        #: correlation_id before build runs, so both events carry it.
        tracked_id = uuid.uuid7()
        return [
            PLAYERGAME_CREATED.new(
                aggregate_id=tracked_id,
                payload={"game": capture_reference(game)},
            ),
            playthrough_created(tracked_id),
        ]
```

Add the import at the top of the file:

```python
from games.events.playthrough import playthrough_created
```

`games.events.playthrough` imports nothing from `games.commands`, so this does
not cycle.

- [ ] **Step 4: Run and watch them pass**

```
make test ARGS="tests/test_playthrough_command.py -p no:randomly"
```

Expected: PASS, including Task 5's two deferred assertions.

- [ ] **Step 5: Fix the one existing test that assumed one event**

`tests/test_playergame_command.py:55` reads
`event = LibraryEvent.objects.get(library=owned_library)`, which now raises
`MultipleObjectsReturned`. Narrow it:

```python
    event = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playergame.created"
    )
```

Then find any other site that assumed one:

```
grep -rn "LibraryEvent.objects.get(library=\|LibraryEvent.objects.count() ==" tests/ e2e/
```

Fix each by naming the event type, not by loosening the count.

- [ ] **Step 6: Run every suite that dispatches TrackGame**

```
make test ARGS="tests/test_playergame_command.py tests/test_playergame_write_path.py tests/test_playergame_projection.py tests/test_playergame_backfill.py tests/test_playergame_backfill_migration.py tests/test_event_idempotency.py tests/test_event_replay.py tests/test_playergame_view_cutover.py -p no:randomly"
```

Expected: PASS. The #676 backfill is unaffected — `games/backfill/playergame.py`
composes `PLAYERGAME_CREATED` directly and never dispatches `TrackGame`, so
migration `0033` still emits one event per game and #684 owns the missing
defaults.

- [ ] **Step 7: Run the fast aggregate**

```
make check-fast
```

Expected: green. Fix anything it turns up before committing.

- [ ] **Step 8: Commit**

```bash
git add games/commands/playergame.py tests/
git commit -m "State a default playthrough when a library tracks a game

TrackGame mints the PlayerGame identity and returns two events under it.
dispatch resolves one correlation_id before build runs, so both carry it,
and the existing idempotency key covers the whole range.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: The display number

**Files:**
- Create: `games/reads/playthrough_numbering.py`
- Create: `tests/test_playthrough_numbering.py`

**Interfaces:**
- Consumes: `Playthrough`, `PlaythroughKind` (Task 2).
- Produces:
  - `with_display_number(queryset: QuerySet[Playthrough]) ->
    QuerySet[Playthrough]` — filters to live ordinary rows and annotates
    `display_number`
  - `display_name(playthrough: Playthrough) -> str`
  - `UnnumberedPlaythrough(ValueError)` — raised by `display_name` for a
    blank-named row carrying no `display_number`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playthrough_numbering.py`:

```python
"""Playthrough N, derived at read time."""

import uuid

import pytest
from django.utils import timezone

from games.models import Game, PlayerGame, Playthrough, PlaythroughKind
from games.reads.playthrough_numbering import (
    UnnumberedPlaythrough,
    display_name,
    with_display_number,
)
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


@pytest.fixture
def tracked(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    return PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )


def make_run(tracked, *, started=None, completed=None, created_at=None, **columns):
    return Playthrough.objects.create(
        id=uuid.uuid7(),
        library=tracked.library,
        player_game=tracked,
        started=started,
        completed=completed,
        created_at=created_at or timezone.now(),
        **columns,
    )


def numbers(tracked):
    return [
        (row.pk, row.display_number)
        for row in with_display_number(
            Playthrough.objects.filter(player_game=tracked)
        ).order_by("display_number")
    ]


def test_a_known_start_orders_before_an_unknown_one(tracked):
    """NULLS LAST on the start bound."""
    unknown = make_run(tracked)
    known = make_run(tracked, started=TemporalValue.from_year(2024))

    assert numbers(tracked) == [(known.pk, 1), (unknown.pk, 2)]


def test_a_removed_row_does_not_shift_the_number(tracked):
    first = make_run(tracked)
    removed = make_run(tracked, removed_at=timezone.now())
    last = make_run(tracked)

    assert [pk for pk, _ in numbers(tracked)] == [first.pk, last.pk]
    assert numbers(tracked) == [(first.pk, 1), (last.pk, 2)]
    assert removed.pk not in {pk for pk, _ in numbers(tracked)}


def test_a_system_row_does_not_shift_the_number(tracked):
    first = make_run(tracked)
    bucket = make_run(
        tracked, kind=PlaythroughKind.IMPORTED_HISTORY, name="Imported history"
    )
    last = make_run(tracked)

    assert numbers(tracked) == [(first.pk, 1), (last.pk, 2)]
    assert bucket.pk not in {pk for pk, _ in numbers(tracked)}


def test_rows_that_share_every_other_key_are_ordered_by_identity(tracked):
    """The case the id key exists for.

    Until #681 every playthrough has two null bounds, and one append
    stamps one recorded_at across every row it writes.
    """
    stamp = timezone.now()
    created = sorted(
        [make_run(tracked, created_at=stamp) for _ in range(4)],
        key=lambda row: row.pk,
    )

    assert numbers(tracked) == [
        (row.pk, position) for position, row in enumerate(created, start=1)
    ]


def test_the_number_partitions_by_tracked_game(owned_library, tracked):
    other_game = Game.objects.create(library=owned_library, name="Tunic")
    other = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=other_game,
        tracked_at=timezone.now(),
    )
    make_run(tracked)
    theirs = make_run(other)

    assert numbers(other) == [(theirs.pk, 1)]


def test_a_blank_name_displays_as_the_number(tracked):
    make_run(tracked)
    row = with_display_number(Playthrough.objects.all()).get()

    assert display_name(row) == "Playthrough 1"


def test_a_named_row_displays_its_name(tracked):
    make_run(tracked, name="Blind run")
    row = with_display_number(Playthrough.objects.all()).get()

    assert display_name(row) == "Blind run"


def test_a_named_row_needs_no_number(tracked):
    """The bucket #700 creates carries a name."""
    bucket = make_run(
        tracked, kind=PlaythroughKind.IMPORTED_HISTORY, name="Imported history"
    )

    assert display_name(bucket) == "Imported history"


def test_a_blank_name_with_no_number_is_refused(tracked):
    """A caller paired a row with a queryset it is not in."""
    unnumbered = make_run(tracked)

    with pytest.raises(UnnumberedPlaythrough):
        display_name(unnumbered)
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_playthrough_numbering.py -x -p no:randomly"
```

Expected: `ModuleNotFoundError: No module named
'games.reads.playthrough_numbering'`.

- [ ] **Step 3: Write the read module**

Create `games/reads/playthrough_numbering.py`:

```python
"""Playthrough N, derived at read time.

The number is stored nowhere. Its order depends on sibling rows, so a
stored column would make every endpoint change, every removal and every
creation rewrite every sibling of one tracked game -- and a rebuild would
have to reproduce that order of writes exactly.
"""

from django.db.models import F, QuerySet, Window
from django.db.models.functions import RowNumber

from games.models import Playthrough, PlaythroughKind


class UnnumberedPlaythrough(ValueError):
    """A blank-named row that carries no display number."""


def with_display_number(
    queryset: QuerySet[Playthrough],
) -> QuerySet[Playthrough]:
    """The live ordinary rows, each carrying its number.

    WHERE runs before a window function, so the filter is what keeps a
    removed row and a system row from shifting the number a player
    learned.

    The key is the fourth sort field and it is what makes the order
    total. Until #681 every row has two null bounds, and one append
    stamps one recorded_at across every row it writes, so the first
    three fields leave whole partitions as peers -- and RowNumber over
    peers follows the plan's input order, which a swap changes.
    """
    return queryset.filter(
        removed_at__isnull=True, kind=PlaythroughKind.ORDINARY
    ).annotate(
        display_number=Window(
            RowNumber(),
            partition_by="player_game",
            order_by=(
                F("started_lower").asc(nulls_last=True),
                F("completed_lower").asc(nulls_last=True),
                "created_at",
                "id",
            ),
        )
    )


def display_name(playthrough: Playthrough) -> str:
    """What a screen calls this run.

    Total: a named row needs no number, and a blank-named row without
    one is refused rather than left to raise from a missing annotation.
    """
    if playthrough.name:
        return playthrough.name
    number = getattr(playthrough, "display_number", None)
    if number is None:
        raise UnnumberedPlaythrough(
            f"Playthrough {playthrough.pk} has no name and no display "
            "number. A blank name is displayed as its number, which only "
            "with_display_number() states, and only over the live ordinary "
            "rows a number is counted across."
        )
    return f"Playthrough {number}"
```

- [ ] **Step 4: Run the tests**

```
make test ARGS="tests/test_playthrough_numbering.py -p no:randomly"
make typecheck
```

Expected: PASS. If the peers test fails, print the generated SQL with
`print(with_display_number(Playthrough.objects.all()).query)` and confirm the
`ORDER BY` ends in `"games_playthrough"."id" ASC`.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_numbering.py tests/test_playthrough_numbering.py
git commit -m "Derive Playthrough N at read time

Ordered by known start bound NULLS LAST, then known completion bound,
then creation time, then the key -- which is what makes the order total
and the number stable across a rebuild.

#1012 is the first consumer; until then the rule is proven by its tests.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: One library per projection row

**Files:**
- Modify: `games/models.py` (`ProjectionModel` docstring, around line 1508)
- Modify: `games/management/commands/audit_library_ownership.py:167-235`
- Test: `tests/test_library_commands.py` (its cross-library case ends at
  line 588)

**Interfaces:**
- Consumes: `Playthrough` (Task 2).
- Produces: `_cross_library_violations` reports a `Playthrough` whose `library`
  differs from its `player_game`'s.

- [ ] **Step 1: Write the failing audit test**

Add to `tests/test_library_commands.py`, beside the six-relation case that ends
at line 588. That case uses the `owner` and `outsider` fixtures and asserts the
command raises `CommandError` matching `"violation"`; this one does the same.

```python
@pytest.mark.django_db
def test_a_playthrough_in_another_library_is_reported(owner, outsider):
    """A cross-library projection row makes a library un-rebuildable.

    The swap works one library at a time, so a child left pointing
    across the boundary fails the deferred foreign key at COMMIT --
    every time, with no way out.
    """
    game = Game.objects.create(library=owner.library, name="Outer Wilds")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owner.library,
        game=game,
        tracked_at=timezone.now(),
    )
    run = Playthrough.objects.create(
        id=uuid.uuid7(),
        #: The offence: not the tracked game's library.
        library=outsider.library,
        player_game=tracked,
        created_at=timezone.now(),
    )
    output = StringIO()

    with pytest.raises(CommandError, match="violation"):
        call_command(
            "audit_library_ownership",
            "--user",
            owner.username,
            stdout=output,
        )

    assert (
        f"Playthrough.player_game: playthrough {run.pk}, "
        f"tracked game {tracked.pk}" in output.getvalue()
    )
```

`StringIO`, `call_command`, `CommandError`, `pytest`, `uuid` and `timezone` are
already imported there; add `PlayerGame` and `Playthrough` to its
`from games.models import …`.

Also extend the six-relation loop in the case above it — the list of relation
names it asserts appear in one report — with `"Playthrough.player_game"`, and
give that case a playthrough to find. That is what keeps the two cases from
disagreeing about what a full report contains.

- [ ] **Step 2: Run it and watch it fail**

```
make test ARGS="tests/<that file> -k playthrough -x -p no:randomly"
```

Expected: FAIL — the audit reports nothing.

- [ ] **Step 3: Add the pair to the audit**

In `games/management/commands/audit_library_ownership.py`, inside
`_cross_library_violations`, after the `UserLibraryPreferences.default_device`
block, as the last loop before its `return`:

```python
@staticmethod
def _cross_library_violations(library_ids):
    violations = []
    ...  # the six existing relation loops, unchanged

    #: This list has no completeness test, so a relation left out of it is
    #: never audited. A projection row is the costly case: the swap works
    #: one library at a time, so a cross-library child fails the deferred
    #: key at COMMIT and the library can never be rebuilt.
    for playthrough_id, player_game_id in (
        Playthrough.objects.filter(
            Q(library_id__in=library_ids) | Q(player_game__library_id__in=library_ids)
        )
        .exclude(player_game__library_id=F("library_id"))
        .values_list("pk", "player_game_id")
    ):
        violations.append(
            "Playthrough.player_game: "
            f"playthrough {playthrough_id}, tracked game {player_game_id}"
        )
```

Add `Playthrough` to the module's `from games.models import …`. `Q` and `F` are
already imported.

- [ ] **Step 4: State the invariant on the base class**

In `games/models.py`, `ProjectionModel`'s docstring currently ends "No check
enforces that last rule." Extend it:

```
    projection row, because the swap deletes and inserts each row. No check
    enforces that last rule.

    A fourth rule arrives with the second projection table. A projection row
    and every projection row it names belong to one library. The swap runs
    one library at a time, so a row pointing across the boundary fails the
    deferred foreign key at COMMIT and leaves that library unable to rebuild
    at all. Nothing in the schema refuses it: `audit_library_ownership`
    reports it, and every command resolves its references within the
    library it is dispatched for.
```

Do not write the refused word for what the swap does to a row — the sentence
above already says "deletes and inserts" because that is the existing text; keep
it as it stands and add only the new paragraph, which avoids the word.

- [ ] **Step 5: Run the audit tests and vale**

```
make test ARGS="tests/<that file> tests/test_playthrough_projection.py -p no:randomly"
make vale
make typecheck
```

Expected: PASS, and vale reports only the seven pre-existing warnings.

- [ ] **Step 6: Commit**

```bash
git add games/models.py games/management/commands/audit_library_ownership.py tests/
git commit -m "Audit that a Playthrough and its tracked game share a library

The rebuild swaps one library at a time, so a projection row pointing
across the boundary fails the deferred foreign key at COMMIT and leaves
that library permanently unable to rebuild. Nothing in the schema
refuses it; the ownership audit now reports it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: The rebuild, proven

**Files:**
- Test: `tests/test_playthrough_projection.py` (append)
- Test: `tests/test_playthrough_numbering.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: no production code. This task is the evidence for the spec's claims
  about the shadow rebuild.

- [ ] **Step 1: Write the replay and rebuild tests**

Append to `tests/test_playthrough_projection.py`. Add these imports, all of
which `tests/test_playergame_projection.py:6-26` already carries:

```python
from django.db import connection

from games.commands.playergame import TrackGame
from games.events.dispatch import dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.replay import replay
```

```python
def track(owned_user, owned_library, game, key="track"):
    return dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_an_empty_database_replay_reproduces_both_tables(owned_user, owned_library):
    """Nothing in either row predates its event."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    before = (
        list(PlayerGame.objects.order_by("pk").values()),
        list(Playthrough.objects.order_by("pk").values()),
    )
    #: The child first: player_game RESTRICTs.
    Playthrough.objects.all().delete()
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert (
        list(PlayerGame.objects.order_by("pk").values()),
        list(Playthrough.objects.order_by("pk").values()),
    ) == before


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_swaps_both_tables_with_an_empty_diff(owned_user, owned_library):
    """The foreign key between two projection tables and the generated
    columns, proven rather than argued."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    #: Both tables, each agreeing with its rebuild.
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
    assert (PlayerGame.objects.count(), Playthrough.objects.count()) == (1, 1)


@pytest.mark.django_db
def test_the_foreign_key_to_playergame_is_deferred():
    """Why the swap's table order is not load-bearing.

    Django emits no ON DELETE clause, so the constraint is Postgres's
    default NO ACTION -- and deferred, so it is checked at COMMIT, after
    the swap has reinserted both tables.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT condeferrable, condeferred, confdeltype
            FROM pg_constraint
            WHERE conrelid = 'games_playthrough'::regclass
              AND contype = 'f'
              AND confrelid = 'games_playergame'::regclass
            """
        )
        rows = cursor.fetchall()

    assert rows == [(True, True, "a")]
```

`report.tables` is sorted by `db_table`, which is the order
`tests/test_projection_rebuild.py:1059` already relies on.

- [ ] **Step 2: Add the rebuild-stability test for the number**

Append to `tests/test_playthrough_numbering.py`, adding these imports:

```python
from games.commands.playergame import TrackGame
from games.commands.playthrough import CreatePlaythrough
from games.events.dispatch import dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
```

```python
@pytest.mark.django_db(transaction=True)
def test_the_number_is_unchanged_across_a_rebuild(owned_user, owned_library):
    """The order is total, so a swap cannot reshuffle it."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked = PlayerGame.objects.get()
    for index in range(4):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key=f"run-{index}",
        )
    before = numbers(tracked)

    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert numbers(tracked) == before
    assert [number for _, number in before] == [1, 2, 3, 4, 5]
```

Note this test dispatches, so it needs `transaction=True`; the module's
`pytestmark` already sets `django_db` without it, so the per-test marker wins.
If it does not, split the dispatching tests into their own module-level mark.

- [ ] **Step 3: Run them**

```
make test ARGS="tests/test_playthrough_projection.py tests/test_playthrough_numbering.py tests/test_projection_rebuild.py -p no:randomly"
```

Expected: PASS. A failure here is the interesting kind — if the swap raises
`IntegrityError` at COMMIT, the deferral assumption is wrong and the design
needs revisiting before going further.

- [ ] **Step 4: Commit**

```bash
git add tests/test_playthrough_projection.py tests/test_playthrough_numbering.py
git commit -m "Prove the rebuild over the first application table with a
projection foreign key and generated columns

Empty-database replay reproduces both tables, the swap leaves an empty
diff, the foreign key is DEFERRABLE INITIALLY DEFERRED so table order is
free, and the display number is unchanged across a rebuild.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: The purge still empties a library

**Files:**
- Test: `tests/test_retention.py`, in its "except during a whole-library purge"
  section (which begins at line 495)

**Interfaces:**
- Consumes: everything above.
- Produces: no production code, unless the test fails.

- [ ] **Step 1: Write the test**

`Playthrough.player_game` is a new `RESTRICT` edge on the one path that destroys
rows, and it also stops `PlayerGame` being fast-deletable. In the same shape as
`test_purging_a_library_takes_its_referenced_rows` at line 496:

```python
@pytest.mark.django_db(transaction=True)
def test_purging_a_library_takes_its_playthroughs(owned_user, owned_library, game):
    """A new RESTRICT edge on the one path that destroys rows."""
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    assert Playthrough.objects.count() == 1

    call_command(
        "purge_user_library",
        user=owned_user.username,
        confirm=owned_user.username,
        stdout=StringIO(),
    )

    assert not Playthrough.objects.exists()
    assert not PlayerGame.objects.exists()
```

The neighbouring purge tests carry no `transaction=True`; this one needs it,
because it dispatches. Add `dispatch`, `TrackGame`, `PlayerGame` and
`Playthrough` to the file's imports.

- [ ] **Step 2: Run it**

```
make test ARGS="tests/test_retention.py -k playthrough -x -p no:randomly"
```

Expected: PASS. The `Playthrough` rows arrive through `UserLibrary` CASCADE, so
Django's collector should reach them before the `PlayerGame` rows they restrict.

- [ ] **Step 3: If it fails, order the collector's work**

A `RESTRICT`-related `ProtectedError` means the collector reached `PlayerGame`
first. Read the purge command and remove the library's playthroughs explicitly
before its tracked games, with a comment naming why. Do not weaken the
`on_delete` — a cascade must never reach a projection row.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "Check the purge against the new RESTRICT edge

Playthrough.player_game restricts, and the purge is the one path that
destroys rows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: Documentation and the benchmark

**Files:**
- Modify: `CLAUDE.md` (the Models section, around the `PlayerGame` bullet)
- Modify: `docs/vocabulary.md`
- Modify: `docs/event-benchmarks.md` (the figures, and its line 209)
- Modify: the #679 issue body and
  `docs/superpowers/specs/2026-09-04-playthrough-wave-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Add the CLAUDE.md bullet**

The `PlayerGame` bullet opens "**the first projection**" and is the only one.
Add a sibling after it:

```markdown
- **Playthrough** — the second projection: one row per run at a tracked game,
  written only by the `Playthroughs` projector, which shares the
  `CURRENT_STATE` family with `PlayerGames`. Every `PlayerGame` gets one from
  the moment a library tracks the game — `TrackGame` returns both creation
  events under one `correlation_id`. Both endpoints are `TemporalValueField`
  with generated lower- and upper-bound columns beside each. Its `removed_at`
  is the projector's, stated by a command, which is why it is absent from
  `REMOVABLE_MODELS`. A blank `name` displays as `Playthrough N`, derived at
  read time by `games/reads/playthrough_numbering.py` and stored nowhere
```

Then check the "**the nine** removable models" count in the same file is still
right — it is, because `Playthrough` is not in `REMOVABLE_MODELS`, and the new
bullet says so.

- [ ] **Step 2: Record what *family* now means**

In `docs/vocabulary.md`, in whatever section holds the event-sourcing words, add
that a projection *family* is an ordering group rather than one class: order
between families is `ProjectorFamily`'s member order, order within one is
registration order, and one event type has one owner inside a family.

- [ ] **Step 3: Rerun the benchmark and restate the figures**

```
make bench
```

This takes about 1.7 minutes and seeds then removes a scratch library. Update
every figure in `docs/event-benchmarks.md` that moved, and correct its line 209,
which reads "for when a second projector **family** makes the budget tight
again" — after #679 the second projector is in the same family.

- [ ] **Step 4: Record the registry decision where the next reader looks**

Add to the #679 issue body's Scope, and to the `#679 — the Playthrough
aggregate` boundary in
`docs/superpowers/specs/2026-09-04-playthrough-wave-design.md`:

> Also relaxes `ProjectorRegistry` so one family holds many projectors, with the
> ownership guard on the `(family, event type)` pair. It belongs here because
> nothing else can consume it: no second `CURRENT_STATE` projector can exist
> until it lands.

- [ ] **Step 5: Run the full gate**

```
make check
```

This is the gate — lint, format check, mypy, vale, ts-check, vitest and the
entire pytest suite **including `e2e/`**. It must be green. Never substitute a
subset.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "Document the second projection and the second projector

CLAUDE.md gains the Playthrough bullet, vocabulary.md records what a
projection family now means, and the benchmark figures are restated
because TrackGame is two events.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification against the spec

Run this list before opening the PR. Each item is the spec's numbered
verification, with the task that discharges it.

| Spec item | Discharged by |
|---|---|
| 1. `make check` green, four pinned inventories | Task 2 step 6, Task 11 step 5 |
| 2. `check_projection_models` passes | Task 2 step 1 |
| 3. Two projectors share `CURRENT_STATE`; one type twice refused; run order | Task 1 step 1 |
| 4. `TrackGame` appends two at *N*, *N+1*, one `correlation_id` | Task 6 step 1 |
| 5. A repeat answers from the record | Task 6 step 1 |
| 6. `CreatePlaythrough` refuses untracked and removed | Task 5 step 1 |
| 7. Empty-database replay reproduces both tables | Task 9 step 1 |
| 8. Rebuild swaps with no constraint error, empty diff, either order | Task 9 step 1 |
| 9. Display number: order, NULLS LAST, exclusions, peers, rebuild | Tasks 7, 9 |
| 10. The audit reports a cross-library Playthrough | Task 8 step 1 |
| 11. `purge_user_library` empties a library with playthroughs | Task 10 |
| 12. `make bench` rerun, `docs/event-benchmarks.md` restated | Task 11 step 3 |

## What this plan does not do

Out of scope for #679, and each named where the code will need it: the endpoint
events (#681), the name and note events (#1010), removal and restoration
(#1011), the shared reference resolver (#909), the imported-history bucket and
Session assignment (#700, #701), the legacy conversion and the missing defaults
(#684), every screen, filter, statistic and API surface (#687, #1012–#1015).

Two things this plan deliberately leaves undone and records instead:

- Renaming `PlayerGame`'s `track` / `created` / `tracked_at` split onto one
  verb. It is the incumbent that breaks the rule, and the rename touches a
  `CommandName` value that an idempotency fingerprint is computed from.
- The composite `(library_id, player_game_id)` foreign key that would make the
  cross-library row refusable by the database. Task 8 ships the audit instead;
  if the audit ever reports a violation, the composite key is the fix.

One hazard #681 inherits: `tests/test_event_vocabulary.py:266` registers
`"library.playthrough.started"` as a test double and asserts it never reaches
`DEFAULT_EVENT_TYPES`, and it appears again at `tests/test_event_append.py:69`.
#681 registers that exact name for real and fails on day one. #679 does not
collide, so renaming those doubles to `library.probe.*` is #681's first commit.
