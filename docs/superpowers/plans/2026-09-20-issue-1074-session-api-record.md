# Record a session through the API (#1074) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/session/` records one session through `CreateSession` and answers the projection row.

**Architecture:** One route on the existing `session_router`, declared beside `PATCH /{session_id}` so it reuses that route's timing schemas (`TimingIn`, `_timing_statement`) and its device pre-check. The run gets a pre-check of its own, over the scope `library_playthrough` resolves, so only "this library holds no such run" is 404 and every other rule stays the command's sentence. `record_session` grows a keyword-only idempotency key, which the route fills from the `Idempotency-Key` header.

**Tech Stack:** Django 6, Django Ninja 1.6, pytest. Python 3.14.

**Spec:** `docs/superpowers/specs/2026-09-20-issue-1074-session-api-record-design.md` (read it first).

## Global Constraints

- Every command through `make`. No `direnv exec .`, no bare `uv run` / `pytest` / `pnpm`.
- Iterate with `make check-fast`; the gate before done/PR is full `make check`, wrapped in the shared lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
- Scope a focused run with `ARGS`, e.g. `make test-fast ARGS="tests/test_api.py -k post_session"`.
- **Every test that POSTs this route needs `@pytest.mark.django_db(transaction=True)`** — `run_in_transaction` refuses to nest. The existing PATCH tests at `tests/test_api.py:424` show the pattern.
- **Every such test seeds the library's calendar** (`_prague_calendar(user)` in `tests/test_api.py`); a Timed or Corrected statement with no calendar row is refused at 409.
- Unabbreviated identifiers; name compound and primitive roles.
- Nothing new in `input.css`; no Django template. Not a UI change.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: `record_session` takes an idempotency key

**Files:**
- Modify: `games/writes/playersession.py:75-92` (`record_session`)
- Test: `tests/test_session_writes.py`

**Interfaces:**
- Produces: `record_session(actor: User, draft: SessionDraft, *, correlation_id: uuid.UUID, idempotency_key: IdempotencyKey | None = None) -> uuid.UUID`. `IdempotencyKey` is already imported in that module from `games.events.idempotency`.
- The keyword goes straight to `_dispatch`, which already takes `idempotency_key` and falls back to `str(uuid.uuid7())`. `reclassify_session` at `:294-313` is the working precedent; copy its shape.

**Gotchas:**
- Default `None`, so the three existing callers (`games/views/session.py:341`, `tests/test_session_writes.py:83`, `tests/test_anonymize_sample.py:107`) are untouched.
- A replayed append still carries a `SequenceRange`, and `CreateSession.build` returns exactly one event, so `_created_id` answers the **first** session's id on the repeat. That is the behaviour the test asserts.

- [ ] **Step 1: Write the failing tests** in `tests/test_session_writes.py`, both `@pytest.mark.django_db(transaction=True)`:
  - `test_record_session_absorbs_a_repeat_under_one_key` — call `record_session` twice with the same `idempotency_key="k-1"` and the same draft; assert one `PlayerSession` row for the run and that the two returned ids are equal.
  - `test_record_session_refuses_a_key_that_names_another_statement` — same key, a draft differing in `note`; assert `CommandFailed` with status 409 (the mapped `IdempotencyKeyMismatch`).
- [ ] **Step 2: Run them, watch them fail** — `make test-fast ARGS="tests/test_session_writes.py -k idempot"`. The first fails on two rows (the key is ignored today), the second on no exception.
- [ ] **Step 3: Add the keyword** and pass it to `_dispatch`. Extend the docstring with one sentence: a key the caller states absorbs its own repeat.
- [ ] **Step 4: Re-run the two tests; both pass.**
- [ ] **Step 5: Commit** — `feat: record_session takes an idempotency key`

---

### Task 2: the route records a session

**Files:**
- Modify: `games/api.py` — new `SessionIn` schema and `create_session` route, declared after `_timing_statement` (`:765-790`) and before or after `partial_update_session`; both live above `api.add_router("/session", session_router)` at `:832`.
- Test: `tests/test_api.py` (session section, after the PATCH tests)

**Interfaces:**
- Produces: `POST /api/session/`, `response={201: SessionOut}`.
- `SessionIn(Schema)` with `model_config = ConfigDict(extra="forbid")`: `playthrough_id: UUIDv7`, `timing: TimingIn`, `device_id: UUIDv7 | None = None`, `note: str = ""`, `emulated: bool = False`.
- Body: resolve the run and the device (Task 3 adds the helpers' refusals — here call `_library_device_or_404` and the new `_library_run_or_404`), then
  `record_session(actor, SessionDraft(playthrough_id=…, timing=_timing_statement(payload.timing, calendar_day_zone(library).key), device_id=…, note=…, emulated=…), correlation_id=new_correlation_id(), idempotency_key=…)`,
  then `messages.success(request, "Session recorded.")`, then `return 201, readable_sessions(library).get(pk=session_id)`.
- Wrap the write in `try: … except CommandFailed as failure: _answered_or_http(failure)`, exactly as `partial_update_session` does at `:803-828`.

**Gotchas:**
- `_timing_statement` already takes the day zone as an argument; pass `calendar_day_zone(library).key`, as `:807` does.
- Ninja passes the request in the serializer context for a directly returned model instance, so `SessionOut`'s zone-label resolvers work — proven by the PATCH returning a raw row at `:829`.
- `"/"` and `"/{session_id}"` are separate path operations; the POST does not shadow `get_session`.
- Do **not** reuse `_readable_runs`, `_writable_runs` or `library_runs` for anything here: all three narrow to live ordinary runs.

- [ ] **Step 1: Write the failing tests** in `tests/test_api.py`, each `@pytest.mark.django_db(transaction=True)` with a seeded calendar:
  - `test_post_session_records_a_timed_session` — body with `playthrough_id` and `{"started_at": …}`; assert 201, the body's `id` names a `PlayerSession` on that run, `timing_mode == "timed"`, and the body's `day` equals the row's `effective_day`.
  - `test_post_session_records_each_timing_shape` — parametrised over the Duration-only (`day` + `duration_seconds`) and Corrected (both instants + `duration_seconds`) bodies; assert the projected `timing_mode` and `duration_seconds` for each.
  - `test_post_session_records_the_described_facts` — `note`, `emulated`, `device_id` in the body; assert all three on the row and in the answer.
  - `test_post_session_refuses_a_key_it_does_not_know` — `{"timestamp_end": …}` and a timing with `{"end": …}`; both 422, nothing recorded.
  - `test_post_session_requires_auth` — plain `Client()`, 401.
- [ ] **Step 2: Run them, watch them fail** — `make test-fast ARGS="tests/test_api.py -k post_session"`; expect 404/405 from the missing route.
- [ ] **Step 3: Write `SessionIn` and the route.** Import `Header` from `ninja` and `record_session`, `SessionDraft` from `games.writes.playersession`. For this task the run pre-check may be `owned_or_404(Playthrough.objects.filter(library=library), library, id=payload.playthrough_id)` written inline; Task 3 lifts it into the named helper.
- [ ] **Step 4: Re-run; all five pass.** Then `make check-fast`.
- [ ] **Step 5: Commit** — `feat: POST /api/session/ records a session`

---

### Task 3: the answers — 404, the command's sentences, and the retry

**Files:**
- Modify: `games/api.py` (`_library_run_or_404` helper beside `_library_device_or_404` at `:680-688`; the header parameter and its measurement on `create_session`)
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `_library_run_or_404(library: UserLibrary, playthrough_id: UUIDv7) -> None` — `owned_or_404(Playthrough.objects.filter(library=library), library, id=playthrough_id)`, discarding the row. Docstring states why the scope is every kind, removed or not: it is `library_playthrough`'s scope, so 404 means only that the library holds no such run, and every other rule keeps the command's sentence.
- Route signature gains `idempotency_key: str | None = Header(None, alias="Idempotency-Key")`.
- Measurement, before the write: strip the value; refuse `""` or more than `IDEMPOTENCY_KEY_MAX_LENGTH` (255, importable from `games.events.dispatch`) with `raise HttpError(422, …)`; pass the stripped value, or `None`, to `record_session`.

**Gotchas:**
- Ninja maps the parameter name to the header; the `alias` is written anyway so the wire name is readable at the call site.
- `validate_idempotency_key` raises a bare `ValueError` that `answered()` does not catch — hence the 422 before dispatch, never after.
- A removed **device** is 404 too, because `Device.objects.for_library` calls `alive()`. That is the existing asymmetry; do not widen the device scope here.
- A run in the imported-history bucket, a removed run and a removed `PlayerGame` each keep their own 409 sentence. Assert the sentence text comes from the command, not from the route.

- [ ] **Step 1: Write the failing tests** in `tests/test_api.py`, all `@pytest.mark.django_db(transaction=True)`:
  - `test_post_session_404s_a_run_another_library_holds` and `test_post_session_404s_an_unknown_run` — 404, no row recorded.
  - `test_post_session_404s_a_device_another_library_holds` — 404.
  - `test_post_session_refuses_the_imported_history_bucket` — 409, body's `detail` is `INTO_THE_BUCKET`.
  - `test_post_session_refuses_a_removed_run` — 409, the removed-run sentence.
  - `test_post_session_refuses_an_end_before_its_start` — Corrected body, 409.
  - `test_post_session_absorbs_a_repeated_idempotency_key` — two identical POSTs under one header; assert 201 twice, one row, equal ids.
  - `test_post_session_refuses_a_reused_key_for_another_statement` — same header, different note; 409.
  - `test_post_session_refuses_an_unusable_idempotency_key` — parametrised over `"   "` and `"k" * 256`; 422, no row.
- [ ] **Step 2: Run them, watch them fail** — `make test-fast ARGS="tests/test_api.py -k post_session"`. Today the foreign run answers 409, the blank key answers 500.
- [ ] **Step 3: Add `_library_run_or_404`**, call it from the route in place of the inline resolve, add the header parameter and its measurement.
- [ ] **Step 4: Re-run; all pass.** Then `make check-fast`.
- [ ] **Step 5: Commit** — `feat: the session POST answers 404, refusals and repeats`

---

### Task 4: the documents, and the gate

**Files:**
- Modify: `CLAUDE.md:750` — the session API bullet. Replace "Device outside library answers 404. No POST: #1074" with the route: `POST /api/session/` states a run, one whole timing statement, device, note and emulated; answers 201 and the row; honours `Idempotency-Key`; a run or device the library does not hold is 404.
- Modify: `docs/superpowers/specs/2026-09-15-issue-702-session-cutover-design.md:43,63` — both say "There is no POST; #1074 owns it." Each becomes a sentence stating the route, in that document's timeless voice.
- No migration, no codegen, no `.ts`.

**Gotchas:**
- `make vale` reads docs *and* code comments; keep the refused words out. `docs/vocabulary.md` lists them.
- Docs-only edits still go through `make vale`; the full gate runs once at the end of this task.

- [ ] **Step 1: Edit the two documents.**
- [ ] **Step 2: Run `make vale`** — expect no findings.
- [ ] **Step 3: Run the full gate** — `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`, and read its exit code from the log rather than grepping the tail.
- [ ] **Step 4: Commit** — `docs: the session API records a session`
- [ ] **Step 5: Open the PR** against `main`, body naming #1074 and the spec.

---

## Follow-up issues (filed)

- #1167 — `PATCH /api/session/{session_id}` answers 409 for a run another library holds, because its move resolves the run in the command alone. Filed.
- #1169 — `readable_sessions` refuses a session under the catalog game's removal mark, which no session command reads, so the read after a successful write can answer 500. Filed against both routes.
