# The selection line's actions — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person selects rows on any of five tables and acts on the
selection from the line that counts them, with bulk Remove as the act every
table offers.

**Architecture:** The view declares its actions on the table; the selection
line renders one form of submits into the slot `<selectable-table>` already
leaves; a small element writes the posted statement into that form. Bulk
Remove is three `BulkAction` values over the runner #713 shipped, and the
confirmation learns to render a row that is not a session.

**Tech Stack:** Django 6, Python 3.14, pytest/pytest-django, custom elements
in TypeScript with vitest, Playwright for e2e.

**Spec:**
[docs/superpowers/specs/2026-09-20-issue-712-selection-actions-design.md](../specs/2026-09-20-issue-712-selection-actions-design.md)

**Wave:**
[docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md](../specs/2026-09-19-selectable-tables-wave-design.md)
— #712 is member 3, after #713, before #714. It merges alone.

## Global constraints

- Every command runs through `make`. Never `uv run`, `pnpm`, `pytest`
  directly. Iterate with `make check-fast`; the gate is full `make check`
  under the shared lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
- Complete words in identifiers, Python and TypeScript alike.
- UI is Python components, htpy form: `Builder(class_="x")[child]`.
- No dispatch inside a transaction. A test that POSTs through a dispatching
  view needs `@pytest.mark.django_db(transaction=True)`.
- Never write a `GeneratedField` (`effective_day`, `effective_duration`,
  `sort_instant`, `price_per_game`).
- After editing any `.ts`, run `make ts` so the served `dist/` is fresh, and
  never run e2e while `make dev` is up.
- A refusal a person can act on is the command's, with a `sentence=`. A
  refusal about the row itself is `RowUnreadable` and carries none.

## Existing shape, so nothing is rediscovered

| thing | where |
|---|---|
| the act table and `Cardinality` | `games/bulk_actions.py` |
| the runner, its two POSTs, `Tally` | `games/views/bulk.py` |
| the confirmation and waypoint pages | `games/views/bulk_pages.py` |
| the one act that exists | `games/bulk_reclassification.py` |
| the table personality and its line | `common/components/primitives.py:2726-2860` |
| the element, its statement, `forgetAndClose` | `ts/elements/selectable-table.ts` |
| the statement grammar, both ends | `ts/elements/selection-statement.ts:116`, `games/views/bulk.py:201` |
| the five row builders | `games/views/session.py:131`, `games/views/historical_playtime.py:113`, `games/views/game.py:1060`, `games/views/playthrough_rows.py:49` |
| the Library panel | `games/views/session_reclassification.py:184` |

---

## Task 1: The confirmation renders any act's rows

**Files:**
- Modify: `games/bulk_actions.py` (generic, `PreviewColumn`, `preview`)
- Modify: `games/views/bulk_pages.py:61-144` (`_sample`, `ConfirmBatch`)
- Modify: `games/views/bulk.py:251-281` (`_confirmation` builds both
  presentations)
- Modify: `games/bulk_reclassification.py` (declares its three columns)
- Test: `tests/test_bulk_actions.py`, `tests/test_bulk_runner.py`

**Interfaces produced:**

```python
type PreviewCell = Callable[[Any, Presentations], Cell]


@dataclass(frozen=True, slots=True)
class PreviewColumn:
    heading: str
    cell: PreviewCell
    align: Align = "left"  # the Column alias, primitives.py:2190


@dataclass(frozen=True, slots=True)
class Presentations:
    dates: DateTimePresentation
    durations: DurationPresentation


class BulkAction[RowT]:  # every field as today, plus:
    preview: tuple[PreviewColumn, ...]
```

`Resolution[RowT]`, `Scope[RowT]`, `Resolve[RowT]`, `RunRow[RowT]` are
parameterised with it. `_TABLE`, `BULK_ACTIONS` and `bulk_action()` stay
`BulkAction[Any]`, and `games/views/bulk.py` keeps holding rows as `Any`:
the generic buys the declaration site, not the runner.

**Gotchas:**
- `_sample` reads `row.playthrough.player_game.game.name` today. That is the
  session act's first column and moves into
  `games/bulk_reclassification.py`, unchanged in output.
- `ConfirmBatch`'s zero-row sentence is hardcoded about sessions
  (`bulk_pages.py:132`). Both sentences read `action.subject` now.
- Any number of columns; #714 widens the session preview without touching
  the runner.
- `mypy` here is not strict, and a frozen `slots=True` PEP 695 generic
  dataclass registering into a module dict is clean on 3.14. Keep
  `__post_init__` as it is.

**Steps:**

- [ ] Write the failing test: an act declaring four preview columns renders
      four headings and one row per resolved row, capped at
      `CONFIRMATION_SAMPLE` with the "and N more" line intact. Assert the
      zero-row sentence names the act's subject, not "sessions".
- [ ] `make test-fast ARGS="tests/test_bulk_runner.py -k preview"` — fails.
- [ ] Add `Presentations`, `PreviewColumn`, the generic, the `preview`
      field; rewrite `_sample` over the spec; thread both presentations
      from `_confirmation`.
- [ ] Declare the reclassification's three columns (Game, Day, Duration —
      duration right-aligned) so its confirmation is byte-identical.
- [ ] `make test-fast ARGS="tests/test_bulk_runner.py tests/test_bulk_actions.py"`
      and `make typecheck` — pass.
- [ ] Commit: `feat: an act states the rows its confirmation shows`.

---

## Task 2: The removal wrappers answer, and carry a key

**Files:**
- Modify: `games/writes/playersession.py:288-311` (`remove_session`,
  `restore_session`)
- Modify: `games/writes/playthrough.py:53-67` (`_dispatch`), `:358-377`
  (`remove_run`, `restore_run`)
- Modify: `games/writes/historical_playtime.py:25-45` (`_dispatch`), `:92-112`
- Test: `tests/test_session_writes.py`, `tests/test_playthrough_writes.py`,
  `tests/test_historical_playtime_writes.py` — the three write-path files
  that already exercise these six. `tests/test_restore_routes.py` covers
  every single-row restore and is the regression to keep green.

**Interfaces produced:** all six become

```python
def remove_session(
    actor: User,
    session: PlayerSession,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult: ...
```

and the same two keyword arguments, both optional, on `restore_session`,
`remove_run`, `restore_run`, `remove_historical_playtime`,
`restore_historical_playtime`.

**Gotchas:**
- All six return `None` today. The runner tells a row that moved from a row
  already in that state through `RowOutcome.of(result)`, so the result must
  come back.
- `games/writes/playthrough.py::_dispatch` takes neither argument and mints
  its own key; `games/writes/historical_playtime.py::_dispatch` takes a key
  but no source metadata and reads `actor.library` rather than taking a
  library. Both grow; neither changes what it already does.
- Mint the key when `None`, never with `or`: a blank key is falsy, and
  minting over it turns a refusal into a second write.
- Single-row routes state neither and must keep passing unchanged — that is
  the regression to watch.

**Steps:**

- [ ] Write the failing test: calling `remove_run` twice with one
      `idempotency_key` writes one event and answers `UNCHANGED` the second
      time; `source_metadata={"bulk": {"action": "x"}}` reaches the event.
      One such test per module.
- [ ] `make test-fast ARGS="-k idempotent_removal"` — fails.
- [ ] Grow the two dispatch helpers, then the six wrappers; return the
      result from each.
- [ ] `make test-fast ARGS="tests/test_session_writes.py tests/test_playthrough_writes.py tests/test_historical_playtime_writes.py tests/test_restore_routes.py"` — pass.
- [ ] Commit: `feat: the removal wrappers answer, and take a key`.

---

## Task 3: Three Remove acts

**Files:**
- Create: `games/bulk_removal.py`
- Modify: `games/bulk_actions.py` (import it at the foot, beside the
  reclassification)
- Test: `tests/test_bulk_removal.py`

**Interfaces produced:** `REMOVE_SESSION`, `REMOVE_RUN`, `REMOVE_RECORD`,
named `session.remove`, `playthrough.remove`, `historicalplaytime.remove`,
each `cardinality=Cardinality.MANY`, `fallback` the list it acts from, and
`inverse_aggregate` `"playersession"` / `"playthrough"` /
`"historicalplaytime"`.

| act | scope | run / inverse | preview columns |
|---|---|---|---|
| session | `library_sessions` + `parse_session_filter` | `remove_session` / `restore_session` | Game, Day, Duration |
| run | `library_runs` + `parse_playthrough_filter` | `remove_run` / `restore_run` | Playthrough, Game, Started, Completed |
| record | `library_records` + `parse_historical_playtime_filter` | `remove_historical_playtime` / `restore_historical_playtime` | Game, When, Duration |

Each resolve: `.filter(pk__in=wanted)` over the scope's read with the
`select_related` the preview needs, ordered so the confirmation is stable;
every key it did not find becomes `Refused(..., lost=True)` with one
sentence per act. Nothing else is checked here.

**Gotchas:**
- Scope is the act's own base **narrowed by** the parsed filter, never
  `apply_structured_filter`, which fails open: a filter it cannot read
  would widen the act to every row the library holds. Let `FilterError`
  rise; the runner answers it.
- The inverse takes a key, not a row, and the row is removed by then, so it
  resolves through the plain manager with `library=` stated.
- `RemovePlaythrough`'s last-live-run and referrer rules refuse one row with
  a sentence at 409 and the batch continues. Do **not** restate either rule
  in `resolve`.
- A row of another library that a run names raises `RowUnreadable` → 500 →
  the batch ends as a defect. That is correct and stays.
- `RestoreSession` refuses while a live record was made from the session
  (#1098); the Undo reports it as a refusal, one row.
- Do not reuse `playthrough_tabledata` for the run preview: it raises
  without the `activity` alias.

**Steps:**

- [ ] Write the failing tests, one file: each act's scope narrows by its
      filter and by nothing else; a key of another library comes out lost; a
      run that is its game's last live ordinary run is refused with the
      command's sentence while its siblings are removed; a session with a
      live record refuses its restore; an unreadable filter raises
      `FilterError`.
- [ ] `make test-fast ARGS="tests/test_bulk_removal.py"` — fails.
- [ ] Write `games/bulk_removal.py`; import at the foot of
      `games/bulk_actions.py`.
- [ ] `make test-fast ARGS="tests/test_bulk_removal.py tests/test_bulk_runner.py"` — pass.
- [ ] Commit: `feat: bulk Remove for sessions, runs and records`.

---

## Task 4: The line renders the actions

**Files:**
- Modify: `common/components/primitives.py:2224-2244`
  (`SelectionDeclaration`), `:2796-2860` (`SelectionLine`), `:3096-3110`
  (`StyledTable` passes the declaration through)
- Create: `games/bulk_tray.py`
- Test: `tests/test_components.py`, `tests/test_bulk_tray.py`

**Interfaces produced:**

```python
# common/components/primitives.py — states its own word, imports no act.
class SelectionAction(TypedDict):
    label: str
    url: str
    cardinality: Literal["one", "many"]


class SelectionDeclaration(TypedDict):
    filter: FilterJson
    actions: NotRequired[Sequence[SelectionAction]]
    csrf_token: NotRequired[str]


# games/bulk_tray.py
def tray_actions(
    *names: BulkActionName, origin: OriginUrl
) -> list[SelectionAction]: ...
```

`tray_actions` reads `BULK_ACTIONS`, keeps the `MANY` ones, and builds each
URL with `action_url("games:run_bulk_action", name, origin=origin)`.

**Gotchas:**
- `common/` must not import `games.bulk_actions` — that cycles through
  `games.filters` and `games.writes`. The `Literal` is spelled in
  `primitives.py`; the view maps.
- One `<form>` holding every submit, each with its own `formaction`. A
  `ControlButton(method="post")` renders a form of its own, so per-act forms
  would each need a copy of the statement.
- The token rides the declaration: `SelectionLine` has no `request`, and
  both existing harnesses call `StyledTable(request=None)`.
- `SelectionLine` must `reverse()` nothing — `e2e/test_selectable_table_e2e.py`
  renders it under a stripped `ROOT_URLCONF`.
- Submits carry `disabled` as rendered; the element clears it. No scripting
  means no line at all, so nothing is lost.
- Touch target: the tray's buttons keep the line's 24px floor
  (`SELECTION_CHECKBOX_CLASS` is the precedent; `ControlButton` already
  floors at `min-h-control`).

**Steps:**

- [ ] Write the failing tests: a declaration with two actions renders one
      form, two submits, each `formaction` carrying `?origin=`, one hidden
      `selection` field and one token; a declaration with none renders the
      empty slot exactly as today; `tray_actions` skips a `ONE` act and
      raises on a name nothing declares.
- [ ] `make test-fast ARGS="tests/test_components.py -k selection_actions"` — fails.
- [ ] Extend the TypedDicts, render the form, write `games/bulk_tray.py`.
- [ ] `make test-fast ARGS="tests/test_components.py tests/test_bulk_tray.py"` — pass.
- [ ] Commit: `feat: the selection line renders the acts a view declares`.

---

## Task 5: `<selection-actions>`

**Files:**
- Create: `ts/elements/selection-actions.ts`,
  `ts/elements/selection-actions.test.ts`
- Modify: `ts/elements/selectable-table.ts` (public `statement()`)
- Modify: `common/components/custom_elements.py` (props + registration),
  `common/components/primitives.py` (builder, wraps the form)
- Modify: `ts/generated/props.ts` via `make gen-element-types`

**Interfaces produced:**

```ts
// selectable-table.ts
statement(): SelectionStatement   // what the change event carries, on demand

// selection-actions.ts — <selection-actions>, no props
```

The element: on connect, `closest("selectable-table")?.statement()` and
write it; then listen for `selectable-table:change` **on that host**, not on
itself. Disable every `button[type=submit]` while the count is zero (an
`all` statement counts `count - except.length`). On `submit`, stop writing
and never write again.

**Gotchas — both are real defects the review caught:**
- `<selectable-table>` already listens for `submit` on
  `[data-selection-actions]` and calls `forgetAndClose()`, which dispatches
  a change carrying an **empty** statement *while the form is being read*.
  Without the latch every act posts nothing and the confirmation silently
  shows zero rows. The latch is the fix; a test must prove the posted field
  still holds the keys after the press.
- The change event is dispatched **on** `<selectable-table>`, and only from
  `render()`, which at connect runs on the restore branch alone — before
  this element upgrades, because it is a descendant and its script is
  emitted second. Hence the pull at connect. A test must prove a restored
  selection reaches the field.
- `ContinuingBatchProps` is the precedent for an empty props TypedDict.
- `make ts` after editing, or e2e serves stale JavaScript.

**Steps:**

- [ ] Write the failing vitest: connect after a restored selection fills the
      field; a change updates it; zero count disables the submits; the
      press leaves the field holding the keys even though the table forgets
      them.
- [ ] `make test-ts` — fails.
- [ ] Add `statement()`, write the element, register its props, run
      `make gen-element-types` and `make ts`.
- [ ] `make test-ts` and `make ts-check` — pass.
- [ ] Commit: `feat: the slot writes the statement it posts`.

---

## Task 6: Five tables become selectable

**Files:**
- Modify: `games/views/session.py:131-156,193-215` (key + declaration)
- Modify: `games/views/historical_playtime.py:113-160` and its list view
- Modify: `games/views/playthrough_rows.py:116` (key) and
  `games/views/playthrough.py:168-185` (declaration)
- Modify: `games/views/game.py:1060-1139` (keys on both inline row
  builders, `request=` threaded into both `StyledTable` calls, declarations)
- Test: `tests/test_rendered_pages.py`, `tests/test_paths_return_200.py`,
  `tests/test_bulk_tray.py`, `tests/test_game_detail_playthroughs.py`,
  `tests/test_game_detail_historical_playtime.py`

**What each table declares:**

| page | rows | acts declared |
|---|---|---|
| Playtime → Sessions | `PlayerSession` | `session.remove`, `session.reclassify` |
| Playtime → Historical | `HistoricalPlaytime` | `historicalplaytime.remove` |
| Playthrough list | `Playthrough` | `playthrough.remove` |
| Game detail → Playthroughs | `Playthrough` | `playthrough.remove` |
| Game detail → Historical playtime | `HistoricalPlaytime` | `historicalplaytime.remove` |

**Gotchas:**
- `make_row(key=str(row.pk))` on each; `playthrough_tabledata` is shared by
  the list and Game detail, so keying it keys both, which is what we want —
  `TableRow` emits `data-selection-key` only where a key exists.
- Game detail's two `StyledTable` calls pass no `request` today, so
  `selection_scope` would store under an empty library segment and the next
  person at that browser would inherit the selection. Thread the request.
- Game detail has no paginator: `SelectionLine(page_obj=None)` omits "Select
  all N matching" and the element reports `count="0"`, which is right — the
  page is the set.
- Game detail's historical rows are built inline in `game.py`, **not** by
  `historical_playtime_tabledata`. Two places, one for each record list.
- The filter in each declaration is the list's own `?filter=` JSON;
  Game detail states `""`.
- Actions columns stay. #718 retires them.

**Steps:**

- [ ] Write the failing test: each of the five pages renders
      `data-selection-key` on every row and a form in the slot whose
      `formaction` names the acts above; Game detail's stored scope carries
      the library.
- [ ] `make test-fast ARGS="tests/test_bulk_tray.py -k pages"` — fails.
- [ ] Add the keys, the declarations and the two `request=` arguments.
- [ ] `make test-fast ARGS="tests/test_rendered_pages.py tests/test_paths_return_200.py tests/test_bulk_tray.py"` — pass.
- [ ] Commit: `feat: five tables offer their acts`.

---

## Task 7: The act leaves the Library page

**Files:**
- Modify: `games/views/session_reclassification.py:167-233`
  (`review_selection` goes; `PlaytimeReviewPanel` loses its `origin` and
  `csrf_token` parameters and the button, keeps prose, count and link)
- Modify: `games/views/library.py:181` (the call site)
- Modify: `tests/test_session_reclassification_views.py:200-250`
- Modify: `e2e/test_bulk_runner_e2e.py`
- Test: as above

**Gotchas:**
- `e2e/test_bulk_runner_e2e.py` is the runner's **only** end-to-end cover
  and drives it entirely through that button, including the two-chunk walk
  under a zeroed `CHUNK_BUDGET`. Re-point both tests at the session list's
  line — select all matching with the review facet applied, act, confirm,
  Stop, Undo — or the wave loses the coverage.
- `STATEMENT_FIELD`, `RECLASSIFY`, `Input`, `action_url` and `OriginUrl`
  become unused in that module; `get_token` and `origin` stay used elsewhere
  in `library.py`. Ruff will name them.
- The panel's third paragraph is the button's copy about Undo and goes with
  it. The count and "See these sessions" stay; #717 adds the other two
  counts.

**Steps:**

- [ ] Rewrite the two view tests to assert the button is gone and the count
      and link remain.
- [ ] `make test-fast ARGS="tests/test_session_reclassification_views.py"` — fails.
- [ ] Take the button, `review_selection` and the dead imports; narrow
      `PlaytimeReviewPanel`'s signature and its call site.
- [ ] Re-point `e2e/test_bulk_runner_e2e.py` at the session list's line.
- [ ] `make test-fast ARGS="tests/test_session_reclassification_views.py"`,
      then `make test-e2e ARGS="-k bulk_runner"` — pass.
- [ ] Commit: `feat: the reclassification is acted from the line`.

---

## Task 8: One end-to-end pass, the gate, and the sweep

**Files:**
- Create: `e2e/test_selection_actions_e2e.py`
- Modify: `docs/superpowers/specs/2026-09-20-issue-712-selection-actions-design.md`
  (only if the build contradicted it)
- Test: the whole suite

**The e2e pass** (real session list, real Chrome): turn the mode on, check
two rows, press Remove, land on the confirmation showing two rows with the
act's own columns, confirm, read the toast, press Undo, and see both rows
back in the list. One more: select a run on the Playthrough list whose game
holds it alone, act, and read the command's refusal in the answer with the
batch's other rows removed.

**Gotchas:**
- Wait on a server-rendered change before reading the ORM: a custom element
  may update its own DOM before the POST lands.
- `make test-e2e` needs system Chrome and must not run beside `make dev`.
- `PYTEST_WORKERS=0` when a failure needs reading.

**Steps:**

- [ ] Write the two e2e tests.
- [ ] `make test-e2e ARGS="-k selection_actions"` — pass.
- [ ] Read the spec against what was built; correct the spec if the build
      taught something, and say so in the commit.
- [ ] Run the gate:
      `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
      and confirm green from the exit code, not from grepping the log.
- [ ] Commit, push, open the PR against `main` naming #712 and the wave.

---

## Follow-up issues to file

- **`Cardinality.ONE` has no rendering.** One sentence in #718's body: the
  line renders `one` acts as links to the row's own pages when the Actions
  columns retire. File as a comment on #718, not a new issue.
- **The confirmation's cap and columns** are #714's call, on the spec this
  plan ships. Already recorded in the wave doc; no new issue.
