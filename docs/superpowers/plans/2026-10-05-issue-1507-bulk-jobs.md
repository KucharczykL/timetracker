# Plan: bulk acts as background jobs (#1507)

Spec: `docs/superpowers/specs/2026-10-05-issue-1507-bulk-jobs-design.md`.
Inline, TDD per behaviour. Iterate with `make check-fast` / focused
`make test ARGS=…` under the shared lock.

## 1. Model and migration

- `games/models.py`: `BulkBatch` beside `BatchChange`. `id` UUIDv7Field pk;
  `token` UUIDField; `library` FK CASCADE `related_name="+"`; `action`
  CharField(100); `undoes` UUIDField null; `choice` TextField blank default
  ""; `origin` TextField; `rows` JSONField; `position`, `total`, `done`,
  `unchanged`, `refused`, `lost`, `chunk`, `attempts` PositiveIntegerField
  default 0; `reasons` JSONField default list; `state` CharField with
  `TextChoices` (queued/running/finished/stopped/failed); `stop_requested_at`,
  `ended_at`, `announced_at` DateTimeField null; `created_at` auto_now_add,
  `updated_at` auto_now. Constraint unique `(library, token)`; index
  `(library, state)`.
- `make makemigrations ARGS="games --name bulk_batch"`.
- Pinned lists: `tests/test_uuid_identity_audit.py` (`EXPECTED_RELATION_COLUMNS`,
  `EXPECTED_IDENTITY_TABLES`), `tests/test_projection_rebuild.py:~1608`,
  any purge-count pin. Run the audit tests to find each.

## 2. Request-free runner `games/bulk_jobs.py`

- Move from `games/views/bulk.py`: `Tally` (drop `rows`; add `position`?
  no — the row holds keys and position; `Tally` keeps counts, reasons,
  total), `BatchAct`, `_forward`, `_backward`, `_undo_name`, log helpers,
  log sentences (`STOPPED_BY_HAND`, `ENDED_BY_A_DEFECT`, `MET_THE_DEFECT`),
  `_counted`, `CHUNK_BUDGET`.
- `start_batch(library, action, *, token, keys, tally, choice, origin,
  undoes=None) -> BulkBatch`: atomic create + `enqueue(batch.pk, 0)`;
  `IntegrityError` caught outside the block → existing row.
- `enqueue(batch_id, chunk)`: `async_task("games.tasks.run_bulk_batch",
  str(batch_id), chunk)`. Tests replace it.
- `run_chunk(batch_id, chunk)`: guards (state, chunk number), stop, attempts
  increment (cap 3 → failed), the row loop with per-row conditional update,
  chunk end transaction, defect handling incl. `BaseException` re-raise.
- `request_stop(library, token)`, `announce(library, token)`,
  `visible_batches(library)`, `batch_toast(batch) -> BatchToast`.
- `games/tasks.py`: `run_bulk_batch(batch_id: str, chunk: int)`.

Tests `tests/test_bulk_jobs.py`: every chunk runs (budget 0); Stop between
chunks; stale chunk number no-op; overtaken attempt stops; third start
fails; redelivery resumes at position; defect stores failed and logs;
timeout (raise `TimeoutException` from a run) stores failed and re-raises;
`batch_toast` per state, reasons in the tally text, Undo absent on Undo/zero-done/
unknown act.

## 3. Views

- `games/views/bulk.py`: press → settle choice → `start_batch` → redirect
  `return_url`. Confirmation unchanged (keeps TOKEN/PROGRESS hidden fields;
  progress now carries keys + pre-refused tally). Delete `_run_a_chunk`,
  `_progress`, `_answer`, `_defect`, STOP handling, `_of_this_batch`,
  `NOT_THIS_BATCH`. `_reconfirmation` keeps the settle-refusal re-ask only.
- Undo: refuse while the target batch row is not terminal (refused page);
  dedupe a non-terminal Undo of it; no rows → `notify` info + redirect;
  set target `announced_at`.
- `stop_bulk_batch(request, token)` POST, `owned` 404, `ORIGIN_AWARE`,
  url `bulk/batch/<uuid:token>/stop/` (before `bulk/<str:action>/`).
- `games/views/bulk_pages.py`: delete `ProgressBatch`.
- `games/api.py`: router `/bulk`: `GET /batches?tokens=` → list of
  `BatchOut {token, state, origin, toast}`; `POST /batches/{token}/announced`
  → 204, 404 for a foreign token.
- `common/layout.py`: inside `is_authenticated`, `data-bulk-batches` (JSON
  of `BatchOut`) and `data-bulk-batches-url`; load `dist/bulk-batch-status.js`
  and `dist/page-stale.js`.

## 4. TypeScript

- `ts/bulk-batch-status.ts`: coordinator; toast per batch, resend on change,
  sessionStorage dismissal for running, announce on terminal dismissal,
  poll 2 s while any non-terminal, dispatch `page:stale` on observed
  transition when `new URL(origin).pathname === location.pathname`.
- No `page-stale.ts`: #1384's `<form-dialog>` reloads on `page:stale`.
- After #1384: `<toast-stack>` fetches a bulk toast action with
  `X-Form-Dialog` while a form dialog is open; `done` shows messages in the
  top dialog and marks the stack dirty.
- Delete `ts/elements/continuing-batch.ts`, its test, its `register_element`
  entry; `make gen-element-types`.
- vitest beside each.

## 5. Test fixtures and rewrites

- `tests/conftest.py` + `e2e/conftest.py`: autouse patch of
  `games.bulk_jobs.enqueue` → queue + on_commit drain loop; `held_batches`
  fixture returns the queue and a `run_all()`.
- `tests/bulk_posts.py`: `press` posts confirmation + press; add
  `batch_of(response or token)` reader and `toast_text`.
- Rewrite message assertions across `tests/test_bulk_*.py`,
  `tests/test_session_reclassification_views.py`, `tests/test_session_release.py`
  to read the batch row / `batch_toast`. Delete waypoint/Stop-field tests;
  port their intent to `test_bulk_jobs.py`.
- Query-count pins: `tests/test_library_page_isolation.py`,
  `tests/test_purchase_finished_column.py`.
- e2e: `e2e/test_bulk_runner_e2e.py` gains held-batch Stop, close/reopen,
  Undo; per-act e2e files keep outcome assertions, adjusting where they wait
  on the old toast.

## 6. Dev and docs

- `Makefile` `dev`: add `"uv run --frozen manage.py qcluster"` to
  concurrently (name `Q`).
- CLAUDE.md bulk-runner paragraph; #713 spec amended; docs sweep later.

## Gotchas

- `ChoiceValue` "" means none; `_forward` maps "" → None.
- No dispatch inside the start/chunk-end atomic blocks.
- Inline hook must run after commit, else `run_in_transaction` refuses.
- `TimeoutException` import from `django_q.exceptions`.
- Toast action URL must start with `/`.
