# CAT-03 (#650): existing Game catalog hierarchy backfill

Status: awaiting approval 2026-08-20. Parent phase: #600. Depends on #649 and
#888. This design is governed by the
[timetracker overhaul charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
and the
[catalog foundation delivery wave](2026-08-20-catalog-wave-design.md).

## Outcome and boundary

CAT-03 migrates every Game present when migration `0020` starts into one
explicitly default private Game–Edition–Release graph. The Game remains the
same row with the same UUID and library owner. The migration copies the legacy
original year to `Game.original_release_date`, and the legacy release year and
Platform to the default Release. A NULL year stays unknown and a NULL Platform
stays explicitly unspecified.

The migration also handles Games already written through #888: it reuses their
explicit default Edition and Release, synchronizes their canonical fields from
the still-authoritative legacy columns, and never creates a second default.
Non-default Edition and Release rows remain untouched. This makes the migration
safe on the catalog integration branch, in development databases, and when the
complete wave is applied to production.

The following remain out of scope:

- moving `sort_name`, status, mastered, playtime, Sessions, Purchases, or other
  private facts away from Game;
- changing any application read or write path, form, URL, API, filter,
  statistic, template, TypeScript, or CSS;
- interpreting a non-default child as the default;
- merging by name, year, Platform, Wikidata, or any external identifier;
- shared/private catalog rules (#651), external references (#652),
  multi-edition management (#893), matching, IGDB, tombstones, or redirects;
  and
- reverse-migration deletion of catalog rows. The accepted rollback is restore
  of the ordinary verified database backup with the prior application image.

## Chosen migration shape

Create one atomic Django data migration,
`games/migrations/0020_catalog_hierarchy_backfill.py`, after
`0019_catalog_write_defaults`. It uses historical models from `apps`, performs
no network or filesystem I/O, and has a no-op reverse function. Django's normal
atomic migration transaction means any preflight or reconciliation mismatch
rolls back every canonical-field update and child insert.

The forward function follows five stages:

1. Snapshot every pre-migration Game's preserved fields and existing explicit
   default graph identities, then preflight all legacy years and private
   Platform ownership.
2. Set `Game.original_release_date` to the four-digit canonical year or NULL in
   batches, create one explicit default Edition where missing, create one
   explicit default Release where missing, and synchronize that Release's date
   and Platform in batches.
3. Run the default-creation step a second time and prove that it inserts
   nothing and leaves every default Edition/Release UUID unchanged.
4. Reconcile every preserved field and graph mapping, collecting all detected
   mismatches in deterministic order rather than stopping after the first.
5. Emit the exact machine and human reports, then raise `RuntimeError` when the
   mismatch count is nonzero.

Batch ORM operations are preferred over calling `save_private_game` once per
row. Historical migrations must use their frozen model state rather than the
future runtime service, and bulk operations avoid thousands of per-row lock and
query round trips while the application is offline. UUIDv7 values come from
the historical Edition/Release field defaults already delivered by #649.

## Source authority and exact mapping

The legacy columns remain authoritative until their owning read cutovers. The
migration therefore applies this mapping even when an existing #888 default
graph differs:

| Source | Destination | Exact rule |
| --- | --- | --- |
| `Game.id` | `Game.id` | Preserve the UUID exactly; never replace the Game. |
| `Game.library_id` | graph owner | Edition inherits through Game; Release may use only a shared or same-library Platform. |
| `Game.name` | `Game.name` | Preserve exact text; never use it as a lookup key. |
| `Game.sort_name` | `Game.sort_name` | Preserve exact text on Game. |
| `Game.original_year_released` | `Game.original_release_date` | `0001`–`9999` becomes the same four-digit year precision; NULL remains unknown. |
| `Game.year_released` | default `Release.release_date` | `0001`–`9999` becomes the same four-digit year precision; NULL remains unknown. |
| `Game.platform_id` | default `Release.platform_id` | Preserve the exact UUID; NULL remains unspecified. |
| `wikidata`, status, mastered, playtime, timestamps | existing Game fields | Preserve exactly for later owning phases. |
| dependent Game foreign keys and M2M links | same `Game.id` | Preserve automatically because the Game row and UUID never change; focused tests pin representative links. |

A legacy non-NULL year outside `0001`–`9999` cannot be represented by #655's
temporal contract. It is reported as `invalid_original_year` or
`invalid_release_year`, and the migration aborts before mutation. A private
legacy Platform owned by a different UserLibrary is reported as
`legacy_platform_cross_library` and also aborts before mutation. Shared
Platforms (`library_id IS NULL`) remain valid.

Same-named Games remain distinct because all creation is keyed solely by the
existing Game UUID and explicit default flags. No query groups or resolves by
text, year, Platform, Wikidata, or child ordering.

## Default graph and idempotency contract

For every pre-migration Game, success means:

- exactly one `Edition(game=game, is_default=True)` exists;
- exactly one `Release(edition=default_edition, is_default=True)` exists;
- the default Edition and Release UUIDs are stable across a repeated forward
  pass;
- canonical original/release dates and Platform exactly match the legacy
  columns; and
- any non-default children and their values are unchanged.

The partial unique constraints from #888 already prove “at most one.” This
migration supplies and verifies “at least one.” Missing defaults are created;
existing explicit defaults are reused. Unmarked children are never adopted,
because doing so would invent semantics and break #649's multiplicity contract.

The second ensure pass is deliberate runtime evidence, not only a unit-test
claim. It must report zero inserted Editions and Releases, and the ordered set
of `(game_id, edition_id, release_id)` identities must remain byte-for-byte
equal. Any difference becomes `non_idempotent_default_graph` and aborts.

## Reconciliation and exact output

The migration prints exactly one compact JSON line with this prefix:

```text
CATALOG_HIERARCHY_RECONCILIATION_JSON=
```

The suffix is a JSON object with `schema_version: 1`, a `summary` object, and a
`mismatches` array. `json.dumps(..., sort_keys=True, separators=(",", ":"))`
makes it deterministic and directly parseable after splitting on the first
`=`. The summary keys are:

```text
games
editions
releases
default_editions
default_releases
original_dates_known
original_dates_unknown
release_dates_known
release_dates_unknown
unspecified_platforms
mismatches
```

The following human summary is printed next, on one line and in that exact
field order:

```text
CAT hierarchy reconciliation: games=<n> editions=<n> releases=<n> default_editions=<n> default_releases=<n> original_dates_known=<n> original_dates_unknown=<n> release_dates_known=<n> release_dates_unknown=<n> unspecified_platforms=<n> mismatches=<n>
```

Each mismatch is present in the JSON array and also receives one human line:

```text
CAT hierarchy mismatch: code=<code> <sorted key=value details>
```

Mismatch objects are sorted by code, Game UUID, Edition UUID, Release UUID,
field, expected, and actual. UUIDs, dates, durations, and NULLs are normalized
to JSON strings or JSON null. This reports every detected invalid year,
cross-library relation, missing/extra default, changed preserved field,
canonical date/Platform disagreement, or idempotency disagreement before the
final exception:

```text
CAT hierarchy reconciliation failed with <n> mismatch(es).
```

On success the mismatch array is empty and the final count is zero. “Known”
means the canonical value is an atomic year-precision value; “unknown” means
SQL NULL. `unspecified_platforms` counts default Releases whose Platform is
NULL. `editions` and `releases` are total table counts, including preserved
non-default children; the two default counts must each equal `games`.

Reconciliation snapshots and compares these pre-existing Game fields:
`id`, `library_id`, `name`, `sort_name`, `original_year_released`,
`year_released`, `platform_id`, `wikidata`, `status`, `mastered`, `playtime`,
`created_at`, and `updated_at`. Focused migration tests additionally pin
representative Session, PlayEvent, GameStatusChange, Purchase related-Game, and
Purchase–Game links to the same Game UUIDs.

## Failure, transaction, and rollback behavior

Preflight emits all discoverable source mismatches and aborts before mutation.
Post-write reconciliation emits every detected result mismatch and raises
inside the same migration transaction, so Django rolls back the Game date
updates and all created children. Tests inspect the database at `0019` after a
forced failure rather than assuming atomicity.

The reverse function is `migrations.RunPython.noop`. Deleting default children
or clearing canonical fields cannot reconstruct whether a graph came from #888
or CAT-03 and would destroy valid catalog state. Before the catalog wave reaches
production, rollback is branch deletion. After deployment, rollback is:

1. keep the web and worker processes offline;
2. stop using the failed database rather than applying reverse migrations;
3. create a clean database and `pg_restore --exit-on-error --no-owner
   --no-privileges` the ordinary verified pre-deployment custom-format dump;
4. point the prior application image at the restored database;
5. verify migration state and the recorded pre-migration counts; and
6. start web/worker only after the restore checks pass.

## Production-copy rehearsal

Before the issue PR is opened, rehearse the exact branch migration against a
current production copy. Use the ordinary protected custom-format backup from
`docs/deployment.md`, record its SHA-256, restore it into a newly created
disposable PostgreSQL database, and keep production credentials and dump data
outside Git. With web and worker absent from that database, run the branch's
ordinary `manage.py migrate` and retain its complete stdout, including the two
exact reconciliation forms above.

The rehearsal record must include:

- source backup path/identifier kept outside Git, SHA-256, and source migration
  leaf;
- before counts for Games and legacy known/unknown years and Platforms;
- migration exit status and elapsed time;
- the exact machine JSON and human output;
- after counts for Games, total/default Editions and Releases, canonical
  known/unknown dates, unspecified Platforms, and zero mismatches;
- `audit_library_ownership --all-libraries` success and representative
  same-name/relationship checks; and
- the affected-file/line forecast comparison.

Rollback-by-restore is rehearsed with the same artifact: restore the verified
dump into another clean disposable database (or recreate the first after the
migrated copy is no longer needed), confirm the source migration leaf and
before counts, and record the restore exit status. The dump—not a reverse
migration—is the rollback artifact. No production mutation is part of this
issue-level rehearsal.

## Testing and verification

Focused migration tests prove:

- a mixed known/unknown dataset receives exact year precision and Platform
  mappings;
- same-named Games in different rows keep distinct UUIDs and distinct graphs;
- existing #888 defaults keep their UUIDs while missing defaults are created;
- non-default Editions/Releases and their values remain untouched;
- preserved Game fields and representative incoming relationships remain
  unchanged;
- shared and same-library Platforms pass, while a foreign private Platform
  reports a mismatch and aborts;
- all invalid years and cross-library source mismatches appear in both machine
  and human output before failure;
- a failed migration leaves no canonical changes or children;
- a repeated forward function creates nothing and preserves default UUIDs;
- empty and populated databases emit the exact deterministic report; and
- migrating backward is data-no-op and forward again remains idempotent.

Verification runs the focused migration file, the existing catalog hierarchy
and writer suites, `make check-migrations`, `git diff --check`, the
production-copy/restore rehearsal, and finally `make check` with the Makefile's
default parallel worker configuration. Normal verification never sets
`PYTEST_WORKERS=0`.

## Alternatives considered

**A separate backfill/audit management command.** Rejected because production
could apply the schema without the required data step, and rehearsal would no
longer exercise the exact ordinary deployment migration. The report belongs to
the atomic data migration that can abort its own writes.

**Call `save_private_game` for every historical row.** Rejected because Django
migrations must use frozen historical models, while the live service will
evolve. Per-row service transactions and locks are also unnecessary while the
application is offline and would multiply production round trips.

**Adopt the only or oldest non-default child.** Rejected because #649 permits
multiple children and #888 makes default status explicit. Child count, UUID
order, or age cannot establish catalog meaning.

**Delete created graphs in the reverse migration.** Rejected because it cannot
distinguish backfilled graphs from #888-written graphs and is not the approved
production rollback. The verified backup plus prior image is lossless.

## Complexity forecast and re-slice gate

Forecast: one runtime subsystem (Django/PostgreSQL migration), two
implementation/test files, and 450–750 non-generated changed lines:

- `games/migrations/0020_catalog_hierarchy_backfill.py`; and
- `tests/test_catalog_hierarchy_migration.py`.

The temporary design and plan add two documentation files during review and
are removed only after implementation and all gates pass, preserving the
planning commit in branch history. No generated output is expected. The work
remains below every mandated re-slice threshold: fewer than three independent
runtime subsystems, 40 files, and 2,000 non-generated changed lines. If the
implementation needs a runtime command, application read/write change, third
implementation file outside focused test support, or crosses any numeric
threshold, work returns to this design gate before expanding scope.
