# Projection write guard — plan

Spec: `docs/superpowers/specs/2026-10-10-issue-110-projection-write-guard-design.md`.
Inline, TDD per task. Iterate with focused `make test ARGS=…` under the
shared lock; `make check-fast` after task 6; full `make check` once at the end.

## 1. Move and widen `write_targets`

- New `games/sql_writes.py`: `write_targets`, `_bare_name`, the regexes,
  `TableName` alias. Keyword check by prefix regex (`^\s*(\w+)` after
  comment strip), no `split`.
- `TRUNCATE [TABLE] [ONLY] a, b, …` returns every name; `… CASCADE`
  returns `("",)`.
- Callers: `games/events/rebuild.py` (`_refuse_a_live_write`),
  `games/events/benchmark.py:19,117`, `tests/test_projection_rebuild.py:49`.
  Move the "Public because…" docstring line.
- Tests (`tests/test_sql_writes.py`, move the parse cases from
  `test_projection_rebuild.py:434-440`): multi-table truncate, cascade,
  CTE, comment-led statement, select, unreadable write.

## 2. Registry and guard

`games/projection_writers.py`:

- `class GuardedKind(StrEnum)`: `PROJECTION`, `VALUATION`.
- `class ProjectionWriter(StrEnum)`: seven members per spec table.
- `@dataclass(frozen=True, slots=True) PermittedWriter(module: ModulePath,
  kinds: frozenset[GuardedKind])`; `type ModulePath = str` (repo-relative).
- `PERMITTED_WRITERS: Mapping[ProjectionWriter, PermittedWriter]`.
- `guarded_tables() -> Mapping[TableName, GuardedKind]`, `lru_cache`d,
  from `projection_models()` + `PurchaseValuation`; lower-cased.
- `_open: ContextVar[ProjectionWriter | None]`;
  `projection_writes(writer)` contextmanager; `open_writer()` reader.
- `ProjectionWriteRefused(RuntimeError)`.
- `refuse_unpermitted_writes(execute, sql, params, many, context)`: the
  wrapper. `""` target → every kind.
- `install_guard(connection)`: insert at 0 unless present.
- `guarded_kinds_written(sql) -> frozenset[GuardedKind]` shared with the
  test door.

Gotcha: importing `projection_models` at module import may cycle with
`games.models`; resolve lazily inside `guarded_tables()`.

## 3. Wire installation and doors

- `games/apps.py` `ready()`: `connection_created.connect(_install,
  dispatch_uid=…)`, and install on already-open connections
  (`connections.all(initialized_only=True)`). `pre_migrate`/`post_migrate`
  receivers with `sender=self` around a module `ExitStack` (MIGRATE).
- `ProjectorRegistry.apply`: `with projection_writes(PROJECTOR):` around
  the loop.
- `swap_in`: around the cursor block.
- `games/retention.py` `purging_library()`: also enters `LIBRARY_PURGE`.
- `games/valuations.py` `publish_valuations`: around delete + bulk_create.
- `anonymize_sample`: `_prune_other_libraries`, `_anonymize`,
  `_reassign_uuids`.

## 4. Test door

`tests/projection_doors.py`:

- `_seeding_wrapper`: if `open_writer()` is None and
  `guarded_kinds_written(sql)`, walk `sys._getframe()`; source-tree
  classification relative to `settings.BASE_DIR`; skip this file's frames.
  Opens `projection_writes(TEST_SEEDING)` for the one statement.
- `_strict: ContextVar[bool]`; fixture `projection_guard_strict`.
- `install()`: `connection_created` receiver inserting the seeding wrapper
  directly before the guard (index of guard, else 0), plus open
  connections. Called at import of `tests/conftest.py` and
  `e2e/conftest.py` (or `pytest_configure`).

Gotcha: test DB creation runs migrate under MIGRATE; seeding wrapper
must not mask a missing MIGRATE door — it only opens when no door is open
and the frame rule allows; migration frames are `.venv`/`games/migrations`
(games → shut). `games/migrations/` counts as `games/`: correct, a
migration has MIGRATE.

## 5. Guard tests (`tests/test_projection_write_guard.py`)

- Parametrized over `guarded_tables()` models, strict: `filter(pk=…)
  .update(library_id=F("library_id"))`, `bulk_create([Model(pk=uuid7(),
  library_id=…)])`, raw `DELETE` → `ProjectionWriteRefused`; refused
  before SQL so invalid rows are fine. Row counts unchanged.
- `VALUATION_PUBLISHER` door writing a projection → refused;
  `PROJECTOR` writing valuation → refused.
- Connection opened inside `connection.execute_wrapper(noop)` keeps the
  guard after exit (thread with fresh connection).
- Reconnect does not duplicate the guard.
- Seeding: a write from a test frame passes; a write through a helper in
  `games/` (e.g. a tiny function defined in a module under `games/`? use
  `games.valuations.publish_valuations` with door removed via monkeypatch
  of `PERMITTED`? simpler: strict fixture covers app-frame semantics;
  unit-test the classifier on synthetic paths).
- MIGRATE: pre_migrate opens, post_migrate closes (send signals directly).

## 6. Completeness walk (`tests/test_projection_writers_registry.py`)

AST over `games/`, `common/`, `timetracker/`, `contrib/`, `scripts/`,
`tests/projection_doors.py`: every `projection_writes(...)` call; argument
must be `Attribute(Name("ProjectionWriter"), member)`; member's
`PERMITTED_WRITERS[...].module` equals the file; every member seen.
Also: every `ProjectionModel` is guarded (`guarded_tables` ⊇
`projection_models()`).

## 7. Full suite

Run `make check-fast`, then e2e. Every refusal is either a real bypass
(fix in app code via its writer) or a door gap (fix the spec). Measure
`make bench` before/after the guard.

## 8. Docs

CLAUDE.md conventions bullet: "Only named writers write a projection".
Delete this plan; rewrite the spec timeless.
