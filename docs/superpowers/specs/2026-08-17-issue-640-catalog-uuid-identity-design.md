# ID-02: Convert catalog identities to UUIDv7 — design specification

Status: approved design from the #640 design interview (2026-08-17).

Parent phase: #600. Depends on #639 (merged as `games.0002_uuid_v7_domain` plus
`timetracker/uuidv7.py`).

## Context

#639 delivered the identity foundation — the PostgreSQL `uuid_v7` domain, the
`UUIDv7Field`, the `uuidv7` URL converter, and clock-skew observation — and
deliberately converted nothing. `UserLibrary` (`games/models.py:751`,
migration `games/migrations/0003_userlibrary.py`) is the only model using it,
and only because it was born with a UUID primary key and never had an integer
identity to leave behind.

`Game` and `Platform` are the first models that must *migrate* an identity
rather than declare one. They are the catalog root: `Session`, `PlayEvent`,
`GameStatusChange`, and `Purchase` all hang off `Game`, and `Purchase` and
`Game` both reference `Platform`. Converting them first means every later
group (#641 Session/play history, #642 Purchase/ownership, #643 library
configuration) can assume its parents already carry a stable UUID, and #644
can repoint every foreign key in one coordinated operation instead of
interleaving parent conversions with child repointing.

The sequence #640–#648 is confirmed as an expand/contract migration:
#640–#643 *add* a populated UUIDv7 column beside the existing integer primary
key; #644 repoints foreign keys and many-to-many links at those columns; #645
verifies the integer→UUID map; #646 removes the integer identities and
promotes the UUID column to primary key; #647–#648 handle URL fallout.

## Goals

- Give every existing and future `Game` and `Platform` row a stable, unique,
  version-7 UUID stored in the `uuid_v7` domain.
- Make the identity's embedded timestamp reflect when the row was actually
  created, so ordering by UUID reproduces ordering by creation for historical
  rows.
- Land the change as one additive, online-safe, fully reversible migration
  with no application-visible behavior change.
- Produce reconciliation evidence — printed by the migration and asserted by
  tests — that every row was assigned exactly one distinct, well-formed
  identity.
- Establish the exact backfill mechanism that #641, #642, and #643 reuse
  verbatim.

## Non-goals

- Splitting `Game` into `Game`/`Edition`/`Release`. The architectural charter
  describes that as IGDB-alignment work; phase #600 lists "Catalog
  foundation" (#649–#654) as a separate group. #640 converts `Game` and
  `Platform` exactly as they exist today.
- `ExternalReference`, provider keys, or any IGDB integration.
- Repointing `Session.game`, `PlayEvent.game`, `GameStatusChange.game`,
  `Purchase.games`, `Purchase.related_game`, `Purchase.platform`, or
  `Game.platform`. All of these stay integer foreign keys against the integer
  primary key. That is #644.
- Promoting the UUID column to primary key or removing `id`. That is #646.
- Changing URLs. `games/urls.py` keeps `<int:game_id>` and `<int:platform_id>`
  routes; canonical UUID-plus-slug URLs are #647 and integer-route removal is
  #648.
- Exposing the UUID in forms, Django Ninja schemas, filter criteria, saved
  presets, statistics, templates, or TypeScript. The column is invisible to
  the application in this issue.
- Regenerating `games/fixtures/sample.yaml.gz`.
- Any offline cutover, manifest, or operator rehearsal of the kind #630
  required.

## Decision: parallel column, not a primary-key flip

**Confirmed: add a new non-primary-key column named `uuid` to `Game` and
`Platform`. `id` is untouched.**

Flipping `Game.id` to `UUIDv7Field(primary_key=True)` directly is not
expressible as a scoped change:

- PostgreSQL has no cast from `integer` to `uuid`. There is no
  value-preserving in-place type change; a fresh UUID has to be generated and
  written per row, which is a backfill, not a type cast.
- Django's schema editor retypes every column with a foreign key to a changed
  primary key in the same migration. Changing `Game.id`'s type would force
  Django to simultaneously retype `Session.game_id`, `PlayEvent.game_id`,
  `GameStatusChange.game_id`, `Purchase.games` (the M2M link table),
  `Purchase.related_game_id`, `Game.platform_id`, and `Purchase.platform_id`.
  Suppressing that with `db_constraint=False` on seven relationships would
  leave orphaned integer columns pointing at nothing — the half-migrated
  runtime state the #630 design refused to build.
- Doing this properly would mean executing #644, #645, and #646 inside #640,
  which the issue's boundary forbids.

The parallel column is the only shape that keeps #640 independently
reviewable, and the only one with a trivial rollback: nothing references the
new column, so reversing the migration drops two columns and loses no data
that any other row, route, or payload depended on.

The honest cost: `Game` and `Platform` each carry two identities until #646,
and #644/#646 must perform the promotion #640 declines. That cost is smaller
than an irreversible, multi-issue, all-tables-at-once operation with no
intermediate reviewable state.

**Field name: `uuid`.** Not `id` (taken), not `public_id` (nothing renders it
yet, so it is not a public identifier), not `uuid_id` (redundant). `uuid` is
what #646 renames to `id`; using the same name across #640–#643 gives #644
and #646 a uniform target.

## Decision: `Game.platform` is not converted in #640

Confirmed deferred to #644. `Game.platform` is catalog-internal, so it is the
one foreign key that could plausibly be repointed while staying inside
"catalog identities" — but doing so now means `ForeignKey("Platform",
to_field="uuid")`, retyping `games_game.platform_id` and backfilling it from
the integer→UUID map that #645 owns and does not exist yet. It would also
create a mixed regime — one relationship resolving through `to_field="uuid"`
against a non-primary key, six resolving through the integer primary key —
that #644 would have to special-case and #646 would have to unwind again once
`uuid` becomes the primary key and `to_field` becomes redundant.

`Game.platform` stays an integer foreign key to `Platform.id`. `Game.clean()`
and `_validate_related_library` (`games/models.py:28`) are untouched.

## Data model after this issue

`Game` gains exactly one field, and `Platform` gains exactly one field:

```python
uuid = UUIDv7Field(unique=True, editable=False)
```

- Column type `uuid_v7` (the #639 domain, which rejects any UUID whose
  version is not 7).
- `NOT NULL`, `UNIQUE` (global, not library-scoped — this becomes a primary
  key in #646).
- Python default `uuid.uuid7` and database default `uuidv7()`, inherited from
  `UUIDv7Field.__init__`. Both are kept so ORM inserts, raw SQL inserts, and
  future data migrations all produce valid identities.
- `editable=False`, matching `UserLibrary.id`, so the field cannot appear in
  a `ModelForm` and cannot be set from a request.

Nothing else changes. `Game.Meta.unique_together`, the
`unique_library_platformless_game_name_year` constraint, both `Platform`
normalized-uniqueness constraints, `LibraryOwnedQuerySet`, and
`PlatformQuerySet.visible_to` are untouched. `id` remains the primary key and
remains what `pk` resolves to, including the `F("pk").asc()` deterministic
tiebreak in `games/sorting.py:189`.

The application surface is unchanged by construction: `GameForm`/`PlatformForm`
(`games/forms.py:821` and `:844`) enumerate fields explicitly, `GameOut` and
`PlatformOut` (`games/api.py:331` and `:326`) are hand-written `Schema`
classes rather than `ModelSchema`, so they don't derive fields from the model
at all, and `games/filters.py` / `common/criteria.py` register criteria
explicitly rather
than deriving them from model introspection. A new model field therefore
leaks into no form, no OpenAPI schema, no filter, no preset, and no
statistic. Tests assert this rather than assume it.

## Backfill: identity timestamps derive from `created_at`

Both models have a non-null `created_at` (`games/models.py:73` and `:181`,
both `auto_now_add=True`). Confirmed: the backfill derives each UUID's
embedded timestamp from `created_at`, with strict within-millisecond
ordering, rather than letting PostgreSQL's `uuidv7()` default stamp every
historical row with "the moment the migration ran".

This matters concretely: `games/sorting.py:189` appends `F("pk").asc()` as
the final deterministic tiebreak for list ordering, and #646 turns that `pk`
into the UUID. If historical UUIDs were all minted within one millisecond of
each other, that tiebreak would become effectively random for every
pre-cutover row, silently reshuffling paginated list output for rows that tie
on the primary sort key.

- Add `uuid7_at(moment: datetime, *, sequence: int | None = None) -> uuid.UUID`
  to `timetracker/uuidv7.py`. It encodes the Unix-epoch millisecond of
  `moment` into the 48-bit `unix_ts_ms` field, sets the version and variant
  bits per RFC 9562, fills `rand_b` from `secrets`, and — when `sequence` is
  supplied — writes it into the 12-bit `rand_a` field as the monotonic
  counter RFC 9562 method 2 permits. Python 3.14's `uuid.uuid7()` takes no
  timestamp argument, so this helper is required; it lives in
  `timetracker/uuidv7.py`, not in the migration, so #641–#643 reuse one
  audited encoder.
- The migration walks each model ordered by `("created_at", "pk")`, tracking
  the previous millisecond and incrementing `sequence` for rows sharing it.
  This makes the guarantee testable and total: `Game.objects.order_by("uuid")`
  yields exactly `Game.objects.order_by("created_at", "pk")` for every
  backfilled row, up to 4096 rows per millisecond.
- Values are written with `bulk_update(batch_size=1000)` on the historical
  model from `apps.get_model`.

Importing `uuid7_at` from application code into a migration is a deliberate
exception to "migrations must be self-contained", justified because the
helper is a pure byte encoder with no model or settings dependency, because
`0003_userlibrary.py` already imports `timetracker.uuidv7`, and because
#641–#643 need the identical function. A test pins the helper's byte layout
so a future edit that would retroactively change what the migration produced
fails loudly.

## Migration and reconciliation mechanics

One migration file, `games/migrations/0005_catalog_uuid_identity.py`,
depending on `0004_user_library_ownership_cutover`, with operations in this
order:

1. `AddField` `game.uuid` as `UUIDv7Field(null=True, default=None,
   db_default=None, editable=False)`. Explicit `None` overrides the field's
   `setdefault` defaults, already covered by `tests/test_uuidv7.py:103`. A
   nullable add with no default is catalog-only with no table rewrite.
2. `AddField` `platform.uuid`, identically.
3. `RunPython(backfill_catalog_uuids, reverse_code=migrations.RunPython.noop)`
   — the ordered, sequenced backfill, followed by in-migration
   reconciliation that raises `RuntimeError` on any mismatch, in the style of
   `require_match` (defined at `0004_user_library_ownership_cutover.py:267`).
4. `AlterField` `game.uuid` to the final `UUIDv7Field(unique=True,
   editable=False)` — sets `NOT NULL`, installs the `uuidv7()` database
   default, and builds the unique index.
5. `AlterField` `platform.uuid`, identically.

`makemigrations` generates a single `AddField` per model with the final
definition; the file is hand-split into the five operations above.
`make check-migrations` compares final model state to final migration state,
so splitting is invisible to the drift guard.

Reconciliation, computed inside step 3 before the unique constraint exists so
failures report a count rather than an opaque index violation, printed once
in the style of the `0004` cutover line:

- Row count equals populated-`uuid` count, per model. Zero `NULL` remaining.
- Distinct `uuid` count equals row count, per model.
- No `uuid` shared between `Game` and `Platform` (a cheap cross-check that
  the two loops did not write the same generated value).
- Every value passes `uuid_extract_version(uuid) = 7` — enforced by the
  domain, asserted anyway so the evidence is self-contained.
- Maximum absolute difference between `uuid_extract_timestamp(uuid)` and
  `date_trunc('milliseconds', created_at)` is zero milliseconds, per model.
- `order_by("uuid")` primary-key sequence equals `order_by("created_at",
  "pk")` primary-key sequence, per model.

The printed line, retained as the migration evidence the acceptance
criterion asks for:

```
CAT identity backfilled game_rows=<n> game_distinct=<n> platform_rows=<m> platform_distinct=<m> max_timestamp_delta_ms=0 order_preserved=true
```

## Rollback and reversibility

`migrate games 0004` drops both columns. Nothing else in the schema, no
route, no payload, and no query references them, so the reversal is total
and loses only the generated identities themselves.

Re-running forward after a reversal mints *different* UUIDs for the same
rows. That matters only if identities have already been exported or
referenced externally, which cannot happen before #644 at the earliest and
#647 in practice. Once #644 has repointed foreign keys, reversing #640 is no
longer a local operation; the reversal window closes when #644 lands, and
this specification records that explicitly so the #644 plan can restate it.

## Deployment assumption

This specification assumes the databases receiving this migration have row
counts in the low thousands and no meaningful production data requiring an
offline rehearsal of the #630 kind. Under that assumption #640 needs no
manifest, no offline window, no dump, and no rehearsal: it is additive,
transactional, and reversible. If a live database with meaningful catalog
data exists by the time this lands, the migration's logic does not change —
it remains additive and safe to run online at this row count — but the
operator should capture a pre-migration dump and retain the printed
reconciliation line, the same evidence discipline #630 used.

## Verification

New file `tests/test_catalog_identity.py`:

- `Game` and `Platform` created through the ORM get a distinct version-7
  `uuid`; a raw `INSERT` omitting the column also gets one, proving the
  database default is installed.
- The database rejects a duplicate `uuid` (`IntegrityError`) and rejects a
  version-4 UUID (domain `CheckViolation`).
- `uuid` is absent from every `ModelForm` bound to `Game` or `Platform`, and
  from the generated Ninja OpenAPI schema for the game and platform
  endpoints.
- Migration test using `MigrationExecutor`, mirroring
  `tests/test_library_cutover_migration.py`: migrate to `0004`, create games
  and platforms at that state with controlled `created_at` values including
  several in the same millisecond and one out of primary-key order, migrate
  to `0005`, then assert every row is populated, all values are distinct and
  version 7, `uuid_extract_timestamp` equals `created_at` truncated to
  milliseconds for every row, and `order_by("uuid")` reproduces
  `order_by("created_at", "pk")`.
- Reverse migration test: back to `0004` drops both columns and leaves all
  other column values intact.

Extended `tests/test_uuidv7.py`:

- `uuid7_at` encodes the requested millisecond, sets version 7 and the RFC
  4122 variant, produces distinct values for repeated calls at the same
  instant, and honors `sequence` in `rand_a` such that sequenced values sort
  in sequence order.
- A byte-layout pin so the encoder cannot silently change what the migration
  produced.

Regression surface — expected unchanged, run as-is rather than modified:
`tests/test_api.py`, `tests/test_filters.py`, `tests/test_filter_execution.py`,
`tests/test_filter_presets.py`, `tests/test_paths_return_200.py`,
`tests/test_rendered_pages.py`, `tests/test_components.py`,
`tests/test_library_api_isolation.py`, `tests/test_library_commands.py`
(sample-fixture loading), and the e2e suite. If any of these need editing,
the change has exceeded its boundary and the diff should be re-examined
before the test is touched.

The gate is the full `make check`.

## Explicit handoffs

- **#641/#642/#643** reuse `uuid7_at`, the five-operation migration shape,
  and the reconciliation checks verbatim for their model groups. They should
  not reinvent the backfill.
- **#644** repoints `Session.game`, `PlayEvent.game`, `GameStatusChange.game`,
  `Purchase.games`, `Purchase.related_game`, `Purchase.platform`, and
  `Game.platform` at the columns #640 created, and inherits the note that
  reversing #640 stops being local once it lands.
- **#645** owns the integer→UUID map verification tool. #640 ships no
  management command; its evidence is the migration's printed line plus
  tests.
- **#646** renames `uuid` to `id`, promotes it to primary key, drops the
  integer columns, and reconsiders the `F("pk").asc()` tiebreak in
  `games/sorting.py:189` in light of the creation-ordered identities #640
  guarantees.
- **#647/#648** own URLs; `docs/deployment.md:94` already documents the
  `uuid_v7` domain and needs no change here.
