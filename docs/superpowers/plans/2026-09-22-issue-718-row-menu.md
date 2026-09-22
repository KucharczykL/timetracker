# Row menu and tray Finish implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the Actions column on five tables into a row menu slot and a
selection tray that holds every act, with Finish declared as a bulk act.

**Architecture:** The trailing menu leaves the column system — a row states it
through `make_row`, the table renders one trailing cell whose drop priority is
computed above every declared column. One `EllipsisTrigger` serves the quick
bar, the library summary rows and the row menu. `FINISH_SESSION` joins the
runner as a `BulkAction` whose batch ends at one stamped instant.

**Tech Stack:** Django 6, Python 3.14, TypeScript custom elements, Tailwind,
pytest + pytest-xdist, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-22-issue-718-row-menu-design.md`

## Global Constraints

- Run everything through `make`. No `direnv exec .`, no bare `uv run`/`pnpm`.
- Iterate with `make check-fast`; gate on full `make check`, under
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- `make format` and `make lint-fix` before every commit, documentation included.
  `lint-fix` is what sorts imports; `format` does not.
- Build UI with `common.components` node builders, htpy form, never HTML strings.
- A component that needs JS declares its own `Media`; views do not thread
  `scripts=` for it.
- Never `instance.delete()`; never write a `GeneratedField`.
- No dispatch inside a transaction. A test that POSTs through a dispatching
  view needs `@pytest.mark.django_db(transaction=True)`.
- Every rejection carries a `sentence=`.
- Comments explain intent only — no issue or PR numbers in them.
- `make vale` governs prose and code comments: a projector *replays*, the row
  it writes is a *projection*, nothing is *deleted*.

---

### Task 1: The two bare ellipsis icons and `EllipsisTrigger`

**Files:**
- Create: `games/templates/icons/ellipsis-vertical.html`,
  `games/templates/icons/ellipsis-horizontal.html`
- Modify: `common/components/icons_generated.py` (by codegen only),
  `common/components/primitives.py` (the builder and its export),
  `common/components/__init__.py`,
  `common/components/quick_filter.py:425-456` (`_overflow_dropdown`)
- Test: `tests/test_components.py`

**Interfaces:**
- Produces: `type EllipsisOrientation = Literal["vertical", "horizontal"]` and
  `EllipsisTrigger(attributes: list[HTMLAttribute] | None = None, /, *, label:
  str, orientation: EllipsisOrientation = "vertical", haspopup: str = "menu")
  -> ControlButton`. Dynamic attributes take the **single positional slot**, as
  every styled builder does; an `attributes=` keyword is rejected by the node
  layer and by CLAUDE.md alike. It answers the component, not an `Element`:
  both `Dropdown` callers need `.as_element()`.

**Gotchas:**
- `ellipsis.html` is three dots in a ring and is **not** touched. It is
  `TruncatedText`'s reveal glyph, and its name is the value of the
  `data-truncated-reveal` attribute that four `e2e/test_truncated_text_e2e.py`
  assertions read.
- Icons are codegen. Write the snippet, run `make gen-icons`, commit
  `icons_generated.py`; never hand-edit it. `make check` runs `check-icons` and
  fails on drift.
- `Icon(name)` falls back to the `unspecified` glyph for an unknown name with
  no error, so a typo ships silently. The test below is what catches it.
- Match the existing snippet's shape: `viewBox="0 0 48 48"`,
  `fill="currentColor"`, `class="w-4 h-4"`, three `2.4` radius dots. Vertical is the same dots at
  x=24, y=15/24/33; horizontal at y=24, x=15/24/33. No ring on either.
- The quick bar today renders the literal `"⋯"` character. Swapping it changes
  the overflow host's measured width, which `quick-filter-bar.ts` measures once
  at connect — no logic change, but it is a visible change to a shipped page
  and belongs in the `render_pages` attribution of Task 10.

- [ ] **Step 1: Write the failing tests.** In `tests/test_components.py`, three
  cases: the rendered trigger contains the vertical icon's path data and not the
  `unspecified` glyph's; the horizontal orientation renders the other path; the
  trigger carries `aria-label` from `label` and `aria-haspopup` from `haspopup`.
  Assert on the path `d` attribute, not on the icon name — that is what proves
  codegen ran and the fallback did not fire.
- [ ] **Step 2: Run them and watch them fail.**
  `make test-fast ARGS="tests/test_components.py -k Ellipsis -x"`
- [ ] **Step 3: Write both snippets, run `make gen-icons`.**
- [ ] **Step 4: Write `EllipsisTrigger`** beside the other styled builders in
  `primitives.py`; export it from `__init__.py`'s `__all__`. Ghost variant,
  `p-2`, the icon carrying `aria-hidden="true"`.
- [ ] **Step 5: Run the tests; they pass.**
- [ ] **Step 6: Convert `_overflow_dropdown`** to
  `EllipsisTrigger(label="More filters", orientation="horizontal",
  haspopup="dialog").as_element()`, dropping the literal character.
- [ ] **Step 7: `make check-fast`**, then `make format && make lint-fix`, commit.

---

### Task 2: `RowActionMenu`, and the library summary rows as its first caller

**Files:**
- Modify: `common/components/custom_elements.py` (the builder, beside
  `ButtonDropdown`), `common/components/__init__.py`,
  `common/components/library_kit.py:207-233` (`_summary_action_menu`)
- Test: `tests/test_custom_elements.py`, `tests/test_library_ui_components.py`

**Interfaces:**
- Consumes: `EllipsisTrigger` from Task 1.
- Produces: `RowActionMenu(items: Sequence[Node], *, label: str, id: str,
  placement: str = "bottom-end") -> Node`. `items` are already-built
  `DropdownLinkItem` / `DropdownPostItem` / `DropdownActionItem` nodes.

**Gotchas:**
- This builder must know **no act**. It lives under `common/components/`, and
  importing `games.bulk_actions` from there closes a cycle: `bulk_actions`
  foot-imports `bulk_move` → `games/forms.py` → `common.components`, which is
  still initialising. Verified by running it. Items are the caller's.
- `ButtonDropdown` is not reusable here: it states no `variant`, appends a
  caret, and passes `aria_label` to the panel rather than the trigger.
- Media bubbles from a `<td>` — `SessionDeviceSelector` already proves it.
- `menu-behavior.ts` pins the panel `position: fixed` before unhiding, so the
  table's `overflow-x-auto` scroll wrapper does not clip it. No change needed.
- `menu-behavior.ts` already calls `preventDefault()` on a closing Escape so
  `selectable-table.ts` does not clear the selection underneath. No change needed.

- [ ] **Step 1: Write the failing test.** `RowActionMenu` renders a
  `role="menu"` panel whose `aria-label` is `label`, a trigger whose
  `aria-label` is `label`, and one `role="menuitem"` per item, in order.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Write `RowActionMenu`** as `Dropdown(trigger_element=
  EllipsisTrigger(...).as_element() through _as_menu_trigger,
  target_element=DropdownMenuPanel(items=..., aria_label=label), id=id,
  placement=placement)`.
- [ ] **Step 4: Run it; it passes.**
- [ ] **Step 5: Rewrite `_summary_action_menu`** as a call to it, keeping its
  `randomid` seed so the id is stable. Delete the hand-rolled trigger.
  `tests/test_library_ui_components.py:184` asserts `aria-label="Games
  actions"` on the trigger and must pass unchanged — that is the proof the
  conversion preserved behaviour.
- [ ] **Step 6: `make check-fast`**, format, lint-fix, commit.

---

### Task 3: The row's menu slot in the table

**Files:**
- Modify: `common/components/primitives.py` — `TableRowData` (~2240),
  `make_row` (~2338), `TableRow` (~2390), `_header_cell` (~2745),
  `StyledTable` (~3050)
- Test: `tests/test_components.py`, `tests/test_column_priority_contract.py`

**Interfaces:**
- Produces: `make_row(*cells, key=None, summary=None, menu: Node | None = None,
  **attributes)`; `TableRowData` gains `menu: NotRequired[Node]`.
- Produces: the trailing header `<th>` carries `data-row-menu`, no visible
  label, an sr-only accessible name, and
  `data-priority = max(column.priority for column in columns) + 1`.

**Gotchas:**
- `<responsive-table>` hides columns with positional
  `[&_tr>*:nth-child(N)]:hidden` built from `thead th` order
  (`ts/elements/responsive-table.ts:48`). The trailing cell therefore needs a
  matching `<th>` or every declared column's index shifts in the body only.
- That element reads `Number(cell.getAttribute("data-priority") ?? "1")`. A
  marker-only `<th>` would be priority 1 and the **first** to drop. The computed
  maximum is load-bearing, not decoration.
- `StyledTable` guards cell count against column count. It must count the menu
  cell on both sides or the guard fires on every menu row.
- The slot is outside `columns`, so `MAX_DATA_TABLE_COLUMNS` is untouched. But
  `common/input.css:15` safelists the drop and alignment classes only to
  `nth-child(12)`, and the slot consumes one of those twelve positions. None of
  the five tables comes near it; say so in a comment rather than leaving the
  next table to discover it.
- `_header_cell` emits `data-priority` only under `data_table`. The trailing
  header follows the same gate, or `tests/test_column_priority_contract.py`'s
  regex reads a table that drops nothing.
- Where some rows state a menu and some do not, the rows without one still get
  an empty trailing cell: the grid stays rectangular, or `nth-child`
  misaddresses every column after it.
- Do not add a `menu` field to `Column`. An earlier draft did; the slot is a
  row's, not a column's.

- [ ] **Step 1: Write the failing tests.** Four cases. A table whose rows state
  a menu renders one extra `<th>` and one extra trailing cell per row. That
  `<th>` carries `data-row-menu` and a `data-priority` strictly greater than
  every declared column's. Its visible text is empty and its accessible name is
  not. A table whose rows state no menu renders neither.
- [ ] **Step 2: Run them and watch them fail.**
  `make test-fast ARGS="tests/test_components.py -k menu_slot -x"`
- [ ] **Step 3: Implement** across the five functions above.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Add the contract test's counterpart.** In
  `tests/test_column_priority_contract.py`, a case asserting that a rendered
  `data-row-menu` header outranks every `data-priority` in its own table. Leave
  `assert_actions_dominates` alone: six tables still declare a labelled
  `Actions` column (`games/views/game.py:251`, `:868`, `:1027`,
  `games/views/purchase.py:141`, `games/views/device.py:90`,
  `games/views/platform.py:97`) and it is their only guard. The test exempts a
  table it finds no `Actions` label on, so the five converted tables fall out of
  it by themselves — that is intended, and the new case is what replaces it.
- [ ] **Step 6: `make check-fast`**, format, lint-fix, commit.

---

### Task 4: Delete `Cardinality`

**Files:**
- Modify: `games/bulk_actions.py` (the enum, the field, `__post_init__` if it
  reads it), `games/bulk_tray.py` (`SPELLED`, the filter),
  `games/bulk_move.py`, `games/bulk_reclassification.py`,
  `games/bulk_removal.py` (three declarations),
  `common/components/primitives.py` (`SelectionCardinality`,
  `SelectionAction["cardinality"]`, the `"many"` filter in
  `_selection_actions_slot` ~2930), `common/components/__init__.py`
- Test: `tests/test_bulk_actions.py`, `tests/test_bulk_runner.py`,
  `tests/test_bulk_tray.py`, `tests/test_components.py`

**Gotchas:**
- Eleven files, not the five the spec's first draft counted.
  `tests/test_bulk_actions.py` alone has eight sites, one of which
  (`test_making_the_value_declares_it`) constructs with `Cardinality.ONE`.
  `tests/test_components.py` has seven literal `"cardinality"` keys, one
  `"one"`.
- The `cardinality` hit in `common/criteria.py` is prose about relation
  cardinality. Leave it.
- `tray_actions`' docstring explains why a `one` act is skipped. The whole
  paragraph goes with the filter.

- [ ] **Step 1: Delete the enum, the field and both filters**, then the four
  test files' references. No new test: this task's proof is that the existing
  suite still passes with the concept gone.
- [ ] **Step 2: `make check-fast`.** Expect `mypy` to name every missed site.
- [ ] **Step 3: `make typecheck`** clean, format, lint-fix, commit.

---

### Task 5: `end_session` and `correct_session` grow the runner's shape

**Files:**
- Modify: `games/writes/playersession.py:166` (`correct_session`), `:227`
  (`end_session`)
- Test: `tests/test_session_writes.py`

**Interfaces:**
- Produces: both gain `idempotency_key: IdempotencyKey | None = None` and
  `source_metadata: SourceMetadata | None = None`, and both answer the
  `CommandResult` that `_dispatch` already returns and they currently discard.

**Gotchas:**
- Defaults keep both existing callers (`games/views/session.py:489`, and
  `games/api.py:1065` for the correction) compiling unchanged; neither reads
  the answer.
- This is **not** enough to satisfy `RunRow`. That protocol names `choice`,
  `idempotency_key` and `correlation_id` as keywords and answers `RowOutcome`,
  and knows nothing of `source_metadata`. Task 6 writes the wrapper, as every
  shipped act has one (`games/bulk_removal.py:125`).

- [ ] **Step 1: Write the failing test** — each function answers a
  `CommandResult` whose outcome is `APPENDED` first and `REPLAYED` on a repeat
  under the **same** key with the same input, and records the given
  `source_metadata` on the event. Not `UNCHANGED`: a same-key repeat is a
  replay (`games/events/dispatch.py:389-399`), and `RowOutcome.of` counts a
  replay as moved because the key was this batch's own. `UNCHANGED` is what a
  *different* key answers when the row already states that value.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Add the two keywords and the two returns.**
- [ ] **Step 4: Run it; it passes.** Commit.

---

### Task 6: `FINISH_SESSION`

**Files:**
- Create: `games/bulk_finish.py`
- Modify: `games/bulk_actions.py:297` (the foot import)
- Test: `tests/test_bulk_finish.py`, `tests/test_bulk_runner.py`

**Interfaces:**
- Consumes: Task 5's `end_session` / `correct_session`.
- Produces: `FINISH_SESSION: BulkAction[PlayerSession]`, name
  `"session.finish"`, label `"Finish"`, colour `"green"`,
  `inverse_aggregate="playersession"`, fallback `"games:list_sessions"`.
- Produces: `FinishStatement` — a frozen slotted dataclass of
  `ended_at: datetime` and `ended_at_zone: ZoneName | None`, with
  `encode(self) -> ChoiceValue` and `classmethod decode(cls, raw: ChoiceValue)
  -> FinishStatement`. The encoding is the ISO instant, a `|`, and the zone key
  or the empty string. It is a named compound type because it crosses three
  boundaries as one string, and CLAUDE.md refuses a bare tuple there.
- Produces: `finish_choice: BulkChoice[PlayerSession]` whose `ChoiceValue` is
  that encoding.

**Gotchas — the one that must not be got wrong:**
- `_run_a_chunk` keys each row `f"{act.name}-{token}-{acted}"`
  (`games/views/bulk.py:499`) and `fingerprint_command_input`
  (`games/events/idempotency.py:146`) hashes the command's input. A payload that
  differs between two posts of one chunk raises `IdempotencyKeyMismatch`, which
  `answered()` maps to a conflict, so **every already-finished row would be
  counted refused**. `<continuing-batch>` posts the waypoint on connect, so a
  reload reproduces it. `timezone.now()` inside `run` is exactly such a payload.
  The instant is stamped once in `offer` and carried in the choice.
**The choice must survive its own output.** `settle` is re-run from
  `request.POST` on every chunk (`games/views/bulk.py:718`), and `_progress`
  round-trips its answer back under `CHOICE_FIELD` (`:607-609`). `ProgressBatch`
  renders hidden pairs only (`games/views/bulk_pages.py:200-235`), so on chunk
  two there is no `<browser-time-zone>` element and no separate zone field —
  only `CHOICE_FIELD` holding what `settle` last returned. Therefore:
  - `offer` renders **two** inputs: one hidden input named `field_name` (the
    `CHOICE_FIELD` the runner hands it) carrying a `FinishStatement` already
    encoded with the server-stamped instant and an empty zone, and
    `BrowserTimeZoneInput()` under its own `browser_time_zone` name, which
    `ts/elements/browser-time-zone.ts` fills.
  - `settle` decodes `CHOICE_FIELD`, and takes the zone from the decoded value
    if it holds one, otherwise from `browser_time_zone`. So chunk one composes
    instant-from-choice with zone-from-browser, and every later chunk decodes a
    value that already holds both. **`settle(settle(x)) == settle(x)` is the
    rule; write a test for it by name.**
  - `run` decodes the `choice` it is handed into a `FinishStatement` and passes
    its two fields to `end_session`. A `choice` of `None` is a defect, not a
    state: raise rather than stamping a fresh instant.
- `offer` is called again by `_reconfirmation` (`games/views/bulk.py:356`) when
  a settle refusal interrupts a batch. It must **reuse the instant already in
  `request.POST`** and stamp a fresh one only when there is none, or the rows
  after the interruption end later than the rows before it and the spec's "one
  batch ends at one instant" is false. `offer` takes no request, so read it off
  the rows' own batch instead: pass the encoded value through by giving
  `offer` the posted `CHOICE_FIELD` — if that means widening `BulkChoice.offer`
  to see the POST, widen it, and say so in the commit; the alternative is an
  act that quietly records two instants.
- `settle` validates both halves, because the field is a person's to edit: an
  instant it cannot parse raises `CommandRejected` with a `sentence=`; the zone
  goes through `zone_or_none` (`common/date_time_presentation.py:423`) and an
  unusable one becomes no zone, matching what the row's Finish records through
  `_posted_browser_zone`.
- `bulk_pages.py:156` widens the confirmation whenever `choice is not None` and
  wraps it in a visible margin block. `BrowserTimeZoneInput()` renders only a
  hidden input, so the page gains an empty block. Give the control a visible
  line naming the instant the batch will record — it is a fact worth stating
  before the press, and it stops the slot rendering nothing.
- **`run` must write `source_metadata`.** `_act_of` (`games/views/bulk.py:773`)
  identifies a batch by `first.source_metadata["bulk"]["action"]` and answers
  `Http404("That act is no batch.")` without it, so the toast's Undo would
  404. Every shipped act writes it through a module-local `_source()`
  (`games/bulk_removal.py`, `games/bulk_move.py`,
  `games/bulk_reclassification.py`); `games/bulk_finish.py` gets its own, and
  both the `run` and the `inverse` pass it.
- `scope` and `resolve` are `bulk_removal.session_scope` /
  `session_resolution`, reused, not copied.
- The inverse restates timing through `correct_session` with
  `TimedTiming(started_at=row.started_at, day_zone=row.day_zone,
  started_at_zone=row.started_at_zone)` and no end. `day_zone` is
  `null=True` on the model and non-null on a Timed row by CHECK alone, so assert
  it as `reset_session` does (`games/writes/playersession.py:267`), or mypy
  reddens.
- `UndoRow` receives a `row_id`, not a row. Read the row back with the plain
  manager scoped to the library, as `_removed_row` does — the row is live here,
  so `library_sessions` also works, but the act must not depend on the catalog
  mark.
- A library whose calendar zone changed between the Finish and the Undo has
  every row of the Undo refused: `CorrectSessionTiming.build` checks the
  calendar before comparing. Accepted; name it in the act's test.

- [ ] **Step 1: Write the failing tests.** Eight:
  1. a running row is ended at the stamped instant with the settled zone;
  2. a row that is not running is refused and named in the report;
  3. two posts of one chunk under one token count the same and **not** as
     refusals — the regression test for the fingerprint, driven through
     `games:run_bulk_action` rather than by calling `run` twice, because the
     key is the runner's;
  4. `settle` is idempotent: feeding its own answer back under `CHOICE_FIELD`,
     with no `browser_time_zone` present, answers the same string;
  5. a batch spanning two chunks ends every row at one instant;
  6. the batch's events carry `source_metadata["bulk"]["action"] ==
     "session.finish"`, and `_act_of` answers `FINISH_SESSION` for its
     correlation id — this is what makes the Undo reachable, and it must be
     driven through the route, not by calling the inverse;
  7. the inverse puts a finished row back to running;
  8. `settle` refuses an unparseable instant with a sentence, and an unusable
     zone settles to no zone.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Write `games/bulk_finish.py`** — the wrapper `run`, the
  `inverse`, `finish_choice`, the preview columns (Game, Day, Started), and the
  declaration. Add it to the foot import in `bulk_actions.py`.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: `make check-fast`**, format, lint-fix, commit.

---

### Task 7: The session table

**Files:**
- Modify: `games/views/session.py:104-148` (`session_row_data`), `:215-258`
  (the columns and the selection), `common/components/domain.py:607`
  (`SessionActions` leaves — delete it there)
- Create: `games/views/session_menu.py`
- Test: `tests/test_session_actions_component.py` (rewritten),
  `tests/test_components.py`, `e2e/test_session_finish_e2e.py`,
  `e2e/test_session_reset_e2e.py`

**Interfaces:**
- Consumes: `RowActionMenu` (Task 2), the menu slot (Task 3),
  `FINISH_SESSION` (Task 6).
- Produces: `session_row_menu(session: PlayerSession, csrf_token: str, origin:
  OriginUrl | None) -> Node`.

**Gotchas:**
- `SessionActions` must leave `common/components/domain.py`. The menu reads the
  tray acts' labels, and `common/` importing `games.bulk_actions` closes the
  import cycle proven in Task 2's gotchas. `games/views/session_menu.py` may
  import it freely — `games/views/session.py` already imports `bulk_tray`.
- Deleting it touches four more places: the two `__init__.py` entries
  (`common/components/__init__.py:87` and its `__all__` at `:450`),
  `tests/test_components.py:455` (`SessionActionsTest`),
  `tests/test_session_actions_component.py`, and
  `tests/test_session_reclassification_views.py:181-188`, which asserts the
  reclassification tooltip is shown on a Duration-only row and not on a
  measured one. That assertion survives as an item-present / item-absent case
  against the menu.
- The items, in order: Finish and Reset while running; Edit; Move to
  playthrough; Record as historical playtime while Duration-only; Remove. A
  gated act is **absent**, never disabled.
- Finish posts, so it is `DropdownPostItem` and needs `hidden_fields` for
  `BrowserTimeZoneInput()` — add that keyword to `DropdownPostItem` in
  `common/components/custom_elements.py:949`. The two playthrough acts in Task 8
  post without one.
- Everything else is a `DropdownLinkItem` to its confirmation page, carrying
  `?origin=` through `action_url` exactly as today.
- Tray order is priority order, destructive last:
  `tray_actions(MOVE.name, FINISH_SESSION.name, RECLASSIFY.name,
  REMOVE_SESSION.name, origin=origin)`.
- `e2e/test_session_finish_e2e.py:38` clicks
  `form[action*="/finish"] button[type="submit"]` inside the row, and
  `e2e/test_session_reset_e2e.py:57` clicks a link by role inside the row. Both
  controls are now inside a panel that starts hidden: each test opens the row's
  menu first.
- `e2e/test_responsive_table_e2e.py:246` asserts the last `thead th` reads
  "actions". It runs on Purchases, which keeps its column, but `LIST_PAGES`
  (`:151`) includes sessions — check both paths.

- [ ] **Step 1: Write the failing tests.** A running Timed row's menu holds six
  items in order; a finished row holds four and no Finish or Reset; a
  Duration-only row holds Record as historical playtime and a Timed row does
  not; the tray offers four acts with Remove last; the table renders no
  `Actions` header.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Write `session_menu.py`, delete `SessionActions`, drop the
  column, extend `DropdownPostItem`, restate the tray.**
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Update the two e2e tests to open the menu first.**
- [ ] **Step 6: `make test-e2e ARGS="-k session_finish or session_reset"`.**
  That target already depends on `css ts` (`Makefile:488`), so no separate
  build step. Never run it while `make dev` is up — its watchers rewrite the
  served assets underneath it.
- [ ] **Step 7: `make check-fast`**, format, lint-fix, commit.

---

### Task 8: The record and run tables

**Files:**
- Modify: `games/views/historical_playtime.py:94-115` (`record_actions` becomes
  the menu), `:148-166` (the column goes);
  `games/views/playthrough_rows.py:75-89` (the column goes), `:288-355`
  (`_actions` / `_act_members` / `_act` become menu items)
- Test: `tests/test_playtime_page.py`,
  `tests/test_game_detail_historical_playtime.py:112-137`,
  `tests/test_game_detail_playthroughs.py`,
  `tests/test_playthrough_view_cutover.py`,
  `tests/test_playthrough_rows.py:198-210`,
  `e2e/test_historical_playtime_entry_e2e.py:46,57`

**Gotchas:**
- Both builders serve **two** surfaces each. `historical_playtime_tabledata` is
  the Historical tab and Game detail's section; `playthrough_tabledata` is the
  Playthrough list page (`games/views/playthrough.py:183`) and Game detail's
  section. Five tables, not the issue's four — settled by the wave organizer,
  retire on both.
- Both builders drop columns by index (`dropped_indexes` against
  `exclude_columns`). Removing `Actions` from `column_list` shifts every index
  after it; the cell lists must lose their last element in the same commit.
- `playthrough_rows.py:89` is the line `#715` also edited. Rebase over `main`
  before starting.
- Record menu: Edit, Remove. Run menu: Started today where the run states
  neither endpoint, Completed today where it states a start and no completion,
  then Edit, Remove. The gating lives in `_act_members` already — keep it, and
  keep its comment about why a completed run is offered no start.
- The two run acts keep their existing titles as item labels: `"Started today"`
  and `"Completed today, also marks the game Completed"`.
- `playthrough_tabledata` raises when a row carries no `activity` alias. The
  menu does not read it; leave that check where it is.
- Three test files break in ways the task must fix, not discover:
  `tests/test_playthrough_rows.py:198-210` reads `row["cell_data"][-1]` and
  asserts `/start`, `method="post"` and the token in it — after the column goes
  that index is the Created date, so the assertion moves to the row's `menu`;
  `tests/test_game_detail_historical_playtime.py:112-116` does
  `dict(policies)["Actions"]` and raises `KeyError`, and `:129-137` states an
  expected column list ending in `"Actions"`.
- One e2e breaks: `e2e/test_historical_playtime_entry_e2e.py:46,57` clicks
  `rows.first.get_by_title("Edit historical playtime")` and
  `("Remove historical playtime")`. Those titles live on `ButtonGroup` icon
  members; as menu items they are text inside a panel that starts hidden. Both
  become "open the row's menu, then click the item by name".

- [ ] **Step 1: Write the failing tests** — each of the four surfaces renders
  no `Actions` header and one menu per row, with the item lists above.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Convert both builders.**
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Update the entry e2e to open the menu first**, then
  `make test-e2e ARGS="-k historical_playtime_entry"`.
- [ ] **Step 6: `make check-fast`**, format, lint-fix, commit.

---

### Task 9: The tray's priority-plus overflow

**Files:**
- Modify: `common/components/primitives.py:2917-2967`
  (`_selection_actions_slot`), `ts/elements/selectable-table.ts`
- Create: `ts/elements/selection-actions.ts` if the slot has no element of its
  own yet — `_SelectionActionsElement` is already declared
  (`primitives.py:2707`), so extend that element rather than adding one
- Test: `ts/elements/selection-actions.test.ts`,
  `e2e/test_selection_actions_e2e.py:33-70`

**Interfaces:**
- Consumes: `EllipsisTrigger` (Task 1), `priorityPlusFitCount` /
  `priorityPlusTotalWidth` from `ts/elements/priority-plus.ts`.

**Gotchas:**
- The selection line renders with the `hidden` attribute and
  `selectable-table.ts:138` clears it only when the mode turns on. `offsetWidth`
  inside a `display:none` ancestor is 0, so measuring at connect measures
  nothing. Measure on the first `setMode(true)` and cache. This is the one way
  this differs from `quick-filter-bar.ts`, which is always visible.
- Declaration order is priority order. Document it on `tray_actions` and on
  `SelectionDeclaration["actions"]`; the views already state Remove last after
  Task 7.
- The acts are rendered disabled until the first count. Disabled is opacity
  only, so widths measured while disabled are the widths used.
- The overflow trigger is horizontal, and its panel is a menu of submits, not a
  dialog of moved nodes — unlike the quick bar's. Moving a `<button
  type="submit" formaction=…>` into a panel keeps it inside the one form, which
  is what makes one statement serve every act; do not wrap it in a form of its
  own. But `menu-behavior.ts:103` roves only `[role="menuitem"]` and fires an
  item with `item.click()` (`:249`), so each moved submit needs
  `role="menuitem"` and an `<li role="presentation">` wrapper, added
  server-side where the button is built rather than by the element as it moves.
- **The panel needs an id unique on the page.**
  `_selection_actions_slot(actions, csrf_token)` (`primitives.py:2917`) is
  handed no caption, and Game detail renders two selectable tables at once
  (`games/views/game.py:1120`, `:1168`). Thread the table's `caption_key` — the
  same fact the selection scope already keys on — into the slot and seed the
  `Dropdown` id from it, or
  `tests/test_html_validity.py::test_ids_are_unique_and_describedby_targets_resolve_once`
  fails on that page.
- `make ts` after every `.ts` edit, or the e2e run serves stale output. Never
  run e2e while `make dev` is up.

- [ ] **Step 1: Write the failing vitest cases** — with a width fitting two
  acts, the third and fourth move into the overflow, rightmost first; widening
  moves them back; measurement taken while the line is hidden yields no layout.
- [ ] **Step 2: Run them and watch them fail.** `make test-ts`
- [ ] **Step 3: Implement** in the selection-actions element, reusing
  `priority-plus.ts` for the arithmetic.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Extend the real-page tray e2e**, which is
  `e2e/test_selection_actions_e2e.py:33-70` on `games:list_sessions` — **not**
  `e2e/test_selectable_table_e2e.py`, which stands up a synthetic
  `ROOT_URLCONF` with two stub routes and no bulk route, so it cannot press a
  real act. Two cases: at a narrow viewport the overflow trigger appears and an
  act inside it still posts the statement; and the existing
  `get_by_role("button", name="Remove", exact=True)` still resolves — Remove is
  declared last after Task 7, so it is the **first** act to overflow, and at
  Playwright's default viewport with four acts it may already be inside the
  menu. If it is, that assertion opens the menu first; check, do not assume.
- [ ] **Step 6: `make ts`, `make check-fast`**, format, lint-fix, commit.

---

### Task 10: The gates

**Files:**
- Modify: `docs/superpowers/specs/2026-09-22-issue-718-row-menu-design.md`
  only if a gate contradicts it

**Gotchas:**
- `make render-pages ARGS="--user NAME --out DIR"` is read-only. Run it at
  `origin/main` and at the branch head against one database and `diff -r`. Every
  differing file is attributed, and three whole classes are expected: the five
  tables losing a header cell and gaining a trailing one, the quick bar's
  overflow glyph becoming an SVG, and the library summary rows' trigger markup
  changing shape under `RowActionMenu`.
- The Orca transcript is one page — the Playtime session list. Turn the mode on
  and hear it announced; Space a row and hear "1 selected"; Space a second and
  hear "2 selected"; reach the tray and press Remove, landing on the
  confirmation; go back and Escape the selection; Tab to a row's menu and open
  it, hearing it named and its items counted; arrow through and confirm a gated
  act is absent rather than disabled; Enter on Edit and land on the form.
- Two visual questions for the same pass, neither measured: a row now shows the
  ringed reveal ellipsis inline after a clipped name **and** the bare kebab in
  the trailing slot, two ellipses a cell apart; and each `<drop-down>` binds two
  document listeners for its connected life, with `per_page` admitting 1000 and
  the run and record lists paying it for the first time.
- The full gate is `make check`, including `e2e/`, under the shared lock. Never
  a hand-picked subset. Read its exit code from a log, never `grep | tail` —
  ruff prints "All checks passed!" while a sibling step is failing.

- [ ] **Step 1: `make render-pages` at both commits, `diff -r`, attribute every
  file.**
- [ ] **Step 2: Capture the Orca transcript; fix what it finds.**
- [ ] **Step 3: Show the user the session list and the run list at desktop and
  at 400px.**
- [ ] **Step 4:**
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
- [ ] **Step 5: Open the PR.**
