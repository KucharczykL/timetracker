# Plan — EV-06 (#660): library event envelope and stream-head schema

Design record: [2026-08-21-issue-660-library-event-schema-design.md](../specs/2026-08-21-issue-660-library-event-schema-design.md).
Branch: `codex/issue-660-event-envelope-schema`, cut from `origin/main` at
`e45911c8`. Migration leaf at cut: `0022_external_references`.

Test-driven: each task writes failing tests first, then the smallest code that
passes them. Do not run the full gate per task — iterate on
`make test ARGS="tests/test_event_models.py"`, gate once at the end.

## Files

| Path | Change |
| --- | --- |
| `docs/superpowers/specs/2026-08-21-…-design.md` | this slice's design record (committed first) |
| `docs/superpowers/plans/2026-08-21-…-schema.md` | this file |
| `games/models.py` | add `LibraryEventQuerySet`, `LibraryEventStreamHead`, `LibraryEvent` |
| `games/migrations/0023_library_event_schema.py` | generated, then hand-extended |
| `games/identity_audit.py` | register `actor_id` as residual-integer; order-source for the events table |
| `tests/test_uuid_identity_audit.py` | extend the two pinned constants |
| `tests/test_event_models.py` | new |
| `tests/test_event_schema_migration.py` | new |
| `Makefile` | add a `sqlmigrate` target (Task 4 needs one; CLAUDE.md forbids reaching around the Makefile) |

Nothing else. If a task wants to touch admin, API, filters, fixtures, or
`common/`, it has left the boundary — stop and re-read the spec's Boundary
table. The audit files are *not* a boundary breach: the audit asserts exact set
equality over the whole schema, so adding a model without registering it is a
failing build, not a deferrable follow-up.

## Conventions this code must match

- Models declare `class Meta` with a `constraints = (...)` **tuple** *before*
  the field list — see `ExternalReference` (`games/models.py:461`, its `Meta` at
  `:478`).
- Constraint names are descriptive snake_case with no app prefix
  (`unique_library_mode_name_preset`, `external_reference_kind_matches_target`).
- `LibraryEventQuerySet` subclasses `LibraryOwnedQuerySet` (`games/models.py:37`)
  and adds nothing — `for_library()` is inherited. Install with
  `objects = LibraryEventQuerySet.as_manager()`.
- Complete words in identifiers, per CLAUDE.md.

## Task 1 — envelope behaviour tests (`tests/test_event_models.py`)

Fixtures: reuse `owned_user` / `owned_library` from `tests/conftest.py`; add a
second user/library locally for the cross-library cases. A head must be created
explicitly in each test — nothing provisions one.

Write these first, watch them fail on `ImportError`:

1. `test_head_and_event_ids_are_uuidv7` — both PKs parse as version 7.
2. `test_event_requires_explicit_aggregate_and_correlation_ids` — omitting
   either raises `IntegrityError` (NOT NULL), not a silently generated UUID.
   This covers the `default=None` half only.
3. `test_explicit_identity_fields_carry_no_database_default` —
   `has_db_default()` is false for `aggregate_id`, `correlation_id`, and
   `causation_id`. The `db_default` half is invisible at runtime (see spec
   decision 4), so this field-level assertion plus `make check-migrations` is
   the whole pin.
4. `test_causation_id_defaults_to_none` — a root event stores `NULL`.
5. `test_effective_time_is_optional_and_round_trips` — `None` stays `None`; a
   parsed `TemporalValue` survives save + refresh.
6. `test_payload_round_trips_nested_structures` — dict/list/nested UUID *strings*
   come back identical. No key means anything; no Game involved.
7. `test_source_metadata_defaults_are_independent` — two events created without
   `source_metadata`; mutating one's dict does not touch the other's.
8. `test_head_current_sequence_starts_at_zero` — the only field of the head that
   is neither identity nor relation, and otherwise untested.
9. `test_for_library_scopes_events` — `LibraryEvent.objects.for_library(a)`
   excludes library B's events.
10. `test_deleting_actor_preserves_event` — delete the actor user, event survives
    with `actor_id IS NULL`. The actor must be a *third* user who owns neither
    library, or the library cascade removes the event and the test proves
    nothing.

## Task 2 — constraint tests (same file)

Each writes through the ORM and asserts the database rejects it. Use
`pytest.raises(IntegrityError)` inside `transaction.atomic()` so the connection
stays usable. The default `django_db` marker suffices throughout — CASCADE and
`RestrictedError` are both observable inside the test transaction, and
`transaction=True` would only buy a full flush per test.

1. `test_head_requires_library` / `test_event_requires_library` — NULL rejected.
2. `test_library_has_at_most_one_head` — second head for a library rejected
   (`OneToOneField`'s unique).
3. `test_sequence_below_one_is_rejected` — `sequence=0`.
4. `test_payload_schema_version_below_one_is_rejected` — `payload_schema_version=0`.
5. `test_blank_text_fields_are_rejected` — `event_type`, `aggregate_type`,
   `idempotency_key`, each `""`, parametrized.
6. `test_duplicate_sequence_in_one_stream_is_rejected`.
7. `test_same_sequence_in_another_stream_is_allowed` — library B, sequence 1,
   succeeds. Proves the unique constraint is per-stream, not global.
8. `test_event_cannot_use_another_librarys_stream` — event with library A and
   library B's stream. **This one fails at the composite FK, which does not
   exist until Task 4**, so it will still be red after Task 3. Expected.
9. `test_deleting_library_removes_its_events_and_head` — the *populated* head
   case. See the gotcha below; this is the load-bearing one.
10. `test_deleting_populated_head_is_restricted` — `RestrictedError`.
11. `test_payload_is_required` — `payload=None` rejected. `JSONField(null=False)`
    still accepts the JSON value `null` only if written as `Value("null")`; the
    Python `None` is what must fail.
12. `test_constraint_names_exist` — query `pg_constraint` for all eight names
    from the spec's table. The composite FK lives outside Django's migration
    state, so this is the only thing that would catch a misspelling in it.

### Gotcha: RESTRICT + CASCADE

Deleting a `UserLibrary` that owns a populated head succeeds. Django clears a
RESTRICT when the restricted rows are also collected by CASCADE from the same
origin, and `RESTRICT` registers a delete-order dependency so events are deleted
before the head — which is what keeps the raw composite FK (plain `NO ACTION`,
not deferrable) satisfied mid-cascade. If this test unexpectedly raises
`RestrictedError`, the only model change that can cause it is
`LibraryEvent.library` no longer being a CASCADE FK (removed, `SET_NULL`, or
`PROTECT`), which stops events being collected from the same origin. Nothing
else does: `related_name="+"` relations are still collected
(`get_candidate_relations_to_delete` uses `include_hidden=True`), and a nullable
`library` changes only fast-delete eligibility, which the guard handles for
querysets too. Fix that FK; do not weaken the test.

## Task 3 — models

Implement the two models per the spec's Schema contract table until Tasks 1–2
pass except case 8 (cross-library), which waits for Task 4.

Watch for:

- `aggregate_id` / `correlation_id` need **both** `default=None` and
  `db_default=models.NOT_PROVIDED` — `UUIDv7Field.__init__` `setdefault`s a
  generated value for each. `db_default=None` is wrong: it emits
  `DEFAULT NULL NOT NULL` into the DDL (measured on Django 6.0.7). `causation_id`
  adds `null=True`.
- Non-empty checks: `~Q(event_type="")` style, matching how the codebase writes
  `CheckConstraint(condition=Q(...))` — `condition=`, not the removed `check=`.
- The head's `(id, library)` unique constraint is redundant against its PK by
  design; it exists to be the composite FK's target. Say so in one comment, per
  CLAUDE.md's comment rules (intent, no issue references).
- `related_name="+"` on `actor` — the charter wants no reverse accessor from
  `User`.

## Task 4 — migration `0023_library_event_schema.py`

Generate with `make makemigrations` (it passes `--noinput`; the autodetector
would otherwise prompt), then **read the generated file** before extending it.
If the autodetector picks another filename, renaming the file is the whole
rename — Django derives the migration name from the filename, and the only
`name=` inside a `CreateModel` is the *model* name. Nothing depends on `0023`
yet, so no `dependencies` entry needs touching.

Append, in order:

1. `migrations.RunSQL` adding the composite FK, following the `sql` /
   `reverse_sql` pair style already used across `games/migrations/` (e.g.
   `0017_temporal_value_domain.py:367`):
   - forward: `ALTER TABLE games_libraryevent ADD CONSTRAINT
     library_event_stream_matches_library FOREIGN KEY (stream_id, library_id)
     REFERENCES games_libraryeventstreamhead (id, library_id)`;
   - reverse: `ALTER TABLE … DROP CONSTRAINT library_event_stream_matches_library`.
   - Verify the real table names from the generated migration rather than
     assuming them.
2. A guard operation whose **forward is a no-op** and whose **reverse raises**
   when either table has rows. Write it as `migrations.RunPython(noop, guard)`;
   the guard opens a cursor, counts both tables, and raises a `RuntimeError`
   naming the counts and telling the operator that reversing would destroy the
   only copy of the history. It must sit **last** so that reversal hits it
   first, before anything is dropped.

Then inspect the emitted DDL. There is no `sqlmigrate` target today, and
CLAUDE.md's rule for that case is to add one rather than to run `uv run` by
hand. Add it next to `makemigrations` (`Makefile:140`), matching that target's
`ensure-postgres` prerequisite and `uv run --frozen` invocation, taking the app
and migration through `ARGS`. Read the output for: both `CREATE TABLE`s, all
eight constraints, `uuid_v7 NOT NULL` (with no `DEFAULT NULL`) on the three
explicit identity columns, and no index beyond the constraint-backed ones.

## Task 5 — migration executor test (`tests/test_event_schema_migration.py`)

Copy the harness shape from `tests/test_external_reference_migration.py:34` —
capture `leaf_nodes()`, migrate back, `flush`, yield historical `apps`, then
flush and restore the leaf in teardown. `pytestmark = pytest.mark.django_db(transaction=True)`.

- `BEFORE = ("games", "0022_external_references")`,
  `AFTER = ("games", "0023_library_event_schema")`.
- Seed at `0022`: two users with libraries, private Games and Platforms for
  each, and one shared `Game` with `library=None`. Snapshot the field values.
- `test_forward_migration_preserves_catalog_data` — after migrating to `0023`,
  every seeded row is byte-identical, and the shared Game still has
  `library_id IS NULL`.
- `test_forward_migration_creates_no_stream_rows` — both new tables count `0`.
  This is the "no backfill" acceptance criterion.
- `test_reverse_migration_succeeds_when_empty` — back to `0022` cleanly.
- `test_reverse_migration_refuses_with_head_rows` and
  `…_with_event_rows` — insert through the historical `apps` models, then assert
  the reverse raises and names the table. No re-migration is needed afterwards:
  the migration is atomic on PostgreSQL, so the guard's exception rolls the
  whole unapply back, `record_unapplied` never runs, and the database is still
  at `0023` for the fixture's teardown to work from.

Restoring the leaf in teardown is not optional; a leaked non-leaf state fails
unrelated tests later in the session, and the failure looks nothing like its
cause.

## Task 5b — UUID identity audit registrations

Not optional and not deferrable: `tests/test_uuid_identity_audit.py` asserts set
equality over the whole schema, so `make check` is red until this lands. Per
spec decision 8:

- `games/identity_audit.py`: add `("games_libraryevent", "actor_id"): NEVER_CONVERTS`
  to `RESIDUAL_INTEGER_RELATIONS` (`:41`) — it points at `auth.User`'s integer
  PK, like the two entries already there — and
  `"games_libraryevent": "recorded_at"` to `IDENTITY_ORDER_SOURCE` (`:59`).
- `tests/test_uuid_identity_audit.py`: add the four new FK columns to
  `EXPECTED_RELATION_COLUMNS` (`:29`) and both new tables to
  `EXPECTED_IDENTITY_TABLES` (`:203`).

Verify with `make audit-uuid-identity` (read-only) before the gate. Expect
`games_libraryeventstreamhead` to appear as an ordering *note* ("no creation
timestamp"), not a violation — that is the accepted outcome, not a gap to patch
by inventing a `created_at` the issue's field contract does not include.

## Task 6 — gate and commit

```bash
make check-fast
```

then the real gate:

```bash
make check
```

plus `git diff --check`. Use the Makefile's default `PYTEST_WORKERS`; do not
narrow with `ARGS` for the gate.

Commits:

1. `docs: add library event schema design and plan` (planning artifacts, before
   any implementation).
2. `feat: add library event envelope schema` (models, migration, both test
   files, the audit registrations, and the `sqlmigrate` target).

## Done means

- Both tables and all eight named constraints exist on a fresh PostgreSQL 18
  database.
- Existing private and shared catalog data is unchanged; no head or event row
  is backfilled.
- Every event and stream has a concrete private-library owner, and a
  cross-library pairing is rejected by PostgreSQL.
- The schema is domain-neutral. A bare `grep -i game` cannot show this — the
  app label, the table prefix, and the `to="games.userlibrary"` FK targets all
  contain it. The check is that `0023` references no model but `UserLibrary`,
  `LibraryEventStreamHead`, `LibraryEvent`, and `AUTH_USER_MODEL`, and that no
  field or payload key names a catalog concept.
- Empty rollback works; rollback with data fails visibly.
- Full `make check` green.
