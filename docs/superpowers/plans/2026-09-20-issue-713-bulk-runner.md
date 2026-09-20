# Bulk-command runner implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One act on many rows, run as one batch a person can undo as one, with
the reclassification rebuilt on it.

**Architecture:** A declaration table (`games/bulk_actions.py`) says what an act
is; one view module (`games/views/bulk.py`) runs any of them. One route tells a
confirm POST from an act POST by the submission token, which *is* the batch's
correlation id. Each row is its own dispatch, its own transaction, keyed from
the token and the row. A batch stamps its action's name in each event's source
metadata, and the Undo reads that back.

**Tech Stack:** Django 6, PostgreSQL 18, the existing event/command/projection
stack, Python components, one TypeScript custom element, pytest + vitest +
Playwright.

**Spec:** [docs/superpowers/specs/2026-09-20-issue-713-bulk-runner-design.md](../specs/2026-09-20-issue-713-bulk-runner-design.md)
**Wave:** [docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md](../specs/2026-09-19-selectable-tables-wave-design.md)
**Issue:** [#713](https://github.com/KucharczykL/timetracker/issues/713). Closes #1123 and #1125.

## Global Constraints

- Python 3.14 only; Node ≥ 26. Drive everything through `make`; never wrap in
  `direnv exec .`, never call `uv run`/`pnpm`/`pytest` directly.
- Every worktree shares one test lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check-fast`
  while iterating, and the same around the final `make check`.
- No dispatch inside a transaction: `run_in_transaction` refuses to nest, so no
  view on this path carries `@transaction.atomic`. A test that POSTs through one
  needs `@pytest.mark.django_db(transaction=True)`.
- Never `QuerySet.iterator()`; `tests/test_iterator_guard.py` walks the tree.
- A command scopes its own resolve through `games/commands/scope.py`; a
  projector writes through `self.project`/`self.amend`.
- New routes must be classified in `games/views/returns.py` or the completeness
  guard fails. Both new routes go in `ORIGIN_AWARE`.
- Refused words (`fold`, `seam`, `heal`, `tombstone`, `archive`, `delete`) —
  `make vale` enforces them over docs and comments.
- Unabbreviated identifiers; compound types get a name; `ControlButton` for
  buttons; `render_page`, never `render`.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File structure

| File | Responsibility |
|---|---|
| `games/migrations/0012_library_event_batch_indexes.py` | the two indexes |
| `games/reads/events.py` | **new** — reads the event stream by batch |
| `games/bulk_actions.py` | **new** — the declaration table and its registry |
| `games/views/bulk.py` | **new** — the runner: confirm, act, chunk, progress, Undo |
| `games/views/bulk_pages.py` | **new** — the two pages the runner renders |
| `ts/elements/continuing-batch.ts` | **new** — auto-submit and Stop |
| `games/writes/playersession.py` | gains `source_metadata` on its wrappers |
| `games/views/session_reclassification.py` | keeps the single-row routes; its bulk half becomes the action |
| `games/views/library.py` | the Playtime panel's button posts a statement |
| `games/events/vocabulary.py` | `event_types_for(aggregate_type)` |
| `games/events/benchmark_workload.py` | a bulk scenario |

---

### Task 1: The indexes and the batch reader

**Files:**
- Create: `games/migrations/0012_library_event_batch_indexes.py`
- Create: `games/reads/events.py`
- Modify: `games/models.py` (`LibraryEvent.Meta`), `games/events/vocabulary.py`
- Test: `tests/test_event_reads.py` (new)

**Interfaces — Produces:**
```python
# games/events/vocabulary.py, on EventTypeRegistry
def event_types_for(self, aggregate_type: AggregateType) -> frozenset[EventType]: ...


# games/reads/events.py
def batch_events(
    library: UserLibrary, correlation_id: uuid.UUID
) -> LibraryEventQuerySet: ...
def batch_aggregate_ids(
    library: UserLibrary, correlation_id: uuid.UUID, aggregate_type: AggregateType
) -> list[uuid.UUID]: ...
```

- [ ] **Step 1: Write the failing tests.** In `tests/test_event_reads.py`:
  `batch_events` answers only this library's rows for the correlation, ordered
  by `sequence`; a second library's batch under the same correlation is absent.
  `batch_aggregate_ids` over `"playersession"` answers session keys **only**,
  from a reclassification batch that also wrote `historicalplaytime.created` —
  this is the case the spec exists for, so assert the record keys are absent by
  identity, not by count. `event_types_for("playersession")` holds
  `library.playersession.reclassified` and not `library.historicalplaytime.created`.
- [ ] **Step 2: Run them, confirm they fail** —
  `make test-fast ARGS="tests/test_event_reads.py -x"`.
- [ ] **Step 3: Add `event_types_for`** — a read over `EventTypeRegistry._registered`,
  on the class rather than in the reader, because `_registered` is private.
- [ ] **Step 4: Add `indexes` to `LibraryEvent.Meta`** — `(library, correlation_id)`
  and `(library, aggregate_id)`. **Gotcha:** `Meta` assigns `constraints` as a
  tuple today; add `indexes` beside it, do not replace it. `LibraryEvent`
  extends `models.Model` directly, so no abstract base's constraints are
  shadowed here.
- [ ] **Step 5: `make makemigrations ARGS="games --name library_event_batch_indexes"`.**
  **Gotcha:** the target passes `--noinput`; check the generated file is
  `AddIndex` only and touches nothing else.
- [ ] **Step 6: Write the reader.** `batch_events` filters
  `library=…, correlation_id=…` and orders by `sequence`. `batch_aggregate_ids`
  narrows it by `event_type__in=event_types_for(aggregate_type)` and answers
  `aggregate_id`s in first-seen order, without repeats.
- [ ] **Step 7: Tests pass; `make check-fast` under the lock.**
- [ ] **Step 8: Commit** — `feat: read a batch's events`.

---

### Task 2: Source metadata on the session wrappers

**Files:**
- Modify: `games/writes/playersession.py` (`_dispatch`, `reclassify_session`, `undo_reclassification`)
- Test: `tests/test_session_writes.py`

**Interfaces — Produces:** each of the three gains
`source_metadata: SourceMetadata | None = None`, threaded to `dispatch`.

- [ ] **Step 1: Write the failing test** — `reclassify_session` with
  `source_metadata={"bulk": {"action": "session.reclassify"}}` leaves that dict
  on **every** event of the append, the record's and the session's alike.
- [ ] **Step 2: Run it, confirm it fails** —
  `make test-fast ARGS="tests/test_session_writes.py -k source_metadata -x"`.
- [ ] **Step 3: Thread the parameter.** Keyword-only, defaulting `None`, so no
  existing call site changes. **Gotcha:** nothing in the app passes
  `source_metadata` today — `append.py` and `idempotency.py` already carry it,
  and `append.py` copies it onto each row of the append, so this is wiring only.
- [ ] **Step 4: Test passes. Commit** — `feat: let a session write name its source`.

---

### Task 3: The declaration table

**Files:**
- Create: `games/bulk_actions.py`
- Modify: `games/views/session_reclassification.py` (its bulk half moves here)
- Test: `tests/test_bulk_actions.py` (new)

**Interfaces — Produces:**
```python
type BulkActionName = str           # "session.reclassify"
type RowKey = str                   # a posted key, before it parses
type FilterJson = str

class Cardinality(StrEnum):
    ONE = "one"
    MANY = "many"

class Refused(NamedTuple):
    key: RowKey
    sentence: str
    #: Gone since the confirmation, rather than refused on its merits.
    lost: bool

class Resolution(NamedTuple):
    rows: tuple[Model, ...]
    refused: tuple[Refused, ...]

@dataclass(frozen=True, slots=True)
class BulkAction:
    name: BulkActionName
    label: str
    title: str
    confirm_label: str
    subject: SubjectNoun
    cardinality: Cardinality
    inverse_aggregate: AggregateType
    fallback: UrlName
    scope: Callable[[UserLibrary, FilterJson], QuerySet[Any]]
    resolve: Callable[[UserLibrary, Sequence[uuid.UUID]], Resolution]
    run: Callable[[User, Any, IdempotencyKey, uuid.UUID], None]
    inverse: Callable[[User, uuid.UUID, uuid.UUID], None]

    @classmethod
    def on(cls, ...) -> "BulkAction": ...

BULK_ACTIONS: dict[BulkActionName, BulkAction]
```

- [ ] **Step 1: Write the failing tests.** `BulkAction.on` refuses a duplicate
  name, refuses an `inverse_aggregate` no `EventSpec` declares (using Task 1's
  `event_types_for`), and refuses a `MANY` action with no inverse. A test holds
  `BULK_ACTIONS` complete against the names the runner's URL accepts.
  `session.reclassify`'s `scope` over `review_filter()` yields the same rows as
  `reviewable_sessions()` — **the regression the spec names**: the filter alone
  cannot exclude the bucket, so assert a bucket session is absent from the
  scope, not merely refused later. `resolve` over a bucket key, an under-threshold
  key, a Timed key, an already-recorded key and a nonexistent key answers the
  five existing sentences, with `lost=True` on the last alone.
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Write the table.** `.on` validates and appends, as
  `BlockingReferrer.on` does in `games/commands/playthrough.py`.
- [ ] **Step 4: Move the reclassification's bulk half.** `reviewable_sessions`,
  `_classified` and the five sentences leave
  `games/views/session_reclassification.py` for the action's `scope` and
  `resolve`. **Gotcha:** `scope` applies the filter to `reviewable_sessions()`,
  never to `library_sessions()`; and it parses the filter itself with
  `parse_session_filter`, raising on a `FilterError` — it must **not** call
  `apply_structured_filter`, which drops an unreadable filter and would widen
  the act to every row.
  Keep `reclassify_session` and `undo_reclassify_session` (the single-row
  routes) exactly as they are.
- [ ] **Step 5: Tests pass; `make check-fast` under the lock. Commit** —
  `feat: declare what a bulk act is`.

---

### Task 4: The confirmation

**Files:**
- Create: `games/views/bulk.py`, `games/views/bulk_pages.py`
- Modify: `games/urls.py`, `games/views/returns.py`
- Test: `tests/test_bulk_runner.py` (new)

**Interfaces — Produces:**
```python
# the POST grammar, named once in bulk.py
STATEMENT_FIELD = "selection"    # the statement, confirm POST only
TOKEN_FIELD = "submission"       # the token, which is the correlation id
PROGRESS_FIELD = "progress"      # rows left and the tally

class SelectionStatement:      # parsed from STATEMENT_FIELD
    keys: tuple[uuid.UUID, ...] | None    # None under "all"
    filter_json: FilterJson
    count: int
    excluded: frozenset[uuid.UUID]

class Tally(NamedTuple):
    done: int
    unchanged: int
    lost: int
    refused: tuple[Refused, ...]

# games/views/bulk_pages.py
def ConfirmBatch(action, rows, refused, token, progress, post_url, csrf_token, cancel_url, total) -> Node
```

- [ ] **Step 1: Write the failing tests.** A POST with a `some` statement
  renders the confirmation, 200, with a `submission` that parses as a UUIDv7 and
  a `progress` field holding the resolved keys. An `all` statement resolves
  through the action's scope minus its exclusions. An unparseable filter
  refuses: no token, no act, a sentence. A statement whose `count` no longer
  matches still renders, saying the current count — it does not refuse. A key
  of another library is absent. Over 50 rows the page lists 50 and says how
  many more, while `progress` holds every key. Zero resolved rows renders with
  no submit.
- [ ] **Step 2: Run them, confirm they fail** —
  `make test-fast ARGS="tests/test_bulk_runner.py -x"`.
- [ ] **Step 3: Route and classify.** `path("bulk/<str:action>/", bulk.run_bulk_action,
  name="run_bulk_action")`, `require_POST`, `login_required`; add
  `games:run_bulk_action` to `ORIGIN_AWARE`. An unknown action name is a 404.
- [ ] **Step 4: Write the confirm half.** Parse the statement, resolve under the
  library, mint `uuid.uuid7()` as the token, render through `ConfirmPage`.
  **Gotcha:** `post_url=request.get_full_path()` so `?origin=` rides the act
  POST, exactly as `confirm_and_apply` does. `ConfirmPage`'s `message` renders
  inside a `<p>`; the sample table and the refusal list go in `details`.
  **Gotcha:** the sample cap is a constant here, `CONFIRMATION_SAMPLE = 50`;
  the wave doc's step 1 states the cap and its reason.
- [ ] **Step 5: Tests pass. Commit** — `feat: confirm a bulk act`.

---

### Task 5: The act, the chunk and the progress page

**Files:**
- Modify: `games/views/bulk.py`, `games/views/bulk_pages.py`
- Test: `tests/test_bulk_runner.py`

**Interfaces — Produces:**
```python
#: A chunk is the rows one request acts on inside this.
CHUNK_BUDGET = timedelta(seconds=3)

def ProgressBatch(action, tally, remaining, token, post_url, csrf_token, stop_url) -> Node
```

- [ ] **Step 1: Write the failing tests.** With `CHUNK_BUDGET` monkeypatched to
  zero, a three-row batch acts on one row and renders the progress page holding
  the other two and a tally of one. Resubmitting that page finishes the batch,
  and **every event of both chunks carries one correlation id** — the token's.
  The same token posted twice converts nothing twice and answers the same counts.
  A row removed between confirm and act counts `lost`. A row whose command
  refuses is named and the next row still runs. A defect (patch the wrapper to
  raise `CommandFailed` at `DEFECT_STATUS`) ends the batch, leaves the earlier
  rows done, and renders with no submit. A finished batch redirects to the
  origin with one toast carrying Undo. **Mark these
  `@pytest.mark.django_db(transaction=True)`** — the view dispatches.
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Write the act half.** Re-resolve the chunk's keys through the
  action's `resolve` each request, so a row gone since counts `lost` rather
  than surfacing as a command refusal. Dispatch per row with
  `idempotency_key=f"{action.name}-{token}-{row.pk}"` and
  `correlation_id=parse_uuidv7(token)`, under
  `source_metadata={"bulk": {"action": action.name}}`. Stop when
  `monotonic()` passes the budget.
  **Gotcha:** the key is capped at 255 characters; `"session.reclassify-" + 36
  + 1 + 36` is 92, so the room is there, but a new action's name must stay short.
  **Gotcha:** a repeated key whose row moved since answers
  `IdempotencyKeyMismatch` → 409, not a replay, because the fingerprint covers
  the command's input. Count it as refused, name it, carry on.
- [ ] **Step 4: Write the progress page.** The tally, the remaining keys, the
  same token, a Continue submit and a Stop. Stop posts the batch's answer
  without acting.
- [ ] **Step 5: Tests pass; `make check-fast` under the lock. Commit** —
  `feat: run a bulk act in chunks`.

---

### Task 6: `<continuing-batch>`

**Files:**
- Create: `ts/elements/continuing-batch.ts`, `ts/elements/continuing-batch.test.ts`
- Modify: `common/components/custom_elements.py`, `games/views/bulk_pages.py`
- Test: vitest, plus `e2e/test_bulk_runner_e2e.py` (new)

**Interfaces — Produces:** `ContinuingBatchProps` = `{}` (no props; the form is
its child), registered as
`register_element("continuing-batch", "ContinuingBatch", ContinuingBatchProps)`.

- [ ] **Step 1: Write the failing vitest.** On connect the element calls
  `requestSubmit()` on its child form. After Stop is pressed it does not submit,
  and a reconnect after Stop does not either.
- [ ] **Step 2: Run it, confirm it fails** — `make test-ts`.
- [ ] **Step 3: Write the element.** `connectedCallback` submits; Stop sets a
  flag and lets its own button submit. **Gotcha:** `connectedCallback` fires on
  parse as well as on an htmx swap — that is the point, and why this is an
  element rather than `onSwap`.
- [ ] **Step 4: `make ts`**, so the e2e run serves fresh output.
- [ ] **Step 5: Write the e2e.** With the budget forced low, a batch walks its
  chunks by itself and lands on the origin with a toast; with Stop pressed at
  the first progress page, it stops and the toast counts what was done.
  **Gotcha:** never run e2e while `make dev` is up — its watchers rewrite the
  served assets. **Gotcha:** wait on the server-rendered redirect before reading
  the ORM.
- [ ] **Step 6: Commit** — `feat: continue a batch without a press`.

---

### Task 7: Batch Undo

**Files:**
- Modify: `games/views/bulk.py`, `games/urls.py`, `games/views/returns.py`
- Test: `tests/test_bulk_runner.py`

**Interfaces — Produces:** `games:undo_bulk_action` at
`bulk/undo/<uuidv7:correlation_id>/`, POST only, `ORIGIN_AWARE`.

- [ ] **Step 1: Write the failing tests.** Undoing a reclassification batch
  restores every session and removes every record. **The batch's aggregates are
  mixed** — assert the Undo reads only `playersession`-typed events, by
  undoing a batch and checking no refusal mentions a record key. A batch one of
  whose records was restated since names that row and undoes the rest. A batch
  Undo that outruns the budget chunks under **its own** token and correlation id,
  distinct from the batch's. An unknown correlation id is a 404. An action name
  in the metadata that `BULK_ACTIONS` does not hold refuses.
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Write it.** Read the action name from the first event's
  `source_metadata`, the rows from
  `batch_aggregate_ids(library, correlation_id, action.inverse_aggregate)`, then
  run the same chunk loop with `action.inverse`. **Gotcha:** the Undo's answer
  offers no further Undo.
- [ ] **Step 4: Tests pass; `make check-fast` under the lock. Commit** —
  `feat: undo a batch`.

---

### Task 8: The Library page cuts over

**Files:**
- Modify: `games/views/library.py`, `games/views/session_reclassification.py`,
  `games/urls.py`, `games/views/returns.py`
- Test: `tests/test_library_page.py`, `tests/test_session_reclassification.py`

- [ ] **Step 1: Write the failing tests.** The Playtime panel renders a POST
  form whose `selection` is an `all` statement over `review_filter()` with the
  waiting count, and whose origin is the library page. Its copy no longer says
  an Undo is not offered. `games:reclassify_reviewed_sessions` no longer
  resolves. The panel's count still matches the action's scope.
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Make the change.** `ControlButton(method="post", …)` renders the
  form and needs `csrf_token`. Remove the old route and its `ORIGIN_AWARE`
  entry. **Gotcha:** `tests/test_returns_classification.py` fails until the
  removed name is gone from the bucket too.
- [ ] **Step 4: Tests pass. Commit** — `feat: move the review's bulk act onto the runner`.

---

### Task 9: The bench

**Files:**
- Modify: `games/events/benchmark_workload.py`, `games/events/benchmark_run.py`,
  `games/events/benchmark.py`
- Test: `tests/test_event_benchmark.py`

**Interfaces — Produces:**
```python
def run_bulk_command_scenario(
    library: UserLibrary, *, actor: User, sessions: int, warmup: int
) -> Timings: ...
```

- [ ] **Step 1: Write the failing test** — the scenario dispatches the asked-for
  count, every event under one correlation id, and reports timings.
- [ ] **Step 2: Run it, confirm it fails.**
- [ ] **Step 3: Write the scenario.** 600 written-down sessions at the review
  threshold, converted through the action's `run` — the runner's own loop, not
  the view. Follow `run_record_command_scenario`'s shape, `analyze_tables` last.
  **Gotcha:** gate reads over rows the same transaction inserted plan against
  empty statistics; `ANALYZE` first or the numbers are nonsense.
- [ ] **Step 4: Report it** in `benchmark_run.py` beside the existing scenarios,
  judged against the 100 ms per-command budget at p95.
- [ ] **Step 5: Run `make bench` and record the figures** in the spec's Proof
  section. **Gotcha:** `make bench` is not in `make check` and takes ~2 minutes.
- [ ] **Step 6: Commit** — `feat: time a bulk through the runner`.

---

### Task 10: The gate

- [ ] **Step 1: Docs sweep.** Delete this plan file. Fold the bench's figures
  into the spec. Add the runner to `CLAUDE.md`'s architecture notes, one
  paragraph in the house voice, beside the PlayerSession entries.
- [ ] **Step 2: `make vale`.**
- [ ] **Step 3: Full gate, under the lock:**
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
  Read the exit code from a log; never `grep | tail` for a pass line — ruff
  prints "All checks passed!" while format-check can still be red.
- [ ] **Step 4: Commit, push, open the PR** against `main`. Do not merge until
  the user says merge.

---

## Self-review

**Spec coverage.** The declaration and its five parts → Task 3, with the
aggregate type validated in Task 1 and consumed in Task 7. The two POSTs and the
token-as-correlation-id → Tasks 4 and 5. One field, not one per row → Task 4's
`progress`. Origin-aware routes → Tasks 4 and 7. The chunk, the refusal, the
lost row, the defect → Task 5. Source metadata → Tasks 2 and 5. The batch Undo
and its aggregate read → Task 7. The index and migration `0012` → Task 1. The
Library page → Task 8. The bench → Task 9.

**Known gap, deliberate.** `(library, aggregate_id)` ships in Task 1 with no
caller in this issue; the wave assigns `aggregate_events` to #714, beside the
move inverse that calls it. Task 1's test covers the index's presence, not a
reader for it.

**Ordering.** Tasks 1–3 are independent of each other and can run in parallel;
4 needs 3; 5 needs 4; 6 and 7 need 5; 8 needs 4; 9 needs 3; 10 needs all.
