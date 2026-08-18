# ID-07: Rewrite `Game.platform` and `Purchase.platform` to UUID — design specification

Status: design for #845 (2026-08-18). Parent phase #600, wave C of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md).

Depends on #640 (`Platform.uuid`, merged as `games.0005_catalog_uuid_identity`).
Follows #644 / ID-07's predecessor, the
[play-history FK design](2026-08-18-issue-644-playhistory-fk-uuid-design.md),
whose migration shape, filter-lookup rewrite, form shim, fixture transform and
loader changes this issue copies and extends.

## Context

ID-06 repointed two `NOT NULL` foreign keys at `Game.uuid` and, in doing so,
named four seams the wave plan had not: FK-column lookups in `games/filters.py`,
`ModelForm` initial values, the committed sample fixture, and
`load_sample_data`'s reference validation. All four recur here.

Three things make this slice different rather than a mechanical repeat:

1. **The relation is nullable.** `Game.platform` and `Purchase.platform` are
   `null=True, blank=True, default=None, on_delete=SET_NULL`. ID-06's
   six-operation migration exists partly to choreograph a `NOT NULL`
   constraint; that choreography is inert here, and its reconciliation
   (`null_count == 0`) asserts the opposite of this slice's invariant.
2. **Nullability is metadata, and the lookup rewrite breaks it.** Rewriting
   `FilterField("platform_id")` to `platform__id` moves the resolved model
   field from the nullable FK to `Platform.id`, which is `NOT NULL`. The filter
   metadata layer reads `.null` off that terminal field, so the platform facet
   would lose its "(None)" modifier and the nested builder would lose
   `IS_NULL`/`NOT_NULL` — on a relation whose "Unspecified" bucket is a
   documented, first-class, and already-linked-to concept.
3. **`Game`'s uniqueness guarantees are built on the column being replaced.**
   `Game.Meta` (`games/models.py:47-56`) declares
   `unique_together = (("library", "name", "platform", "year_released"),)` and a
   partial `UniqueConstraint(fields=("library", "name", "year_released"),
   condition=Q(platform__isnull=True))`. Dropping the column drops both, in
   PostgreSQL, silently. ID-06's models carry no `Meta` constraints on `game`,
   so its migration shape has no provision for this.

## Scope: slice by target model, not by owning model

**This issue moves every foreign key that points at `Platform`:
`Game.platform` and `Purchase.platform`.**

The wave plan originally assigned `Purchase.platform` to ID-09 (#847), grouping
by owning model. That boundary is wrong for this relation, and splitting it is
what manufactures three otherwise-unnecessary transitional artifacts:

- `load_sample_data`'s platform remap would have to carry **two identities at
  once** (`games.game.platform` naming a `uuid`, `games.purchase.platform`
  naming a `pk`) for a full wave, including two different `reference_field`
  values against the same target model.
- `games/filters.py` would move two of the five platform lookups and leave
  three, so the same facet name would mean different column types in
  `GameFilter` and `PurchaseFilter`.
- `GameForm.platform` would need the initial-value shim while
  `PurchaseForm.platform` — same field name, same widget, same target — must
  not have it. A same-name-opposite-treatment trap in one module.

Both relations are structurally identical (nullable `SET_NULL` to `Platform`),
so moving them together costs a larger diff and no additional design. ID-09
keeps the part that is genuinely its own problem: `Purchase.games` (M2M) and
`Purchase.related_game`.

Consequence to propagate: the wave plan's Wave C table and #847's body both
need amending. See "Propagation".

## Goals

- `Game.platform` and `Purchase.platform` resolve through `Platform.uuid`, with
  a real database foreign key on a `uuid_v7`-typed column.
- No user-visible behavior change, **including the platform facet's "(None)"
  modifier and the stats page's "Unspecified" platform link.**
- The migration is data-preserving in both directions, NULLs included.
- The committed sample fixture keeps loading, and `load_sample_data` keeps
  reusing pre-existing shared platforms rather than duplicating them.
- Reconciliation evidence asserted in-migration and in tests.

## Non-goals

- `Purchase.games`, `Purchase.related_game` (ID-09/#847), `Session.game`,
  `Session.device` (ID-08/#846), `UserLibraryPreferences.default_device`
  (unclaimed; see the wave plan).
- Promoting any `uuid` column to primary key, or dropping any integer `id`
  (Wave E).
- Changing URLs or route converters (#647/#648). `platform/<int:platform_id>/`
  in `games/urls.py` is untouched — that parameter is `Platform.pk`, which
  still exists.
- Flipping filter criterion values or `/api/platforms/search` option values to
  UUIDs. Those flip once, globally, after the last Wave C slice.
- Remapping existing `FilterPreset` content (wave plan; the only real
  deployment has zero preset rows).

## Decision: `to_field="uuid"`, integer column dropped in this migration

```python
# Game
platform = models.ForeignKey(
    "Platform",
    to_field="uuid",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    default=None,
)

# Purchase
platform = models.ForeignKey(
    Platform,
    to_field="uuid",
    on_delete=models.SET_NULL,
    default=None,
    null=True,
    blank=True,
)
```

Column name stays `platform_id`; only its type changes (`bigint` → `uuid_v7`),
so Wave E's contraction is a pure `to_field` deletion with no column rename.
`Platform.uuid` is `UUIDv7Field(unique=True, editable=False)`
(`games/models.py:179`), which is all `to_field` requires, and the referencing
column inherits the `uuid_v7` domain — the version-7 check applies to it for
free.

The integer column is dropped in the same migration, for the reason ID-06
records: a retained column would keep a live write-path obligation for two more
waves.

## Migration shape: five operations per model, not six

One hand-written `games/migrations/0010_platform_fk_uuid.py`, depending on
`0009_playhistory_game_uuid_fk`. Per model, in order:

1. `AddField platform_uuid` → `UUIDv7Field(null=True, default=None,
   db_default=None, editable=False)` — the explicit `None`s suppress
   `UUIDv7Field`'s own defaults so the column is added empty.
2. `RunPython(fill_uuid_from_integer, fill_integer_from_uuid)`, then
   reconciliation.
3. `RemoveField platform`.
4. `RenameField platform_uuid → platform`.
5. `AlterField platform` → the final `ForeignKey(..., to_field="uuid",
   on_delete=SET_NULL, null=True, blank=True, default=None)`: renames the
   column to `platform_id` and creates the FK constraint and index.

**`Game` additionally needs its uniqueness constraints taken down and put back
around that swap**, as the first and last operations of its block:

- before step 3: `AlterUniqueTogether(name="game", unique_together=set())` and
  `RemoveConstraint(model_name="game",
  name="unique_library_platformless_game_name_year")`;
- after step 5: the mirrored `AddConstraint` and
  `AlterUniqueTogether(unique_together={("library", "name", "platform",
  "year_released")})`.

This is not defensive tidiness. `RemoveField` compiles to a bare
`ALTER TABLE … DROP COLUMN`, and PostgreSQL cascades away every index and
constraint involving that column — so both of `Game`'s uniqueness guarantees
would vanish while Django's migration *state* still believes they exist.
`make check-migrations` compares state, so it would report no drift, and **no
test asserts either constraint today**, so the whole suite would stay green
with the platformless-duplicate guard silently gone. CLAUDE.md documents that
guard as a deliberate design decision ("a conditional `UniqueConstraint` keeps
(name, year) unique among platformless games"), which is exactly the kind of
invariant that must not be lost to a column swap.

Ordering also matters for Django itself: `unique_together` names the `platform`
*field*, so it must be empty across the window where that field does not exist
(between `RemoveField` and `RenameField`).

`Purchase` needs none of this — it declares no `Meta.unique_together` and no
`UniqueConstraint` touching `platform` (verified at `games/models.py:239`).

**ID-06's step 1 is deliberately absent.** It relaxed `NOT NULL` so the reverse
direction could re-impose it after the reverse backfill refilled the column.
These columns are already nullable in both the before and after states, so
there is no constraint to choreograph; adding an inert `AlterField` for
copy-paste symmetry with ID-06 would be a no-op operation that implies a
constraint that does not exist. Of the remaining Wave C relations, only
`Session.game` is `NOT NULL` and so needs ID-06's six-op shape; the rest are
nullable and use this five-op shape. `Purchase.games` is neither — an
auto-created M2M through table has no model field whose NOT NULL could be
relaxed, so ID-09 must design its own shape for it.

Both models' blocks live in one migration, with a single
`RunSQL("SET CONSTRAINTS ALL IMMEDIATE")` after the backfill and before the
schema alterations — every FK in this schema is `DEFERRABLE INITIALLY
DEFERRED`, so a row inserted earlier in the same transaction leaves a pending
trigger event that blocks `ALTER TABLE`.

`makemigrations` would emit a single `AlterField` per model that PostgreSQL
cannot execute (no `bigint`→`uuid` cast); the file is hand-written, and the
drift guard compares final state only. Confirm `makemigrations --check
--dry-run` is clean after the model change — with `--noinput`, per the
autodetector-prompt trap.

### Reversibility on a nullable column

Both backfill directions are `UPDATE … FROM` joins:

```sql
UPDATE games_game AS child SET platform_uuid = platform.uuid
FROM games_platform AS platform WHERE platform.id = child.platform_id
```

A row whose `platform_id` is NULL matches no join row and is simply not
touched, so its `platform_uuid` stays NULL. NULL→NULL falls out of the join
shape rather than needing a special case, and the mirror join through
`Platform.uuid` restores integers the same way. This is what keeps the slice
reversible without the NOT NULL dance.

### Reconciliation, adjusted for nullability

ID-06 asserts `null_count == 0` after backfill. Here the invariant is that the
**NULL set is unchanged** — and as a set, not a count, since a count comparison
would pass if one row gained NULL while another lost it. Computed inside the
`RunPython`, before the FK constraint exists, raising `RuntimeError` on
mismatch in the `require_match` style of `0004`/`0006`/`0009`:

- **NULL-set identity**, both directions: zero rows where `platform_id IS NULL
  AND platform_uuid IS NOT NULL`, and zero rows where `platform_id IS NOT NULL
  AND platform_uuid IS NULL`.
- **Non-NULL anti-join**: zero rows where the row joins `games_platform` on the
  old integer and `platform_uuid IS DISTINCT FROM platform.uuid`.
- **Distinct referenced-platform count unchanged** per model.

One evidence line, in the established format:

```
FK identity rewritten game_rows=<n> game_platforms=<n> game_nulls=<n> purchase_rows=<m> purchase_platforms=<m> purchase_nulls=<m> unmatched=0
```

The committed fixture exercises the NULL path in both models: **30 of 851
games** and **7 of 795 purchases** have no platform.

## Nullability metadata: the enabling fix

`common/criteria.py`'s `field_metadata` computes

```python
nullable = bool(getattr(model_field, "null", False))
```

from `_resolve_model_field(model, lookup)`, which returns the lookup's
*terminal* field. That conflates two different questions: "is this column
nullable" and "can this path yield NULL". They coincide only for
single-segment lookups.

| lookup | terminal `.null` | path can yield NULL | today's `nullable` |
| --- | --- | --- | --- |
| `year_released` | True | True | True |
| `platform_id` (FK attname) | True | True | True |
| `platform__id` | False | **True** | False |
| `platform__group` | False | **True** | False |

The third column was verified empirically against the real ORM before adopting
this fix, not reasoned from the docs — a throwaway test created a platformless
game and asserted both `Game.objects.filter(platform__group__isnull=True)` and
`Game.objects.filter(platform__id__isnull=True)` match it, despite
`Platform.group` and `Platform.id` both being `null=False`. The ORM has always
treated a path through a nullable relation as nullable; only the metadata layer
disagrees.

**Fix.** Extract the segment walk in `_resolve_model_field` into one private
generator, and add `_lookup_is_nullable(model, lookup) -> bool` consuming the
same walk: True when any traversed relation hop is nullable, or the terminal
field is. `field_metadata` calls it instead of reading `.null`.

It takes the same `model is None` / unresolvable-lookup guards `field_metadata`
already applies: that function computes `nullable` for aggregate and
handler-mapped fields too, which name no column and today degrade to `False`
through `getattr(..., "null", False)`. `_lookup_is_nullable` must return `False`
in those cases rather than raise, or every aggregate field (`playtime_hours`,
`session_count`, …) breaks.

`_resolve_model_field` keeps its exact signature and return value — it still
resolves `platform__id` to `Platform.id`, truthfully. This is deliberately
*not* the alternative shape where the resolver special-cases a trailing pk
segment and returns the relation instead: that would make the function lie
about what a lookup names, and its other consumers (`_static_choices`,
`is_m2m`, `criterion_kind`) would silently receive a different field than the
lookup spells. One walk, two consumers, no drift, and the five existing
`_resolve_model_field` assertions in `tests/test_filters.py` (`:5138`, `:5142`,
`:5146`, `:5153`, `:5155`) stand unchanged.

**Blast radius, enumerated rather than asserted.** Of every `FilterField`
lookup in `games/filters.py` containing a relation hop (`:152`, `:153`, `:273`,
`:274`, `:278`, `:392`, `:393`, `:551`, `:610`, `:677`, `:682`), exactly one
changes value under the new rule: `platform__group`, False → True, the
deliberate side effect below. `PlayEventFilter`'s `game__id` stays False
(`PlayEvent.game` is `NOT NULL`), every `*__date` lookup has no relation hop,
and the `games` M2M stays False — so `tests/test_filters.py:5101` and
`test_nullable_reads_fk_attname` both keep passing as written. The TypeScript
tests build `FieldMeta` fixtures by hand, so nothing crosses the language
boundary.

### Why this is not optional

The "(None)" modifier is not a cosmetic widget affordance:

- **`tests/test_field_widget.py:106-114` fails without it.**
  `assert "IS_NULL" in str(field_widget(GameFilter, "platform"))`, paired with
  the negative case on `status`. The nullability fix is therefore not a
  judgement call at all: shipping the lookup rewrite without it turns
  `make check` red. This is the regression sentinel.
- `games/views/stats_links.py:75-87` builds
  `GameFilter(platform=MultiCriterion(modifier=Modifier.IS_NULL))` for the
  stats "Unspecified" platform row. That `Q` is composed server-side and never
  consults `field_metadata`, so this link keeps *working* without the fix —
  while the facet it lands on claims the field cannot be null. A silent
  divergence, not a failure, which is why it is not the sentinel.
- `_SetCriterion._not_in_q` (`common/criteria.py:612`) adds its isnull arm
  unconditionally, so exclude-mode would keep matching platformless rows while
  the metadata says NULL is impossible. Metadata contradicting the query layer
  is precisely the kind of divergence a later slice trips over.
- CLAUDE.md documents unset platform as NULL-with-a-render-layer-label, with
  no sentinel row — "Unspecified" is a first-class state of this model.

### Deliberate side effect

`platform_group` (`platform__group`) gains a "(None)" modifier it never had.
Its meaning is **"has no platform"**, not "has a blank group" — the empirical
probe confirmed a platform with `group=""` does not match
`platform__group__isnull=True`, consistent with this project's
empty-string-is-not-NULL convention. This is a correction of a latent gap
(there is currently no way to ask that question from that facet), not a new
feature, and it is asserted in tests so it cannot regress silently.

## Filter lookups: six rewrites, values stay integers

Every lookup naming the FK column, `platform_id` → `platform__id`:

| Location | Kind |
| --- | --- |
| `games/filters.py:148` | `GameFilter.fields["platform"]` |
| `games/filters.py:216` | `GameFilter._extra_q`, `platform_filter` → `parent_field` |
| `games/filters.py:374` | `PurchaseFilter.fields["platform"]` |
| `games/filters.py:440` | `PurchaseFilter._extra_q`, `platform_filter` → `parent_field` |
| `games/filters.py:634` | `PlatformFilter._extra_q`, `game_filter` → `related_lookup` |
| `games/filters.py:644` | `PlatformFilter._extra_q`, `purchase_filter` → `related_lookup` |

Six distinct call sites — `:634` and `:644` are two separate `relation_to_q`
calls inside `PlatformFilter._extra_q`, one per referencing model. ID-06's
lesson was that missing any single one surfaces as `operator does not exist:
uuid_v7 = bigint`, so they are enumerated rather than described.

The declaration comments at `games/filters.py:102` and `:338`
(`# platform_id (int FK)`) become wrong and are corrected to name the criterion
value type, which is what those comments are actually for.

Criterion values stay **integer** `Platform.pk`s, and `/api/platforms/search`
keeps emitting integer option values — the wave-wide rule, since one endpoint
feeds the facets of every mode. No TypeScript change and no filter-tree
contract change: the serializer keys on the field *name* (`platform`), never on
the ORM lookup.

`platform_group` keeps its `platform__group` lookup unchanged; only its
computed nullability changes.

## Forms

ID-06 left a standing instruction: promote the initial-value shim to a named
helper once a second call site appears. This is that moment, with two more
arriving in ID-08.

```python
def seed_related_initial(form: forms.ModelForm, *field_names: str) -> None:
    """Seed a bound form's initial with the related *instance*, not the attname.

    Transitional. ``model_to_dict`` reads a foreign key's attname, which is now
    a UUID for every relation moved in Wave C, while the SearchSelect widgets
    still carry integer option values. ``ModelChoiceField.prepare_value``
    resolves an instance back to its pk, so feeding the instance produces the
    value the widget's options use. Disappears in Wave E.
    """
```

Call sites: `GameForm.__init__` and `PurchaseForm.__init__` with `"platform"`;
`PlayEventForm.__init__` (`games/forms.py:880-887`) migrates its two open-coded
lines onto it.

`PlatformForm` needs nothing — it edits `Platform` itself.

`games/forms.py:185`, `game_option_data`, currently reads `game.platform_id`
into a `data-*` payload that `ts/add_purchase.ts:100-129` feeds to
`platformSelect.setSelected(String(platformId), …)` — matched against integer
option values from `/api/platforms/search`. It becomes
`str(game.platform.id) if game.platform else ""`. The docstring's existing
"Callers must select_related('platform')" requirement now has teeth rather than
being a performance note; both callers already comply
(`games/forms.py:200`, `games/api.py:146`).

## Sample fixture and loader

### The fixture

Regenerated so that:

- every `games.platform` record carries a `uuid` field — currently **none of
  the 25 do**, since Wave B added the column after the last regeneration;
- every `games.game.platform` and `games.purchase.platform` value is that
  `uuid` string instead of an integer pk.

Produced by a **throwaway, uncommitted** transform, per ID-06's recipe (a
database round trip is impossible: loading the old fixture needs pre-cutover
code, the migration needs post-cutover code, and no checkout has both):

1. Walk `games.platform` records ordered by `(created_at, pk)`, minting each
   `uuid` with `timetracker.uuidv7.uuid7_at(created_at, sequence=…)`, resetting
   the sequence counter per millisecond — the same algorithm the `0005`
   backfill uses, so fixture identities carry the same creation-ordering
   guarantee. This matters more here than it did in ID-06: **all 25 platform
   records share the identical `created_at` of `2020-01-01T00:00:00Z`**, so
   every one of the 25 uuids depends on the per-millisecond sequence counter
   for uniqueness. A transform that mints from the timestamp alone produces 25
   identical uuids and a fixture that cannot load.
2. Rewrite each `games.game.platform` and `games.purchase.platform` to that
   platform's UUID string, leaving `null` values as `null`.
3. Re-emit exactly as `anonymize_sample._write_fixture` does:
   `yaml.safe_dump(sort_keys=True, default_flow_style=False)` then
   `gzip.compress(compresslevel=9, mtime=0)`.

Verification recorded in the PR: per-model record counts unchanged (851 game,
2718 session, 795 purchase, 203 playevent, 25 platform, 14 device, 75
exchangerate); no field on any record differs except the added `platform.uuid`
and the two rewritten reference fields; the NULL counts are preserved exactly
(30 games, 7 purchases); every non-NULL reference resolves to exactly one
`platform.uuid`; and
`test_committed_sample_load_owns_private_rows_and_reuses_shared_platform`
passes against it.

### `load_sample_data`

- `FIXTURE_RELATIONSHIPS` gains `reference_field="uuid"` on both
  `games.game.platform` and `games.purchase.platform`. The `FixtureRelationship`
  docstring (`games/management/commands/load_sample_data.py:48-62`) names the
  moved relations explicitly and must be updated with them.
- `_load_platforms` returns `{str(fixture_uuid): str(real_uuid)}` instead of
  `{fixture_pk: real_pk}`, and `_prepare_private_records` rewrites both models'
  `platform` field through it. **The values must be `str`, not `uuid.UUID`**:
  the prepared records are re-serialized with
  `yaml.safe_dump(loadable, sort_keys=False)`
  (`load_sample_data.py:120`) before being handed to `serializers.deserialize`,
  and a `UUID` object raises `yaml.representer.RepresenterError` there. The
  command already stringifies for exactly this reason at `:318`
  (`fields["library"] = str(library.pk)`).
- `_load_platforms` must read the fixture uuid with `fields.get("uuid")` and
  skip mapping a record that has none — **not** `fields["uuid"]`. A platform
  record without a `uuid` is legal input: `_validate_records` indexes reference
  fields with `.get()` (`:218`) and only errors at the *referencing* record, and
  `tests/test_library_commands.py:405-419` defines exactly such a record (pk
  501, no `uuid`, nothing referencing it). A subscript read fails that existing
  test.

**The remap is load-bearing, not bookkeeping.** `_load_platforms` matches each
fixture platform against an existing row by `(library, name, group)` and reuses
it when found, creating one only otherwise — and a created `Platform` mints its
own `uuid` from `UUIDv7Field`'s default rather than adopting the fixture's. So
the real uuid is *never* the fixture's uuid, on either path. Leaving a game's
platform reference untranslated would dangle. All 25 fixture platforms are
shared (`library: None`), which is exactly the deduplication path
`make loadplatforms` primes, so reuse is the normal case rather than the edge
case.

The created `Platform` deliberately does **not** adopt the fixture's uuid:
`_reject_primary_key_collisions` guards pks only, so a second load into a
database that already carries that uuid would violate the unique constraint,
and the reuse path could not honor it anyway. One rule — the remap translates —
holds on both paths.

`_reject_primary_key_collisions` itself is unaffected; it keys off `pk`.

### `anonymize_sample`

**No change.** The generic Wave C checklist says each moved relation needs a
matching UUID-keyed offset map, but that item is specific to *`Game`*
relations: the command's `game_offsets` /`game_offsets_by_uuid` maps
(`games/management/commands/anonymize_sample.py:187-196`) are keyed by game and
looked up through `session.game_id` / `event.game_id`. Nothing in the command
is keyed by platform, and `Purchase` date offsets are drawn independently
(`:236`). Verified by reading the command, not assumed from the checklist.

## Surfaces confirmed unaffected

Checked explicitly; if one of these needs editing, the diff has exceeded its
boundary.

- `games/views/stats_data.py:279-286` annotates `platform_id=F("game__platform__id")`
  — a relation traversal terminating on `Platform.id`, so it still yields an
  integer, and `stats_links.sessions_for_platform(platform_id: int | None)`
  stays integer-typed.
- `games/api.py:275-282`, `/api/platforms/groups`: builds from a `Platform`
  queryset with no FK-column predicate.
- `games/sorting.py`: no sort map names a platform FK column.
- `games/urls.py:44,49`: `platform/<int:platform_id>/` addresses `Platform.pk`,
  which is untouched until Wave E.
- `games/models.py:104` and `:356`: `if self.platform_id is not None` in
  `Game.clean` / `Purchase.clean` — a presence test that reads correctly for a
  UUID attname.
- `games/views/purchase.py:367,642`: pass `game.platform` / `purchase.platform`
  *instances*, already the correct shape.
- `common/import_data.py`: no platform references at all.
- `ts/`: no filter or serializer change (see "Filter lookups").
- No Django admin registration for either model.

## The recency subqueries in `/api/platforms/search`

`games/api.py:231-256` is **not** an unaffected surface, and it is the highest
blast-radius line in this slice: it is the endpoint feeding the platform facet
of two filter modes and the platform combobox of both forms.

Its no-`q` branch orders platforms by recency of use through two correlated
subqueries:

```python
Game.objects.for_library(library).filter(platform=OuterRef("pk"))  # :243
Purchase.objects.for_library(library).filter(platform=OuterRef("pk"))  # :250
```

`filter(platform=…)` **is** the FK column. Once it holds a `uuid_v7`, comparing
it against `OuterRef("pk")` — `games_platform.id`, a `bigint` — raises
`operator does not exist: uuid_v7 = bigint`, the exact ID-06 failure mode. Both
become `OuterRef("uuid")`.

Note that both subqueries move together, because this slice moves both
relations. Under the original ID-07/ID-09 split, one of these two adjacent,
identical lines would have had to change while the other stayed — independent
confirmation that the boundary belongs at the target model.

## Read paths repaired

One surface changes meaning and is repaired:
`games/management/commands/audit_library_ownership.py:169-187` reports
violations via `.values_list("pk", "platform_id")`, which would start printing
a UUID for `Game.platform` while the adjacent `Purchase.platform` line printed
an integer. Both become `platform__id` so the report stays integer-addressed
and internally consistent; the messages are operator-facing text, and a report
whose two lines disagree about what a platform id looks like is worse than
either choice alone.

## Verification

New `tests/test_platform_fk_uuid.py`:

- **Migration test** with `MigrationExecutor` (mirroring
  `tests/test_library_cutover_migration.py`): at `0009`, create several
  platforms, plus games and purchases spread across them **including rows with
  `platform=None` in both models**; migrate to `0010`; assert every row still
  points at the same platform (compared by platform name), every previously-NULL
  row is still NULL, and no previously-non-NULL row became NULL.
- **Reverse test**: migrate back to `0009` and assert every row's integer
  `platform_id` is exactly what it was, NULLs included.
- **Schema**: column type is `uuid_v7` via `information_schema`, and a FK
  constraint exists on both tables.
- **ORM behavior**: `game.platform_id == platform.uuid`,
  `filter(platform=instance)`, `filter(platform__id=<int>)`,
  `filter(platform__isnull=True)`, the reverse accessors, and `Platform.delete()`
  setting both models' columns to NULL (`SET_NULL` through a `to_field` target).
- **Database-level integrity**: inserting a row with a UUID no platform owns is
  rejected.

Extended existing tests:

- `tests/test_filters.py`: `test_nullable_reads_fk_attname` extended (or
  renamed) to assert path nullability — `platform` and `platform_group` nullable
  on `GameFilter`, `platform` nullable on `PurchaseFilter`, alongside the
  existing non-nullable cases (`games` M2M, `status`) so the fix cannot be
  implemented as "everything is nullable". Direct `_lookup_is_nullable` unit
  cases for a plain column, an FK attname, a nullable hop, and a non-nullable
  hop.
- `tests/test_filter_execution.py`: include / exclude / `IS_NULL` on both
  `GameFilter.platform` and `PurchaseFilter.platform` with integer values select
  the right rows, exclude-mode still matching platformless rows; the
  `platform_filter` relation under ANY/NONE/ALL in both directions
  (`GameFilter`→`PlatformFilter` and `PlatformFilter`→`GameFilter`/
  `PurchaseFilter`).
- `tests/test_stats_links.py:170`: **breaks and must be edited.**
  `.filter(timestamp_start__year=YEAR, game__platform_id=platform.id)` compares
  the UUID attname to an integer → `operator does not exist: uuid_v7 = bigint`.
  Becomes `game__platform=platform`. The `sessions_for_platform(None)` parity
  case at `:192` uses `game__platform__isnull=True` and is genuinely unaffected.
- `tests/test_filters.py:5128`: **breaks and must be edited.**
  `assert GameFilter.fields["platform"].lookup == "platform_id"` → `"platform__id"`.
- `tests/test_field_widget.py:106-114`: the nullability sentinel — must stay
  green, and is the test that fails if the lookup rewrite lands without the fix.
- **New constraint tests for `Game`.** Neither `unique_together` nor
  `unique_library_platformless_game_name_year` is asserted anywhere in the
  suite today, which is precisely why the migration could drop them unnoticed.
  Add: after migrating to `0010`, both exist in `pg_constraint`, and both are
  *enforced* — a duplicate `(library, name, platform, year_released)` and a
  duplicate platformless `(library, name, year_released)` each raise
  `IntegrityError`.
- `tests/test_forms.py` (or nearest): a bound `GameForm` and a bound
  `PurchaseForm` render the platform combobox preselected with the **integer**
  id; posting an integer id saves the right platform; an unset platform renders
  empty rather than as a UUID.
- `tests/test_library_commands.py`: **new** parametrized dangling-reference
  cases for `games.game.platform` and `games.purchase.platform`, naming a UUID
  no platform record carries. These are additions, not edits: the existing
  parametrized list (`:299-317`) covers only `session.game`, `playevent.game`,
  `gamestatuschange.game`, `purchase.games` and `purchase.related_game`, and
  `load_sample_data.py:324`'s "references unknown Platform" error has **no test
  coverage at all** today. Also new: the shared-platform reuse case asserting
  the loaded game points at the **reused** platform rather than a duplicate —
  the test that catches a missing or wrong remap, which is the failure this
  slice is most likely to ship.

Regression surface expected to pass untouched: `tests/test_api.py`,
`tests/test_signals.py`, `tests/test_paths_return_200.py`,
`tests/test_rendered_pages.py`, `tests/test_stats.py`, the TS suite, and `e2e/`.

The gate is the full `make check`, including `e2e/`.

## Rollback

`manage.py migrate games 0009` restores the integer columns with their original
values and NULLs. Reversing after the fixture regeneration also requires
reverting the fixture blob — revert them as one unit.

## Propagation

- **Wave plan** (`2026-08-17-uuid-identity-cutover-wave-plan.md`): the Wave C
  table moves `Purchase.platform` from ID-09 to ID-07. ID-07's `blocked-by` set
  is unchanged — it stays `#640` alone, since both relations point at
  `Platform.uuid` and nothing here reads `Purchase.uuid`. The "learned in ID-06"
  checklist gains a
  fifth item covering nullable relations (the five-op migration shape, the
  NULL-set reconciliation invariant, and the nullability-metadata fix — the
  last now done once, for every remaining slice) and a sixth: **check the
  owning model's `Meta.unique_together` and `constraints` for the column being
  dropped**, since PostgreSQL cascades them away and the state-based drift
  guard cannot see it.
- **#847 (ID-09)**: comment recording that `Purchase.platform` moved out, so
  the remaining scope is `Purchase.games` + `Purchase.related_game`.
- **#845**: comment recording the boundary change and the nullability fix.
- **#846 (ID-08)**: comment noting that `Session.device` is nullable and
  therefore uses the five-op shape, and that the nullability-metadata fix is
  already in place, so it needs no per-relation nullability work.

## Follow-ups

None new. ID-06's two follow-ups are already filed as #869 (anonymizer leaks
real creation timestamps through UUIDs) and #870 (`AutoPlayEventIn` is unused
and misdescribes its column); neither is touched here.

## Handoffs

- **ID-08 (#846)** reuses: the five-op nullable migration shape and NULL-set
  reconciliation for `Session.device`, ID-06's six-op shape for the `NOT NULL`
  `Session.game`, `seed_related_initial` for `SessionForm`'s two fields, and
  `games/signals.py:113` (`getattr(instance, "game_id", None)` on `Session`,
  feeding a `Game.objects.filter(pk=game_pk)` that must become a `uuid`
  lookup). It needs no nullability-metadata work.
- **ID-09 (#847)**: `Purchase.games` (M2M) and `Purchase.related_game` only.
  The M2M through-table column is the genuinely new shape; the anonymizer's
  per-game offset map is keyed by game and will need the UUID-keyed variant for
  purchases' game links.
- **ID-10 (#645)** verifies the integer→UUID map across every converted
  relation; this issue ships no management command, only the migration's
  printed evidence line and tests.
- **Wave E (ID-11/#646)** deletes `to_field="uuid"` from both fields, reverts
  the six filter lookups to the FK column, and removes `seed_related_initial`'s
  platform call sites. The nullability fix in `common/criteria.py` **stays** —
  it is correct independently of which identity a lookup spells.
