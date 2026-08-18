# ID-06: Rewrite `PlayEvent.game` and `GameStatusChange.game` to UUID — design specification

Status: design for #644 (2026-08-18). Parent phase #600, wave C of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md).

Depends on #640 (`Game.uuid`, merged as `games.0005_catalog_uuid_identity`) and
#641 (`PlayEvent.uuid`/`GameStatusChange.uuid`, merged as
`games.0006_session_playhistory_uuid_identity`).

## Context

Wave B gave eight models a populated, unique, creation-ordered `uuid` column
beside their integer primary key. Nothing references those columns yet. Wave C
repoints the relations, one coupling group per issue; this issue is the first
and deliberately the smallest — two single-`Game` foreign keys, one on an
append-only audit table (`GameStatusChange`) and one on a low-traffic play-log
table (`PlayEvent`). It exists to establish the FK-rewrite pattern that ID-07
(`Game.platform`), ID-08 (`Session.game`, `Session.device`) and ID-09
(`Purchase.games`, `related_game`, `platform`) copy.

The cheap-slice framing held up only partially. The relation itself is small,
but repointing *any* FK at a non-primary-key target reaches four seams that the
wave plan did not name, and all four recur in ID-07–ID-09:

1. **Filter lookups that name the FK column** (`FilterField("game_id")`,
   `relation_to_q(related_lookup="game_id")`) start yielding UUIDs where the
   surrounding code compares integers.
2. **`ModelForm` initial values** come from `model_to_dict`, which reads the FK
   *attname* — now a UUID — and hands it to a widget whose options are integer
   game ids.
3. **The committed sample fixture** serializes FK references as the target's
   `to_field` value. `games/fixtures/sample.yaml.gz` currently writes
   `game: 2` for 203 `PlayEvent` rows and carries no `uuid` field at all, so it
   stops loading the moment the FK points at `Game.uuid` — and
   `tests/test_library_commands.py::test_committed_sample_load_owns_private_rows_and_reuses_shared_platform`
   loads that exact blob, so this is a `make check` failure, not a dev-only
   inconvenience.
4. **`load_sample_data`'s reference validation** cross-checks every FK value
   against the set of fixture *primary keys*, which a UUID reference can never
   be in.

This specification resolves all four.

## Goals

- `PlayEvent.game` and `GameStatusChange.game` resolve through `Game.uuid`,
  with a real database foreign key on a `uuid_v7`-typed column.
- No user-visible behavior change: same pages, same filter semantics, same API
  payloads, same saved-preset compatibility for the `playevents` mode.
- The migration is data-preserving in **both** directions — the integer FK
  values are reconstructable, so this issue does not close the Wave B reversal
  window on its own.
- The committed sample fixture keeps loading, through the same tool
  (`anonymize_sample`) that produces it, with no bespoke one-off rewriter.
- Reconciliation evidence: every child row points at the same `Game` after the
  migration as before it, asserted in-migration and in tests.

## Non-goals

- Any other relation. `Session.game`, `Session.device`, `Game.platform`,
  `Purchase.games`/`related_game`/`platform` stay integer FKs (ID-07–ID-09).
- Dropping `Game.id`, `PlayEvent.id`, `GameStatusChange.id`, or promoting any
  `uuid` column to primary key (Wave E, #646/#848).
- Changing URLs, route converters, or any `<int:...>` path (#647/#648).
- Exposing UUIDs in the REST API, the filter JSON, saved presets, or
  TypeScript. Filter criteria for `game` keep carrying **integer** game ids —
  see "Filter values stay integers".
- Remapping existing `FilterPreset` content (wave plan, Wave C note: the only
  real deployment has zero preset rows). The measures below mean playevent
  presets would not have needed remapping anyway.
- Re-minting fixture UUIDs from anonymized timestamps (see "Follow-ups").

## Decision: `to_field="uuid"`, integer column dropped in this migration

The final model definitions:

```python
# PlayEvent
game = models.ForeignKey(
    Game, to_field="uuid", related_name="playevents", on_delete=models.CASCADE
)

# GameStatusChange
game = models.ForeignKey(
    Game, to_field="uuid", related_name="status_changes", on_delete=models.CASCADE
)
```

Column name stays `game_id`; only its type changes (`integer` → `uuid_v7`).
Keeping the Django-default column name means Wave E's contraction is a pure
`to_field` deletion with no column rename, once `Game.uuid` becomes `Game.id`.

`Game.uuid` is `unique=True NOT NULL`, which is all `to_field` requires.
`UUIDv7Field.db_type` returns the `uuid_v7` domain and no `rel_db_type`
override exists, so the referencing column inherits the domain — the version-7
check applies to the FK column too, for free.

**The old integer column is dropped in the same migration, not left behind.**
The wave plan's Wave E paragraph says Wave E "drops … every now-unused integer
FK column Wave C replaced"; its Wave C paragraph says Wave C drops it. The
contradiction resolves in favor of dropping it here: a retained
`games_playevent.game_id` integer column is `NOT NULL` with no default, so
every insert would have to keep populating it, which means keeping a second
model field pointing at `Game` (`related_name="+"`, nullable, written by
nobody) — carrying a live write-path obligation for two more waves to avoid a
column drop that is trivially reversible. Update the wave plan's Wave E
paragraph accordingly.

Empirically verified before adopting this shape: a Django FK whose target is a
`uuid_v7` domain column round-trips as a real `uuid.UUID` in Python — probed
against the existing `Game.library` → `UserLibrary.id` FK, which is already
exactly this arrangement (`library_id` reads back as
`UUID('01a013a1-…')`, equal to `library.id`). psycopg resolves the domain to
its base uuid loader, so no `str`/`UUID` mismatch appears at the attname.

## Migration shape: six operations per model, reversible in both directions

One file, `games/migrations/0009_playhistory_game_uuid_fk.py`, depending on
`0008_library_config_uuid_identity`. PostgreSQL has no `integer`→`uuid` cast,
so the column is replaced rather than retyped. Per model, in this order (the
ordering is what makes the reverse direction work, so it is load-bearing):

1. `AlterField` `game` → `ForeignKey(Game, null=True, …)`. Forward: allows the
   NOT NULL to be re-established last on the way back. Reverse: re-imposes NOT
   NULL *after* step 3's reverse has refilled the column.
2. `AddField` `game_uuid` → `UUIDv7Field(null=True, default=None,
   db_default=None, editable=False)` — the explicit `None`s suppress
   `UUIDv7Field`'s own defaults so the column is added empty (same trick as
   `0005`/`0006`).
3. `RunPython(fill_uuid_from_integer, fill_integer_from_uuid)`. Forward:
   `UPDATE … SET game_uuid = g.uuid FROM games_game g WHERE g.id = child.game_id`,
   then reconciliation. Reverse: the mirror join through `Game.uuid`. Both
   directions are total because `Game.uuid` is `NOT NULL UNIQUE` and the child
   FK is `NOT NULL`.
4. `RemoveField` `game` (drops the integer column and its constraint; reverse
   re-adds it nullable and empty, which step 3's reverse then fills).
5. `RenameField` `game_uuid` → `game` (column `game_uuid` → `game`).
6. `AlterField` `game` → the final `ForeignKey(Game, to_field="uuid",
   related_name=…, on_delete=CASCADE)`: renames the column to `game_id`, sets
   NOT NULL, and creates the FK constraint and index.

Both models' operation blocks live in one migration, with a single
`RunSQL("SET CONSTRAINTS ALL IMMEDIATE")` after the backfill and before the
schema alterations — the same pending-trigger-events guard `0006` needed, for
the same reason (every FK in this schema is `DEFERRABLE INITIALLY DEFERRED`).

`makemigrations` would emit a single `AlterField` per model that PostgreSQL
cannot execute; the file is hand-written. The drift guard (`make
check-migrations`) compares *final* state only, so the hand-split is invisible
to it — but the implementer must confirm `makemigrations --check --dry-run` is
clean after landing the model change.

**Fallback if step 6 misbehaves.** The risky assumption is that Django's
`_alter_field` will rename a column *and* attach a new FK constraint in one
operation. If it does not, replace steps 5–6 with
`SeparateDatabaseAndState(database_operations=[RunSQL(rename + add constraint +
index)], state_operations=[RenameField, AlterField])`. Decide this by writing
the migration test first and reading the failure, not by guessing.

### Reconciliation

Computed inside step 3, before the FK constraint exists, raising `RuntimeError`
on mismatch in the `require_match` style of `0004`/`0006`, and printing one
evidence line:

- Populated `game_uuid` count equals row count, per model (no NULLs).
- Every `(child.pk, child.game_uuid)` pair matches
  `(child.pk, game.uuid)` for the `game` the row pointed at before — asserted
  as a zero-row anti-join, not a count comparison.
- Distinct referenced-`Game` count is unchanged per model.

```
FK identity rewritten playevent_rows=<n> playevent_games=<n> gamestatuschange_rows=<m> gamestatuschange_games=<m> unmatched=0
```

## Filter values stay integers

Three lookups in `games/filters.py` name the FK column and must change, all
keeping integer criterion values:

- `PlayEventFilter.fields["game"]`:
  `FilterField("game_id", search_url="/api/games/search")` →
  `FilterField("game__id", …)`.
- `GameFilter._extra_q`'s playevent relation:
  `relation_to_q(…, related_model=PlayEvent, related_lookup="game_id")` →
  `related_lookup="game__id"`. `relation_to_q` feeds that lookup into
  `values_list(...)` and compares it against `Game.pk`, so leaving it naming
  the FK column would compare UUIDs against integers.
- `PlayEventFilter._extra_q`'s `game_filter` sub-filter, the reverse direction
  of the same relation: `relation_to_q(…, related_lookup="id",
  parent_field="game_id")` → `parent_field="game__id"`. Missed by the first
  draft of this design and found by writing the failing test:
  `operator does not exist: uuid_v7 = bigint`.

All three now traverse the relation and filter `Game.id`, one join deeper, on
tables of this size an irrelevant cost.

Why not switch the criterion values to UUIDs now: `/api/games/search` (which
supplies the option values for **every** game facet, including the sessions and
purchases modes whose FKs stay integer until ID-08/ID-09) would have to emit
UUIDs, breaking those two modes for two waves. The values flip once, globally,
when the last game relation lands — record it as ID-09's handoff, with #647 as
the natural place for the API-surface change. As a side effect, existing
`playevents`-mode saved presets keep working through this wave.

Everything else in the filter stack is untouched: `QUICK_FACETS`,
`is_quick_editable`, the TS serializer, the criterion classes, and
`filter_url(PlayEventFilter.where(game=[game.id]))` in
`games/views/game.py:704` all keep speaking integer game ids.

## Form initial values

`GameStatusChangeForm` derives its `game` field from the model, so Django sets
`to_field_name="uuid"` on the generated `ModelChoiceField` and its plain
`<select>` renders UUID option values — internally consistent, no change
needed.

`PlayEventForm` declares `game = SingleGameChoiceField(...)` with a
`SearchSelectWidget` whose options come from `/api/games/search` (integer
values) and `_game_options` (`filter(pk__in=values)`). Its `to_field_name` is
`None`, so binding and cleaning stay integer-correct — but a **bound instance**
breaks: `ModelForm` initial comes from `model_to_dict`, which reads
`instance.game_id` (now a `UUID`), and `ModelChoiceField.prepare_value` passes
a non-instance straight through, so the widget would render a UUID the resolver
cannot resolve and the edit page would lose its preselected game.

Fix: feed the *instance* instead of the attname, in `PlayEventForm.__init__`:

```python
if self.instance.pk:
    self.initial["game"] = self.instance.game
```

`ModelChoiceField.prepare_value` turns a model instance into `value.pk`
(`django/forms/models.py:1572`), i.e. the integer the resolver expects; the
`add_playevent` view already seeds `initial["game"]` with an instance
(`games/views/playevent.py:244`), so this is the established shape here.
`ForeignKey.formfield` passing `to_field_name=self.remote_field.field_name`
(`django/db/models/fields/related.py:1209`) is what makes the derived
`GameStatusChangeForm` field self-consistent. This is transitional — it disappears in Wave
E when `Game.pk` *is* the UUID and option values flip. ID-08 needs the same
shim for `SessionForm`'s game and device fields; if a second call site appears
there, promote it to a named helper in `games/forms.py` rather than copying the
two lines a third time.

## Sample fixture and loader

The fixture must carry what the schema now references:

- `games/fixtures/sample.yaml.gz` is regenerated so every `games.game` record
  carries its `uuid` field and every `games.playevent` record's `game` field is
  that UUID. (The fixture contains no `games.gamestatuschange` rows —
  `anonymize_sample` omits the model deliberately.)
- `load_sample_data.FIXTURE_RELATIONSHIPS` currently declares
  `(field, target_model, many, required)` and validates each reference against
  the set of fixture **primary keys**. Extend the tuple with the target's
  reference field (default `pk`), and index fixture records by that field, so
  `games.playevent.game` is checked against the games' `uuid` values. This is
  the shape ID-08/ID-09 reuse for `session.game`, `purchase.games`, and
  `purchase.related_game`.
- `_reject_primary_key_collisions` and the platform remapping are unaffected —
  both key off `pk`.

Confirmed in the installed Django source, not assumed:
`deserialize_fk_value` resolves a fixture FK value as
`model._meta.get_field(field.remote_field.field_name).to_python(field_value)`
(`django/core/serializers/base.py:388`), so an integer where a `uuid` is
expected raises during deserialization; the serializer writes the same
`to_field` value on the way out.

**Regeneration procedure.** A database round trip (load the fixture at `0008`,
migrate, re-dump with `anonymize_sample`) is *not* executable: loading the
integer-referenced fixture needs the pre-cutover code, while running the new
migration needs the post-cutover code, and no single checkout has both. The
fixture is instead transformed directly, once, by a throwaway script that is
not committed:

1. Read the gzip'd YAML; walk `games.game` records ordered by
   `(created_at, pk)` and mint each one's `uuid` with
   `timetracker.uuidv7.uuid7_at(created_at, sequence=…)`, resetting the
   sequence counter per millisecond — the same algorithm the `0005`/`0006`
   backfills use, so the fixture's identities carry the same
   creation-ordering guarantee.
2. Rewrite each `games.playevent` record's `game` to that game's UUID string.
3. Re-emit exactly as `anonymize_sample._write_fixture` does:
   `yaml.safe_dump(sort_keys=True, default_flow_style=False)` then
   `gzip.compress(compresslevel=9, mtime=0)`.

The result is byte-for-byte what `dumpdata` now produces for these models, so
the next real `make anonymize-sample` run against a production copy stays
consistent with it.

Verification of the regenerated blob, recorded in the PR: per-model record
counts match the current fixture (851 game, 2718 session, 795 purchase, 203
playevent, 25 platform, 14 device, 75 exchangerate); no field on any record
differs except the added `game.uuid` and the rewritten `playevent.game`; every
`playevent.game` value resolves to exactly one `game.uuid`; and
`test_committed_sample_load_owns_private_rows_and_reuses_shared_platform`
passes against it.

## Surfaces confirmed unaffected

Checked explicitly, expected to need no edit — if one of these does need
editing, the diff has exceeded its boundary:

- `games/api.py`: `PlayEventIn.game_id: int` is a payload field resolved via
  `Game.objects…get(id=…)`, not a column; `PlayEventOut` exposes `game.name`;
  `/api/games/search` keeps integer option values. `AutoPlayEventIn`
  (`ModelSchema`, `fields=("game", …)`) is referenced by no endpoint and only
  by `tests/test_session_playhistory_identity.py`; its derived `game` field
  stays typed `int` — Ninja derives a relation's type from
  `field.related_model._meta.pk.get_internal_type()`
  (`ninja/orm/fields.py:134`), i.e. `Game`'s untouched integer primary key, not
  from `to_field`. So the schema silently *disagrees* with the column it
  describes. Harmless while nothing uses it; recorded in the test and in
  "Follow-ups".
- `games/signals.py`: `game_status_changed` creates `GameStatusChange` with a
  `Game` instance. The `getattr(instance, "game_id", None)` at
  `games/signals.py:113` is on **`Session`**, so it is ID-08's problem, not
  this issue's — but it is a `Game.objects.filter(pk=game_pk)` and will need to
  become a `uuid` lookup there.
- `games/sorting.py`: `PLAYEVENT_SORTS` sorts by `game__sort_name`; no FK
  column appears in any sort map.
- Views: `games/views/playevent.py` and `games/views/statuschange.py` render
  `event.game.name` / `sc.game.name` and link via `game.id`;
  `games/views/game.py` passes `game_id=game.id` to `_PlayEventRow` and the API.
- `common/import_data.py` resolves `Game` objects, not ids.
- No Django admin registration exists for either model.

One surface *is* affected and was missed by the first draft:
`anonymize_sample._anonymize` keys its per-game date-offset dictionary by
integer `Game.pk` and looks it up with `event.game_id`, which now reads back a
UUID. It needs a parallel UUID-keyed offset map for the playevent loop. ID-08
and ID-09 hit the same lines for sessions and purchases.

## Verification

New `tests/test_playhistory_fk_uuid.py`:

- Migration test with `MigrationExecutor` (mirroring
  `tests/test_library_cutover_migration.py`): at `0008`, create several games
  and child rows across them, migrate to `0009`, assert every child still
  points at the same game (compared by game name), the column type is
  `uuid_v7` (via `information_schema`), and a FK constraint exists.
- Reverse test: migrate back to `0008` and assert every child's integer
  `game_id` is exactly what it was before — the property that keeps Wave B
  reversible through this issue.
- ORM behavior: `playevent.game_id == game.uuid`, `filter(game=game_instance)`,
  `filter(game__id=game.id)`, `game.playevents` / `game.status_changes`
  reverse accessors, and `Game.delete()` cascading both children.
- Database-level integrity: inserting a child row with a UUID no game owns is
  rejected.

Extended existing tests:

- `tests/test_filters.py` / `tests/test_filter_execution.py`: `PlayEventFilter`
  `game` criterion with integer values still selects the right rows; `GameFilter`
  with a `playevent_filter` relation under ANY/NONE/ALL still selects the right
  games.
- `tests/test_forms.py` (or the nearest existing form test module): editing an
  existing `PlayEvent` renders the game combobox preselected with the integer
  id; posting an integer id saves the right game.
- `tests/test_library_commands.py`: the parametrized dangling-reference cases
  for `games.playevent` / `games.gamestatuschange` move from `{"game": 999}` to
  an unreferenced UUID, and a fixture whose child names a UUID no game record
  carries is still rejected.
- `tests/test_session_playhistory_identity.py`: keep the `AutoPlayEventIn`
  assertion honest about the derived `game` type.

Regression surface expected to pass untouched: `tests/test_api.py`,
`tests/test_signals.py`, `tests/test_paths_return_200.py`,
`tests/test_rendered_pages.py`, `tests/test_stats.py`, and the e2e suite.

The gate is the full `make check`, including `e2e/`.

## Rollback

`manage.py migrate games 0008` restores the integer columns with their original
values (step 3's reverse join), so this issue is reversible on its own. It does
*not* stay reversible once ID-07–ID-09 land on top, and reversing it after the
fixture regeneration also requires reverting the fixture blob — call them a
single unit when reverting.

## Follow-ups to file

- **Anonymizer leaks real creation timestamps through UUIDs.** Once `uuid`
  columns are in the dump (true since Wave B, made load-bearing here),
  `anonymize_sample` randomizes every date but emits UUIDs whose embedded
  millisecond is the row's *real* creation time. Fix is to re-mint each `uuid`
  from the anonymized timestamp — which needs `uuid7_at` to accept seeded
  entropy, otherwise the command's documented byte-determinism per `--seed`
  breaks. Out of scope here because the regeneration procedure above never
  touches production data.
- **`AutoPlayEventIn` is dead code that now misdescribes its column.** No
  endpoint references it, and its derived `game` field claims `int` while the
  column holds a UUID (see "Surfaces confirmed unaffected"). Delete it, or wire
  it up with an explicitly typed `game` field.

## Handoffs

- **ID-07/ID-08/ID-09** reuse: the six-operation migration shape, the
  `field__id` filter-lookup rewrite (all three directions: the facet lookup,
  the parent's `related_lookup`, and the child's `parent_field`), the
  form-initial shim, the reference-field-aware `FIXTURE_RELATIONSHIPS`, the
  fixture transform, and the `anonymize_sample` offset-map fix. ID-08
  additionally owns `games/signals.py:113`.
- **ID-10 (#645)** verifies the integer→UUID map across every converted
  relation; this issue ships no management command, only the migration's
  printed line and tests.
- **Wave E (#646/#848)** deletes `to_field="uuid"` from both fields, the
  `PlayEventForm` initial shim, and reverts both filter lookups to the FK
  column once `Game.pk` is the UUID.
