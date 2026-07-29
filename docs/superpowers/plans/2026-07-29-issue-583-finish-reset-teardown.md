# Finish/reset teardown (#583) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the client-side session row swap on finish/reset with plain POST routes and a full page reload.

**Architecture:** Finish becomes a POST-acting view reached from a `ControlButton(method="post")`. Reset becomes a GET-confirms/POST-acts view on one URL, built on a generalized `confirm_and_apply()` extracted from `confirm_and_delete()`. `<session-actions>` survives only as a browser-time-zone stamper. The row-rebuild TypeScript and its server-side parity partner are deleted.

**Tech Stack:** Django 6, the `common.components` node tree, pytest + pytest-django, Playwright e2e, TypeScript compiled by `tsc` to `games/static/js/dist/`.

## Global Constraints

- Python 3.14 only. `except A, B:` (PEP 758) is valid here; a `SyntaxError` there means the wrong interpreter.
- Drive everything through `make`. No `direnv exec .` wrappers, no raw `uv run` / `pnpm` / `pytest`.
- Iterate with `make check-fast`; **gate on the full `make check`** (includes `e2e/`) before pushing.
- Never run `make test-e2e` while `make dev` is up — its watchers rewrite served assets and cause mass phantom failures.
- `ARGS` does not scope `make test-e2e`; it appends to `pytest e2e/`.
- Every mutating link is built with `action_url(name, *args, origin=...)`; every mutating view ends in `redirect(return_url(...))`.
- No route mutates on GET.
- Build UI with `common.components` builders in htpy form: `Builder(class_="x")[children]`. No HTML strings, no `attributes=`/`children=` kwargs on the generic or styled builders.
- Name variables with complete words.
- Comments explain non-obvious intent only — no issue or PR references.
- Run `make ts` after editing any `.ts` so e2e and local serving see fresh output.

---

### Task 1: Generalize `confirm_and_delete` into `confirm_and_apply`

`confirm_and_delete()` hardcodes `instance.delete()` and `confirm_label="Delete"`, so reset cannot reuse it. Extract the GET-confirm/POST-act shape and keep the delete version as a thin wrapper, leaving all seven existing delete views untouched.

**Files:**
- Modify: `games/views/deletion.py:23-70`
- Test: `tests/test_deletion_helper.py` (create)

**Interfaces:**
- Produces: `confirm_and_apply(request, *, action: Callable[[], None], title: str, message: str, confirm_label: str, fallback: UrlName, fallback_args: Sequence[Any] = (), details: Children = None, reject: str | None = None) -> HttpResponse`
- Produces: `confirm_and_delete(...)` unchanged in signature; now delegates, passing `action=instance.delete`, `confirm_label="Delete"`, and `reject=detail_url`.

- [ ] **Step 1: Write failing tests**

In `tests/test_deletion_helper.py`, cover the behaviour the wrapper must preserve and the new capability:

- `test_get_renders_confirmation_without_running_the_action` — GET a view built on `confirm_and_apply`; assert the response is 200, contains the confirm label, and a sentinel list the action would have appended to is still empty.
- `test_post_runs_the_action_once_and_redirects` — POST; assert the sentinel has exactly one entry and the response is a 302.
- `test_origin_rides_through_the_confirmation` — GET with `?origin=/tracker/session/list`, assert the rendered form posts to a URL carrying the same `origin`; then POST that URL and assert the redirect targets it.
- `test_confirm_and_delete_still_deletes` — the existing wrapper path, against a real model instance, asserting the row is gone and the redirect lands on the fallback.

- [ ] **Step 2: Run tests to verify they fail**

```bash
make test ARGS="tests/test_deletion_helper.py -x"
```

Expected: FAIL — `cannot import name 'confirm_and_apply'`.

- [ ] **Step 3: Implement**

Move the existing body into `confirm_and_apply`, replacing `instance.delete()` with `action()` and the literal `"Delete"` with the `confirm_label` parameter. `detail_url` becomes the more general `reject`, which is what it already feeds (`return_url(..., reject=detail_url)`). Rewrite `confirm_and_delete` as a call to it. Keep the module docstring's explanation of why both verbs share one URL.

- [ ] **Step 4: Run tests and the existing delete suite**

```bash
make test ARGS="tests/test_deletion_helper.py tests/test_returns_classification.py -x"
```

Expected: PASS, and no change in behaviour for existing delete views.

- [ ] **Step 5: Commit**

```bash
git add games/views/deletion.py tests/test_deletion_helper.py
git commit -m "refactor: confirm_and_apply generalizes the confirm-then-act flow"
```

---

### Task 2: Add the finish and reset views

**Files:**
- Modify: `games/views/session.py`
- Modify: `games/urls.py:126` (add two paths beside `edit_session`/`delete_session`)
- Modify: `games/views/returns.py:40-69` (`ORIGIN_AWARE`)
- Test: `tests/test_session_finish_reset.py` (create)

**Interfaces:**
- Produces: URL names `games:finish_session` and `games:reset_session`, both taking `session_id`.
- Produces: both views accept an optional `browser_time_zone` POST field; a value that `zone_or_none()` rejects is ignored rather than fatal.

**Gotchas:**
- `duration_calculated` and `duration_total` are `GeneratedField`s — never assign them. Setting `timestamp_end` is enough; the DB recomputes.
- Saving a `Session` fires the `post_save` signal that recalculates `Game.playtime`. Do not recalculate by hand.
- Both routes go in `ORIGIN_AWARE`, not `CONFIRMATION`. `CONFIRMATION` is for separate-URL confirm pages (refund/split); every `games:delete_*` route is GET-confirms/POST-acts at one URL and already sits in `ORIGIN_AWARE`. `tests/test_returns_classification.py` enforces exactly-one-bucket membership and will fail until both names are classified.

- [ ] **Step 1: Write failing tests**

In `tests/test_session_finish_reset.py`:

- `test_finish_sets_timestamp_end_and_redirects_to_origin`
- `test_finish_records_the_posted_browser_time_zone` — POST `browser_time_zone="Asia/Tokyo"`, assert `session.timestamp_end_timezone == "Asia/Tokyo"`
- `test_finish_ignores_an_unknown_time_zone` — POST `browser_time_zone="Not/AZone"`, assert the save succeeds and the field is left unset
- `test_finish_rejects_get` — assert 405
- `test_reset_get_renders_a_confirmation_and_does_not_mutate` — assert 200, the game name appears, and `timestamp_start` is unchanged
- `test_reset_post_moves_timestamp_start_to_now_and_redirects`
- `test_reset_records_the_posted_browser_time_zone` — asserts `timestamp_start_timezone`
- `test_both_routes_require_login`

- [ ] **Step 2: Run tests to verify they fail**

```bash
make test ARGS="tests/test_session_finish_reset.py -x"
```

Expected: FAIL — `NoReverseMatch: 'finish_session' is not a valid view function or pattern name`.

- [ ] **Step 3: Implement**

`finish_session` is `@login_required`, POST-only (`require_POST`), sets `timestamp_end = timezone.now()` plus the validated posted zone, saves, and returns `redirect(return_url(request, fallback="games:list_sessions"))`.

`reset_session` is `@login_required` and delegates to `confirm_and_apply` from Task 1, with `confirm_label="Reset to now"`, a message naming the game, and an action that sets `timestamp_start = timezone.now()` plus the validated posted zone. Reset overwrites the original start time and is only recoverable via Edit, so the confirm copy must say so.

Validate the posted zone through `zone_or_none()` (`common/date_time_presentation.py:422`), which already returns `None` for an unusable name.

Add both URLs to `games/urls.py` beside the other session routes, and both names to `ORIGIN_AWARE`.

- [ ] **Step 4: Run tests**

```bash
make test ARGS="tests/test_session_finish_reset.py tests/test_returns_classification.py -x"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views/session.py games/urls.py games/views/returns.py tests/test_session_finish_reset.py
git commit -m "feat: finish and reset a session over POST"
```

---

### Task 3: Rebuild `SessionActions` around the new routes

**Files:**
- Modify: `common/components/domain.py:341-414`
- Modify: `common/components/custom_elements.py:176-184` (`SessionActionsProps`)
- Modify: `ts/elements/session-actions.ts` (shrink to a time-zone stamper)
- Modify: `tests/test_components.py:307`, `tests/test_rendered_pages.py:467`
- Test: `tests/test_session_actions_component.py` (create)

**Interfaces:**
- Consumes: `games:finish_session`, `games:reset_session` from Task 2.
- Produces: `SessionActionsProps` reduced to `{session_id: int, is_open: bool}`. `api_url`, `csrf`, and `game_name` all go — the forms carry their own CSRF, and the game name now lives on the reset confirmation page.

**Gotchas:**
- **Do not delete `ts/elements/session-actions.ts`.** `custom_element_builder` auto-attaches `Media(js="dist/elements/session-actions.js")` (`common/components/primitives.py:252`) and `HashedStaticStorage` treats a missing manifest entry as a hard error, so removing the file while keeping the element emits a `<script>` for a file that does not exist.
- `ts/generated/props.ts` is gitignored and regenerated by `make gen-element-types` (a prerequisite of `ts`, `ts-check`, and `dev`), so no manual codegen step is needed — but `make ts-check` will fail on any `.ts` still reading a removed prop.
- `tests/test_rendered_pages.py:467` and `tests/test_components.py:307` assert the `api-url` attribute and fail outright once the prop goes. These are not cosmetic touch-ups.
- Never wrap a `ControlButton` in `A(href=...)`; pass `href=` or `method="post"` to it.

- [ ] **Step 1: Write failing tests**

In `tests/test_session_actions_component.py`:

- `test_open_session_renders_a_finish_post_form` — the rendered node contains a form whose action reverses `games:finish_session` for that pk and carries the `origin`
- `test_reset_is_a_link_to_the_confirmation_page` — a link to `games:reset_session`, not a modal
- `test_finished_session_renders_neither_finish_nor_reset`
- `test_no_reset_modal_markup_is_emitted` — assert `data-reset-modal` is absent
- `test_browser_time_zone_input_is_present_on_the_finish_form` — the hidden input the element fills

- [ ] **Step 2: Run tests to verify they fail**

```bash
make test ARGS="tests/test_session_actions_component.py -x"
```

Expected: FAIL — the finish button still renders as a bare `<button data-finish>`.

- [ ] **Step 3: Implement**

Rebuild `SessionActions` as a `ButtonGroup` of four members: Finish (`method="post"`, action `action_url("games:finish_session", session.pk, origin=origin)`, green, only while open), Reset (`href=action_url("games:reset_session", ...)`, gray, only while open), Edit, Delete — the last two unchanged. Delete the `Modal(self_dismiss=False)` block and the `game_name` local it fed.

Add a hidden `browser_time_zone` input inside the finish form, marked with a data attribute for the element to find.

Shrink `ts/elements/session-actions.ts` to a `connectedCallback` that writes `Intl.DateTimeFormat().resolvedOptions().timeZone` into every `input[data-browser-time-zone]` it contains. Drop the PATCH, the modal handling, `bindPopupDismiss`, the `disconnectedCallback` portal cleanup, and the `renderSessionRow` import.

The reset confirmation page needs the same hidden input, so the reset view's `ConfirmPage` details slot carries one and the element wraps that page's form too — or the page renders its own `<session-actions>`; pick one and say which in the code.

- [ ] **Step 4: Run tests and the type check**

```bash
make ts && make test ARGS="tests/test_session_actions_component.py tests/test_components.py tests/test_rendered_pages.py -x" && make ts-check
```

Expected: PASS. Update the two pre-existing `api-url` assertions as part of this step.

- [ ] **Step 5: Commit**

```bash
git add common/components/domain.py common/components/custom_elements.py ts/elements/session-actions.ts tests/
git commit -m "refactor: session finish and reset post instead of patching in place"
```

---

### Task 4: Delete the row-swap machinery

Only after Task 3, so nothing still imports it.

**Files:**
- Delete: `ts/session-row.ts`, `ts/session-row.test.ts`, `tests/test_session_row.py`
- Modify: `ts/date-time-presentation.ts:468-518` (remove `formatSessionTimeRange`)
- Modify: `ts/date-time-presentation.test.ts:266-530` (remove its describe block)
- Modify: `ts/elements/modal-dialog.ts:9,19`, `common/components/primitives.py:1679-1681`, `tests/test_components.py:1088-1091`, `ts/elements/modal-dialog.test.ts:51`

**Gotchas:**
- `formatSessionTimeRange` has `ts/session-row.ts` as its only consumer (verified across `ts/`, `dist/`, and e2e). Its zone-label and date-line rules are a hand-port of server logic, which is the point of removing it.
- Removing the reset modal orphans `Modal(self_dismiss=False)` — its only consumer — and the `data-manage="false"` branch in `modal-dialog.ts`. Either delete that branch and its two tests, or keep it deliberately; do not leave the comments at `primitives.py:1679` and `modal-dialog.ts:9` pointing at a component that no longer exists.

- [ ] **Step 1: Delete the files and the dead exports**

- [ ] **Step 2: Verify nothing references them**

```bash
grep -rn "session-row\|renderSessionRow\|formatSessionTimeRange" ts/ tests/ e2e/ common/ games/
```

Expected: no output.

- [ ] **Step 3: Rebuild and type-check**

```bash
make ts && make ts-check && make test-ts
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A ts/ tests/ common/
git commit -m "refactor: drop the session row rebuild and its time-range port"
```

---

### Task 5: Rewrite the browser tests

**Files:**
- Modify: `e2e/test_session_finish_e2e.py`, `e2e/test_session_reset_e2e.py`
- Modify: `e2e/test_time_zone_row_e2e.py:100-117`
- Modify: `e2e/test_control_sizing_e2e.py`

**Gotchas:**
- `test_finish_stamps_the_end_zone` asserts the finish button vanishes **without a page reload** and is the only regression guard for the browser-zone behaviour. Rewrite it against the reload; do not drop it.
- A UI assertion is not a database assertion. After the reload, wait on the server-rendered row before reading the ORM.
- Reset is now a page: the e2e must navigate to the confirmation and submit it, not click a modal button.

- [ ] **Step 1: Rewrite the three e2e files**

Finish: click Finish, wait for the sessions list to re-render, assert the row shows an end time and the finish control is gone, then assert `timestamp_end_timezone` equals the browser zone.

Reset: click Reset, assert the confirmation page renders and names the game, submit, assert the redirect returns to the list and `timestamp_start_timezone` equals the browser zone.

Control sizing: the finish/reset members are now a form submit and a link; update the selectors.

- [ ] **Step 2: Run the browser suite**

```bash
make test-e2e
```

Expected: PASS. Confirm `make dev` is not running first.

- [ ] **Step 3: Full gate**

```bash
make check
```

Expected: PASS, including lint, format-check, mypy, ts-check, vitest, and the whole pytest suite.

- [ ] **Step 4: Commit and open the PR**

```bash
git add -A e2e/
git commit -m "test: cover finish and reset as full page navigations"
```

PR targets `main`, closes #583, and notes that #486 is unblocked by it.
