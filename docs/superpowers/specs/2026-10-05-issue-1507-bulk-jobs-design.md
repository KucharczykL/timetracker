# Bulk acts run as background jobs

Issue: [#1507](https://github.com/KucharczykL/timetracker/issues/1507). Part of
[#1485](https://github.com/KucharczykL/timetracker/issues/1485). After #1384.
Amends [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md): the
declaration, the confirmation, the chunk, the keys and the Undo's reading
stay; the waypoint chain goes.

## The batch row

`BulkBatch` (`games/models.py`) is a conventional, library-scoped row. It is
no projection and writes no event.

| column | meaning |
|---|---|
| `id` | minted at insert, so `created_at` orders it (`make audit-uuid-identity`) |
| `token` | the batch's correlation id (UUIDv7), minted by the confirmation; unique per library |
| `library` | `CASCADE`; every read states it |
| `action` | the declared act's name |
| `undoes` | for an Undo, the correlation id it takes back; else null |
| `choice` | the settled `ChoiceValue`, or `""` for an act that asks nothing |
| `origin` | where the press returned; the page that refreshes |
| `rows` | JSON list of the batch's keys, written once |
| `position` | the index in `rows` of the next key to act on |
| `total`, `done`, `unchanged`, `refused`, `lost`, `reasons` | the tally |
| `chunk` | the number of the chunk due next |
| `attempts` | how often the due chunk has started |
| `state` | `queued`, `running`, `finished`, `stopped`, `failed` |
| `stop_requested_at` | set by Stop; read between chunks |
| `created_at`, `updated_at`, `ended_at` | |
| `announced_at` | set once the person dismissed the end's toast or pressed its Undo |

`Tally` keeps its shape and its sentences; it now reads from and writes to the
row (`Tally.of(batch)`, `tally.columns()`), not a form field. Index
`(library, state)` serves the page's read. Nothing prunes a batch row: a
finished one holds no keys, and the table stays small. `games_bulkbatch` joins
the identity audit's pinned table lists.

## Starting

The confirmation is unchanged: it resolves, logs each row the resolve refused,
and carries the token and the tally in hidden fields. The press reads them,
settles the act's choice from the POST (a refusal answers the confirmation
again, as now), then in one `transaction.atomic()` creates the row and calls
`enqueue(batch, 0)`. With the ORM broker the queue row commits with the batch
row or not at all; no dispatch runs inside that block. The press answers a
redirect to the origin with no message. A token that is no UUIDv7
(`parse_uuidv7`) is refused as unreadable. A second press of one token hits
the `(library, token)` constraint; the `IntegrityError` is caught outside the
atomic block, and the press redirects without a second job. The same token in
another library is a different row.

An Undo press does the same with a fresh token: `undoes` is the batch,
`rows` is `undo_rows.rows(...)` read once, `total` its length. It is refused
while the batch it undoes has a row that is not terminal, because the rows
read then would miss the later ones. While an Undo of that batch is not
terminal, a second press redirects without a new job. A batch with no row
(one run before this change) is undone as before.

## Running

`games.tasks.run_bulk_batch(batch_id, chunk)` calls `run_chunk` in
`games/bulk_jobs.py`, the request-free runner. It reads the row; a chunk number
other than the row's, or a terminal state, returns at once. A stop request
ends the batch: each remaining key is logged `STOPPED_BY_HAND`, state
`stopped`. Otherwise it increments `attempts` in its own transaction and runs
rows inside `CHUNK_BUDGET`, as `_run_a_chunk` did, each row its own dispatch
keyed `<act>-<token>-<row>`. After every row it writes the tally and
`position` in one `UPDATE ... WHERE chunk = n AND attempts = k`, so a run
another delivery overtook stops. At the chunk's end one transaction
advances `chunk`, resets `attempts`, and, when rows remain, enqueues chunk
`n + 1`. When none remain, state is `finished`. An update that matches no row
means another run overtook this one, and the chunk stops.

A defect (a `CommandFailed` other than 409, an `Http404`, any other exception,
the resolve and the tally writes included, and the cluster's timeout, which
is a `BaseException`, re-raised after the write) logs the row it met with
`MET_THE_DEFECT` and the rest with `ENDED_BY_A_DEFECT`, stores the tally and
state `failed`, and returns normally, so the cluster does not retry it.

The cluster acknowledges a task that returned, and a timed-out one (a failed
result). It redelivers a task its worker never acknowledged, after a crash,
after `retry` (120 s), with no attempt cap. A
redelivered chunk resumes at the row in flight, since the tally is written
per row. That row may already be done: its re-resolve may then call it lost,
or its keyed run unchanged, so at most one row per redelivery is miscounted.
Its keyed dispatch writes nothing twice. A chunk that starts a third time
stores `failed`, so a row that crashes the worker cannot hold the toast open
forever. Every writer of the row writes named columns through
`QuerySet.update()`: the runner, Stop and the announcement never overwrite
each other.

Each chunk is one task of about three seconds, so a long batch and
`convert_library_prices` take turns on the one worker. `Q_CLUSTER` is
unchanged. `make dev` starts `manage.py qcluster` beside runserver. Without
a running cluster a batch stays `queued`, and its toast says so.

The worker reads no request. No act's run or resolve reads one today; the
choice and any instant are settled at the press. The settings resolver's
cache is per process, so a future act that reads a setting in the worker may
see a stale value.

## Following

`Page()`, for a signed-in person only, renders the library's visible batches into `<html
data-bulk-batches>` with `data-bulk-batches-url`: every batch not yet
terminal, and every terminal one with no `announced_at` that ended within
`ANNOUNCE_WINDOW` (one day). `ts/bulk-batch-status.ts`, after
`LibraryConversionCoordinator`, reads them and polls
`GET /api/bulk/batches?tokens=…` every two seconds while one runs. The read
filters on `request.user.library`, which is cached, so it adds one query. Each
batch carries its toast, composed in Python (`batch_toast` in
`games/bulk_jobs.py`, a `BatchToast` `TypedDict` in the shape of the store's
`ToastMessage`), so the wording lives in one language:

| state | type | action | text |
|---|---|---|---|
| queued | info, sticky | Stop | `<title>: waiting to start. <tally>` |
| running | info, sticky | Stop | `<title>: <tally>` |
| stop requested | info, sticky | none | `<title>: stopping. <tally>` |
| finished | success, or info when nothing moved; sticky | Undo | `<title>: <tally>` |
| stopped | info, sticky | Undo | `<title>: stopped. <tally>` |
| failed | error, sticky | Undo | `<title>: a problem on our side stopped it (error <token's last 12 digits>). <tally>` |

`<title>` is `ActTitle.for_count(total)`, prefixed `Undo: ` for an Undo. Undo
is offered only where something moved, never on an Undo, and never for an act
the table no longer holds. Without an Undo a terminal toast keeps its type's
timer. The reasons follow the tally in the same toast, so a batch never holds
more than one of the store's three places. The toast id is
`bulk-batch:<token>`; the coordinator sends it again only when its text or
action changes, so the store replaces it in place and no countdown restarts.
A dismissed running toast stays dismissed for that state, kept in
`sessionStorage` as the conversion coordinator does. When the person
dismisses a terminal toast, the coordinator posts
`/api/bulk/batches/{token}/announced` with `X-CSRFToken`; an Undo press sets
`announced_at` on the server. An Undo of a batch whose rows are all gone
starts no batch and says so in a message.

Stop is a toast action posting `/bulk/batch/<token>/stop/`, which sets
`stop_requested_at` and ends with `redirect(return_url(...))`. It is
`ORIGIN_AWARE` in `games/views/returns.py`; another library's batch answers
404. The API answers only the asking library's batches.

## The page underneath

When the coordinator sees a batch it held as running become terminal, and the
batch's `origin` has this page's path, it dispatches `page:stale` on
`document`. A batch that ended before the page rendered needs no refresh.
#1507 adds no listener. #1384's `<form-dialog>` is the one reloader: it
waits until no modal is open, merges `page:stale` with its own pending
reload, then reloads. The page swaps nothing in place.

## Toast actions inside a form dialog

Stop and Undo are POST forms that end on `redirect(return_url(...))`. While
no form dialog is open they post natively and navigate. #1384 adds a
middleware that turns a 3xx into a JSON result on a request carrying
`X-Form-Dialog`. While a form dialog is open, `<toast-stack>` fetches a
bulk toast's action with that header; a `done` result shows its messages in
the top dialog and marks the dialog stack dirty, which reloads when the last
dialog closes. That part lands after #1384, on its middleware.

## Gone

`ProgressBatch`; `<continuing-batch>`, its test, its `register_element`
entry and its generated props; `STOP_FIELD`; the per-chunk choice re-settle
and the comments that describe it (`games/bulk_finish.py`); the mid-batch
end in `_reconfirmation`; `_of_this_batch` and `NOT_THIS_BATCH`, since an
Undo's keys are stored by the server, not posted. `CHOICE_FIELD` stays in
`games/views/bulk.py`, which the acts' `settle` functions import. CLAUDE.md's
bulk-runner paragraph and the #713 spec lose the waypoint.

## Tests

The suite runs every enqueued chunk on commit, inline (`tests/conftest.py`,
`e2e/conftest.py`), so a press acts before its redirect. The hook queues
each chunk and drains the queue in a loop on commit, never recursing. A `held_batches`
fixture keeps the chunks for the test to run. Tests that read messages after
a press read the batch row instead (`tests/bulk_posts.py` grows a reader);
tests that post waypoints or Stop fields are rewritten against the job. The
page's batch read adds one query to `Page()`, which moves the pinned query
counts in `tests/test_library_page_isolation.py` and
`tests/test_purchase_finished_column.py`. Unit: every chunk runs; Stop between
chunks; a redelivered chunk writes nothing twice and counts once; a stale
chunk number does nothing; each row left alone is logged, unreached ones
included; a defect stores `failed`; another library's batch is absent from
the read and the API. e2e: an act from a list ends with its Undo toast; a
held batch shows Stop, survives a closed page and ends on the next load with
its Undo; Stop. vitest: the coordinator fires `page:stale` once per batch, only on its
origin's path.

## Follow-up issues to file

None.
