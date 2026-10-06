# A toast action inside a dialog shows its batch at once

## Problem

A toast action that a person presses while a modal is open posts as a dialog
request (`postBehindModal`, `ts/elements/toast-stack.ts`). The Undo view
stores a new `BulkBatch` and redirects without a message. The answer is
`done` with no messages. The page reloads only when no modal is open. Without
more work, the new batch has no toast until that reload.

## Rule

After a `done` answer, `<toast-stack>` dispatches `page:stale`. The batch
coordinator (`ts/bulk-batch-status.ts`) listens for that event. It reads
`GET /api/bulk/batches` without `tokens`. That answer is
`visible_batches(library)`, the set that `Page()` embeds.

The coordinator then reconciles:

- It applies each batch in the answer. A new batch shows its toast and starts
  the poll.
- It forgets each known batch that the answer does not contain, and removes
  its toast.

After a reconcile, the toasts are the toasts a reload shows. These results
follow from the rule:

- Undo marks the batch it undoes as seen. That batch leaves the set, so the
  toast whose Undo the person pressed goes away.
- Stop records the stop request before it answers. The toast says
  "stopping." at once and has no Stop.
- A dismissed running batch stays hidden, as on a load.
- A non-sticky end, or an end older than `ANNOUNCE_WINDOW`, goes away. A
  reload does not show it either.

## Route

`tokens` is `str | None`. An absent parameter answers the visible batches.
An empty `tokens=` answers `[]`. The poll always names its tokens.

## Guards

- The coordinator ignores the `page:stale` that it dispatches itself.
- It listens only when the page states `data-bulk-batches-url`. `destroy()`
  removes the listener.
- `apply` never changes a known terminal batch back to live. A late answer
  that was read before the end must not show the Stop toast again or fire a
  second end.
- Only the latest reconcile's answer applies. An older answer can omit a
  batch that a newer action started.
- One poll at most is in flight. `scheduleNext` sets no timer while a poll
  runs.
- A failed reconcile logs and changes nothing. It shows no warning and does
  not count as a poll failure, because the next load shows the batches.

## Accepted

A reconcile shows every visible batch of the library. It can push the newest
dialog messages past the three-toast limit. A load does the same.

## Not chosen

- An "Undoing …" message from the Undo view. It puts a second wording beside
  the coordinator's toast.
- A dedicated event from `<toast-stack>`. `page:stale` already means "shown
  data changed on the server", and the batch list is shown data.

## Tests

- `tests/test_bulk_jobs.py`: absent `tokens` answers the visible batches;
  `tokens=` answers `[]`.
- `ts/bulk-batch-status.test.ts`: the reconcile, each guard, and its failure.
- `e2e/test_bulk_runner_e2e.py`: Undo pressed inside a dialog shows the
  running Undo batch, with Stop, while the dialog stays open.
