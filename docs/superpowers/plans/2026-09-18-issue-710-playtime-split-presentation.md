# Tracked and historical playtime split — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** State the tracked and historical halves beneath every playtime total
that can include a record, on five surfaces, through one component.

**Architecture:** One `PlaytimeSplit` node in `common/components/domain.py`
wraps today's `Duration`/`DurationText` and adds a micro second line, omitted
when the historical half is zero. Four surfaces let it own the popover; Game
detail's `hours` stat already owns one, so it states `popover=False`. The stats
games card stops loading every played game to print five rows and answers a row
of its own carrying a breakdown.

**Tech Stack:** Django 6, Python 3.14, the repo's Python component system
(`common/components/`), pytest.

**Spec:** [2026-09-17-issue-710-playtime-split-presentation-design.md](../specs/2026-09-17-issue-710-playtime-split-presentation-design.md)

## Global Constraints

- Every command goes through `make`. No `direnv exec .`, no raw `uv run` /
  `pytest` / `pnpm`. Iterate with `make check-fast`; the gate is full
  `make check` including `e2e/`.
- Wrap every pytest target in the shared lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
- Playtime is read only through `games/reads/playtime.py`. A new figure is a
  function in that module.
- Build UI with the Python component builders, htpy form
  (`Builder(class_="x")[child]`). No HTML strings, no `attributes=`/`children=`
  on generic or styled builders.
- A component that needs JS declares its own `Media`. `Popover` already does,
  and it bubbles; no `scripts=` threading.
- Elements carry their own classes. Nothing new in `common/input.css`, no
  selector that reaches across the DOM.
- `make vale` enforces the refused-word list over docs and comments.
- Comments explain non-obvious intent only, present tense, no issue or PR
  references.
- Branch is `claude/github-issue-710-plan-19c71a`, already level with
  `origin/main` at `3d0456f0`. Rebase before starting if that has moved.

## Interfaces this plan introduces

```text
common/components/domain.py
    PlaytimeSplit(breakdown, presentation, *, id_scope=None,
                  popover=True, link=None) -> Node

games/reads/sums.py
    PlaytimeBreakdown          (moved from playtime.py, re-exported there)

games/reads/playtime.py
    class GameByPlaytime(NamedTuple):
        game: Game
        playtime: PlaytimeBreakdown
    games_by_playtime_queryset(library, *, year) -> QuerySet[Game]
    games_by_playtime(library, *, year, limit) -> list[GameByPlaytime]

games/views/stats_data.py  (StatsData keys)
    games_by_playtime: list[GameByPlaytime]      # was top_10_games_by_playtime
    games_by_playtime_count: int

common/components/library_kit.py
    StatisticCard(label, value: Child | int, *, href=None, title=None,
                  spoken: str | None = None) -> Node
```

## File map

| File | Responsibility after this issue |
|---|---|
| `games/reads/sums.py` | owns `PlaytimeBreakdown` |
| `games/reads/playtime.py` | re-exports it; adds `GameByPlaytime`, the games-by-playtime queryset builder and reader |
| `common/components/domain.py` | `PlaytimeSplit` beside `Duration` |
| `common/components/library_kit.py` | `StatisticCard` takes a node value and a stated spoken label |
| `games/views/game.py` | `hours` stat renders the split; `_game_header` takes the breakdown |
| `games/views/stats_content.py` | four playtime row kinds render the split; the games card renders a list |
| `games/views/stats_data.py` | renamed keys, two new queries, classification |
| `games/views/general.py` | navbar figures split, no links |
| `games/views/library.py` | Playtime card states a duration, no link |

---

### Task 1: `PlaytimeBreakdown` moves to `games/reads/sums.py`

**Files:**
- Modify: `games/reads/sums.py` (add the dataclass)
- Modify: `games/reads/playtime.py:66-76` (remove it, import and re-export)
- Test: `tests/test_playtime_sources.py`

**Interfaces:**
- Produces: `games.reads.sums.PlaytimeBreakdown`, still importable from
  `games.reads.playtime`.

Move the frozen slots dataclass verbatim, docstring included. `playtime.py`
imports it and keeps it in `__all__`, which already names it. The three
importers — `games/views/stats_data.py:50`,
`tests/test_playtime_sources.py:30`, `tests/test_stats.py:19` — are untouched.

Gotcha: `sums.py` must not grow an import of `playtime.py`; the dependency runs
one way only.

- [ ] **Step 1: Write the failing test** — in `tests/test_playtime_sources.py`,
      `test_the_breakdown_is_importable_from_both_modules`: import the name from
      `games.reads.sums` and from `games.reads.playtime` and assert they are the
      same object.
- [ ] **Step 2: Run it and watch it fail** —
      `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playtime_sources.py -k importable -x"`.
      Expected: `ImportError` on `games.reads.sums`.
- [ ] **Step 3: Move the dataclass** and add the re-export import.
- [ ] **Step 4: Run the test plus the module's own suite** —
      `make test ARGS="tests/test_playtime_sources.py tests/test_stats.py -x"`.
- [ ] **Step 5: Commit** — `refactor: move the playtime breakdown beside the sums`.

---

### Task 2: the `PlaytimeSplit` component

**Files:**
- Modify: `common/components/domain.py` (after `Duration`, ~line 540)
- Modify: `common/components/__init__.py` (export)
- Test: `tests/test_duration_component.py`

**Interfaces:**
- Consumes: `PlaytimeBreakdown` from Task 1; `Duration`, `DurationText`
  (`domain.py:460`, `:493`).
- Produces: `PlaytimeSplit(breakdown, presentation, *, id_scope=None, popover=True, link=None) -> Node`.

Shape:

```python
def PlaytimeSplit(
    breakdown: PlaytimeBreakdown,
    presentation: DurationPresentation,
    *,
    id_scope: str | None = None,
    popover: bool = True,
    link: str | None = None,
) -> Node:
    """A total, and beneath it the two sources that made it."""
```

Rules, each its own test:

1. `popover=True` requires `id_scope`; `popover=False` refuses one. Refuse with
   `ValueError` naming the argument.
2. `link` beside `popover=False` is refused: `DurationText` renders no anchor.
3. Historical zero → return the bare `Duration(...)` / `DurationText(...)` node.
   No wrapper element, no extra class. This is what the `render_pages`
   invariant rests on, so the test compares the rendered string against a
   `Duration` built with the same arguments, character for character.
4. Historical non-zero → two block-level lines in one wrapper that adds no
   flex: line one the total, line two `142 h tracked · 100 h historical` in
   `text-type-micro` muted text.
5. The parts are `DurationText`, so each carries its own `sr-only` spoken form.
   The `·` separator is `aria-hidden`.
6. `link` is forwarded to `Duration` untouched.

Gotchas:

- `Popover` renders `<pop-over>` with `self-start inline-flex`
  (`primitives.py:456`). Block lines in a line box honour the host's
  `text-align`; a `flex flex-col` wrapper would pin the total left while the
  micro line stayed right, on the account menu and the stats table's second
  column both. Do not reach for flex.
- `Duration` prefixes the DOM id itself: `id=f"duration-{id_scope}"`. Pass
  `id_scope` through unchanged so today's ids survive — three test modules
  slice the page on them.
- The wrapper is a `Div` by default and a `Span` with `block` children where
  the host renders inside a `<span>` (Task 3). Take the wrapper's element from
  a `wrapper` argument, or render block `Span`s always — the second is simpler
  and valid in both hosts. Prefer it and state why in one comment.

- [ ] **Step 1: Write the failing tests** — six cases named for the rules
      above, in `tests/test_duration_component.py`:
      `test_zero_historical_renders_exactly_a_duration`,
      `test_the_split_states_both_halves`,
      `test_each_half_carries_its_spoken_form`,
      `test_a_popover_requires_an_id_scope`,
      `test_no_popover_refuses_an_id_scope`,
      `test_a_link_without_a_popover_is_refused`.
- [ ] **Step 2: Run them and watch them fail** —
      `make test ARGS="tests/test_duration_component.py -x"`. Expected:
      `ImportError` on `PlaytimeSplit`.
- [ ] **Step 3: Implement the component** and export it.
- [ ] **Step 4: Run the tests** — same command, all green.
- [ ] **Step 5: Commit** — `feat: state a playtime total beside its two sources`.

---

### Task 3: Game detail's headline

**Files:**
- Modify: `games/views/game.py:549-570` (`_stat_popover`'s row classes),
  `:851-861` (`_game_header` signature), `:877-881` (the stat),
  `:1165-1170` (the caller)
- Test: `tests/test_rendered_pages.py`, `tests/test_historical_playtime_pages.py`

**Interfaces:**
- Consumes: `PlaytimeSplit` from Task 2; `game_playtime(library, game)`
  already answers a `PlaytimeBreakdown` (`playtime.py:119`).
- Produces: `_game_header(..., playtime: PlaytimeBreakdown, ...)`.

`_game_header` takes the breakdown instead of `timedelta` and hands
`breakdown.total` to `DurationAlternates`, which stays in `_stat_popover`'s
`details` slot. The stat's value becomes
`PlaytimeSplit(breakdown, durations, popover=False)`.

The value row is `Span(class_="flex gap-2 items-center")` inside
`<pop-over>` (`primitives.py:444`); it states `items-baseline` so a two-line
value does not centre the icon and the reveal glyph against both lines.

Gotchas:

- Do not nest a `Duration` here. `_stat_popover` *is* the `Popover`; a second
  one gives one stat two tooltips.
- `popover-hours` and the other `popover-*` ids stay verbatim —
  `tests/test_rendered_pages.py:392` and
  `tests/test_historical_playtime_pages.py:58` slice on them.
- Every other header stat comes from `_game_overview_metrics` and reads
  sessions alone. Leave them; a record moves no session count, average or play
  range.

- [ ] **Step 1: Write the failing test** — in
      `tests/test_historical_playtime_pages.py`, extend the Game detail case:
      a game with a session and a record states the total, "tracked" and
      "historical" inside the `popover-hours` slice; a game with only sessions
      states neither word.
- [ ] **Step 2: Run it and watch it fail** —
      `make test ARGS="tests/test_historical_playtime_pages.py -x"`.
- [ ] **Step 3: Change the signature, the caller, the stat and the row class.**
- [ ] **Step 4: Run the page tests** —
      `make test ARGS="tests/test_historical_playtime_pages.py tests/test_rendered_pages.py -x"`.
- [ ] **Step 5: Commit** — `feat: split the playtime on the game headline`.

---

### Task 4: the stats page's three row kinds

**Files:**
- Modify: `games/views/stats_content.py:141` (Hours), `:378-386` (months),
  `:417-426` (platforms)
- Test: `tests/test_historical_playtime_pages.py`

**Interfaces:**
- Consumes: `PlaytimeSplit`; `ctx["total_hours"]`,
  `month_playtime.playtime` and `platform.playtime` are already
  `PlaytimeBreakdown` (`playtime.py:78`, `:84`).

Three call sites stop reading `.total` and pass the breakdown. The month and
platform rows keep their `link=` by forwarding it — they are why the component
takes the argument.

Gotcha: the Hours row has no link and the other two do. Nothing else on the
page changes: "Longest session" and "Average session" read
`effective_duration` and are session figures.

- [ ] **Step 1: Write the failing test** — a library with a contained record
      states the split on the Hours row, its month row and its platform row,
      and the month and platform figures still carry their filter hrefs.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Change the three call sites.**
- [ ] **Step 4: Run the stats and page tests** —
      `make test ARGS="tests/test_stats.py tests/test_historical_playtime_pages.py -x"`.
- [ ] **Step 5: Commit** — `feat: split every playtime row on the stats page`.

---

### Task 5: the games-by-playtime reader and its two queries

**Files:**
- Modify: `games/reads/playtime.py` (add `GameByPlaytime`, the builder, the
  reader)
- Modify: `games/views/stats_data.py:68-69` (drop `GamePlaytime`), `:82`,
  `:333-341`, `:362`, `:127-133` (classification), `:110` (docstring)
- Test: `tests/test_stats.py`, `tests/test_library_api_isolation.py`,
  `tests/test_sorting.py`

**Interfaces:**
- Produces: `GameByPlaytime(game, playtime)`;
  `games_by_playtime_queryset(library, *, year) -> QuerySet[Game]`;
  `games_by_playtime(library, *, year, limit) -> list[GameByPlaytime]`;
  StatsData keys `games_by_playtime: list[GameByPlaytime]` and
  `games_by_playtime_count: int`.

The builder answers today's queryset unexecuted — `visible_to`, annotated with
`playtime_by_game`, filtered `> 0`, ordered `-total_playtime, sort_name, name,
pk`. The reader slices it to `limit` and runs one further query annotating
`tracked_summed_by_game` and `historical_summed_by_game` over those keys alone,
then pairs each game with its `PlaytimeBreakdown`. `compute_stats` calls the
reader with `_LIST_CAP` and the builder's `.count()` for the second key, and
slices nothing itself.

Three queries where there is one today: the rows, the count, the halves. The
count stays its own query rather than a window function, so the rows query keeps
the plan this task pins.

Classification: both new keys go under `StatsSource.BOTH`. `StatsSource`'s
docstring says "which playtime sources a figure reads" and widens — the count
is not a playtime figure but reads both. It must not land in
`SESSIONS_PLAYED_GAMES`, or `test_a_contained_record_moves_only_the_playtime_figures`
fails, because a record does move this count.

Test cases:

- `test_the_card_reads_the_halves_over_the_sliced_keys` — a library with more
  than `_LIST_CAP` played games answers `_LIST_CAP` rows whose halves are
  right, and a count of all of them.
- `test_a_shared_record_sums_once` — the halves add to `.total` for a game
  holding both a session and a record.
- In `tests/test_sorting.py`, beside the existing plan assertion at line 530:
  `test_the_games_card_query_scans_each_source_twice` — call
  `.explain()` on `games_by_playtime_queryset(...)` and assert
  `plan.count(" on games_playersession ") == 2` and the same for
  `games_historicalplaytime`. Two, not one: `filter(total_playtime__gt=…)`
  names the annotation, so each `Coalesce(Subquery(...))` half compiles once in
  the select list and once in `WHERE`. `ORDER BY` reads the column by position.
- Existing assertions to restate: `tests/test_stats.py` lines 123, 144 and 258
  read `.total_playtime` and become `.playtime.total`; lines 136, 204 and 286
  and `tests/test_library_api_isolation.py:412` read `.id`/`.name` and become
  `.game.id`/`.game.name`.

Gotchas:

- `test_every_stats_key_states_its_sources_once` (`tests/test_stats.py:212`)
  fails until both keys are classified exactly once.
- The rename also touches three documents: this wave's design doc, and the
  `2026-07-20-stats-styledtable-migration` and `2026-09-14-issue-697-playtime-reads`
  specs. Handle them in Task 8.
- Both per-game readers answer NULL, not zero, for a game absent from that
  source. Coalesce in the reader, or the breakdown holds `None`.

- [ ] **Step 1: Write the failing tests** — the two reader cases and the plan
      case named above.
- [ ] **Step 2: Run them and watch them fail** —
      `make test ARGS="tests/test_stats.py -k by_playtime tests/test_sorting.py -k games_card -x"`.
- [ ] **Step 3: Add `GameByPlaytime`, the builder and the reader** to
      `games/reads/playtime.py`.
- [ ] **Step 4: Rewire `compute_stats`** — both keys, the classification, and
      `GamePlaytime` removed.
- [ ] **Step 5: Restate the seven existing assertions.**
- [ ] **Step 6: Run the three test modules** —
      `make test ARGS="tests/test_stats.py tests/test_sorting.py tests/test_library_api_isolation.py -x"`.
- [ ] **Step 7: Commit** — `feat: read the games card's rows and their halves`.

---

### Task 6: the games card renders the list

**Files:**
- Modify: `games/views/stats_content.py:295-305` (`_two_col_table`),
  `:390-410` (the card)
- Test: `tests/test_stats.py`, `tests/test_historical_playtime_pages.py`

**Interfaces:**
- Consumes: `games_by_playtime` and `games_by_playtime_count` from Task 5;
  `PlaytimeSplit` from Task 2.

`_two_col_table` takes `total: int | None = None` beside its items, as
`_finished_table` already does, and keeps slicing for the callers that hand it
a queryset. The games card passes the pre-read list, the count, and
`PlaytimeSplit(row.playtime, durations, id_scope=f"stats-game-{row.game.id}-playtime")`.

Gotchas:

- The same function serves the platform card with no `view_all_url`; it must
  keep rendering every row it is given.
- `View all (N)` prints the total today, not the remainder. Keep that.
- The `stats-game-<pk>-playtime` id_scope is unchanged;
  `tests/test_historical_playtime_pages.py:77` slices on the resulting id.

- [ ] **Step 1: Write the failing test** — the games card states a split for a
      game with a record, and "View all" still prints the whole count.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Add the `total` argument and rewire the card.**
- [ ] **Step 4: Run the stats tests.**
- [ ] **Step 5: Commit** — `feat: split the playtime on the games card`.

---

### Task 7: the navbar figures

**Files:**
- Modify: `games/views/general.py:44-94` (`model_counts`)
- Test: `tests/test_library_page_isolation.py`, `tests/test_rendered_pages.py`

Both figures become `PlaytimeSplit(breakdown, durations, id_scope="navbar-today")`
and `"navbar-last-7"`, with no `link`. `playtime_between_each` already answers
breakdowns; stop taking `.total` off them. The anonymous branch states
`PlaytimeBreakdown(ZERO, ZERO)` where it states `timedelta(0)` today, so the
navbar renders one figure as it does now.

`today_url`, `last_7_url` and both `filter_url` calls go, and with them the
`PlayerSessionFilter` and `filter_url` imports — ruff will name them.

Gotchas:

- This changes the navbar's markup for every library, records or not. That is
  the decision, not a defect: the session list cannot show a record, so the
  link undercounts the figure it hangs from. #1105 restores it.
- `tests/test_library_page_isolation.py:424-437` pins the zero render.

- [ ] **Step 1: Write the failing test** — a library with a record in the last
      seven days states the split in the account menu, and no figure carries an
      href.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Change `model_counts` and drop the dead imports.**
- [ ] **Step 4: Run the page tests** —
      `make test ARGS="tests/test_library_page_isolation.py tests/test_rendered_pages.py -x"`.
- [ ] **Step 5: Commit** — `feat: split the navbar playtime figures`.

---

### Task 8: the Library page's Playtime card

**Files:**
- Modify: `common/components/library_kit.py:39-60` (`_value_node`,
  `StatisticCard`), `games/views/library.py:70`, `:92-97`
- Test: `tests/test_library_ui_components.py`, `tests/test_playtime_page.py`,
  `tests/test_library_page_isolation.py`

**Interfaces:**
- Produces: `StatisticCard(label, value: Child | int, *, href=None, title=None, spoken: str | None = None)`.

`Child` is `Node | str` (`core.py:153`) and admits no integer, which every
other card passes, so the annotation is `Child | int`. `_value_node` stops
folding the value into a string: it renders the value as a child, and takes the
spoken label rather than deriving one from a node it cannot read. The five
remaining linked cards pass `spoken`.

The Playtime card states `total_playtime(library)` through `PlaytimeSplit`,
drops its `href`, and its `title` becomes "Tracked sessions and historical
records". `record_count` and the `library_records` import go if nothing else
reads them.

Gotchas:

- A node value inside a `Link` is refused, not handled: `Duration` contains a
  `<button>`, and `Duration`'s own contract forbids an anchor around it. The
  Playtime card has no link precisely because it now holds one.
- `SummaryRow` shares `_value_node` (`library_kit.py:228`). Its
  `SummaryValue.value` stays `str | int` and it passes no `spoken`;
  `tests/test_library_ui_components.py:184` pins its derived aria-label.
- Three assertions read the card's spoken label and change:
  `tests/test_playtime_page.py:292`, `tests/test_library_page_isolation.py:67`
  (which asserts the same string as page text), and
  `tests/test_library_ui_components.py`.
- `data-statistic-card` and every e2e selector are untouched.

- [ ] **Step 1: Write the failing tests** — the card renders a node value as
      markup rather than escaped text; a linked card speaks its stated label;
      the Playtime card states a duration and carries no href.
- [ ] **Step 2: Run them and watch them fail** —
      `make test ARGS="tests/test_library_ui_components.py -x"`.
- [ ] **Step 3: Change `_value_node` and `StatisticCard`.**
- [ ] **Step 4: Rewire the Library page and restate the three assertions.**
- [ ] **Step 5: Run the Library tests** —
      `make test ARGS="tests/test_library_ui_components.py tests/test_playtime_page.py tests/test_library_page_isolation.py -x"`.
- [ ] **Step 6: Commit** — `feat: state the library's playtime and its sources`.

---

### Task 9: the rename's documents, the sweep and the gate

**Files:**
- Modify: `docs/superpowers/specs/2026-09-17-historical-playtime-wave-design.md:217`,
  `docs/superpowers/specs/2026-07-20-stats-styledtable-migration-design.md:90,155`,
  `docs/superpowers/specs/2026-09-14-issue-697-playtime-reads-design.md:79`
- Delete: `docs/superpowers/plans/2026-09-18-issue-710-playtime-split-presentation.md`
  (this file, once the work has landed)

The three documents name `top_10_games_by_playtime`. The wave doc's
classification table and #697's table state the key; the styledtable spec names
it as a misleading name and an uncapped queryset, which this issue fixes, so
that sentence states the current shape instead.

Then the `render_pages` rehearsal, which is the real verification of the
zero-historical rule:

1. `make render-pages ARGS="--user <name> --out /tmp/before"` at
   `origin/main`.
2. The same at `HEAD`, into `/tmp/after`.
3. `diff -r /tmp/before /tmp/after`.

Read the diff against the spec: the navbar's two lines and the Library card
differ on every page and are expected. On a library with no record, a differing
file anywhere else is a finding. On the dump, Game detail of every recorded game
and every stats page differ by design — attribute each to the figure that gained
a split.

- [ ] **Step 1: Rename the key in the three documents.**
- [ ] **Step 2: Run `make vale`** — expected: no findings.
- [ ] **Step 3: Run the rehearsal** and write the attribution into the commit
      message.
- [ ] **Step 4: Run the full gate** —
      `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
      Read the exit code, not a grep of the output.
- [ ] **Step 5: Delete this plan file and commit** —
      `docs: sweep the playtime split (#710)`.

---

## Verification contract

From the spec, each already covered by a task above:

- Zero historical renders exactly today's output on Game detail, the stats page
  and the Library card's value (Task 2, step 1's character-for-character test).
- A split states total, tracked and historical, and the three agree, asserted
  against the reader rather than typed-in numbers (Tasks 3–6).
- One popover where the component owns one, none on Game detail; the spoken
  order is total, reveal button, parts (Tasks 2, 3).
- Every figure that carries a filter link today still carries it, months and
  platforms included (Task 4).
- `STATS_SOURCES` names every `StatsData` key once (Task 5).
- The rows query scans each source table twice, as it does today; the halves
  arrive in one further query (Task 5).
- No test reads `total_playtime` off a `Game` (Task 5).
- The navbar figures carry no link; the account menu renders at 390 px with no
  horizontal scroll (Task 7 — check the width by hand in the browser pane).
- The Library card states a duration, no link, rendered as markup; the other
  cards still state scalars and speak their labels (Task 8).
- Full `make check`, `e2e/` included (Task 9).

## Follow-ups already filed

- #1119 — the Playthroughs table's run rows and the brace gutter.
- #1105 — the link predicates that count a record by containment, which restore
  the navbar's and the Library card's links.
- #1106 — a stated session count on a record.
