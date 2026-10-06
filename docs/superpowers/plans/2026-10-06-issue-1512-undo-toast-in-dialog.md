# #1512 plan: an Undo inside a dialog shows its batch at once

Spec: [2026-10-06-issue-1512-undo-toast-in-dialog-design.md](../specs/2026-10-06-issue-1512-undo-toast-in-dialog-design.md)

## Task 1 — route answers visible batches when `tokens` is absent

Files: `games/api.py` (`bulk_batches`), `tests/test_bulk_jobs.py`.

- Signature `tokens: str | None = None`; `None` → `visible_batches(library)`;
  otherwise parse as today (empty string → `[]`).
- Docstring ≤ 7 words.
- Tests (red first):
  - `test_the_api_answers_the_visible_batches_without_tokens`: running +
    unseen end + announced end + other library's running → tokens of the
    first two, in `created_at` order.
  - `test_the_api_answers_nothing_for_an_empty_token_list`: `tokens=""` → `[]`
    with a running batch present.

## Task 2 — coordinator reconciles on `page:stale`

File: `ts/bulk-batch-status.ts`, tests in `ts/bulk-batch-status.test.ts`.

- `onPageStale` bound in constructor; `document.addEventListener(PAGE_STALE)`
  only when `statusUrl`; removed in `destroy()`.
- `dispatchingStale` flag around the coordinator's own `dispatchEvent`;
  listener returns while set.
- `reconcile()`: `reconciliation += 1`, keep the number; fetch
  `statusUrl` with `Accept: application/json`, no query; on non-ok / non-list
  log `console.error` and return (no failure count, no toast); drop the answer
  if the number is not the latest or destroyed; `apply` each; `forget` each
  known token the answer omits; `scheduleNext()`.
- `apply`: if held is terminal and the answer is not, return without change.
- `polling` flag set across `poll()`; `scheduleNext` returns while set; poll
  clears it before its own `scheduleNext` (also on the `PollRefused` return).
- vitest cases (red first):
  - page:stale fetches `/api/bulk/batches` once, without `tokens`.
  - new running batch from the answer is toasted and then polled by token.
  - known batch absent from the answer → `removeToast(id)`.
  - own page:stale (batch ends via poll) → fetch count stays 1 (existing test
    still holds; add an explicit reconcile-fetch assertion).
  - late running answer after a known end → no second toast, no restart.
  - two reconciles, first answer resolves last → first dropped.
  - reconcile during an in-flight poll → no second poll request.
  - failed reconcile → `toast` not called with the poll warning.
  - no `data-bulk-batches-url` → page:stale fetches nothing.

## Task 3 — e2e

File: `e2e/test_bulk_runner_e2e.py`.

- `test_an_undo_inside_a_dialog_shows_its_batch_at_once` (`held_batches`):
  run act via `held_batches.run_all()` → "2 of 2 done." with Undo; open a
  dialog (inject a `data-form-dialog` link to a read-only-safe form page, as
  `e2e/test_form_dialog_e2e.py` does, e.g. the device edit or add page);
  inside the dialog's Notifications region press Undo; expect the Undo
  batch's "waiting to start." toast with a Stop button inside the open
  dialog, and the finished toast's Undo gone; dialog still open.

## Gotchas

- `make ts` after editing `.ts` before e2e.
- Module starts a coordinator on import in vitest: the no-route guard keeps
  it from fetching.
- e2e: chunks drain on commit unless `held_batches`.
