# #1241 — the stacked cell's summary on the other selectable tables

Spec: [design](../specs/2026-09-21-issue-1241-other-table-summaries-design.md).
Wave: [Selectable tables](../specs/2026-09-19-selectable-tables-wave-design.md).
Branch is cut from `main` and rebased before the first edit.

Five phases, each green on `make check-fast` before the next. The gate at the
end is one full `make check`, e2e included.

---

## Phase 1 — `row_summary()` and the clip guard

**`common/components/primitives.py`**

- `row_summary(*parts: str | None) -> str` beside `make_row`: drops falsy parts,
  joins with `", "`. Carries the comma rule in its docstring (a screen reader
  speaks a comma as a pause, a middle dot as a word). Export from
  `common/components/__init__.py` in both the import block and `__all__`.
- `StyledTable`: beside the DEBUG cell-count guard, and under the same
  `settings.DEBUG` gate, refuse a table where any row states a `summary` while
  `columns[0].shrinkable` is false. The message names the table's caption and
  says to declare `shrinkable=True` on the first column. Reason, which the
  comment states: `_ROW_SUMMARY_CLASS`'s `overflow-hidden text-ellipsis` clips
  nothing without the width `SHRINKABLE_COLUMN_CLASS` gives the cell
  (`max-md:max-w-0`), which `TableRow` applies to a shrinkable first column
  alone — a summary under any other first column widens the table and the phone
  scrolls sideways instead.

**`games/views/session.py`** — `_row_summary` calls `row_summary(...)`; the
parts and their order do not move.

**Tests — `tests/test_components.py`** (beside the existing stacked-cell class):

- `row_summary` drops `None` and `""`, keeps `0`-like strings, joins with
  `", "`, and answers `""` for no parts at all.
- A summary row under a non-shrinkable first column raises in DEBUG, and the
  message names the first column.
- The same table with `shrinkable=True` renders.

---

## Phase 2 — the two playthrough summaries

**`games/views/playthrough_rows.py`**

- `_span(run, presentation) -> str | None` — the run's endpoints as one part.
  Reads `stated_start` / `stated_completion` from
  `games/reads/playthrough_endpoints.py`; each carries a `TemporalValue | None`
  as `.when`.
  - Neither endpoint stated → `None`.
  - Either stated value `is_range` or `is_unknown` → no span; the caller states
    `Started …` / `Completed …` as separate parts instead (see `_summary`).
  - Otherwise build one `TemporalValue.range(...)` and hand it to
    `present_temporal_value`, so the words are the temporal grammar's own.
- `_summary(run, presentation, *, with_game: bool) -> str` — `row_summary` over
  the game name (list only), the span or the two labelled endpoint parts, and
  the activity part.
- `_activity_part(run, clock) -> str | None` — `RunActivity(run.activity).label`
  and `recency_phrase(day, clock.today)` in one string, `None` where `activity`
  is null. Reuses what `_activity_cell` reads; both keep the
  `hasattr(run, "activity")` refusal.
- `playthrough_tabledata` passes `summary=` on every `make_row`, with
  `with_game=("Game" not in exclude_columns)`.

**Gotchas, each verified against the code**

- `TemporalEndpoint.open()`, never `.unknown()`: `_present_range` reads
  `start.is_open` → `until …` and `end.is_open` → `since …`. The **other**
  endpoint's openness picks the word. An unknown endpoint renders `Unknown`,
  not `since`.
- `TemporalEndpoint.known()` raises unless the value's kind is atomic, which is
  why the `is_range` / `is_unknown` test comes first.
- A qualifier renders as a suffix inside a range (`1984 (approximate) – …`) and
  as a prefix in the cell (`around 1984`). Accepted: the summary states the
  range grammar's spelling.
- Both callers already carry the `activity` alias — the list through
  `runs_with_condition`, Game detail through `numbered_for(..., with_condition=True)`.

**Tests — `tests/test_playthrough_rows.py`**

- List row: summary names the game; Game detail row (`exclude_columns=["Game"]`)
  does not.
- Two known days → `5 Mar 2026 – 2 Apr 2026`.
- Start alone → `since 5 Mar 2026`. Completion alone → `until 2 Apr 2026`.
- Neither → no span part, and the summary is the remaining parts alone.
- A range-valued start beside a known completion → `Started …, Completed …`,
  no ` – ` joining them.
- A completed run states no activity part.
- A run with no endpoint and no activity on Game detail states `""`.

---

## Phase 3 — one builder for both record tables

**`games/views/historical_playtime.py`** — `historical_playtime_tabledata`
gains `exclude_columns: Sequence[str] = ()`, `sortable: bool = False` and
`caption: str`, and drops columns by label the way `playthrough_tabledata`
does (its `_SORT_KEYS` map plus a local `column()` helper is the pattern to
copy). One column list serves both pages:

| Column | sort key | priority | notes |
|---|---|---|---|
| Name | `name` | 1 | shrinkable; excluded on Game detail |
| When | `when` | 3 | **becomes shrinkable** — it leads on Game detail |
| Duration | `duration` | 2 | |
| Provenance | `provenance` | 2 | |
| Playthroughs | — | 1 | shrinkable; renamed from `Runs` |
| Device | `device` | 1 | |
| Created | `created` | 1 | excluded on Game detail |
| Actions | — | 4 | |

**`games/views/game.py`** — `_historical_playtime_section` calls the builder
with `exclude_columns=["Name", "Created"]`, `sortable=False`,
`caption="Historical playtime of this game"`, and keeps its own `StyledTable`
call with its `selection=` and `request=`, as `_playthroughs_section` does. Its
inline row construction goes.

**What the merge changes on Game detail, each deliberate**

- Provenance renders as the toned `Badge`, not `Pill`.
- A record naming two or more runs gains the `shared` badge.
- `Device` moves from priority 3 to 1, so it drops before Duration and
  Provenance. The summary states the device below `md`, so nothing is lost
  there.
- `When` moves from priority 1 to 3, which only matters above `md`.
- Row id becomes `record-row-{pk}` and the `Duration` scope `record-{pk}`.

**`games/views/historical_playtime.py`** — `list_historical_playtime` passes
`sortable=True` and `caption="Historical playtime"`. Missing the flag silently
strips every sort header from the Historical tab.

**Tests to update, not add**

- `tests/test_game_detail_historical_playtime.py:63` — expects
  `id="historical-row-…"`; becomes `record-row-`.
- `tests/test_historical_playtime_views.py:441` — the cross-library leak test
  on Game detail, same rename.
- `tests/test_playtime_page.py:118` already reads `record-row-` and does not
  move.

**Tests to add — `tests/test_historical_playtime_views.py`**

- Game detail's table states the six columns, in order, headed `Playthroughs`.
- The list states eight, and its headers sort.
- Both pages render one builder's rows: a record with two runs shows the shared
  badge on each.

---

## Phase 4 — the two record summaries

**`games/views/historical_playtime.py`**

- `_record_summary(record, labels, presentation, durations, *, with_when: bool)`
  — `row_summary` over the parts the spec states. With the game leading the row
  (the list): when, duration, device. With the day leading it (Game detail):
  duration, provenance, runs, device. `with_when` follows
  `"Name" not in exclude_columns`, because the identity cell is what decides.
- `_runs_part(record, labels) -> str` — the first label, and `and N more` where
  the record names more.
- An unknown `when` and an absent device each state no part. A record read from
  the database carries a `TemporalValue`, so `record.when.is_unknown` is the
  test; `when` is `None` for a record that states none.

**Tests — `tests/test_historical_playtime_views.py`**

- List row summary: `5 Mar 2026, 2 hours, Steam Deck`.
- Game detail row summary states the provenance and the run, and no day.
- A record naming three runs states `Playthrough 1 and 2 more`.
- An unknown `when` states no part rather than `Unknown`.
- A record with no device states no part rather than `No device`.

---

## Phase 5 — the browser proof

**`e2e/test_playthrough_list_mobile_e2e.py`**, modelled on
`e2e/test_session_list_mobile_e2e.py` (375 px viewport, the same login
fixture): one game, one run with a start and a completion, and the Playthrough
list at that width. The summary names the game and the activity while the
`Game` column is hidden. `Game` is index 1 at priority 1, so the drop reaches
it third.

---

## Gate

`make format`, `make lint-fix`, `make vale`, then one full `make check` under
the shared lock:

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check
```

No TypeScript changes, so no `make ts`. No migration. No follow-up issues: the
duplication this issue would have deferred is Phase 3.
