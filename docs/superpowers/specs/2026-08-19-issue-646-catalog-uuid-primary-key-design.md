# ID-11: the catalog's UUID becomes its primary key — design

Slice ID-11 (#646) of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md),
the first slice of Wave E. The wave plan's "What *swap every read/write path*
actually means" checklist carries the reusable Wave C mechanics; this record
keeps what neither the code nor that checklist can — what the database actually
does when a `unique` column is promoted to a primary key underneath four
dependent foreign keys, and what the promotion drags in that the wave plan had
assigned elsewhere.

Delivered: `Game.uuid` and `Platform.uuid` become `Game.id` / `Platform.id`, the
real primary keys. The legacy integer identities are gone. In the same migration,
`games_purchase_games.game_id` converts to `uuid_v7` — the deferral ID-09 handed
here.

Everything below marked *probed* was run against a real PostgreSQL 18 database
seeded from the committed sample fixture (851 games, 25 platforms, 795 purchases,
4505 through rows), not inferred from reading Django.

## The blocker, and why `sqlmigrate` hides it

ID-10 left one question open: `primary_key=True` subsumes `unique=True`, so does
Django's schema editor *attempt* to drop `games_game_uuid_…_uniq` — which cannot
be dropped, because the four foreign keys referencing `Game.uuid` depend on that
specific index — and fail the migration outright?

**It does.** `BaseDatabaseSchemaEditor._alter_field` drops the old unique
constraint when `_field_became_primary_key(old_field, new_field)`, and the
migration dies:

```
django.db.utils.InternalError: cannot drop constraint games_game_uuid_06153fb1_uniq
  on table games_game because other objects depend on it
DETAIL:  constraint games_playevent_game_id_… depends on index games_game_uuid_…_uniq
         constraint games_gamestatuschange_game_id_… depends on index …
         constraint games_session_game_id_… depends on index …
         constraint games_purchase_related_game_id_… depends on index …
```

**`sqlmigrate` reports this operation clean.** It resolves constraint names by
introspecting the live database, which for an unapplied migration is still in the
*pre*-migration state, so the lookup that finds the doomed constraint at
`migrate` time finds nothing at `sqlmigrate` time. The emitted SQL for the whole
migration looks correct and applies to nothing. Any verification of this slice
that stops at `sqlmigrate` is worthless; only a real `migrate` against a real
database proves the shape.

## The fix: detach the foreign keys, promote, reattach

`CASCADE` is not a way out — it would take the four FK constraints with it,
producing exactly the state-versus-database divergence `audit_uuid_identity`
exists to catch. Dropping and recreating them by hand is the obvious remedy, but
it means hand-written DDL with hand-picked constraint names in a schema whose
names Django otherwise owns.

**Chosen — toggle `db_constraint` across the promotion.** `AlterField` each of
the six *field-backed* referencing foreign keys (four at `Game`, two at
`Platform`) to `db_constraint=False` before the promotion and back afterwards
(with `to_field` deleted). Django drops each constraint on the way in, the
redundant unique index then drops cleanly, and Django recreates each constraint
against the new primary key on the way out, naming everything itself. Public
operations end to end: no `SeparateDatabaseAndState`, no raw DDL for the
promotion, nothing for a future migration to trip over. The seventh reference,
`games_purchase_games.game_id`, has no Django field to alter and is handled by
the `RunPython` steps below.

Probed: applies clean, and afterwards all seven foreign keys reference
`games_game(id)` / `games_platform(id)`, `games_game_uuid_…_uniq` is gone,
`makemigrations --check` reports no drift, and all 4505 through rows survive with
their links intact.

**Rejected — `SeparateDatabaseAndState` with raw DDL.** Full control, but it
takes the primary-key promotion out of Django's hands for no benefit the
`db_constraint` toggle does not already give, and hand-named constraints would
diverge from what ID-12/13/14 regenerate.

## The order is forced

Each of these was probed by running this slice's own sequence, and each failed
the naive way first:

1. **The through table converts before anything else.** `DROP COLUMN
   games_game.id` fails while `games_purchase_games.game_id` references it
   (`DependentObjectsStillExist`).
2. **The backfill needs `SET CONSTRAINTS ALL IMMEDIATE` before the `ALTER
   TABLE`s.** Every foreign key here is `DEFERRABLE INITIALLY DEFERRED`, so the
   `UPDATE` leaves a pending trigger event and the next `ALTER TABLE` fails with
   `cannot ALTER TABLE … because it has pending trigger events`. Same guard, same
   reason, as migrations `0004` and `0009`–`0012`.
3. **The through table's `DROP COLUMN game_id` silently cascades away both the
   `(purchase_id, game_id)` unique index and the `game_id` index.** Afterwards
   only the primary key and the `purchase_id` index remain — while Django's
   migration *state* still lists the `unique_together`, so `check-migrations`
   stays quiet and the suite stays green with the guarantee gone. This is wave
   checklist item 6, applied to an auto-created through rather than a model
   `Meta`.

So the migration is, in order: convert the through table (raw, `RunPython`, with
reconciliation) → detach six foreign keys → promote `Game` → promote `Platform` →
reattach six foreign keys → restore the through table's constraint and indexes.

Each promotion is `RemoveField(id)`, `RenameField(uuid → id)`,
`AlterField(id, UUIDv7Field(primary_key=True))`. Django renders the intermediate
pk-less state without complaint; no `SeparateDatabaseAndState` is needed to get
through it.

The restore step goes through `schema_editor` (`_create_fk_sql`,
`_create_index_sql`, `alter_unique_together`) rather than literal SQL, so the
recreated names match Django's convention — probed, and the unique index comes
back under the byte-identical name it had before. ID-13 performs the mirror
conversion on `purchase_id` and will look for exactly those names.

## Irreversible, explicitly

`DROP COLUMN games_game.id` destroys the only integer→UUID mapping. Nothing
remains to restore the original integers from, so a reverse could at best
*renumber* rows — inventing values that look like the originals and are not.

The migration therefore declares an explicit raising reverse rather than a
plausible one. Because reverse operations run last-to-first, the raise belongs on
the final `RunPython` so `migrate games 0012` fails immediately, having changed
nothing, with a message naming the restore-from-backup requirement.

This breaks the reversibility chain: no Wave B or Wave C migration below `0013`
can be reversed without first restoring a dump. That is a real cost, accepted
because the alternative is a reverse that silently fabricates identities.
Reversing also requires reverting the regenerated fixture blob; migration and
fixture are a single unit, as in every prior slice.

## The larger half: everything keyed to the catalog ceasing to be integers

### URLs — scope this slice takes from ID-15

Not anticipated by the wave plan, and not optional. Every catalog route is
declared `<int:…>`:

| Route | |
| --- | --- |
| `game/<int:game_id>/edit`, `/view`, `/delete` | 3 |
| `platform/<int:platform_id>/edit`, `/delete` | 2 |
| `playevent/add/for-game/<int:game_id>` | 1 |
| `purchase/add/for-game/<int:game_id>` | 1 |
| `session/add/for-game/<int:game_id>` | 1 |

The moment the pk is a UUID, `reverse()` on any of these raises
`NoReverseMatch` and every existing URL 404s. They convert to `<uuidv7:…>` here.
The converter is already registered (`timetracker/urls.py`, from ID-01) and has
had no route using it until now.

**This is a converter swap only.** The slug prefix, and the question of which
entities deserve a slug-plus-UUID canonical URL at all, stay ID-15's (#647).

**Old integer URLs 404; no alias is possible.** Serving a redirect would need the
integer→UUID map, which this migration destroys. Preserving it would mean
carrying a `legacy_id` column on two tables through every remaining wave, plus an
audit-inventory exception for columns that are integer on purpose forever, to
serve redirects for a single-deployment single-user application whose bookmark
holder can regenerate links. Rejected. This forecloses the choice #648's title
("Remove integer routes **without permanent aliases**") presumes; see
*Amendments* below.

### Filter criterion values — `MultiCriterion` stops meaning "integer"

`common/criteria.py`'s `MultiCriterion` is *the* set criterion for every
foreign-key and many-to-many facet, and it hard-codes `value: list[int]` with
`_coerce_int`. Promoting the catalog makes the game and platform facets send
UUIDs, which `_coerce_int` rejects — and a rejected filter is caught by the view
boundary, logged, and turned into an "Ignored invalid filter" toast over an
*unfiltered* page. Every catalog facet would degrade silently rather than fail
loudly. Four of the five `MultiCriterion` declarations are affected; `device`
stays integer until ID-14.

**Chosen — a `UUIDMultiCriterion` sibling** with a `_coerce_uuid7` hook built on
the existing strict RFC 9562 v7 parser, onto which the four catalog declarations
move. Each declaration then states its real value type, and ID-14 deletes the
integer variant rather than re-widening a shared one.

`PurchaseFilter.games` moves to it as well. It is currently a `ChoiceCriterion`
whose values are id-bearing by exception, made 500-safe by a hand-rolled `int()`
coercion inside `_games_to_q`; that coercion is deleted rather than retyped, and
the criterion class carries the guarantee like every other id-bearing field.
Both classes derive from `_SetCriterion`, so the M2M modifier handling
(`INCLUDES_ALL` / `INCLUDES_ONLY` routing through the filter-level Q builder) is
unchanged — that equivalence is a verification item, not an assumption.

**Rejected — resolve the coercer from the target's primary key at parse time.**
Architecturally the strongest answer: the criterion would coerce to whatever the
target pk actually is, ID-12/13/14 would need no criterion changes at all, and a
future pk type change would need none either. It requires threading field context
into `_SetCriterion.from_json`, a context-free classmethod called generically by
`OperatorFilter.from_json` over dataclass fields. Not worth restructuring the
parse layer for a transition with three slices left.

**Rejected — widen `_coerce_int` to accept either.** It stops rejecting a
wrong-typed id for the field it is on, which is the entire reason the hook exists.

The TypeScript side needs nothing: `CriterionPayload` is
`Record<string, unknown>`, the serializer never inspects values, and the widget
layer carries no numeric-id assumption (checked: `search-select.ts`'s only
`parseInt` is the prefetch count).

### Search-endpoint option schemas

One `GameOption(Schema)` with `value: int` is the declared response of
`/api/games/search`, `/api/platforms/search` **and** `/api/devices/search`. A
`UUID` against it raises a pydantic `ValidationError`, so the promotion 500s two
of those three endpoints.

**Chosen — split per entity:** `GameOption.value: UUID`,
`PlatformOption.value: UUID`, `DeviceOption.value: int`. This removes the
mixed-type window the wave plan expected to tolerate, rather than encoding it as
a union that describes no endpoint precisely; ID-14 becomes a one-line change to
`DeviceOption`. It also ends the standing oddity of a schema named `GameOption`
typing the device and platform endpoints.

`SearchSelectOption["value"]` is already `str | int` and needs `UUID` added.

### The remaining production sites

- `OuterRef("uuid")` → `OuterRef("pk")` in `games/views/game.py` (the games
  list's unconditional `filtered_playtime` annotation) and in
  `/api/platforms/search`'s two recency subqueries. Wave checklist item 0.
- `games/signals.py`'s `Game.objects.filter(uuid=…)` → `filter(pk=…)`.
- `to_field="uuid"` deleted from all six catalog foreign keys — mandatory, since
  it becomes `fields.E312` the moment the field is renamed. The two `Device`
  ones stay until ID-14.
- Three of the four `seed_related_initial` call sites disappear entirely; the
  fourth keeps only `"device"`. The helper itself dies with ID-14.
- `audit_library_ownership`'s `platform__id` / `related_game__id` projections
  keep resolving and now yield UUIDs, while its device projections still yield
  integers. Its comment claims the report never mixes two id kinds; the comment
  is corrected, the queries are not changed. Mixing is the honest state of the
  world for the next three slices.
- `games/sorting.py`'s `F("pk").asc()` tiebreak needs no change. It is
  model-generic, and a UUIDv7 pk preserves the creation ordering the integer
  encoded.

## Fixture and sample tooling

**`load_sample_data`:** `FixtureRelationship.reference_field` flips from
`"uuid"` to `"pk"` for the catalog relations; the device relations keep `"uuid"`.
The platform remap, which resolves a fixture platform to a real shared or
newly-created row, now yields that row's pk. Values must stay `str` — prepared
records are re-serialized with `yaml.safe_dump`, which cannot represent a `UUID`.

**`anonymize_sample`** needs more than a rename, and two of its problems are
silent:

- `_resequence_identity` writes each re-derived identity with
  `bulk_update(rows, ["uuid"])`. Once that field is the primary key, Django
  raises `ValueError: bulk_update() cannot be used with primary key fields`
  (probed). A queryset `.update(id=…)` does write a primary key (probed), and
  works for the non-promoted models too.
- `_remap_referrers` skips a relation whose `field.target_field.name != "uuid"`,
  so after the promotion it would skip every catalog referrer and leave them
  pointing at dead identities.
- `_remap_referrers` also skips `many_to_many` outright. That was harmless while
  `games_purchase_games.game_id` referenced the integer pk. It is not harmless
  now: `_anonymize` rebuilds the through rows *before* `_reassign_uuids` runs, so
  they would carry pre-resequence uuids. **The deferred foreign key never catches
  it** — the command's transaction is deliberately rolled back and never commits,
  so the constraint is never checked, and the corruption reaches the committed
  fixture silently.

**Chosen — one generic identity writer.** Resolve each model's identity field by
name (`id` when promoted, `uuid` when not), always write it through the
queryset-`update` path that works for both, and have `_remap_referrers` compare
against that same resolved name and walk the through table. One code path, no
promoted-versus-unpromoted branch, and it is already the terminal shape once
ID-14 lands — so ID-12, ID-13 and ID-14 need no anonymizer change at all.

**Rejected — branch on promoted versus not.** Smallest diff now, at the price of
carrying a two-armed shape for three more waves while models migrate across it
one group at a time.

**Rejected — resequence at dump time.** Abandons the in-transaction design and
makes a YAML rewriter re-derive the parent/child graph the ORM already knows.

**Fixture regeneration** is a throwaway transform of the committed blob, not a
database round trip: loading the old fixture needs pre-cutover code while the
migration needs post-cutover code. The transform is exact, because ID-10 already
derived every uuid from the anonymized timestamps and this slice changes no
timestamp — only where an identity lives. Per catalog record, `pk` becomes the
uuid and `fields.uuid` is deleted; every `games:` list on a purchase is rewritten
from integers to the corresponding uuids; foreign-key values are already uuids
and do not change.

Note for whoever regenerates from production later: `all_game_ids` is read
`.order_by("pk")`, which after this slice orders by uuid rather than by integer,
so the `random.sample` / `random.choice` draws differ. The RNG is consumed
identically and the output stays byte-deterministic per `--seed`; it simply will
not reproduce the transformed blob. That is expected — a production regeneration
never reproduces the previous blob anyway.

## Inventory and tripwires

Two independent sites pin what this slice converts, and both must move or
`make check` goes red on whichever is missed:

- `games/identity_audit.py` — remove
  `RESIDUAL_INTEGER_RELATIONS[("games_purchase_games", "game_id")]` and both
  `RESIDUAL_INTEGER_PRIMARY_KEYS` catalog entries. The audit asserts set
  *equality*, so a converted column left listed fails exactly as an unowned
  integer column does. Confirmed against the probed database: the audit reports
  precisely these three as stale and nothing else, and it discovers the promoted
  `games_game.id` as an identity column without any change.
- `tests/test_purchase_fk_uuid.py::test_the_purchase_games_through_table_is_still_integer_keyed`
  — **rewritten, not deleted.** It becomes the pin for the remaining half:
  `purchase_id` still integer (ID-13's), `game_id` now `uuid_v7` with a foreign
  key to `games_game(id)`. Deleting it would leave ID-13 with no warning.

## Verification

`make audit-uuid-identity` against a real database, and the full `make check`
including `e2e/`. Focused tests:

- **Forward migration**, from a seeded pre-cutover world: both pks promoted,
  every through row's link preserved, all seven foreign keys repointed, the
  redundant unique index gone.
- **`Game`'s uniqueness guarantees still enforced** — both the
  `unique_together` and the partial platformless-name `UniqueConstraint`, asserted
  by inserting a colliding row via `bulk_create` to bypass `save()`/`clean()`,
  which would otherwise raise in Python before PostgreSQL sees anything (wave
  checklist item 7). A NULL never collides in a unique index, so the colliding
  row needs non-NULL values in every constrained column.
- **The through table's uniqueness enforced**, driven through the through model
  directly — `related.add(obj)` a second time is silently filtered by
  `_get_missing_target_ids` and proves nothing.
- **Per-endpoint option value types**, one test per search endpoint, so the
  device endpoint's integer contract is pinned across the window rather than
  assumed.
- **`UUIDMultiCriterion` coercion**, including that a stale integer value — the
  shape a saved preset or bookmarked filter URL from before this slice carries —
  degrades to the logged "Ignored invalid filter" toast over an unfiltered page
  rather than a 500.
- **A catalog route resolves for a UUID and 404s for an integer.**
- **The anonymizer's through remap**, asserted *inside* the command's
  transaction. A test hooked at `_write_fixture` runs after
  `transaction.set_rollback(True)` and would measure a database where everything
  has already been undone, passing against the bug (wave checklist item 8).

## Amendments this slice owes

Per the repository's practice of keeping `docs/superpowers/specs/` and the issue
tracker in sync, all of these land with the slice:

- **The wave plan** — Wave E's ID-11 paragraph records that Django attempts the
  impossible unique drop (the open question it left), that the `db_constraint`
  toggle is the remedy, that `sqlmigrate` misreports the whole shape, and that
  ID-11 took the catalog URL conversion.
- **#647 (ID-15)** — the catalog routes are already on `<uuidv7:…>`; its scope is
  the slug prefix and the remaining entities, not the converter swap.
- **#648 (ID-16)** — there are no integer catalog routes left to remove and no
  aliases are possible for them. Its remaining scope is whatever ID-15 leaves.

## Follow-up issues to file

- **Remap or invalidate `FilterPreset` values across an identity promotion.** The
  wave plan recorded stale saved-filter content as a deliberate gap for Wave C on
  the grounds that the only real deployment has zero `FilterPreset` rows. Wave E
  is where the values actually flip, so the gap stops being theoretical here.
  This slice ships graceful degradation (a rejected criterion becomes a toast,
  not a 500) and no remap tooling; the issue tracks building one if a deployment
  with real presets appears.

## Handoffs

Each is also a comment on the issue itself.

- **ID-12 (#848)** — `Session`, `PlayEvent`, `GameStatusChange`. Inherits the
  `db_constraint` detach/reattach recipe, and the warning that `sqlmigrate`
  cannot verify it. `Session.game` is the one `NOT NULL` relation left in the
  cutover. No anonymizer or criterion work: the generic identity writer and
  `UUIDMultiCriterion` already cover it.
- **ID-13 (#849)** — `Purchase`. Owns the mirror-image conversion of
  `games_purchase_games.purchase_id`, against the same table, with the same
  unique index cascading away again and the same restore under Django's names.
  The rewritten tripwire test in `tests/test_purchase_fk_uuid.py` is its warning.
- **ID-14 (#850)** — `Device`, `FilterPreset`. Deletes the last two
  `to_field="uuid"` pointers, the last `seed_related_initial` call and then the
  helper itself, `DeviceOption.value: int` → `UUID`, and the integer
  `MultiCriterion` variant. After it, `audit_library_ownership` stops mixing id
  kinds on its own.
