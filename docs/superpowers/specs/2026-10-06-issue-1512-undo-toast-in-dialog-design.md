# An Undo inside a dialog shows its batch at once (#1512)

Part of #1485. After #1507.

## Problem

A toast action pressed while a modal is open posts as a dialog request
(`postBehindModal`, `ts/elements/toast-stack.ts`). The Undo view stores a new
`BulkBatch` and redirects with no message, so the answer is
`done {url, messages: []}`. `<toast-stack>` shows nothing and dispatches
`page:stale`. The coordinator (`ts/bulk-batch-status.ts`) learns batches only
from `data-bulk-batches` at load and from polls of tokens it already holds, so
the Undo batch stays invisible until the host reloads, after the last modal
closes.

## Design

**The coordinator reconciles on `page:stale`.** It listens for `page:stale` on
`document`. On the event it reads the library's visible batches from the
server, the same set `Page()` embeds, and reconciles:

- each answered batch is applied, as a poll applies it: a new one shows its
  toast and starts the poll loop; a known one updates;
- each known batch the answer omits is forgotten, its toast removed.

After a reconcile the toasts are what a reload would show. Two cases follow
from that rule and need no code of their own:

- Undo announces the batch it undoes (`undo_bulk_action` calls `announce`).
  The announced batch leaves `visible_batches`, so its toast, the one whose
  Undo was pressed, leaves too. Without the reconcile it would stay, Undo
  button and all, until the reload.
- Stop stamps `stop_requested_at` before it answers, so the reconcile's
  toast already says "stopping." and drops its Stop at once. Where the batch
  had no worker, Stop ends it, and the reconcile applies that end like a poll
  would.
- A running batch whose toast the person dismissed stays hidden, as on a
  load; `forget` leaves its dismissal key.

Two removals follow from the same rule, and both are accepted, since a
reload would not show either toast:

- A non-sticky terminal toast announces itself when shown, so a reconcile
  during its timer removes it early.
- A sticky end the person never dismissed leaves `visible_batches` after
  `ANNOUNCE_WINDOW`, so a reconcile on a page open that long removes it.

**The route answers visible batches when no token is named.**
`GET /api/bulk/batches` keeps `tokens` for the poll, now typed
`str | None = None` so absence is visible. With the parameter absent it
answers `visible_batches(library)`. An empty `tokens=` still
answers `[]`: the poll never sends one, and an absent parameter is the one
spelling of "everything".

**The coordinator ignores its own `page:stale`.** It dispatches the event
itself when a batch from this page ends. A flag held around that synchronous
dispatch skips the reconcile; the poll that saw the end already holds the
current state.

**No listener without a route.** The module starts a coordinator on import.
With no `data-bulk-batches-url` the listener returns at once, and `destroy()`
removes it.

**Concurrency.** A reconcile and a poll may overlap, and their answers may
arrive in either order. Two rules keep the state monotonic:

- `apply` never steps a held terminal batch back to live. A late answer read
  before the end would otherwise show the Stop toast again, restart polling,
  and fire `page:stale` and the end toast a second time.
- One poll is in flight at most. `scheduleNext` sets no timer while a poll
  runs; the poll schedules the next one when it ends. Failure counting stays
  per poll.

- Only the latest reconcile's answer applies. Each reconcile takes the next
  number; an answer whose number is no longer the latest is dropped. Without
  it, an answer read before a second toast action's batch existed could land
  after that batch was applied and forget it.

A reconcile that fails logs and changes nothing; the page's own reload remains
the fallback, so it counts toward no poll failure and shows no warning.

## Not chosen

- The Undo view queuing an "Undoing …" message for `done` to carry. Smaller,
  but a second wording beside the coordinator's toast.
- A dedicated event from `<toast-stack>`. `page:stale` already means "shown
  data changed on the server", and the batch list is shown data; any later
  dispatcher gets the same reconcile without another listener.

`<form-dialog>` reloads on `page:stale` only on a read-only host, and only once
no modal is open; on a form host, or a page with no `<form-dialog>`, nothing
reloads. The reconcile is then the only path that shows the new batch. The
coordinator skips its own dispatch, so no reconcile races its own reload.

A library-wide reconcile can push the dialog's newest messages past the
stack's three-toast limit. A load does the same; this is accepted.

## Tests

- vitest (`ts/bulk-batch-status.test.ts`): `page:stale` fetches the route
  without `tokens`; a new running batch is shown and polled; a known batch
  absent from the answer is forgotten and its toast removed; the
  coordinator's own `page:stale` fetches nothing; a late live answer does not
  undo a known end; a stale reconcile answer is dropped; no second poll starts while one is in flight; a failed
  reconcile shows no warning; no route, no fetch.
- pytest (`tests/test_bulk_jobs.py`): absent `tokens`
  answers the visible batches; `tokens=` answers `[]`.
- e2e, with `held_batches` so the Undo batch stays running: open a dialog,
  raise a bulk act's Undo toast inside it, press Undo, and see the Undo
  batch's running toast and its Stop in the dialog before closing it. No e2e
  covers a toast action inside a dialog today.
