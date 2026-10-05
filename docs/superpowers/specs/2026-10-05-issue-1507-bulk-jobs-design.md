# Bulk acts run as background jobs

A bulk act runs in the django-q cluster. [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md) states the
declaration, the confirmation, the keys and the Undo.

## The batch row

`BulkBatch` (`games/models.py`) holds one batch. `token` is the correlation id, unique in a library. `rows`
holds the keys, and the runner writes it once. `position` is the index of the
next key. `state` is `queued`, `running`, `finished`, `stopped` or
`failed`. CHECK constraints bind `ended_at` to an ended state and
`position` to `total`. After the creation, every writer writes named columns
through `QuerySet.update()`, fenced by `chunk` and `attempts`, and never
touches an ended row.

## Starting

The press settles the act's choice, then stores the row and queues chunk 0
in one transaction. A token
pressed twice stores one row. A tally field with a negative or non-integer
count is refused. The press redirects to its origin.

An Undo reads its rows on the server. It is refused while its batch runs. A
partial unique constraint lets one Undo of a batch run at a time. An Undo
with no rows posts a message. An Undo of an Undo is refused with its own
sentence. An older batch's act comes from its events or ledger.

## Running

`games.tasks.run_bulk_batch` calls `run_chunk` (`games/bulk_jobs.py`). A stale
chunk number or an ended batch does nothing. A Stop ends the batch before the
chunk and bumps `attempts`, so a run in flight stops. Each row is its own
keyed dispatch, then a tally write; a run another delivery overtook stops. A
chunk that ends with rows left queues the next, in one transaction.

A defect stores `failed`. The cluster's timeout is a `BaseException`; the
runner stores `failed`, then raises it again. A chunk that starts a third time
stores `failed`. The log names every row left alone.

A live batch silent for `STALE_AFTER` has no worker; its toast says so, and
Stop or Undo ends it.

## Following

`Page()` puts the library's batches in `data-bulk-batches`: every running
batch, and every end not seen within `ANNOUNCE_WINDOW`. `ts/bulk-batch-status.ts`
shows one toast for each batch and polls `/api/bulk/batches` every two
seconds while one runs. `batch_toast` writes each toast: Stop while live,
Undo where a row moved. A dismissed end posts
`/api/bulk/batches/{token}/announced`, and so does an end whose toast closes
on its own timer. A dismissed live toast stays dismissed for this tab. A batch
the poll drops is forgotten. Failed polls back off, and then a toast says so.

When a running batch ends, and its origin path is this page, the coordinator
dispatches `page:stale` on `document`; `<form-dialog>` reloads the page once no
modal is open. While a modal is open, `<toast-stack>` posts a toast's action
with `X-Form-Dialog: 1`. A `done` answer shows its messages and dispatches
`page:stale`; any other answer posts the form natively.

## Tests

`tests/bulk_batches.py` runs queued chunks on commit; `held_batches` keeps
them. A batch that ends
`failed` fails the test unless it asks for `failing_batches`.
`ts/bulk-batch-status.fixtures.json` holds every `batch_out` shape for
vitest.
