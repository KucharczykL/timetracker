# A person chooses which columns a list shows — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person turns a list's columns off and on, the choice outlives the
page, and every list keeps dropping what does not fit among the columns left.

**Architecture:** A `ListColumnChoice` row per person per mode holds the keys the
person hid. `Column` gains a stable `key` and a `hideable` flag. The hidden set
is a parameter each table builder takes — not a pass over a finished `TableData`
— because the same set decides the stacked summary's content. A `<drop-down>` on
the quick filter bar posts it to one origin-aware route.

**Tech Stack:** Django 6, PostgreSQL 18, Python 3.14, pytest + pytest-xdist,
Playwright for e2e, TypeScript custom elements, Tailwind.

**Spec:** `docs/superpowers/specs/2026-09-22-issue-1245-column-choice-design.md`

## Global Constraints

- Read `CLAUDE.md` first. It governs every convention below and overrides habit.
- Run targets through `make`. Never wrap in `direnv exec .`, never bare `uv run`.
- Iterate with `make check-fast`. The gate before a PR is the **full**
  `make check`, e2e included, under the shared lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
- `make format` **and** `make lint-fix` before every commit. `format` leaves
  import order alone; only `lint-fix` fixes `I001`.
- Build UI with `common.components` builders in htpy form. No HTML strings, no
  new inline Alpine.
- Every new route is classified in `games/views/returns.py` or the completeness
  guard fails. No route mutates on GET.
- `make vale` governs prose and comments. `fold`, `seam`, `leg`, `tombstone`,
  `archive`, `delete` and `heal` are refused; see `docs/vocabulary.md`.
- Comments explain non-obvious intent only. No issue or PR references in them.

---

### Task 1: The row and its module

**Files:**
- Modify: `games/models.py` (new model beside `FilterPreset`)
- Create: `games/migrations/0013_list_column_choice.py` (via `make makemigrations`)
- Modify: `games/identity_audit.py:41` (`RESIDUAL_INTEGER_RELATIONS`)
- Modify: `tests/test_uuid_identity_audit.py:32` (`EXPECTED_RELATION_COLUMNS`)
- Create: `games/list_columns.py`
- Test: `tests/test_list_columns.py`

**Interfaces — Produces:**

```python
def hidden_columns(user: object, mode: str) -> frozenset[ColumnKey]:
    """The keys this person turned off on this list. Empty where none."""
```

```python
def state_hidden_columns(
    user: object, mode: str, hidden: Collection[ColumnKey]
) -> None:
    """Replace the person's choice. An empty set removes the row."""
```

`ColumnKey` is defined in Task 2 and imported here; write Task 2 first if you
prefer a clean import, or use `str` and tighten it in Task 2.

**Model shape, exactly:**

```text
ListColumnChoice
  id       UUIDv7Field(primary_key=True, editable=False)
  user     ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE,
                      related_name="list_column_choices")
  mode     CharField(max_length=50, choices=FilterPreset.MODE_CHOICES)
  hidden   JSONField(default=list, blank=True)
  updated_at DateTimeField(auto_now=True)
  Meta.constraints: UniqueConstraint(fields=["user", "mode"],
                                     name="unique_list_column_choice_per_mode")
```

**Gotchas:**
- The `UUIDv7Field` key is what keeps this table out of
  `RESIDUAL_INTEGER_PRIMARY_KEYS` and its pinned twin at
  `tests/test_uuid_identity_audit.py:79`. Do not use an implicit integer key.
- `user_id` is a bigint, so it needs **both** inventory lines. Use the existing
  `NEVER_CONVERTS` label; `games_userpreferences.user_id` is the precedent.
- `make makemigrations` prompts on a new `UUIDv7Field`. The Make target passes
  `--noinput`; do not call `manage.py` directly.
- `choices` is **not** a database refusal — Django reads it in `full_clean()`.
  `state_hidden_columns` refuses an unknown mode itself.
- Not removable: no `removed_at`, absent from `REMOVABLE_MODELS`. A preference is
  not a record a person removes.

- [ ] **Step 1: Write the failing tests** in `tests/test_list_columns.py`:
  - `hidden_columns` answers an empty set for a person with no row
  - `state_hidden_columns` then `hidden_columns` round-trips two keys
  - a second `state_hidden_columns` replaces rather than adds
  - an empty collection removes the row (`ListColumnChoice.objects.count() == 0`)
  - a mode outside `FilterPreset.MODE_CHOICES` raises `ValueError`
  - two people state different sets on one mode and neither reads the other's
- [ ] **Step 2: Run them and confirm they fail.**
  `make test-fast ARGS="tests/test_list_columns.py -x"`
- [ ] **Step 3: Add the model, run `make makemigrations ARGS="games --name list_column_choice"`, then `make migrate`.**
- [ ] **Step 4: Add both inventory lines.** Run
  `make audit-uuid-identity` and confirm no violations.
- [ ] **Step 5: Write `games/list_columns.py`.** Read with
  `.values_list("hidden", flat=True).first()`, write with `update_or_create`.
- [ ] **Step 6: Run the tests plus the audit's own.**
  `make test-fast ARGS="tests/test_list_columns.py tests/test_uuid_identity_audit.py"`
- [ ] **Step 7: `make format && make lint-fix`, then commit.**

---

### Task 2: A column's key and its hideable flag

**Files:**
- Modify: `common/components/primitives.py:2263-2288` (`Column`)
- Modify: `games/views/game.py:245-251`, `purchase.py:133-141`,
  `device.py:87-90`, `platform.py:92-97`, `session.py:212-222`,
  `playthrough_rows.py:75-88`, `historical_playtime.py:157-173`
- Test: `tests/test_column_keys.py`

**Interfaces — Produces:** `Column.key: ColumnKey` and `Column.hideable: bool`,
plus `type ColumnKey = str` exported from `common/components/primitives.py`.

**Gotchas:**
- `Column` is a `NamedTuple`. New fields go **after** `priority` with defaults,
  or every positional call site breaks.
- The game list's playtime header is computed per request and reads one of three
  labels (`games/views/game.py:196-208`). Its key is `"playtime"` and never the
  label. This column is why keys exist.
- `hideable=False` on: every list's first column, and the Actions column of
  games, purchases, devices and platforms. Nothing else.
- Game detail's tables (`game.py:863-868`, `:1023-1027`, `:1065-1067`) carry no
  picker and need no keys.

- [ ] **Step 1: Write the failing test** in `tests/test_column_keys.py`,
  parametrized over the seven modes, asserting: every column of every list
  states a non-empty `key`; the keys of one list are distinct; the first column
  and any Actions column state `hideable=False`; every other column states
  `hideable=True`. Build each list's columns by calling the view, or import the
  module-level tuples where the view exposes them.
- [ ] **Step 2: Run it and confirm it fails.**
  `make test-fast ARGS="tests/test_column_keys.py -x"`
- [ ] **Step 3: Add the two fields to `Column`** with defaults `key: ColumnKey = ""`
  and `hideable: bool = True`, and export `ColumnKey`.
- [ ] **Step 4: State a key on every column of the seven lists.** Use the
  lowercased single-word label where one exists (`name`, `date`, `duration`,
  `device`, `created`, `playthrough`, `status`, `year`, `wikidata`, `type`,
  `price`, `infinite`, `purchased`, `finished`, `refunded`, `icon`, `group`,
  `references`, `when`, `provenance`, `playthroughs`, `game`, `started`,
  `completed`, `activity`, `days`, `note`, `actions`), and `playtime` for the
  game list's computed header.
- [ ] **Step 5: Run the test and the render suite.**
  `make test-fast ARGS="tests/test_column_keys.py tests/test_rendered_pages.py tests/test_sort_header_parity.py"`
- [ ] **Step 6: `make format && make lint-fix`, then commit.**

---

### Task 3: Narrowing as a builder parameter

**Files:**
- Modify: `common/components/primitives.py` (new helper beside `Column`)
- Modify: `games/views/playthrough_rows.py:54-131`,
  `games/views/historical_playtime.py:137-226`
- Modify: `games/views/game.py:1101`, `:1146` (the two Game detail call sites)
- Test: `tests/test_column_narrowing.py`

**Interfaces — Produces:**

```python
def drop_columns(
    columns: Sequence[Column], rows: Sequence[list[Cell]], hidden: Collection[ColumnKey]
) -> tuple[list[Column], list[list[Cell]]]:
    """Drop each hidden column and the cell at its index in every row.

    A column stating `hideable=False` is kept whatever the set says, and so is
    column 0, which must stay shrinkable while any row carries a summary.
    """
```

**Why this is not a pass over a finished `TableData`:** `exclude_columns` also
decides summary content — `with_game` at `playthrough_rows.py:120`, `with_when`
at `historical_playtime.py:224`, which swaps between two different summaries at
`:246-258`. Narrowing after the builder would drop a cell and leave its fact in
the stacked line.

**Gotchas:**
- Rename `exclude_columns` to `hidden`, keyed on `ColumnKey` rather than label.
  Update both Game detail call sites: `["Name", "Created"]` → `["name", "created"]`,
  `["Game"]` → `["game"]`.
- `StyledTable` raises under `DEBUG` on a cell count that does not match the
  column count, and on a summary under a first column that is not `shrinkable`
  (`common/components/primitives.py:3269-3294`). In production both degrade to a
  ragged table, so the test is the real guard.
- The menu slot is outside `columns` and counted on neither side.

- [ ] **Step 1: Write the failing tests** in `tests/test_column_narrowing.py`:
  - `drop_columns` drops one column and its cell from each row
  - it drops two non-adjacent columns and keeps every other cell in order
  - a `hideable=False` column survives being named
  - column 0 survives being named
  - an unknown key drops nothing
  - the returned column count equals every returned row's cell count
- [ ] **Step 2: Run them and confirm they fail.**
  `make test-fast ARGS="tests/test_column_narrowing.py -x"`
- [ ] **Step 3: Write `drop_columns`.**
- [ ] **Step 4: Re-key both builders' `exclude_columns` to `hidden`** and have
  them call `drop_columns` instead of their hand-written index walks. Keep
  `with_game` and `with_when`, now reading the same set by key.
- [ ] **Step 5: Run the builders' own suites.**
  `make test-fast ARGS="tests/test_playthrough_rows.py tests/test_historical_playtime_pages.py tests/test_game_detail_playthroughs.py tests/test_game_detail_historical_playtime.py"`
- [ ] **Step 6: `make format && make lint-fix`, then commit.**

---

### Task 4: The session list stops deciding

**Files:**
- Modify: `games/views/session.py:200-247`
- Modify: `games/reads/player_sessions.py:52-61` (remove `sole_game`)
- Modify: `games/reads/session_run_labels.py:60-70` (remove `ambiguous_run_labels`)
- Modify: `tests/test_session_list.py:126-140`, `:56-62`
- Modify: `tests/test_player_session_reads.py`, `tests/test_session_run_labels.py`

**Gotchas:**
- `every_run_label` has a **second** reader, `games/bulk_move.py:125`, which
  raises `RowUnreadable` for a row arriving without a label. Do not change its
  signature.
- `_labelled_runs` already runs on every load through whichever branch the view
  took, so this adds no query. `tests/test_session_list.py:170-184` pins that
  and must keep passing.
- The Playthrough column keeps `priority=3` and its position after Name. It ties
  with Date deliberately: the rightmost of equals drops first, so the grouping
  key outlives the others.
- `session_row_data` builds its summary from `run_name` internally. With the
  column hidden, `run_name` is `None` and `row_summary` drops the part — confirm
  the stacked line still reads correctly rather than showing a stray comma.

- [ ] **Step 1: Rewrite the breaking test.**
  `test_a_list_naming_two_games_keeps_the_name_cells_label` asserts a mixed list
  shows name-cell labels and no Playthrough column. Replace it with two tests: a
  mixed list shows the Playthrough column with a label per row; a mixed list with
  `playthrough` hidden shows no label anywhere, name cell and stacked summary
  included.
- [ ] **Step 2: Run them and confirm they fail.**
  `make test-fast ARGS="tests/test_session_list.py -x"`
- [ ] **Step 3: Declare the column unconditionally** and drop `organized`,
  passing `run_name` for every row and `run_label` for none.
- [ ] **Step 4: Remove `sole_game` and `ambiguous_run_labels`** and their tests.
- [ ] **Step 5: Run the session suites.**
  `make test-fast ARGS="tests/test_session_list.py tests/test_player_session_reads.py tests/test_session_run_labels.py tests/test_bulk_move.py"`
- [ ] **Step 6: `make format && make lint-fix`, then commit.**

---

### Task 5: The route

**Files:**
- Create: `games/views/list_columns.py`
- Modify: `games/urls.py`
- Modify: `games/views/returns.py:41` (`ORIGIN_AWARE`)
- Test: `tests/test_list_columns_view.py`

**Interfaces — Produces:** url name `games:state_list_columns`, path
`lists/<str:mode>/columns/`, POST only.

**Gotchas:**
- `ORIGIN_AWARE` is the bucket: this POSTs, acts and redirects to its origin.
  `CONFIRMATION` is GET-only and `IN_PLACE` is a partial swap; neither fits.
  Leaving it unclassified fails the completeness guard.
- The posted field is the **shown** keys. Store `declared − posted`, computed
  from the live column list, so a hidden column's unchecked box keeps it hidden
  and an orphaned key is gone after the next save.
- A `hideable=False` key must never land in the stored set even if posted.
- `return redirect(return_url(request, fallback=...))`, never a bare `reverse()`.
- **Reset is a named submit button**, `name="reset" value="1"`, which posts only
  when it is the button pressed. The view reads it and removes the row before it
  looks at the checkboxes. Without that branch, Reset would post whatever boxes
  happen to be checked and store the rest as hidden, which is the opposite of a
  reset. A `formaction` was rejected: the reset would then be a second URL the
  route table has to classify.

- [ ] **Step 1: Write the failing tests:** a POST naming two shown keys stores
  the rest as hidden; a POST naming every key removes the row; a POST carrying
  `reset` removes the row whatever boxes it carries; a GET answers 405;
  an unknown mode answers 404; a posted `hideable=False` key changes nothing;
  the response redirects to the `?origin=` it carried; a foreign origin falls
  back rather than redirecting off a mutating route.
- [ ] **Step 2: Run them and confirm they fail.**
  `make test-fast ARGS="tests/test_list_columns_view.py -x"`
- [ ] **Step 3: Write the view, register the path, classify the route.**
- [ ] **Step 4: Run them plus the guard.**
  `make test-fast ARGS="tests/test_list_columns_view.py tests/test_returns.py"`
- [ ] **Step 5: `make format && make lint-fix`, then commit.**

---

### Task 6: The picker on the bar

**Files:**
- Create: `common/components/column_picker.py`
- Modify: `common/components/__init__.py` (export)
- Modify: `common/components/quick_filter.py:306-350` (`_editable`), `:458-465`
  (`_degraded`), `:263-285` (constructor)
- Test: `tests/test_column_picker.py`

**Interfaces — Consumes:** `ColumnKey`, `Column.hideable` (Task 2),
`games:state_list_columns` (Task 5).
**Produces:** `ColumnPicker(columns, hidden, post_url, csrf_token, mode)` → a
`Fragment` of the `<drop-down>` trigger and the sibling `<form>`.

**The one thing that makes or breaks this task:** the quick bar wraps every row
child in one `<form>` (`quick_filter.py:349`), and a nested `<form>` start tag is
**dropped by the HTML parser** — its controls would be owned by the bar's form,
whose submit `ts/elements/quick-filter-bar.ts:60` turns into a navigation. So:

```text
<quick-filter-bar>
  <form>                      ← the bar's own, unchanged
    <div data-quick-row>
      … facets … <drop-down id="quick-<mode>-columns">
                   panel: <input type="checkbox" form="column-picker" …> ×N
                          <button type="submit" form="column-picker">Apply</button>
                          <button type="submit" form="column-picker"
                                  name="reset" value="1">Reset to defaults</button>
                 </drop-down>
      … preset picker … action group …
    </div>
  </form>
  <form id="column-picker" method="post" action="…">  ← sibling, not nested
    csrf
  </form>
</quick-filter-bar>
```

Verified in jsdom: two forms parse, and both the checkbox and the button report
`column-picker` as their form owner.

**Gotchas:**
- The picker renders in **both** branches. `_degraded()` returns a bare pill Div
  for any filter the facets cannot state, and a picker written into `_editable`
  alone disappears under exactly the filters a person builds deliberately.
- Place the trigger in `row_children` after the preset picker, before the action
  group. The TS reserve walks every row child but the host and the facets, so it
  needs no second registration — but confirm it does not enter the overflow.
- Use `ComboboxDropdown(label="Columns", content=…, id=…, ghost=True)`.
- A `hideable=False` column renders its box **checked and disabled**, not absent.
  The panel is then the whole table's inventory. Use `DISABLED_CONTROL_CLASS` on
  the box and the `has-[:disabled]:` wrapper variant on the label, per the
  repo's one disabled look.
- A disabled checkbox posts nothing, so the view must never read the posted keys
  as the whole truth: a `hideable=False` key is kept shown whatever arrives.
  Task 5's "a posted `hideable=False` key changes nothing" test covers the other
  direction; add one for the absent key too.

- [ ] **Step 1: Write the failing tests:** the panel renders one checkbox per
  hideable column and none for the rest; a hidden column's box is unchecked;
  every checkbox and both buttons state `form="column-picker"`; the rendered page
  parses to two forms and the picker's form is not a descendant of the bar's;
  the picker renders under a degraded filter.
- [ ] **Step 2: Run them and confirm they fail.**
  `make test-fast ARGS="tests/test_column_picker.py -x"`
- [ ] **Step 3: Write `ColumnPicker` and place it in both branches.**
- [ ] **Step 4: Run them plus the bar's suite.**
  `make test-fast ARGS="tests/test_column_picker.py tests/test_quick_filter_bar.py"`
- [ ] **Step 5: `make format && make lint-fix`, then commit.**

---

### Task 7: Wire the seven lists

**Files:**
- Modify: `games/views/game.py`, `purchase.py`, `session.py`, `playthrough.py`,
  `historical_playtime.py`, `device.py`, `platform.py`
- Test: `tests/test_column_choice_lists.py`

**Interfaces — Consumes:** everything from Tasks 1, 2, 3, 5, 6.

Each view reads `hidden_columns(request.user, mode)` once, passes it to its
table builder, and passes the full column list plus the hidden set to
`QuickFilterBar` so the picker can render every box.

- [ ] **Step 1: Write the failing tests,** parametrized over the seven modes: a
  person with no row sees every declared column; a person hiding one key sees
  the list without that column and without its cells; the picker's box for that
  key renders unchecked; a `hideable=False` key hidden in the row changes
  nothing; two people on one mode see their own lists; a sort naming a hidden
  column still orders the rows and warns nothing, because the sort key stays in
  the mode's `*_SORTS` map whether or not a header renders it.
- [ ] **Step 2: Run them and confirm they fail.**
  `make test-fast ARGS="tests/test_column_choice_lists.py -x"`
- [ ] **Step 3: Wire each view.**
- [ ] **Step 4: Run the list suites.**
  `make test-fast ARGS="tests/test_column_choice_lists.py tests/test_rendered_pages.py tests/test_paths_return_200.py"`
- [ ] **Step 5: `make format && make lint-fix`, then commit.**

---

### Task 8: Browser proof and the docs sweep

**Files:**
- Create: `e2e/test_column_picker_e2e.py`
- Modify: `CLAUDE.md` (the `sole_game` sentence in the PlayerSession section)
- Modify: `docs/superpowers/specs/2026-09-21-issue-715-session-organizer-design.md`
  (its "## The column" section describes a read this issue removes)
- Remove: `games/static/mockup-column-picker.html` (the throwaway mockup)
- Remove: `docs/superpowers/plans/2026-09-22-issue-1245-column-choice.md` (this file)

**Gotchas:**
- Never run e2e while `make dev` is up: its watchers rewrite the served assets
  and cause mass phantom failures.
- Run `make ts` after any `.ts` edit so the e2e run serves fresh output.
- UI assertion is not database assertion. Wait on the server-rendered table after
  the POST before reading the row.

- [ ] **Step 1: Write the e2e test:** open a list, open the Columns panel,
  uncheck a column, press Apply, and assert the header is gone after the reload;
  reload again and assert it is still gone; press Reset to defaults and assert it
  returns.
- [ ] **Step 2: Run it.** `make test-e2e ARGS="-k column_picker"`
- [ ] **Step 3: Amend `CLAUDE.md` and #715's spec** to describe what is true now.
  `sole_game` and `ambiguous_run_labels` no longer exist; the Playthrough column
  is declared always and the person decides.
- [ ] **Step 4: Remove this plan file.** The spec is the durable half.
- [ ] **Step 5: `make format && make lint-fix && make vale`.**
- [ ] **Step 6: The gate.**
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
  Read the exit code from the log; do not grep for a success string.
- [ ] **Step 7: Commit, push, open the PR.** Merge only when the user says merge.
