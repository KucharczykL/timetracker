# The PlayerGame current-state projection

Issue [#671](https://github.com/KucharczykL/timetracker/issues/671), the first
slice of the PlayerGame wave ([#601](https://github.com/KucharczykL/timetracker/issues/601)).

## What it is

One row per catalog game a library tracks, written only by a projector, from one
event, appended by one command. It is the first *real* thing built on the event
store: the first registered event type, the first projector family, the first
command that is not a test placeholder, and the first projection table the
application ships.

The slice is deliberately identity-only. `PlayerGame` records **that** a library
tracks a game and **when** it started; what the player then does with it —
status, mastered, exclusion, archive — arrives one event at a time in #672–#675.
That keeps this issue about the seam between the catalog and the event store,
which is the part nothing has exercised yet.

## Boundary

| In | Out |
| --- | --- |
| `PlayerGame` model and its migration | Any status, mastered, exclusion, or archive column |
| `library.playergame.created` event type | Any other event type |
| The `CURRENT_STATE` projector family | The `JOURNAL` and `STATS` families |
| A `TrackGame` command reached by dispatch | Any view, form, or API that calls it |
| Two-library isolation and replay-parity tests | Backfill (#676), write cutover (#677), read cutover (#678) |
| | Any change to `Game.status`, `mastered`, or `playtime` |

Nothing outside the event path reads or writes the new table in this issue. That
is what makes it independently reviewable: the projection can be wrong in
production and no page changes.

## Preconditions

Everything this builds on is already in `main`:

- `games/events/projection.py` — `Projector`, `ProjectorFamily`,
  `DEFAULT_REGISTRY`; subclassing registers.
- `games/events/vocabulary.py` — `EventSpec`, `spec.new()`, `DEFAULT_EVENT_TYPES`,
  which is empty by design.
- `games/events/references.py` — `catalog.game` is registered as a
  `Resolution.REQUIRED` kind over `Game`, with `_capture_game` as its snapshot.
- `games/events/dispatch.py` — `dispatch()`, `Command`, `CommandRejected`,
  `CommandName`, whose only members today are six `TEST_COMMAND_*` placeholders.
- `games/models.py` — `ProjectionModel`, which supplies the `library` column.
- `games/checks.py` — E001–E006, which refuse a projection field the events
  cannot determine.
- `games/apps.py` — `ready()` already imports `games.projectors`.

## Design

### The table

```python
class PlayerGame(ProjectionModel):
    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    game = models.ForeignKey(Game, on_delete=models.RESTRICT, related_name="player_games")
    tracked_at = models.DateTimeField(editable=False)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("library", "game"), name="unique_library_player_game"),
        )
```

Both defaults are opted out of explicitly, and that is the one non-obvious line
in the model. `UUIDv7Field.__init__` does `kwargs.setdefault("default", uuid.uuid7)`
and `kwargs.setdefault("db_default", PostgreSQLUUIDv7())` — convenience that
every other table in the codebase wants and that a projection must refuse. A
minted default trips `games.E005`, a database default trips `games.E004`, and
both would mean a rebuild produced an identity the live table never had. The key
is the event's `aggregate_id`, so the row is a pure function of the stream.

`tracked_at` has no default for the same reason (`games.E006`): the projector
copies the creation event's `recorded_at`.

`on_delete=RESTRICT` on `game` matches `LibraryEvent.stream`. It still permits a
whole-library purge, where the library and its private games die inside one
cascade, and it refuses a lone catalog deletion — which #653's reference
tombstones already make impossible for any game an event names.

The unique constraint over `(library, game)` is the acceptance criterion
"two libraries tracking the same shared Game receive independent PlayerGames",
stated as a database rule: it is per-library, so it constrains nothing across
libraries.

### The event type

`games/events/playergame.py` holds the first production spec and registers it
into `DEFAULT_EVENT_TYPES`:

```python
@with_config(ConfigDict(extra="forbid", strict=True))
class PlayerGameCreatedPayload(TypedDict):
    game: Reference


PLAYERGAME_CREATED = EventSpec(
    event_type="library.playergame.created",
    aggregate_type="playergame",
    payload=PlayerGameCreatedPayload,
)
```

Declaring the field as `Reference` is the whole integration with #653 and #669:
`reference_fields()` enumerates the key at registration, `append` writes the
`LibraryEventReference` row, the tombstone refuses a hard delete of a referenced
game, and `require_resolvable_references()` checks it before every fold — with
`manage.py rebuild_projections` printing the reconciliation if one ever goes
missing. No code in this issue mentions any of that.

The payload carries the reference and nothing else. The library is on the event,
the identity is the `aggregate_id`, and the time is `recorded_at`; a payload key
repeating any of them would be a second copy of a fact the envelope already
records.

Version stays 1, as the registry requires until an upcaster exists.

### The command

`games/commands/playergame.py`, a new package, with one new `CommandName` member
`PLAYERGAME_TRACK = "library.playergame.track"`:

```python
@dataclass(frozen=True, slots=True)
class TrackGame(Command):
    command_name = CommandName.PLAYERGAME_TRACK
    game_id: uuid.UUID
```

The field is a UUID rather than a `Game`, as `Command` requires: a model
instance has no canonical form to fingerprint, so the command re-fetches inside
`build`, where it has the library to scope the lookup.

`build()` does three things:

1. Resolve the game as *visible to this library* — its own private row
   (`library_id == context.library.pk`) or a shared one (`library_id IS NULL`),
   and not archived. Anything else raises `CommandRejected`, which is the
   cross-library refusal the acceptance criteria ask for. The lookup is written
   inline here and is the first customer for #909's shared resolver.
2. Refuse a second track of the same game with `CommandRejected`. Whether that
   should instead succeed as a no-op is #906; until that is decided, refusing is
   the answer that cannot be wrong twice.
3. Mint the aggregate id and return one
   `PLAYERGAME_CREATED.new(aggregate_id=..., payload={"game": capture_reference(game)})`.

Both reads happen after dispatch has taken the stream-head lock, which is what
makes the duplicate check hold: no concurrent `TrackGame` for the same library
can land between the read and the append.

Nothing calls the command yet. Tests dispatch it directly; #677 is where the
write path switches.

### The projector

`games/projectors/playergame.py`:

```python
class PlayerGames(Projector):
    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None: ...

    handles: ClassVar[HandlerMap] = {PLAYERGAME_CREATED: _created}
```

The map names the function read out of the class body, which is why `handles`
is declared after the handler rather than at the top.

The handler writes `self.target.model(PlayerGame)`, never the imported model, so
a shadow rebuild redirects it. It writes with `update_or_create` keyed on
`event.aggregate_id`, setting `library_id`, `game_id` from the payload
reference, and `tracked_at` from `event.recorded_at`. Keying on the event's own
identity is what makes folding an already-folded event a no-op rather than a
duplicate row, which is what replay parity needs.

The `library_id` comes from the event, never from a command's context — a
projector is handed a `RecordedEvent` and has no other source, and that is why a
replay reproduces the same ownership.

### Registration and import order

`games/projectors/__init__.py` imports the family module, which imports the
event module. `GamesConfig.ready()` already imports the package, so both
registries fill at startup with no new hook. Neither module may be imported from
`games/models.py`: the event modules import the models, and the reverse edge
would be a cycle.

### What this changes elsewhere

`projection_models()` stops being empty, so
`tests/test_projection_rebuild.py::test_the_application_declares_no_projection_table_yet`
inverts: the application now declares exactly one. The foundation issues wrote
that assertion knowing this issue would retire it. The docstrings in
`games/projectors/__init__.py` ("Empty until the first evented domain lands")
and on `CommandName` ("Placeholders exercising dispatch until real commands
exist") both need a sentence adjusted rather than removed — the six placeholders
remain placeholders.

Two downstream issues get their first real subject: #670's benchmark harness no
longer needs a synthetic workload, and #667's rebuild finally has a table to
rebuild.

## Where the behaviour is pinned

- `tests/test_playergame_projection.py` — a dispatched `TrackGame` writes one
  row whose pk is the event's `aggregate_id`, whose `tracked_at` is the event's
  `recorded_at`, and whose `game` is the named catalog game.
- Two libraries tracking one shared game get two rows; neither sees the other's.
- A library tracking another library's private game is rejected; so is an
  archived game, and so is a second track of a game already tracked.
- Dispatching the same command twice under one idempotency key writes one row
  and reports `replayed=True` the second time.
- `rebuild_projections(library, mode=CHECK)` over a dispatched stream reports
  zero drift; `REBUILD` swaps and leaves the rows equal, which is replay parity
  stated as a test.
- A game a `PlayerGame` event names refuses hard deletion (#653's rule, checked
  here because this is the first payload that exercises it).
- `tests/test_projection_model.py` gains `PlayerGame` passing the E001–E006
  checks — the regression guard on the two opted-out field defaults.
- `manage.py makemigrations --check` stays clean.

## Verification

The full `make check`, including `e2e/`, must be green. Nothing in this issue
renders, so no e2e test is added; the gate runs the suite anyway because a new
model and a new startup import can break pages that never mention either.

## Follow-up issues

#672–#675 add the state columns and their events. #676 backfills baseline events
for existing rows, #677 switches writes, #678 switches reads. #906 decides
whether a duplicate track is a rejection or a no-op. #909 extracts the
library-scoped resolver this command writes inline.
