# CAT-01 (#649): additive Game, Edition, and Release identities

Status: awaiting approval 2026-08-20. Parent phase: #600. This design is
governed by the
[timetracker overhaul charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
and the
[catalog foundation delivery wave](2026-08-20-catalog-wave-design.md). It uses
the temporal-value contract delivered by #655.

## Outcome and boundary

CAT-01 adds the durable relational identities for the catalog hierarchy without
changing any current application read or write. `Game` remains the
platform-independent work identity and keeps its existing UUIDv7 primary key.
An `Edition` belongs to one `Game`; a `Release` belongs to one `Edition` and may
point to one `Platform` or retain an explicitly unspecified Platform as `NULL`.

The issue also adds the final temporal storage shape for a Game's original
release and a Release's availability. It does not copy either legacy year into
those fields. Existing Games therefore receive an unknown
`original_release_date`, while the new Edition and Release tables start empty.
#650 owns the historical backfill. #888 owns graph creation and compatibility
synchronization for new and edited Games.

The following remain out of scope:

- changing or removing legacy `Game.platform`, `year_released`,
  `original_year_released`, `wikidata`, `status`, `mastered`, or `playtime`;
- creating Edition or Release rows for existing or newly written Games;
- adding a catalog writer, form adapter, reconciliation report, or production-
  copy migration rehearsal;
- adding names, kinds, default markers, external references, uniqueness policy,
  archive/tombstone behavior, or private-to-shared redirects;
- changing the user-visible URLs, forms, filter vocabulary, saved presets,
  APIs, statistics, Sessions, Purchases, templates, TypeScript, or CSS; and
- adding PlayerGame, catalog matching, IGDB ingestion, dedicated catalog UI,
  product relationships, or automatic merges.

## Chosen schema

### Game

`Game.id` is not altered. The model gains one nullable, non-editable
`TemporalValueField` named `original_release_date` plus the eight persisted
generated projections required by #655:

| Field | Type | Meaning |
| --- | --- | --- |
| `original_release_date` | `temporal_value`, nullable | Canonical temporal scalar; `NULL` is unknown. |
| `original_release_date_lower` | date, nullable | Earliest possible calendar day. |
| `original_release_date_upper` | date, nullable | Latest possible calendar day. |
| `original_release_date_kind` | varchar(7), non-null | `atomic`, `range`, or `unknown`. |
| `original_release_date_precision` | varchar(7), nullable | Atomic `day`, `month`, `year`, or `decade`. |
| `original_release_date_start_kind` | varchar(7), nullable | Range start `known`, `unknown`, or `open`. |
| `original_release_date_end_kind` | varchar(7), nullable | Range end `known`, `unknown`, or `open`. |
| `original_release_date_start_precision` | varchar(7), nullable | Precision of a known range start. |
| `original_release_date_end_precision` | varchar(7), nullable | Precision of a known range end. |

No current surface reads or writes these columns. Existing
`original_year_released` remains authoritative until the backfill and later
read/write cutovers.

### Edition

`Edition` is deliberately an identity and parent relation in this slice:

```text
id       uuid_v7 primary key
game_id  uuid_v7 not null -> Game.id
```

`Edition.id` uses `UUIDv7Field(primary_key=True, editable=False)`, including
the existing Python and PostgreSQL UUIDv7 defaults. `game` uses
`on_delete=CASCADE` and `related_name="editions"`. The non-null relation means
an Edition cannot exist outside one Game; deleting a Game through Django also
deletes its Editions and their Releases.

The model has no independent `library`: ownership and visibility are derived
through `edition.game.library`, as required by #651. It has no name or default
flag because this issue introduces identity, not the later management/writer
contract. Multiple Editions remain representable by distinct UUIDs without
inventing premature uniqueness rules.

This bare identity schema intentionally cannot distinguish a default Edition or
Release once a Game has multiple children. #888 must close that contract before
it creates graphs: it must either add an explicit default discriminator with an
enforced uniqueness rule, or guarantee and lock an exact-one-Edition and
exact-one-Release graph for every compatibility write. CAT-01 does not claim
that UUID identity alone identifies a default.

### Release

`Release` contains the identity, parent, optional Platform, and temporal value
that define this slice:

```text
id          uuid_v7 primary key
edition_id  uuid_v7 not null -> Edition.id
platform_id uuid_v7 null -> Platform.id
release_date and its eight persisted generated projections
```

`Release.id` uses the same `UUIDv7Field` contract. `edition` uses
`on_delete=CASCADE` and `related_name="releases"`. `platform` uses
`on_delete=SET_NULL`, `null=True`, `blank=True`, `default=None`, and
`related_name="+"`. The suppressed reverse accessor prevents this passive
child from entering Platform metadata-derived filter paths before a Release
filter contract exists. `NULL` is a first-class explicitly unspecified
Platform, not a value to infer from Game, Device, Edition, another Release, or
its date. Deleting a Platform through Django preserves the Release and changes
it to unspecified, matching the current legacy Game behavior. #653 may later
replace hard deletion of referenced catalog records with archive/tombstone
rules; CAT-01 does not pre-implement that policy.

`release_date` uses the same explicit nine-column temporal shape as
`Game.original_release_date`, with the prefix `release_date`. In particular,
`TemporalValue.from_year(1998)` round-trips as canonical `1998`, bounds
`1998-01-01` through `1998-12-31`, kind `atomic`, and precision `year`.
`None`/`TemporalValue.unknown()` persists as SQL `NULL`, has null bounds and
precision, and has generated kind `unknown`.

No additional unique constraint is added. One Game can have any number of
Editions, and one Edition can have any number of Releases, including Releases
whose Platform is unspecified. The durable writer in #888 owns idempotent
default-graph creation; later multi-edition and external-catalog issues own any
semantic duplicate policy they require.

## Persistence implementation

`games.models` imports the nine public #655 persistence types:

- `TemporalValueField`;
- `TemporalLowerBound` and `TemporalUpperBound`;
- `TemporalKind` and `TemporalPrecisionValue`; and
- `TemporalStartKind`, `TemporalEndKind`, `TemporalStartPrecision`, and
  `TemporalEndPrecision`.

Each temporal fact declares its fields explicitly. A helper that dynamically
injects model fields or an abstract pseudo-field is not introduced: explicit
declarations preserve ordinary Django migration state, inspection, generated-
column dependencies, and the semantic field prefixes approved here.

All eight stored generated projections use `serialize=False`. Django's fixture
serializer therefore emits the canonical temporal scalar but not database-
derived values that cannot be loaded directly. The seven nullable projections
set `null=True` on both the `GeneratedField` wrapper and its output field; the
generated `kind` projection is non-null in both migration state and the
physical PostgreSQL schema.

Migration `0018_catalog_hierarchy` depends on
`0017_temporal_value_domain`. It adds the nine Game columns and creates the
Edition and Release tables. The migration contains no `RunPython`, writes no
canonical values, mints no graph identities, and performs no reconciliation.
PostgreSQL must nevertheless compute each stored Game projection for every
existing row and may take a strong table lock while adding it; this is a schema
rewrite risk, not a logical backfill. `sqlmigrate` output is inspected before
merge, and the catalog wave's production-copy rehearsal must measure the
resulting lock/rewrite behavior before rollout. If the emitted statements imply
unacceptable repeated rewrites, the migration is consolidated before the
implementation PR merges rather than hidden behind a data migration. A
material change to the approved migration strategy returns to the design gate.
The dependency guarantees that a fresh PostgreSQL database creates the
`temporal_value` domain and immutable projection functions before any consuming
column or generated expression.

The generated bound, kind, and precision columns receive no indexes in CAT-01
because no current query consumes them. The UUID primary keys and Django
foreign keys receive their normal indexes. The issue that introduces a query
path must justify and test the indexes needed by that path.

## Runtime compatibility

The migration is additive and the models are passive:

- `GameForm` continues to list only legacy fields explicitly.
- Game create/edit paths continue to write only the existing Game row.
- A current Game write does not implicitly create an Edition or Release.
- Existing Game uniqueness, ownership validation, URLs, user-visible filters,
  statistics, Session entry, and Purchase entry keep using legacy fields and
  relations.
- The canonical `original_release_date` scalar is intentionally present in
  Django fixture serialization as additive model state; all generated
  projections are excluded. No user-facing API serializer changes.
- The field-comparison registry explicitly ignores #655 temporal projection
  expressions, preventing new generated columns from silently expanding Game
  or relationship-derived filter choices. Release's Platform relation exposes
  no reverse accessor for the same compatibility reason.
- The UUID identity audit recognizes Edition and Release as UUIDv7 tables and
  records that neither has an integer ordering source.
- No signal, manager, queryset, service, admin registration, or API schema is
  added for Edition or Release.

Focused tests pin this passivity, while the complete existing suite is the
behavioral regression proof. CAT-01 does not duplicate broad URL/form/filter/
API/statistics assertions already owned by that suite.

## Migration, reversibility, and rollback

Forward migration from `0017` preserves every pre-existing Game row and UUID,
adds an unknown `original_release_date`, and leaves Edition and Release counts
at zero. A migration-state test proves the table/column/domain types, generated
column status, foreign-key targets, and the absence of accidental backfill.
The normal test database build plus `make check-migrations` proves the complete
fresh PostgreSQL migration graph.

Reversing `0018` before any consumer issue removes the two empty tables and the
nine unused Game columns without touching legacy Game data. Once a later issue
stores Edition/Release or original-release temporal data, reversing CAT-01
would discard that new catalog state. In accordance with the catalog wave,
rollback before the final `main` merge is branch deletion; rollback after a
deployment is restoration of the verified database backup plus the prior
application image. A reverse migration is not represented as a substitute for
that backup.

## Alternatives considered

**Add names, default flags, and uniqueness now.** Rejected because neither the
issue nor an existing consumer defines their semantics. UUID identity and
parentage are sufficient for #650 to address rows, while #888 must define the
default-selection invariant described above before it writes a compatibility
graph. Later multi-edition management can add user-visible metadata with an
approved contract rather than inheriting guesses from this slice.

**Hide the temporal projections behind an abstract model or dynamic field
injector.** Rejected by #655's explicit consumer contract. The repetition is
intentional and keeps migration state and queryable column names visible.

**Keep only legacy integer years until backfill.** Rejected because #649 owns
the final additive date columns and must prove that year precision and unknown
dates are representable before #650 migrates data into them.

**Create Edition/Release rows in this migration.** Rejected because #650 owns
existing-data backfill and reconciliation, while #888 owns supported writes.
Combining either with schema introduction would erase the review and rollback
boundaries established by the catalog wave.

## Verification and complexity forecast

Focused model tests cover:

- preservation of an explicitly assigned Game UUID;
- UUIDv7 generation for Edition and Release;
- multiple Editions per Game and multiple Releases per Edition;
- exact parent/related-name behavior;
- cascade deletion from Game and Edition;
- Platform `SET_NULL` behavior and explicit unspecified Platform;
- Game original-release and Release range/year/unknown round trips and all
  generated projections;
- fixture serialization of canonical values without generated projections;
- unchanged metadata-derived Game, Session, Purchase, PlayEvent, and Platform
  filter surfaces;
- UUID identity-audit inclusion for both new tables; and
- continued legacy Game writes without automatic hierarchy creation.

Focused migration tests cover:

- forward migration from `0017` with a representative legacy Game;
- unchanged legacy field values and exact Game UUID;
- no Edition/Release backfill;
- `uuid_v7`, `temporal_value`, generated-column, and foreign-key schema shape;
- database-side UUIDv7 defaults when raw inserts omit both IDs;
- exact physical nullability for every generated projection;
- reverse migration back to `0017` while preserving the legacy Game; and
- physical absence of both tables and all nine Game columns after reverse,
  while the `uuid_v7` and `temporal_value` domains remain; and
- restoration of the migration graph's leaf nodes in `finally` so xdist worker
  databases are never stranded behind head.

Verification also inspects `sqlmigrate games 0018`, then finishes with all
focused files, `make check` using the
Makefile's default parallel worker configuration, `git diff --check`,
`make check-migrations`, and a full diff/scope audit against this specification.

Forecast: two closely coupled runtime subsystems (Django application/model
metadata and PostgreSQL schema), six implementation/test files
(`games/models.py`, `common/criteria.py`, one migration, two focused test files,
and the UUID identity-audit test), 700–1,100 non-generated changed lines, and no
generated frontend output. The `common.criteria` change is a compatibility
exclusion, not a new filter feature. This remains below every re-slice
threshold: it does not cross three independent runtime subsystems, 40 files, or
2,000 non-generated changed lines.
