# The Playthrough aggregate and its mandatory default

Issue [#679](https://github.com/KucharczykL/timetracker/issues/679). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).

`Playthrough` is the second projection table and the second command family. It
follows the shape #671 delivered for `PlayerGame`: a model and its migration, a
creation event, a projector in the `CURRENT_STATE` family, and the commands that
state a new row.

This issue also carries the display-number rule and the system kind, absorbed
from #680. A number decided after the projection ships is a second migration
over the same table.

## What the wave asked for that the code refuses

The wave review says the projector `Playthroughs` is "in the `CURRENT_STATE`
family". As shipped, that sentence cannot be written.
`ProjectorRegistry.register` keys `_families` on a `ProjectorFamily` member and
raises `TypeError` when a second class claims one, and
`tests/test_event_projectors.py::test_two_families_cannot_claim_one_member`
pins the refusal. `PlayerGames` holds `CURRENT_STATE` today.

So the first act of this issue is a change to the registry, not to the domain.

The change belongs here rather than in its own issue because nothing else can
consume it: no second `CURRENT_STATE` projector can exist until it lands. Two
alternatives were refused. Hanging the Playthrough handlers off the
`PlayerGames` class makes one projector the writer of two tables and makes the
`Playthroughs` name a lie. A new `ProjectorFamily` member makes run order depend
on a family that is not one, and `ProjectorFamily`'s docstring says member order
is run order because later families read the current-state rows written earlier.

The #679 issue body and the wave doc's #679 boundary do not mention the registry
today. Both get the sentence, so the scope decision lives where the next reader
looks rather than only in this file.

## The registry

A family becomes a group of projectors rather than one.

```
_families: dict[ProjectorFamily, dict[DefinitionSite, Projector]]
_classes:  dict[ProjectorFamily, dict[DefinitionSite, type[Projector]]]
_claims:   dict[tuple[ProjectorFamily, EventType], DefinitionSite]
```

Three properties survive the change.

Re-registering one definition site replaces its instance rather than adding a
second copy, because the inner mapping keys on that site. This is what
`test_registering_one_family_twice_is_not_a_collision` asks for.

Two classes may not claim one event type inside one family. The ownership guard
moves from the family to the pair, and keeps the words "already owned by", so
`test_two_families_cannot_claim_one_member` passes unchanged — both its classes
claim `PROBE_RECORDED` inside `STATS` from two definition sites, which still
collides on the pair. Its name no longer says what it checks, so it is renamed.

Run order is unchanged between families: `_rebuild_handlers` walks families in
`_RUN_ORDER` and, inside a family, in registration order. `for_target` copies
the same nesting.

A new test states the thing that was impossible before: two classes share
`CURRENT_STATE`, each handling its own event type, and both run.

### Two docstrings the change falsifies

`ProjectorFamily`'s docstring says run order "must not depend on which module
Python imported first". After the change, order *within* a family is the order
`games/projectors/__init__.py` imports the modules. It is harmless — the
`(family, event type)` claim means no two same-family handlers ever see one
event — but the sentence has to say so: order across families is the enum,
order within one is registration order, and the claim is what makes that not
matter.

`games/projectors/__init__.py`'s docstring is "One module per family; importing
registers it." That becomes false with the second module in `CURRENT_STATE`.

Both are code comments, so `make vale` reads them.

## The table

`Playthrough` subclasses `ProjectionModel`. Only the `Playthroughs` projector
writes it. Migration `0043_playthrough`; the head of `games/migrations/` is
`0042_external_reference_choices`.

```
id           UUIDv7Field(primary_key, default=NOT_PROVIDED, db_default=NOT_PROVIDED)
library      from ProjectionModel
player_game  ForeignKey(PlayerGame, on_delete=RESTRICT, related_name="playthroughs")
kind         CharField(choices=PlaythroughKind, default=ORDINARY)
name         CharField(blank=True, default="")
note         TextField(blank=True, default="")
started              TemporalValueField
started_lower        GeneratedField(
                         expression=TemporalLowerBound("started"),
                         output_field=models.DateField(null=True),
                         null=True, serialize=False, db_persist=True, editable=False)
started_upper        GeneratedField(... TemporalUpperBound("started") ...)
completed            TemporalValueField
completed_lower      GeneratedField(... TemporalLowerBound("completed") ...)
completed_upper      GeneratedField(... TemporalUpperBound("completed") ...)
created_at   DateTimeField(editable=False)
removed_at   DateTimeField(null=True, default=None, editable=False)
```

The four bound columns copy `Release.release_date_lower` exactly. `db_persist`
is `True`, which is what lets the display-number index cover them.

The primary key is the creation event's `aggregate_id`. `UUIDv7Field` supplies a
minted default and a database default; this model refuses both, because
`games.checks` E004 and E005 refuse a default a rebuild would evaluate again.

`created_at` is the creation event's `recorded_at`. It carries no default, and
E006 refuses a *clock* default specifically — a non-clock callable is E007, and
a constant would pass every check and still be wrong here.

`library` arrives from `ProjectionModel` and repeats what `player_game` already
implies. It is not decoration: `swap_in` removes rows by `library_id` and the
rebuild diff filters on it, so a projection table without the column cannot be
swapped.

### One verb for the act

The event name is fixed by the wave doc and the issue body:
`library.playthrough.created`. `docs/event-retention.md` says the event type,
the command and the projection column all take one verb, and the column names
the act in the past participle. So the command is `CreatePlaythrough` /
`CommandName.PLAYTHROUGH_CREATE = "library.playthrough.create"`, and the column
is `created_at`. Three places, one verb.

`PlayerGame` does not read that way: its command is `track`, its event is
`library.playergame.created`, and its column is `tracked_at`. It is the
incumbent that breaks the rule, not the newcomer that should copy the break.
Renaming it is a real cost — a `CommandName` value that a
`LibraryIdempotencyRecord` fingerprint is computed from, and a projection column
— and this issue does not pay it. It is worth its own issue; the divergence is
recorded here so the next reader does not read two conventions where there is
one rule and one exception.

### What each column is for, and who writes it

The whole set ships in one migration. Column by column:

- `started`, `completed` and the four bounds — **#679 owns the shape.** The
  issue body specifies it and the wave doc gives the three consumers. #681
  states the values.
- `name` — **#679 owns it.** #680 was absorbed for the `Playthrough N` rule, and
  `display_name()` reads the column. #1010 owns the command that sets it.
- `removed_at` — **#679 owns it**, because the numbering rule filters on it.
  #1011 owns the command that stamps it.
- `note` — **#1010 owns it outright.** Nothing in #679 reads or writes it. It
  ships early only so that #1010 adds an event and a handler and no migration.
  Deferring it costs one more migration over this table and buys nothing.

An index over `(player_game, started_lower, completed_lower, created_at, id)` is
the display-number order. The Sessions wave asks a different question of the
bound columns and owns the index that answers it.

`Playthrough` is **not** in `REMOVABLE_MODELS`. That tuple and the `BUILDERS`
dict in `tests/test_removable_models.py` are both hand-written and neither
introspects for a `removed_at` column, so nothing fails. The mark is the
projector's, as `PlayerGame`'s is, and `games/removal.py` already carries the
precedent comment.

### Where the new table must be registered

Four inventories are hard-pinned literals rather than introspection, so each one
fails the moment the model exists:

- `tests/test_projection_rebuild.py:136` — `assert projection_models() ==
  (PlayerGame,)`, docstring "The one projection table so far."
- `tests/test_projection_model.py:244` — `PINNED_DEFAULTS` needs a
  `"games.Playthrough"` entry for `kind`, `name`, `note` and `removed_at`.
- `tests/test_uuid_identity_audit.py:32` `EXPECTED_RELATION_COLUMNS` — needs
  `("games_playthrough", "library_id")` and `("games_playthrough",
  "player_game_id")`. Re-asserted at `tests/test_projection_rebuild.py:1274`.
- `tests/test_uuid_identity_audit.py:238` `EXPECTED_IDENTITY_TABLES` — needs
  `games_playthrough`. This is the `make audit-uuid-identity` gate.

Three inventories need nothing, checked rather than assumed:
`games/views/returns.py` trips only on a new route name and this issue adds no
route; `tests/test_iterator_guard.py` trips only on `.iterator()`;
`tests/test_filters.py::test_no_nullable_string_fields_in_games_models` accepts
`blank=True, default=""`. There is no admin, `purge_user_library` names no
models, and a projection does not go in the sample fixture.

### The shadow rebuild

`Playthrough` is the first **application** table with a foreign key to another
projection table, and the first with generated columns. The rebuild machinery
for both is already proven — against synthetic models, not against a real one:

- `tests/test_projection_targets.py:15-51` declares `Shelf`/`Entry` with a
  projection→projection FK, and `:140-155` covers the twin rewiring;
- `tests/test_projection_rebuild.py:916-936` swaps them, removing the parent
  while a child still references it;
- `tests/test_projection_targets.py:179-186` and
  `tests/test_projection_rebuild.py:665-675` cover a generated column on the
  twin.

So the design does not rest on an unproven premise. What #679 adds is the first
real table on that path, and four sentences worth pinning:

The temp twin gets **no** foreign key. `CREATE TEMP TABLE ... (LIKE ...
INCLUDING ALL)` copies the primary key and the not-null constraints and leaves
`contype='f'` behind, so the replay into shadow is never validated against live
rows.

The swap survives because Django writes every foreign key `DEFERRABLE INITIALLY
DEFERRED` and emits **no `ON DELETE` clause at all** — `on_delete=RESTRICT` is a
Python collector rule. A real `ON DELETE RESTRICT` in DDL is checked
immediately even on a deferred constraint, so the absence of the clause is the
load-bearing fact. Table order is *not*: the swap commits with either table
removed first. The test asserts the deferral, not the order.

The generated columns are carried onto the twin by the same `LIKE ... INCLUDING
ALL` (`attgenerated = 's'` survives), and `insertable_columns` leaves them out
of both inserts. The row-wise `IS DISTINCT FROM` diff compares them like any
other column.

The `temporal_value` domain that `0017_temporal_value_domain` creates is a
schema-level type over `varchar(64)`; the temp table names it like any other.

### The library a Playthrough belongs to

The projector writes `library_id` from the event and `player_game_id` from the
payload, and nothing checks that the two agree. Today nothing can disagree:
`CreatePlaythrough` resolves through the library-scoped `tracked_game`, and
`TrackGame` mints both identities itself. But the invariant is load-bearing for
the swap, and it is written down nowhere.

A Playthrough in library B naming a PlayerGame in library A makes library A
**permanently un-rebuildable**: the replay and the diff both pass, and
`swap_in`'s commit fails with an `IntegrityError` that `rebuild_projections`
does not catch. The same error, reached from an append rather than a rebuild,
arrives as a raw 500 — a deferred constraint fires inside
`transaction.atomic().__exit__`, past every place `answered()` could give it a
sentence.

So this issue states the invariant twice. `ProjectionModel`'s docstring gains
the sentence that a projection row's own `library` and the `library` of every
projection row it names are one library. And the pair
`(Playthrough.player_game)` goes into `_cross_library_violations` in
`games/management/commands/audit_library_ownership.py`, which is a hand-written
list with no completeness test — a pair left out of it is unaudited forever and
silently. The issue's own acceptance block names user isolation, and this is
what discharges it.

A composite `(library_id, player_game_id)` foreign key against a new
`UniqueConstraint(("library", "id"))` on `PlayerGame` would make the database
refuse the row at append time, which is strictly better. It is refused here for
size: it adds a constraint and an index to the shipped `PlayerGame` table and
would have to be reasoned about against the twin machinery. If the audit ever
reports a violation, that is the fix, and this paragraph is the record of why it
was not the first one.

## The kind

```
PlaythroughKind: ORDINARY = "ordinary", IMPORTED_HISTORY = "imported_history"
```

`IMPORTED_HISTORY` is the kind the bucket named "Imported history — needs
sorting" will carry. This issue defines the word and creates no bucket. The wave
that assigns Sessions is the wave that needs one.

The kind is carried by the creation event, not left to the column default. A
payload schema is declared `extra="forbid"` and `strict=True`, and nothing
upcasts a recorded payload, so a key added at #684 or #700 would make every
creation event already recorded unreadable on replay.

## The event

`games/events/playthrough.py`:

```
type PlaythroughKindValue = Literal["ordinary", "imported_history"]

@with_config(STRICT_SCHEMA)
class PlaythroughCreatedPayload(TypedDict):
    player_game: ReferenceId
    kind: PlaythroughKindValue

PLAYTHROUGH_CREATED = EventSpec(
    "library.playthrough.created",
    aggregate_type="playthrough",
    payload=PlaythroughCreatedPayload,
)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_CREATED)
```

Both the decorator and the `register` call are load-bearing.
`EventTypeRegistry.register` raises `SchemaNotConfigured` without the first, and
`tests/test_event_wiring.py::test_every_spec_a_default_projector_claims_is_a_registered_event_type`
fails without the second.

`player_game` is a `ReferenceId` — canonical UUIDv7 text — and not a
`Reference`, for two reasons that are both about mechanics.

`TrackGame` structurally cannot capture one. `capture_reference` takes a model
instance, and when `build` composes the second event the `PlayerGame` row does
not exist: the projector creates it during the append, after `build` has
returned.

And a `Reference` would break rebuild-as-repair. `replay()` calls
`require_resolvable_references` before it writes the first row, against the
**live** tables. Registering a `ReferenceKind` for `PlayerGame` would make a
rebuild of a library whose live `games_playergame` has lost rows refuse to
run — which is exactly the drift a rebuild exists to repair.

(The tempting argument — "a same-stream aggregate has nothing to reconcile" — is
false. `unresolved_among` checks the row, not the stream, and would check this
one like any other.)

A `Literal` rather than `PlaythroughKind`, for the reason `StatusValue` gives:
strict validation refuses a plain string for an enum field, and a recorded
payload is read back as one. A test pins the `Literal` arguments to
`PlaythroughKind.values`.

The module also holds `playthrough_created(player_game_id)`, the one builder
both commands call. It sits beside the spec rather than in
`games/commands/playthrough.py`, because that module and
`games/commands/playergame.py` would otherwise import each other.

## The commands

`CommandName.PLAYTHROUGH_CREATE = "library.playthrough.create"`.

`CreatePlaythrough(game_id)` lives in `games/commands/playthrough.py`. It
resolves the tracked game and returns one creation event with a freshly minted
`uuid7` and `kind="ordinary"`. It takes no name: #1010 owns naming, and a blank
name is what the display number is for.

Two refusals, each with the sentence a person is shown:

- the library does not track the game — *"That game is not in your library."*
- the tracked game's `removed_at` is set — *"That game was removed from your
  library. Restore it before adding a playthrough."*

`TrackGame.build` returns two events where it returned one. It mints the
PlayerGame identity, returns `library.playergame.created` under it, then
`library.playthrough.created` naming that identity. The library's first act on a
game states both facts, which is what "mandatory" means. `TrackGame` is not the
first multi-event command — `RecordPlayerGameFacts` already emits two.

Nothing about correlation needs writing. `dispatch` resolves one
`correlation_id` per dispatch, before the build runs, so every event a build
returns already shares it.

Idempotency needs nothing either, checked rather than assumed. The record stores
a sequence *range*, and the fingerprint is over the command name and its
dataclass fields — `TrackGame.game_id` — so a second event does not move it. A
repeat answers `ReplayedAppend` from the record: nothing is re-appended and no
projector runs.

`_tracked_game` in `games/commands/playergame.py` becomes `tracked_game`, so the
new module can call it. #909 replaces it with the shared library-scoped
resolver; the comment on it names that issue. `TrackGame._visible_game` is
unchanged — #909 collects it with the other two.

### Two behaviours left alone, and what that leaves broken

`TrackGame` does not supply a missing default for a game the library already
tracks: `build` returns `Unchanged` whenever a `PlayerGame` row exists. #684
owns that conversion. In production the #676 backfill has **not yet run** — the
deployment stands at `0022_external_references` — so after this ships, the set
of tracked games with no Playthrough is not a leftover, it is the whole library.

Two consequences this issue states rather than discovers later. Until #684,
every reader tolerates a `PlayerGame` with zero Playthroughs; the display-number
module returns an empty set for such a game and that is correct, not a bug. And
nothing re-establishes the invariant after #684 either — there is no
`make audit-uuid-identity`-style check that a live `PlayerGame` has at least one
Playthrough. That audit is named as #684's exit criterion rather than built
here, because before #684 it would fail on every row.

`RemovePlayerGame` does not touch the playthroughs of the game it removes.
#1011 owns removal and restoration for this family, including the question of
what a removed Playthrough means for a Session that names it.

## The projector

`Playthroughs` in `games/projectors/playthrough.py`, `family_name =
ProjectorFamily.CURRENT_STATE`, one handler:

```
self.project(
    Playthrough,
    event.aggregate_id,
    library_id=event.library_id,
    player_game_id=uuid.UUID(event.payload["player_game"]),
    kind=event.payload["kind"],
    created_at=event.recorded_at,
)
```

Every value comes off the event and none off a command's context, so a replay
writes the row it wrote before. The write is keyed on `aggregate_id`, so a
second run writes no second row.

Naming only those four columns is deliberate, for the reason `PlayerGames._created`
omits `status`: a rebuild inserts the Python model defaults, the amendment
events that follow set the real values, and naming a column in `update_fields`
would let a re-applied creation event overwrite a later amendment.

One caveat #681 inherits. `_required_columns` exempts any field with a default,
and `TemporalValueField.__init__` does `kwargs.setdefault("default", None)` — so
`started` and `completed` are exempt, and `project()` accepts a call that omits
them without complaint. Omitting them is right here, but the guard gives no
protection over those two columns. #681's endpoint handlers use `amend`, never
`project`, and must never be added to this handler's column list.

`games/projectors/__init__.py` imports the module, which is what registers it.

The two events of one `TrackGame` are separate events, applied event-major in
sequence order after the head advance, so the PlayerGame row exists before the
Playthrough handler names it. Registration order inside `CURRENT_STATE` does not
decide this — and the deferred foreign key means even the reverse order would
commit.

## The display number

`games/reads/playthrough_numbering.py` holds the rule and nothing else.

```
with_display_number(queryset)
    .filter(removed_at__isnull=True, kind=PlaythroughKind.ORDINARY)
    .annotate(display_number=Window(
        RowNumber(),
        partition_by="player_game",
        order_by=(
            F("started_lower").asc(nulls_last=True),
            F("completed_lower").asc(nulls_last=True),
            "created_at",
            "id",
        ),
    ))

display_name(playthrough)  ->  the name, or f"Playthrough {display_number}"
```

`id` is the fourth key and it is what makes the order total. Without it the
number is not stable across a rebuild, and the failure is not hypothetical:
until #681 ships, *every* Playthrough has two null bounds, and `recorded_at` is
one value for a whole append and a caller argument besides — `#676`'s backfill
already passes a fixed one for a whole run, and the wave doc says #684 copies
that pattern. So a converted game's playthroughs are total peers on the first
three keys. `RowNumber()` over peers follows the plan's input order, which
follows physical row order, which a swap changes. The primary key is unique and
UUIDv7, so it breaks the tie in creation order and the stability property holds
because the key is unique — not because nothing has collided yet.

`WHERE` runs before a window function, so the filter is what keeps a removed row
and a system row from shifting the number a player learned.

`display_name` is total. A row with a name returns it. A blank-named row with a
`display_number` returns `Playthrough N`. A blank-named row *without* one — a
removed or system row, filtered out before the annotation — is a caller pairing
a row with a queryset it is not in, so the function refuses with a stated
sentence rather than raising `AttributeError` from the annotation's absence.
#700's bucket carries a real name and never reaches that path.

The number is derived at read time and stored nowhere. The order depends on
sibling rows, so a stored column would make every endpoint change, every
removal and every creation rewrite every sibling of one PlayerGame, and the
rebuild would have to reproduce that order of writes exactly.

No screen reads this yet; #1012 is the first consumer. Until then the rule is
proven by its own tests. It ships with the columns it orders, which is why #680
was absorbed.

## Documentation

`docs/event-benchmarks.md` is restated for the new figures, and its line 209 —
"for when a second projector **family** makes the budget tight again" — is
corrected, because after this issue the second projector is in the same family.

`CLAUDE.md` gains a `Playthrough` bullet beside the `PlayerGame` one, which
opens "the first projection" and needs to stop being the only one. The new
bullet says what PlayerGame's says about the mark, because the same file counts
"the nine removable models" and a reader will otherwise ask why a tenth
`removed_at` is missing from `REMOVABLE_MODELS`.

`docs/vocabulary.md` records what *family* now means, since the registry change
changes it.

The two docstrings named in the registry section are amended in the same commit.

Nothing tests any of this, so leaving it out of the spec means it does not
happen.

## Verification

1. `make check` is green, including the four pinned inventories above.
2. The model passes `check_projection_models`: no auto key, no database
   default, no clock default, no minted default.
3. Two projectors share `CURRENT_STATE` and both run; one event type claimed
   twice inside one family is still refused; family run order is unchanged.
4. `TrackGame` appends two events at sequences *N* and *N+1* under one
   `correlation_id`, and leaves one `PlayerGame` and one ordinary
   `Playthrough`.
5. A repeat under the same idempotency key answers from the record — nothing is
   re-appended, no projector runs, and the library still holds one Playthrough.
6. `CreatePlaythrough` refuses a game the library does not track, and refuses
   one it removed, each with its stated sentence.
7. An empty-database replay reproduces both tables.
8. `rebuild_projections(mode=REBUILD)` over a library holding playthroughs
   swaps with no constraint error and an empty diff, with either table removed
   first. This is the foreign key between two projection tables and the
   generated columns, proven rather than argued.
9. The display number follows the stated order, puts an unknown bound last,
   omits a removed row and a system row, and is unchanged across a rebuild —
   including for a partition whose rows share one `created_at` and carry no
   bounds, which is the case the `id` key exists for. The removed-row and
   named-row cases are set by a direct `UPDATE` in the test, because the
   commands that state them are #1011 and #1010; the projector stays the only
   writer in application code.
10. `audit_library_ownership` reports a cross-library Playthrough, and reports
    none for an ordinary library.
11. `purge_user_library` still empties a library that holds playthroughs. The
    new `RESTRICT` edge is on the one path that destroys rows, and it also
    stops `PlayerGame` being fast-deletable.
12. `make bench` is rerun and `docs/event-benchmarks.md` is restated, because
    `TrackGame` is two events now and its per-event figures move.

## Rollback

The migration adds one table and touches no existing row, so it reverses by
`migrate games 0042_external_reference_choices`. The registry change is code.

Production stands at `0022_external_references`. This migration therefore ships
alongside twenty others, including the #676 baseline backfill
(`0033_playergame_baseline_backfill`), and the whole run is rehearsed through
`make verify-dump` against a restored copy before it deploys. Reversing to
`0042` is the in-deployment step; a rollback past the backfill is a different
operation this issue does not describe.

The events are the record: a library that ran the new `TrackGame` holds creation
events for both aggregates, and reversing the migration leaves those events with
no table to project into. The reversal is therefore code-and-schema together,
not a schema step on its own, and the projection rebuild #667 provides is what
restores the rows afterwards.

## Out of scope

`library.playthrough.started` and `library.playthrough.completed` (#681). The
name and the note events (#1010). Removal and restoration (#1011). The shared
reference resolver (#909). The bucket itself and the Session assignment (#700,
#701). The conversion of legacy `PlayEvent` rows and the missing defaults
(#684). Every screen, filter, statistic and API surface (#687, #1012 through
#1015). Renaming `PlayerGame`'s `track`/`created`/`tracked_at` split onto one
verb. The composite library-scoped foreign key.

One hazard #681 inherits: `tests/test_event_vocabulary.py:266` registers
`"library.playthrough.started"` as a test double and asserts it never reaches
`DEFAULT_EVENT_TYPES`; it appears again at `tests/test_event_append.py:69`. #681
registers that exact name for real and fails on day one. #679 does not collide —
the doubles register into private registries and its own name is different — so
the rename of the doubles to `library.probe.*` is #681's first commit.
