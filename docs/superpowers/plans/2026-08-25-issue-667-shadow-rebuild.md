# Shadow projection rebuild and atomic swap — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild a library's event-sourced projections into private shadow tables and swap them into place in one transaction that asserts no event landed while the rebuild worked.

**Architecture:** Per attempt: manufacture a temp-table twin of every `ProjectionModel`, replay the stream through a projector registry pointed at those twins with a write guard armed, diff the result against live, then (rebuild mode) lock the stream, `require_sequence(folded_through)`, and delete-and-reinsert this library's rows. A conflict redoes the whole attempt, because the expectation is what went stale.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django.

Spec: [2026-08-25-issue-667-shadow-rebuild-design.md](../specs/2026-08-25-issue-667-shadow-rebuild-design.md). Read it before Task 1 — it carries the probe results and the reasoning behind every choice below, and this plan does not repeat them.

## Global Constraints

- **Drive everything through `make`.** `make test ARGS="tests/test_x.py -k name -x" PYTEST_WORKERS=0` for focused runs. Never `uv run pytest`, never `direnv exec .`.
- **Python 3.14.** PEP 758 `except A, B:` is valid here; ruff 0.16 formats to it.
- **No migration, no schema change.** `ProjectionModel` is abstract. If a step produces a migration, the step is wrong.
- **Name variables with complete words** (`element`, not `el`). Comments explain obscure intent only, never issue or PR numbers.
- **Test models use `@isolate_apps("games")`** and are created with `schema_editor`. Passing them to the rebuild means passing `Model._meta.apps` — never the global registry.
- **The gate is the full `make check`**, including `e2e/`. `make check-fast` while iterating.
- Every task ends green and committed. Commit messages: imperative subject ≤50 chars, body only where the "why" is not obvious.

## File structure

| File | Responsibility |
| --- | --- |
| `games/models.py` (modify) | `ProjectionModel` abstract base, beside `UserLibrary` (~line 1187) |
| `games/checks.py` (create) | The system check over `ProjectionModel` subclasses |
| `games/apps.py` (modify) | Import `games.checks` in `ready()` |
| `games/events/targets.py` (create) | `ProjectionTarget`, `LIVE_TARGET`, `ShadowTarget` — model manufacture and cache |
| `games/events/projection.py` (modify) | `Projector.__init__(target=...)`, `register(..., target=...)`, `for_target()` |
| `games/events/rebuild.py` (create) | Discovery, DDL, guard, phases, diff, swap, retry, report |
| `games/management/commands/rebuild_projections.py` (create) | Argument parsing and printing only |
| `tests/test_projection_model.py` (create) | The base and the system check |
| `tests/test_projection_targets.py` (create) | Manufacture, caching, `run_checks()` cleanliness |
| `tests/test_projection_rebuild.py` (create) | Everything from discovery through the command |

`rebuild.py` is the one file that will grow. Keep it sectioned in the phase order the spec names; if it passes ~600 lines, split the diff into `games/events/projection_diff.py` and nothing else.

---

### Task 1: `ProjectionModel` and the purity check

**Files:**
- Modify: `games/models.py` (add beside `UserLibrary`, ~1187), `games/apps.py:16`
- Create: `games/checks.py`
- Test: `tests/test_projection_model.py`

**Interfaces:**
- Produces: `games.models.ProjectionModel` (abstract, field `library` → `UserLibrary`, `on_delete=CASCADE`, `related_name` chosen per repo convention); `games.checks.check_projection_models(app_configs, **kwargs) -> list[CheckMessage]` registered with `@register()`.

- [x] **Step 1: Write the failing tests.** In `tests/test_projection_model.py`, under `@isolate_apps("games")`, declare one conforming projection model (explicit `UUIDField(primary_key=True)`, no defaults) and one offender per rule. Assert `check_projection_models(None)` returns exactly the expected error ids for: `auto_now`, `auto_now_add`, an implicit `AutoField` primary key (declare no pk at all), any `db_default`, and `default=uuid.uuid4`. Assert the conforming model produces `[]`. Add one test that a subclass inheriting `auto_now` from an intermediate abstract base is still caught — `_meta.local_fields` sees it, and that is the property being pinned.
- [x] **Step 2: Run them.** `make test ARGS="tests/test_projection_model.py -x -q" PYTEST_WORKERS=0`. Expected: `ImportError` / `ModuleNotFoundError` on `games.checks`.
- [x] **Step 3: Implement.** `ProjectionModel` in `games/models.py`; `check_projection_models` in `games/checks.py` walking `apps.get_models()` for `issubclass(model, ProjectionModel)` and `model._meta.local_fields`. Distinct error ids per rule (`games.E001`…`games.E005`) so the tests name them. Import `games.checks` from `GamesConfig.ready()` for its registration side effect, in the existing `from games import projectors, signals` line's spirit.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.** `git add games/models.py games/checks.py games/apps.py tests/test_projection_model.py`

**Gotchas:** The check must skip abstract models and the shadow twins Task 2 manufactures (they are `managed = False` and carry the same fields — excluded by `model._meta.managed`). A `db_default` is `field.db_default` and is `NOT_PROVIDED` when unset, not `None`.

---

### Task 2: `ShadowTarget` — manufacturing a twin

**Files:**
- Create: `games/events/targets.py`
- Test: `tests/test_projection_targets.py`

**Interfaces:**
- Consumes: `games.models.ProjectionModel`.
- Produces: `ProjectionTarget` (Protocol, `def model[M: ProjectionModel](self, model: type[M]) -> type[M]`), `LIVE_TARGET`, `ShadowTarget()` with `.model(...)` and `SHADOW_SUFFIX = "__shadow"`.

- [x] **Step 1: Write the failing tests.** Under `@isolate_apps("games")`: a projection model with a `library` FK, a nullable column, a `GeneratedField`, and a child model with an FK to the parent. Assert (a) `ShadowTarget().model(Parent)` returns a class whose `_meta.db_table` is `"<live table>__shadow"`, `managed` is `False`, and whose concrete field names equal the live model's; (b) calling it twice returns the *same* class; (c) `LIVE_TARGET.model(Parent) is Parent`; (d) **`django.core.checks.run_checks()` is empty afterwards, and `Parent.check()` is empty** — the `fields.E304` regression; (e) the `GeneratedField` survives onto the twin, or, if it cannot, that `ShadowTarget.model` raises a named error instead of producing a broken class.
- [x] **Step 2: Run them.** Expected: FAIL on the missing module.
- [x] **Step 3: Implement.** Manufacture with `type(name, (models.Model,), namespace)`. Each field is rebuilt from `field.deconstruct()` — `name, path, args, kwargs = field.deconstruct()`, then `field.__class__(*args, **{**kwargs, "related_name": "+"})` for relations. **Do not deep-copy and mutate `related_name`**: `ForeignObjectRel.hidden` is a `cached_property` and the mutation is invisible, which reds the live model's checks too. `Meta` carries `app_label = "games"`, `managed = False`, `db_table`, and `apps = live_model._meta.apps` so a twin of an isolated model lands in the isolated registry.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

**Gotchas:** The cache key is the live model class, and the cache must be per-registry, not one global dict — otherwise an `isolate_apps` test poisons the next one with a twin pointing at a dead registry. `GeneratedField.deconstruct()` returns an `expression` that resolves against its model; if it fails to attach, prefer the named error in (e) over a silent half-model, and record the outcome in the spec's open question.

---

### Task 3: Registry targeting

**Files:**
- Modify: `games/events/projection.py:100-120` (`register`), `:160-190` (`Projector`)
- Test: `tests/test_event_projectors.py` (extend)

**Interfaces:**
- Consumes: Task 2's `ProjectionTarget`, `LIVE_TARGET`.
- Produces: `Projector.__init__(self, target: ProjectionTarget = LIVE_TARGET)` storing `self.target`; `ProjectorRegistry.register(cls, *, target=LIVE_TARGET)`; `ProjectorRegistry.for_target(target) -> ProjectorRegistry`.

- [x] **Step 1: Write the failing tests.** In `tests/test_event_projectors.py`: families registered into a module-owned registry; assert every family in `registry.for_target(shadow)` holds that target while the original registry's families still hold `LIVE_TARGET`; assert the sibling resolves the same handlers in the same `ProjectorFamily` order; assert a family's handler, when applied, writes through `self.target`.
- [x] **Step 2: Run them.** Expected: FAIL — `Projector()` takes no arguments.
- [x] **Step 3: Implement.** Keep the registered classes on the registry so `for_target` can build a sibling directly; do not route `for_target` through `register`, whose duplicate-claim guard would reject the same classes a second time. Update the two comments that promise zero-argument instantiation (`projection.py:112` and the `Projector` docstring) — left as-is they become lies.
- [x] **Step 4: Run them again.** Expected: PASS. Also run `make test ARGS="tests/test_event_append.py tests/test_event_replay.py tests/test_event_dispatch.py -q" PYTEST_WORKERS=0` — `DEFAULT_REGISTRY` behaviour must be unchanged.
- [x] **Step 5: Commit.**

**Gotchas:** `__init_subclass__` registers at class-definition time and must keep working with no target argument. `for_target` returns a registry whose `_claims` are copied, not re-derived.

---

### Task 4: Discovery and shadow DDL

**Files:**
- Create: `games/events/rebuild.py`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Produces: `projection_models(apps: Apps = global_apps) -> tuple[type[ProjectionModel], ...]`; `shadow_tables(models) -> AbstractContextManager[None]` creating the temp tables on enter and dropping them on exit; `insertable_columns(model) -> tuple[str, ...]` (concrete columns minus generated ones).

- [x] **Step 1: Write the failing tests.** Under `@isolate_apps("games")` with `schema_editor`-created models: `projection_models(Model._meta.apps)` returns the projection models and **not** their `managed=False` twins, and returns `()` for the global registry today. Inside `shadow_tables(...)`: the temp table exists (`to_regclass('pg_temp."<t>__shadow"')`), carries the live table's indexes, carries **no** `contype = 'f'` constraint, and is gone after the block — including when the block raises. `insertable_columns` omits a `GeneratedField`'s column and keeps the rest in table order.
- [x] **Step 2: Run them.** Expected: FAIL on the missing module.
- [x] **Step 3: Implement.** DDL is exactly `CREATE TEMP TABLE "<table>__shadow" (LIKE "<table>" INCLUDING ALL)`, one statement per model, and `DROP TABLE IF EXISTS` in a `finally`. Table names come from `model._meta.db_table`; quote them, never interpolate a caller's string.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

**Gotchas:** Everything in this task and the four that follow must run on **one connection** — the default one. Do not open a second alias, and do not call `connection.close()` between phases; the temp tables live on the session.

---

### Task 5: The write guard

**Files:**
- Modify: `games/events/rebuild.py`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Produces: `LiveWriteRefused(RuntimeError)`; `only_shadow_writes(models) -> AbstractContextManager[None]` installing a `connection.execute_wrapper`.

- [x] **Step 1: Write the failing tests.** Inside `only_shadow_writes([...])`, assert `LiveWriteRefused` for each of: `Model.objects.create(...)`, `Model.objects.bulk_create([...])`, `Model.objects.filter(...).update(...)`, `Model.objects.bulk_update([...], [...])`, `Model.objects.filter(...).delete()`, and a raw `INSERT` through `connection.cursor()`. Assert a write to the `__shadow` table is **allowed**, that a plain `SELECT` on the live table is allowed, and that all six paths work normally once the block exits. These five write paths are the whole point of the mechanism — a signal-based guard passes only the first.
- [x] **Step 2: Run them.** Expected: FAIL — writes succeed.
- [x] **Step 3: Implement.** `with connection.execute_wrapper(refuse_non_shadow_writes)`. The wrapper inspects the statement: if its first keyword is `INSERT`/`UPDATE`/`DELETE`/`COPY`/`TRUNCATE` and it names any quoted live projection table, raise `LiveWriteRefused` naming the table and the statement's first 200 characters. Match the **quoted** identifier (`"games_x"`), so `"games_x__shadow"` is not a false hit.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

**Gotchas:** The wrapper must let Django's own bookkeeping through — savepoints, `SET`, and the temp-table DDL are not write statements by this rule. Raise from the wrapper rather than returning; `execute_wrapper` propagates.

---

### Task 6: Phase 2 — replay into the shadow

**Files:**
- Modify: `games/events/rebuild.py`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Produces: `replay_into_shadow(library, models, *, wiring) -> ReplayResult` — one `transaction.atomic()` containing `shadow_tables` already entered by the caller, `only_shadow_writes` armed, and `replay(library, wiring=replace(wiring, projectors=wiring.projectors.for_target(ShadowTarget())))`.

- [x] **Step 1: Write the failing tests.** With a test family writing its target: dispatch commands appending several events, then call `replay_into_shadow`; assert the shadow table holds the projected rows, the live table is untouched, and `folded_through` equals the head. Assert a family that writes its live model raises `LiveWriteRefused` out of this function. Assert `StreamNotContiguous` from a deleted middle event propagates with its type intact.
- [x] **Step 2: Run them.** Expected: FAIL.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

**Gotchas:** The `atomic()` wrap is deliberate — in autocommit every shadow row is its own transaction. It also makes replay's cursor non-holdable, which is fine. Do **not** hold this transaction open into Task 8's swap: they are separate transactions, in sequence.

---

### Task 7: The diff

**Files:**
- Modify: `games/events/rebuild.py`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True, slots=True) TableDiff(table: str, live_rows: int, rebuilt_rows: int, only_live: int, only_rebuilt: int, differing: int, sample: tuple[str, ...])`; `diff_table(model, library) -> TableDiff`; `diff_tables(models, library) -> tuple[TableDiff, ...]`.

- [x] **Step 1: Write the failing tests.** Live and shadow identical → all counts zero. A row only live → `only_live == 1`. A row only in the shadow → `only_rebuilt == 1`. A changed column → `differing == 1`. **A column that is NULL live and set in the shadow, and the reverse → `differing == 1` in both directions** (the null-safety pin). A second library's rows in the live table change nothing. `sample` is bounded when 50 rows differ.
- [x] **Step 2: Run them.** Expected: FAIL.
- [x] **Step 3: Implement.** One query per table:

```sql
SELECT ... FROM (SELECT * FROM "<table>" WHERE library_id = %s) live
FULL OUTER JOIN "<table>__shadow" shadow ON live."<pk>" = shadow."<pk>"
```

with the differing test as **whole-row** `(live.*) IS DISTINCT FROM (shadow.*)`. Two details are load-bearing and were probed: `ROW(a, b) <> ROW(c, d)` returns NULL when either side is NULL and the row is silently dropped, and putting `library_id = %s` in `WHERE` instead of the subquery degrades the outer join and hides the rebuilt-only rows.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

**Gotchas:** The shadow holds only this library, so it needs no scope of its own. Aggregate the four counts and the sample in one statement; a per-count query multiplies the table count by four.

---

### Task 8: The swap

**Files:**
- Modify: `games/events/rebuild.py`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Produces: `swap_in(library, models, folded_through) -> None` — raises `StreamSequenceMismatch` when the head moved.

- [x] **Step 1: Write the failing tests.** After a shadow replay: `swap_in` makes the live rows equal the shadow rows; a second library's rows are byte-identical afterwards; a corrupted live row is corrected. Append an event after the replay and assert `StreamSequenceMismatch` with the live rows unchanged. For a library that never appended: `swap_in` empties its projections, inserts nothing, and a head row now exists. Pin the query count with `django_assert_num_queries` at two library sizes — one `DELETE` and one `INSERT` per table, plus the lock and the head read.
- [x] **Step 2: Run them.** Expected: FAIL.
- [x] **Step 3: Implement.** `transaction.atomic()` → `lock_stream(library)` → `require_sequence(folded_through)` → per table `DELETE FROM "<t>" WHERE library_id = %s` → per table `INSERT INTO "<t>" (cols) SELECT cols FROM "<t>__shadow"`, with `cols` from `insertable_columns` (generated columns are refused by PostgreSQL and recompute identically). Raw DML, not `QuerySet.delete()`.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

**Gotchas:** Order across tables does not matter — every FK Django's schema editor emits is `DEFERRABLE INITIALLY DEFERRED`, so violations surface at `COMMIT`. Do not add ordering logic to "be safe"; it would imply a guarantee the deferral already provides and the spec's no-inbound-FK rule already relies on.

---

### Task 9: The attempt loop and the report

**Files:**
- Modify: `games/events/rebuild.py`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Produces: `RebuildMode(StrEnum)` (`CHECK`, `REBUILD`); `RebuildAttempt(folded_through, replay_seconds, diff_seconds, swap_seconds: float | None, conflict: str | None)`; `RebuildReport(library_id, stream_id: uuid.UUID | None, mode, swapped: bool, folded_through, head_at_diff, tables, attempts, elapsed_seconds)`; `rebuild_projections(library, *, mode=RebuildMode.CHECK, wiring=DEFAULT_WIRING, apps=global_apps) -> RebuildReport`.

- [x] **Step 1: Write the failing tests.** An append landing between replay and swap produces one conflicting attempt and one that swaps; the report carries two `RebuildAttempt`s and the sleeps come from an injected `RetryPolicy` (assert the recorded delays, using the policy's `sleep`/`random` fields as `tests/test_event_retry.py` does). An always-conflicting stream exhausts the budget: `swapped is False`, the conflict recorded, live rows untouched. `CHECK` mode: diffs are populated, `swapped is False`, live rows unchanged, no shadow table survives, and `head_at_diff` is reported (assert it differs from `folded_through` when an append lands during the diff). A never-appended library returns `stream_id=None` in check mode.
- [x] **Step 2: Run them.** Expected: FAIL.
- [x] **Step 3: Implement.** Loop `retry_policy.retries + 1` attempts; catch only `StreamSequenceMismatch`; sleep `retry_policy.delay_for(attempt)`; fresh `shadow_tables` per attempt. Do not reach for `run_in_transaction` — it classifies on SQLSTATE and would decline this exception, correctly.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

---

### Task 10: The management command

**Files:**
- Create: `games/management/commands/rebuild_projections.py`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Consumes: `rebuild_projections`, `RebuildReport`.
- Produces: `manage.py rebuild_projections <library-uuid> [--check]`.

- [x] **Step 1: Write the failing tests.** `call_command` with a library uuid and `--check` prints the per-table counts, the event count and the elapsed time, and writes nothing. Without `--check` it swaps and exits zero. A conflict-exhausted rebuild exits non-zero (`CommandError`). An unknown library uuid exits non-zero without touching anything.
- [x] **Step 2: Run them.** Expected: FAIL.
- [x] **Step 3: Implement.** Argument parsing, `self.stdout.write`, and nothing else — the command holds no logic. Follow `games/management/commands/audit_uuid_identity.py` for output shape and exit conventions.
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit.**

---

### Task 11: Registry hygiene and the gate

**Files:**
- Modify: `tests/test_projection_rebuild.py`
- Test: existing `tests/test_uuid_identity_audit.py`

- [x] **Step 1: Write the failing test.** In `tests/test_projection_rebuild.py`, after a full rebuild has run and cached its shadow twins, assert (a) `django.core.checks.run_checks()` is empty, and (b) `{relation.key for relation in relation_columns()}` still equals `EXPECTED_RELATION_COLUMNS` from `tests/test_uuid_identity_audit.py:76`. Both are leak detectors: an un-isolated test model or a globally-cached twin breaks the audit, and `test_projection_rebuild.py` sorts *before* `test_uuid_identity_audit.py` in the same process under CI's `PYTEST_WORKERS=0`.
- [x] **Step 2: Run it.** Expected: PASS if Tasks 1–10 respected `isolate_apps`; FAIL loudly if not, which is the point.
- [x] **Step 3: Run the real gate.** `make check`. Expected: green, including `e2e/`. Do not gate on a subset.
- [x] **Step 4: Commit.**

---

## Notes for the dispatcher

Batch roughly three tasks per implementer dispatch (1–3, 4–6, 7–9, 10–11); the controller owns `make check` and runs it once per batch, not once per task. Tasks 1–3 are independent of 4–11 and could run in parallel with nothing but the interface block above shared. Task 2's step (e) may return a finding rather than an implementation — if `GeneratedField` cannot survive the manufacture, that is a spec amendment, not a workaround to invent in the moment.
