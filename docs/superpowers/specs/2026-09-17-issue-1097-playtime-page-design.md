# The Playtime page

Issue: [#1097](https://github.com/KucharczykL/timetracker/issues/1097).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Runs beside #706 and #709, each in its own worktree.
Shared surface: [parallel spec review](../../review/2026-09-17-historical-playtime-parallel-specs.md),
decisions D1 to D6.

## Purpose

One place, Playtime, holds two lists: the session list that exists today, and
a new list of Historical Playtime Records. The new list filters, sorts and
saves presets like every other list, and the API serves the same rows.

## Where Playtime is reached

The issue speaks of a nav entry "Sessions". None exists: the navbar holds Log
game, Library and the account menu, and the entity menus were removed on
purpose. Sessions is reached from the Library page, from the landing-page
setting, and from the `index` redirect. So:

- The Library page's "Sessions" statistic card becomes "Playtime"; its link
  is the Sessions tab. Its value stays a row count, live sessions plus live
  records, and the card's `title` says so ("Sessions and historical
  records"): `StatisticCard` gains an optional `title`. #710 replaces the
  count with the `PlaytimeSplit` total, which #709 reads.
- `LANDING_PAGE_CHOICES` keeps `games:list_sessions` and relabels it
  "Playtime". A stored landing page does not change.
- The navbar does not change.

The wave document's Screens section says "nav entry". This issue's PR amends
that sentence to name the three entries above.

## Tabs

`PageTabs(label, tabs)` is a new primitive in `common/components/primitives.py`:
a `<nav aria-label=…>` of plain links, the current one marked
`aria-current="page"`. It needs no script: each tab is its own route.
`PlaytimeTabs(current)` states the two tabs. Both list views put it at the
top of their `ContentContainer`, above the quick bar.

| tab | route | name | mode |
|---|---|---|---|
| Sessions | `session/list` | `games:list_sessions` | `sessions` |
| Historical | `historical-playtime/list` | `games:list_historical_playtime` | `historical_playtime` |

The Sessions tab keeps its route, its mode key and its sorts, so every stored
preset and every link still resolves. The new route is `READ_ONLY` in
`games/views/returns.py` and is listed in `render_pages.LIST_ROUTES`. The
view lives in `games/views/historical_playtime.py`; #706 takes
`games/views/historical_playtime_entry.py`.

## The read scope

`HistoricalPlaytimeQuerySet` states `alive()` and no `for_library()`, and its
`alive()` reads the record's mark and the `PlayerGame`'s, never the catalog
game's. The read layer states every mark itself, as `library_sessions` does
(review D1, D2).

`games/reads/historical_playtime_records.py` is shared by #706, #709 and this
issue. Its text is fixed by review D1 and no branch adds to it: the first of
the three to merge creates it, and the others take `main`'s copy on rebase.
It holds:

- `RECORD_ORDER` — `when_lower` descending with an unknown `when` last, then
  `-created_at`, then `id` (review D3);
- `library_records(library)` — five conditions: the record's library, the
  tracked game's library, the record's mark, the `PlayerGame`'s mark and the
  catalog game's mark;
- `readable_records(library)` — `library_records` with
  `player_game__game__platform` and `device` selected;
- `game_records(library, game)` — `library_records` at one catalog game.

The module is D1's text on `main`, copied verbatim.

The list prefetches runs itself (`Prefetch("runs")`); run names are joined in
Python from `numbered_for` over the page's `player_game_id`s.

#709's sums live in `games/reads/historical_playtime.py`, which this issue
does not touch.

## The mode `historical_playtime`

Model key `historicalplaytime`, so `filter_for_model` finds
`HistoricalPlaytimeFilter` by name. The mode joins every per-mode table:

- `FilterPreset.MODE_CHOICES` (migration `0010`);
- `MODE_PARSERS`, through `parse_historical_playtime_filter`;
- `MODE_SORTS`;
- `FILTER_MODE_LIST_URLS`, `FILTER_MODE_MODELS`, `BUILDER_MODES`;
- `QUICK_FACETS`;
- `_FILTER_LIST_URL`;
- `filter_queryset_for_library` and `filter_query_context_for_library`, both
  answering `library_records(library)`. The generic fallback calls
  `for_library()`, which this queryset does not state.

The tests that walk these tables then cover the new mode: the plan relies on
`test_mode_parsers_cover_every_mode_choice` in `tests/test_filter_presets.py`
(parsers against `MODE_CHOICES`), `tests/test_filter_widgets.py`
(`FILTER_MODE_LIST_URLS` against `MODE_PARSERS`),
`tests/test_quick_filter_bar.py` (`QUICK_FACETS` and `BUILDER_MODES`), and
`tests/test_render_pages.py` (`LIST_ROUTES`).

## HistoricalPlaytimeFilter

| field | compiles to |
|---|---|
| `game` | `player_game__game__id`, with game search |
| `provenance` | choice over `HistoricalPlaytimeProvenance`, all three |
| `device` | `device_id`, with device search |
| `emulated` | bool |
| `duration_hours` | `duration_hours_handler("duration")` |
| `when` | `temporal_interval_handler("when", "when_lower", "when_upper")`, `metadata_lookup="when_lower"` |
| `note` | string |
| `created_at` | `created_at__date` |

`when` reads as Playthrough's endpoints read: a day matches a record whose
interval may name that day, so `when` between two days matches a `2020/2022`
record for any day range that touches it. `is null` is an unknown `when`.
#709's statistics count by containment. The gap is #709's follow-up (a
`GameFilter` relation to records with a containment modifier); this issue
files nothing for it.

There is no `run` field: a record's runs are a to-many hop, and
`check_comparison_through` refuses one. `comparison_through` is already
declared on the model.

`search` matches the game name, the platform name, the device name and the
note. `game_filter` and `device_filter` are forward relations, as on
`PlayerSessionFilter`. No reverse relation is added to `GameFilter` or
`DeviceFilter`.

## Quick bar and sorts

Facets, in order: provenance, duration (hours), game, device, when, created.

| sort key | column |
|---|---|
| `name` | `player_game__game__sort_name` |
| `when` | `when_lower` |
| `duration` | `duration` |
| `provenance` | `provenance` |
| `device` | `device__name` |
| `created` | `created_at` |

Default `-when,-created`: newest first, newest recorded first on a tie, as
`RECORD_ORDER` orders (review D3). `apply_sort` puts an unknown `when` last.

## The table

`StyledTable` through `paginated_table_content`, caption "Historical
playtime", every column but Runs sortable:

- **Name** — the game link, shrinkable.
- **When** — the temporal text Playthrough rows use; "Unknown" for null.
- **Duration** — the viewer's duration presentation.
- **Provenance** — a badge; `Externally measured` reads distinctly, because
  import (#798) writes it.
- **Runs** — each run's display name through `numbered_for`, one query for
  the page. A record naming two or more runs carries a "shared" mark.
- **Device** — "No device" when null.
- **Created**.

Empty: the table's empty state, "No historical playtime."

**Row actions and "View all"** (review D4). Edit and Remove need #706's
routes. Whichever of #706 and #1097 merges second adds, in its own PR:

- the Actions column on this list: Edit to the restate form, Remove to its
  confirm page, both through `action_url` with the origin;
- the "View all" link from #706's Game detail section to this list, narrowed
  to the game, through `_game_section`'s `view_all_url`.

Neither issue files a follow-up for it.

## API

`historical_playtime_router`, mounted at `/api/historical-playtime`.

- `GET /` — `filter`, `sort`, `page`, answered as
  `HistoricalPlaytimeListOut`: `items`, `count`, `page`, `page_size`,
  `num_pages`, the five fields `SessionListOut` has. The two envelopes stay
  separate schemas; neither router changes the other's. A bad filter or an
  unknown sort key answers 400 and logs, as the session list does.
- `GET /{id}` — the row, 404 outside the library or removed.

`HistoricalPlaytimeOut`: `id`, `player_game_id`, `game`, `playthrough_ids`
(sorted), `duration_seconds`, `when` (canonical temporal text or null),
`when_lower`, `when_upper`, `provenance`, `device`, `emulated`, `note`,
`created_at`. No write endpoint: writes are #706's form.

## Tests

New files, named apart from #705's (`_command`, `_events`, `_projection`) and
#706's (`_form`, `_views`, `test_game_detail_historical_playtime.py`):
`tests/test_historical_playtime_filter.py`,
`tests/test_historical_playtime_api.py`, `tests/test_playtime_page.py`,
`e2e/test_playtime_page_e2e.py`. Existing files are extended where a
registry walk or route list lives.

- Filter: every field, each modifier a widget offers; `when` overlap, a
  decade, an open range and unknown; `search`; both relations.
- Scope: a removed record, a record under a removed `PlayerGame`, a record
  under a removed catalog game, and another library's record never appear.
- Registry: the four walks named above pass with the new mode;
  `filter_for_model` resolves it; the builder page renders it.
- Contract: `ts/elements/filter-tree/fixtures.json` gains a
  `historicalplaytime` model and cases (a leaf, a `when` range, `NOT`, a
  `game_filter` relation); `FILTER_FOR_MODEL` in
  `tests/test_filter_tree_contract.py` gains the filter.
- Presets: save, list and load under the new mode; a stored `sessions`
  preset still loads on the Sessions tab.
- Sorts: every key orders; the sort-header parity test covers the table.
- API: list, filter, sort, 400s, detail, 404, another library's record.
- Pages: both tabs in `test_paths_return_200`; the tabs render with the
  right `aria-current`; the Library card reads "Playtime", counts both and
  carries its `title`.
- e2e: the Historical quick bar applies a provenance facet; a tab click moves
  between the lists; the table-width and responsive-table checks include
  the new list.

## Parallel work

#706 and #709 run at the same time.

- Migration `0010` is a choice change on `FilterPreset.mode`. If a sibling
  merges a migration first, renumber on rebase.
- `games/urls.py`, `games/views/returns.py` and `games/api.py` take one
  block each; #706 edits the first two as well. Conflicts are adjacent lines.
- `games/filters.py` gains a new class and registry lines; #709 edits
  `GameFilter`'s playtime pieces in the same file.
- `historical_playtime_records.py` is shared by all three (review D1).
- `CLAUDE.md`: the HistoricalPlaytime entry's sentence "Nothing reads or
  writes it from a page yet." is replaced by one sentence of this issue's.
  A branch merging after another keeps `main`'s sentence and appends its own
  (review D5). Nothing else in that entry changes.
- No merge order is required. The agreement lives in the review document;
  this issue links it in one comment (review D6).

## Not here

Row actions and "View all" unless this issue merges after #706; the union list (#1100); the review facet
and "Convert all shown" (#1098); the split presentation (#710); reverse
relations into this filter.
