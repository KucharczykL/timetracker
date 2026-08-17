# ID-03: Convert Session and play-history identities to UUIDv7 — design specification

Status: draft for approval. Parent phase: #600. Depends on `#639` (identity
foundation) and, for the shared mechanics, `#640`'s established pattern —
see the [catalog identity design](2026-08-17-issue-640-catalog-uuid-identity-design.md)
and the [wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md). This
issue does **not** depend on `#640` merging first; it applies the same
recipe to a disjoint set of models and can land in either order.

## Context

`#640` established the pattern for adding a stable, creation-ordered UUIDv7
identity to an existing model without touching its primary key: a parallel
non-PK `uuid` column, backfilled from `created_at` with strict
within-millisecond ordering, verified by an in-migration reconciliation
check. This issue applies that pattern to `Session`, `PlayEvent`, and
`GameStatusChange` — the play-history group named in the phase-#600
checklist.

Everything in `#640`'s "Decision: parallel column, not a primary-key flip"
and "Decision" sections applies unchanged here and is not repeated: same
field name (`uuid`), same reasoning for why a PK flip is not expressible,
same `editable=False` / `unique=True` contract, same non-goals (no FK
repointing — that is `#644`'s split, specifically ID-06/#644 for
`PlayEvent.game`/`GameStatusChange.game` and ID-08/#846 for `Session.game`/
`Session.device`).

## Goals

Same as `#640`, applied to `Session`, `PlayEvent`, `GameStatusChange`: a
populated, unique, creation-ordered `uuid` column on each, landed as one
additive, reversible migration with reconciliation evidence.

## Non-goals

Same list as `#640`'s non-goals, plus: this issue does not touch `Device`
(that is `#643`) even though `Session.device` is a foreign key to it — FK
repointing for both `Session.game` and `Session.device` is ID-08/#846, not
here.

## Model-specific deltas from `#640`

### `Session` and `PlayEvent`: identical to the catalog pattern

Both have a non-null `created_at` (`auto_now_add=True`,
`games/models.py:496` and `:640`). The backfill derives each row's UUID
timestamp from `created_at` exactly as `#640` does for `Game`/`Platform`:
same `uuid7_at` helper (already added by whichever of `#640`/`#641` lands
first — see "Shared helper ownership" below), same ordering guarantee
(`order_by("uuid")` reproduces `order_by("created_at", "pk")`).

Field placement: `uuid = UUIDv7Field(unique=True, editable=False)` declared
as the first field on each model (immediately after the `objects = ...`
manager assignment), since neither model has a `library` field of its own
to place it after — ownership is derived through `game__library`
(`SessionQuerySet.for_library`, `PlayEventQuerySet.for_library`).

**API surface note:** `AutoPlayEventIn` (`games/api.py:106`) is a
`ModelSchema` over `PlayEvent` — the one such class in the codebase that
actually touches a model `#640`/`#641` convert (`GameOut`/`PlatformOut` are
hand-written `Schema`, not `ModelSchema`). Its `Meta.fields` is the explicit
tuple `("game", "started", "ended", "note")` (`games/api.py:109`), so the new
`uuid` field does not leak into it — but this is the first case in the
identity-cutover sequence where a `ModelSchema` exists at all, so a test
explicitly asserts `uuid` is absent from its generated schema rather than
relying on the general "no `ModelSchema` touches these models" argument
`#640` could make.

### `GameStatusChange`: no `created_at`, nullable `timestamp`

`GameStatusChange` has no `created_at` field. Its only datetime field is
`timestamp = models.DateTimeField(null=True)` (`games/models.py:670`),
ordered by `Meta.ordering = ["-timestamp"]`. It is nullable at the schema
level, but the only code path that creates rows —
`game_status_changed` in `games/signals.py:149` — always passes
`timestamp=now()`. A fixture-loaded or otherwise directly-inserted row could
still carry a `NULL` timestamp; the migration must not assume non-null.

Backfill ordering for `GameStatusChange` uses `("timestamp", "pk")` instead
of `("created_at", "pk")`. PostgreSQL's default `ASC` ordering is `NULLS
LAST`, so any `NULL`-timestamp row naturally sorts after every timestamped
row; those rows get their UUID's embedded timestamp set to the moment the
migration runs (there is no historical value to preserve for them), still
assigned in a stable, deterministic order via the `pk` tiebreak. The
reconciliation check's "UUID timestamp equals source timestamp" assertion is
scoped to rows where `timestamp IS NOT NULL`; `NULL`-timestamp rows are
counted and reported separately (expected to be zero in every real
database, verified rather than assumed).

Field placement: same as `Session`/`PlayEvent` — first field, after
`objects = GameStatusChangeQuerySet.as_manager()`.

## Shared helper ownership

`uuid7_at` (added to `timetracker/uuidv7.py` by `#640`) is reused verbatim.
If `#641` is implemented before `#640` merges, `#641` adds `uuid7_at` itself
following `#640`'s design exactly, and whichever of the two merges second
rebases to drop the now-duplicate addition. This is a merge-order mechanic,
not a design choice — the function's contract is fixed by `#640`'s spec.

## Migration and reconciliation mechanics

One migration file, depending on whichever of `#639`'s successors is latest
at implementation time (expected `0004_user_library_ownership_cutover`, or
`#640`'s migration if it has already merged). Same five-operation shape per
model as `#640`: nullable `AddField` ×3 (`Session`, `PlayEvent`,
`GameStatusChange`), one `RunPython` backfill+reconciliation covering all
three, final `AlterField` ×3.

Reconciliation checks, per model, mirroring `#640`'s list exactly for
`Session`/`PlayEvent` (row count = populated count, distinct count = row
count, no `uuid` shared across the three models or with `Game`/`Platform`,
every value version-7, `order_by("uuid")` reproduces the natural order,
UUID timestamp matches source timestamp to the millisecond) plus, for
`GameStatusChange` only, the `NULL`-timestamp count called out above.

Printed evidence line, extending `#640`'s format:

```
SES identity backfilled session_rows=<n> playevent_rows=<n> gamestatuschange_rows=<n> gamestatuschange_null_timestamp_rows=<n> max_timestamp_delta_ms=0 order_preserved=true
```

## Rollback and reversibility

Identical to `#640`: `migrate games <previous>` drops the three columns;
nothing references them yet, so the reversal is total. Same caveat that the
window closes once ID-06/#644 and ID-08/#846 repoint the relevant foreign
keys.

## Deployment assumption

Same as `#640`: development/CI row counts, no live-database rehearsal
needed. Unverified assumption, same confirmation requirement.

## Verification

New file `tests/test_session_playhistory_identity.py`, mirroring
`tests/test_catalog_identity.py`'s structure:

- Field-contract tests for all three models (ORM insert, raw-SQL insert,
  duplicate rejection, non-v7 rejection).
- `uuid` absence from `SessionForm`, `PlayEventForm`, and
  `GameStatusChangeForm` field sets, and explicitly from `AutoPlayEventIn`'s
  generated schema (the `ModelSchema` case called out above).
- `MigrationExecutor` forward test covering same-millisecond and
  out-of-order fixtures for `Session` and `PlayEvent` (as `#640`), plus a
  `GameStatusChange`-specific case with a mix of populated and `NULL`
  `timestamp` values, asserting `NULL` rows land after every timestamped row
  in `uuid` order and get a migration-time embedded timestamp.
- Reverse migration test.

Regression surface expected unchanged: `tests/test_api.py`,
`tests/test_filters.py`, `tests/test_filter_execution.py`,
`tests/test_filter_presets.py`, `tests/test_paths_return_200.py`,
`tests/test_rendered_pages.py`, `tests/test_components.py`,
`tests/test_signals.py` (GameStatusChange creation), plus the e2e suite. A
failure here is a boundary violation.

The gate is the full `make check`.

## Explicit handoffs

Same as `#640`'s, scoped to this issue's models: `#645`/ID-10 reuses this
issue's reconciliation checks; ID-06/#644 and ID-08/#846 repoint the
relevant foreign keys; the corresponding slice of ID-12/#848 removes the
integer identities once verified.
