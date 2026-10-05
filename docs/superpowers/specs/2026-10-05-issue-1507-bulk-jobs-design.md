# Bulk acts run as background jobs

A bulk act runs in the django-q cluster. The page that started it does not
wait. [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md) states the
declaration, the confirmation, the keys and the Undo.

## The batch row

`BulkBatch` (`games/models.py`) holds one batch. It is a conventional row. It
writes no event. `token` is the correlation id, unique in a library. `rows`
holds the keys, and the runner writes it once. `position` is the index of the
next key. The tally columns are `total`, `done`, `unchanged`, `refused`, `lost`
and `reasons`. `state` is `queued`, `running`, `finished`, `stopped` or
`failed`. Every writer writes named columns through `QuerySet.update()`.

## Starting

The press settles the act's choice. Then one transaction stores the row and
queues chunk 0. The queue row and the batch row commit together. A token
pressed twice stores one row. The press redirects to its origin.

An Undo reads its rows on the server. It is refused while its batch runs. A
second Undo press while one runs starts nothing. An Undo with no rows posts a
message. A batch with no row reads its act from its events.

## Running

`games.tasks.run_bulk_batch` calls `run_chunk` (`games/bulk_jobs.py`). A stale
chunk number or an ended batch does nothing. A Stop request ends the batch
before the chunk. Each row is its own keyed dispatch. After each row, the
runner writes the tally and `position`, guarded by `chunk` and `attempts`. A
run that another delivery overtook stops. The last row of a chunk queues the
next chunk, in one transaction.

A defect stores `failed`. The cluster's timeout is a `BaseException`; the
runner stores `failed`, then raises it again. A chunk that starts a third time
stores `failed`. The log names every row left alone.

## Following

`Page()` puts the library's batches in `data-bulk-batches`: every running
batch, and every end not seen within `ANNOUNCE_WINDOW`. `ts/bulk-batch-status.ts`
shows one toast for each batch and polls `/api/bulk/batches` every two
seconds while one runs. `batch_toast` writes each toast. A running toast
offers Stop. An end offers Undo where a row moved. A dismissed end posts
`/api/bulk/batches/{token}/announced`. A dismissed running toast stays
dismissed for this tab.

When a running batch ends, and its origin path is this page, the coordinator
dispatches `page:stale` on `document`. The form dialog reloads the page.

## Tests

`tests/bulk_batches.py` runs each queued chunk when the transaction commits.
`held_batches` keeps the chunks for the test to run.
