# A toast action inside a dialog shows its batch at once

## Problem

A toast action pressed while a modal is open posts as a dialog
request (`postBehindModal`, `ts/elements/toast-stack.ts`). The Undo view
stores a new `BulkBatch` and redirects without a message. The answer is
`done` with no messages. The page reloads only when no modal is open. Without
more work, the new batch has no toast until that reload.

## Rule

After a `done` or `created` answer, `<toast-stack>` dispatches `page:stale`. The batch
coordinator (`ts/bulk-batch-status.ts`) listens for that event. It reads
`GET /api/bulk/batches` without `tokens`. That answer is
`visible_batches(library)`, the set that `Page()` embeds.

The coordinator then reconciles:

- It applies each batch in the answer. A new batch shows its toast and starts
  the poll.
- It forgets each known running batch or sticky end that the answer does not
  contain, removes its toast, and logs the token.

After a reconcile, the toasts are the toasts a reload shows. These results
follow from the rule:

- Undo marks the batch it undoes as seen. That batch leaves the set, so the
  toast whose Undo the person pressed goes away.
- Stop records the stop request before it answers. The toast says
  "stopping." at once and has no Stop.
- Stop on an ended batch changes nothing and says so (`StopAnswer`). A
  batch that ends while Stop reads it counts as ended.
- A dismissed running batch stays hidden, as on a load.
- A sticky end older than `ANNOUNCE_WINDOW` goes away. A reload does not
  show it either.
- A non-sticky end marks itself seen when it shows, so the answer omits it.
  Its toast stays until its own timer ends.

## Route

`tokens` is `str | None`. Absent, it answers the visible batches; empty, `[]`.

## Guards

- The coordinator ignores the `page:stale` that it dispatches itself.
- It listens only when the page states `data-bulk-batches-url`. `destroy()`
  removes the listener.
- `apply` never changes a known terminal batch back to live. A late answer
  that was read before the end must not show the Stop toast again or fire a
  second end.
- Only the latest reconcile's answer applies. An older answer can omit a
  batch that a newer action started.
- A poll applies only batches the coordinator still holds. A poll answer
  that arrives after a reconcile forgot a batch does not show it again.
- One poll at most is in flight. `scheduleNext` sets no timer while a poll
  runs.
- A failed reconcile changes nothing and goes to `reportClientError`. It
  does not count as a poll failure. A refused session (401, 403) shows the
  poll's warning, because the person must reload. An answered reconcile
  clears the failure count and that warning.

## Not chosen

- An "Undoing …" message from the Undo view: a second wording.
- A dedicated event: `page:stale` already means "shown data changed".

## Tests

`tests/test_bulk_jobs.py` holds the route. `ts/bulk-batch-status.test.ts` holds
each guard. `e2e/test_bulk_runner_e2e.py` presses Undo inside a dialog.
