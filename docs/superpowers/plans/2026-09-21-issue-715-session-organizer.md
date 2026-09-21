# The desktop Session organizer — implementation plan

**Spec:** [2026-09-21-issue-715-session-organizer-design.md](../specs/2026-09-21-issue-715-session-organizer-design.md)

**Issue:** [#715](https://github.com/KucharczykL/timetracker/issues/715) (ORG-02)

**Goal:** The session list can name and group by the run each session sits
on, Game detail reaches that list, and the session row has the stacked mobile
cell #711 built.

**Branch:** `claude/timetracker-issue-715-7f18bd`, rebased onto `4dfc4b5a`
(#1244). Spec and this plan are the first commit.

## Global constraints

- Python 3.14, Node ≥ 26, PostgreSQL 18. Drive everything through `make`.
- `make format` **and** `make lint-fix` before every commit — `format` leaves
  import order alone and only `lint-fix` fixes `I001`.
- Ruff rewrites ` ```python ` fences inside `.md`. The spec's fences hold
  whole top-level statements, so they survive; keep it that way.
- Full `make check` (including `e2e/`) is the gate, once, at the end, under
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`. `make
  check-fast` while iterating. Never run `e2e/` while `make dev` is up.
- Never write a `GeneratedField`. No dispatch inside a transaction. Reads live
  in `games/reads/`.

## File map

| File | Responsibility |
|---|---|
| `games/reads/playthrough_numbering.py` | owns the run's display order; gains the field tuple, the projection and the ORM twin of `is_numbered` |
| `games/sorting.py` | `SortSpec.then`; the two `playthrough` keys |
| `games/reads/player_sessions.py` | `sole_game` |
| `games/views/session.py` | the column, the label drop, the summary |
| `games/views/playthrough_rows.py` | the run column's sort key |
| `games/views/game.py` | `_game_section`'s third button; `_sessions_section`'s Organize |
| `games/templates/icons/list-tree.html` | new glyph; `make gen-icons` regenerates `common/components/icons_generated.py` |
| `Makefile`, `CLAUDE.md` | `make shell` takes `ARGS` (already edited; document it) |

---

## Task 1 — A sort key is an ordering

**Files:** modify `games/sorting.py`, `games/reads/playthrough_numbering.py`;
test `tests/test_sorting.py`, `tests/test_playthrough_numbering.py`.

**Produces:**

```
SortSpec(expression, annotate=None, then=())   # then: tuple[OrderField, ...]
DISPLAY_ORDER_FIELDS: tuple[str, ...]
display_order_through(path: str = "") -> tuple[str, ...]
numbered_sort_key(path: str = "") -> Case      # Value(0) | None
```

`apply_sort` emits `expression` then each `then` entry, each under the term's
own direction with `nulls_last=True`, before the closing `F("pk")`.

**Tests, in this order:**

1. `apply_sort` with a `then` of two fields emits both, in order, in the
   term's direction — assert on `queryset.query.order_by`, not on rows.
2. Every existing `SortSpec` still orders as it did: the existing
   `TestEverySortKeyReturns200` classes cover this; run them.
3. `numbered_for` returns the same order before and after `DISPLAY_ORDER` is
   rebuilt from `DISPLAY_ORDER_FIELDS`, over a fixture holding a run with no
   stated endpoint. Do **not** write a test that rebuilds one tuple from the
   other — it is a comprehension over it and proves nothing.
4. `numbered_sort_key()` answers `None` for a bucket and for a removed run,
   `0` for a live ordinary run.

**Gotchas:**

- `DISPLAY_ORDER`'s last two entries are bare strings today. Building all four
  as `F(name).asc(nulls_last=True)` changes the SQL text (`"id" ASC` becomes
  `"id" ASC NULLS LAST`) but not the order — both columns are `null=False`.
  Both consumers (`Window(order_by=…)`, `.order_by(*…)`) already accept
  `OrderBy` objects.
- `games/sorting.py` importing `games.reads.playthrough_numbering` must not
  close a cycle. `playthrough_numbering` imports `games.models` and
  `games.reads.playthrough_activity`; check with an import at module scope and
  run `make typecheck`.

---

## Task 2 — The two playthrough keys

**Files:** modify `games/sorting.py`, `games/views/playthrough_rows.py`;
test `tests/test_sorting.py`.

**Consumes:** Task 1. **Produces:** `SESSION_SORTS["playthrough"]`,
`PLAYTHROUGH_SORTS["playthrough"]`, `_SORT_KEYS["Playthrough"]`.

Both keys lead with the game's `sort_name`, then the `run_numbered`
annotation, then `display_order_through(...)`. The session key ends with
`sort_instant`. Shapes are in the spec.

**Tests:**

1. **The ordering test the review demanded.** One game, three live ordinary
   runs — two dated, **one stating no start** — plus a bucket, each holding
   sessions. Ascending: run order equals `numbered_for`'s numbering, bucket
   last. Descending: `2, 1, 3`, bucket last. Assert the undated run's place
   explicitly; without it the test proves a mirror that does not exist.
2. Each run's sessions come out in `sort_instant` order under `playthrough`.
3. A second game's rows do not interleave: two games sort as two blocks.
4. `GET /api/session/?sort=playthrough` and `?sort=-playthrough` answer 200
   (`games/api.py:830` shares `apply_sort`).
5. The Playthrough list sorts on the key and its header links to it.

**Gotchas:**

- `tests/test_sorting.py::TestPlaythroughSorts::test_the_run_sorts_read_the_projection`
  asserts `set(PLAYTHROUGH_SORTS)` **exactly**. It fails until `"playthrough"`
  is added to it. This is expected, not a regression.
- `SESSION_GAME` lives in `games/filters.py`, which `games/sorting.py` already
  imports from.
- The dev database holds no live runs; seed fixtures, do not probe it.

---

## Task 3 — `sole_game`

**Files:** modify `games/reads/player_sessions.py`; test
`tests/test_session_list.py` or a new `tests/test_player_session_reads.py`.

**Produces:** `sole_game(sessions: PlayerSessionQuerySet) -> UUID | None`.

Clears ordering, `values_list(SESSION_GAME, flat=True).distinct()[:2]`,
answers the single key or `None`.

**Tests:** `None` for an empty list; `None` for two games; the key for one
game with several sessions; the key for one game reached through a filter;
the key for a one-game library with no filter at all.

**Gotchas:**

- Ordering must be cleared. Django adds ordering expressions to the
  `SELECT DISTINCT` list itself, so an ordered queryset distincts over the
  game key plus `sort_instant` and `id`, and one game with two sessions
  answers two rows. Nothing raises; the answer is just wrong.
- Call it on the filtered queryset **before** `apply_sort`, or the sort's
  `CASE` joins the same list.

---

## Task 4 — The column, the label and the summary

**Files:** modify `games/views/session.py`; test `tests/test_session_list.py`.

**Consumes:** Tasks 2 and 3.

`list_sessions` calls `sole_game` on the filtered queryset. When it answers a
key: insert `Column("Playthrough", "playthrough", shrinkable=True,
priority=3)` after Name, read `every_run_label` instead of
`ambiguous_run_labels`, pass the cell as `TruncatedText(label)` keyed on
`session.playthrough_id`, and pass `run_label=None` to `NameWithIcon`.

`session_row_data` gains `summary=`: the run label (only while the list names
one game), `session_time_range(...)`, `durations.format(...)`, and the device
name when the session names one — `", ".join`, no middle dot, no hand-entered
mark.

**Tests:**

1. One game filtered: the column renders, its cells name every run including
   a sole one, the bucket reads `Imported history`, and `data-run-label` is
   absent from the name cell.
2. Two games: no column, `data-run-label` behaves as today.
3. The summary renders under the name with the expected parts, and omits the
   device when the session names none.
4. Rewrite the three one-game tests named in the spec:
   `test_a_game_with_two_live_runs_labels_each_session` and
   `test_a_session_in_the_bucket_is_labelled_beside_a_live_run` read the
   column, not `data-run-label`;
   `test_a_game_with_one_run_shows_no_run_label` is renamed for its new
   reason.
5. `test_the_list_costs_no_query_per_row` still holds — `sole_game` is one
   query, constant in the row count. Run it; do not edit it.

**Gotcha:** `every_run_label` and `ambiguous_run_labels` both call
`_labelled_runs`, one query either way. Swapping adds no query.

---

## Task 5 — Game detail's Organize button

**Files:** create `games/templates/icons/list-tree.html`; modify
`games/views/game.py`, `common/components/icons_generated.py` (via
`make gen-icons`); test `tests/test_game_detail_links.py`.

`_game_section` takes `organize_url` beside `view_all_url` and its header row
gains `flex-wrap`. `_sessions_section` passes
`filter_url(PlayerSessionFilter.where(game=[game.id]), sort="playthrough")`.

Icon: Lucide-style stroke glyph matching `history.html`'s shape
(`fill="none" stroke="currentColor" stroke-width="2"`, `viewBox="0 0 24 24"`),
three rows with two indented under a parent stem.

**Tests:** the button renders with the sorted URL when the section has rows
and not when it is empty; the `list-tree` slug resolves to its own node, not
to `unspecified`.

**Gotchas:**

- `make gen-icons` after editing the snippet, and `check-icons` inside
  `make check` guards the drift. Never hand-edit `icons_generated.py`.
- `ICON_NODES` is one namespace for platform badges and interface glyphs, and
  `get_icon_node` falls back to `unspecified` **silently** — the slug test is
  what catches a typo.
- Check the section header in a browser at 375 px. Three buttons beside a
  heading and a badge is what `flex-wrap` is for; do not reason about it.

---

## Task 6 — The stacked cell on the real list

**Files:** create `e2e/test_session_list_mobile_e2e.py`.

One test at 375 px against the live session list, narrowed to one game: the
summary line renders under the name, and the checkbox sits inside
`[data-row-identity]` beside the name rather than centred across both lines.

**Gotchas:** `make ts` after any `.ts` edit so the served assets are fresh;
never run `e2e/` while `make dev` is up — its watchers rewrite the assets and
cause mass phantom failures. `e2e/test_selectable_table_e2e.py` is the
synthetic precedent to copy the fixture shape from.

---

## Task 7 — Documentation and the gate

**Files:** modify `CLAUDE.md`.

The Commands table's `make shell` row notes `ARGS` reaches `manage.py`, so
`make shell ARGS='-c "..."'` runs one snippet. Add the Playthrough column and
sort to the `PlayerSession` section's description of the list's read surfaces.

Then, once:

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check
```

Read the exit code from the log — never `grep | tail`, which has matched
ruff's "All checks passed!" while format-check was red.

---

## Self-review against the spec

| Spec section | Task |
|---|---|
| `SortSpec.then`, `apply_sort` | 1 |
| `DISPLAY_ORDER_FIELDS`, `display_order_through`, `numbered_sort_key` | 1 |
| The two keys, leading with the game | 2 |
| Playthrough list's run column | 2 |
| `sole_game` | 3 |
| Column, cells, `run_label=None` | 4 |
| One-game-library consequence, three rewritten tests | 4 |
| The stacked cell's summary | 4 (built), 6 (measured) |
| Game detail, the icon, `flex-wrap` | 5 |
| Verification / Left unproven | 1–7; the second-shrinkable-column question stays unmeasured, as the spec says |
