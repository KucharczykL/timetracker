# The Playtime page

Issue: [#1097](https://github.com/KucharczykL/timetracker/issues/1097).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Runs beside #706 and #709, each in its own worktree.

## Purpose

One place, Playtime, holds two lists: the session list that exists today, and
a new list of Historical Playtime Records. The new list filters, sorts and
saves presets like every other list, and the API serves the same rows.

## Where Playtime is reached

The issue speaks of a nav entry "Sessions". None exists: the navbar holds Log
game, Library and the account menu, and the entity menus were removed on
purpose. Sessions is reached from the Library page, from the landing-page
setting, and from the `index` redirect. So:

- The Library page's "Sessions" statistic card becomes "Playtime". Its value
  is the count of live sessions plus live records; its link is the Sessions
  tab.
- `LANDING_PAGE_CHOICES` keeps `games:list_sessions` and relabels it
  "Playtime". A stored landing page does not change.
- The navbar does not change.

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
`games/views/returns.py` and is listed in `render_pages`.

## The read scope

`HistoricalPlaytimeQuerySet` states `alive()` and no `for_library()`.
`games/reads/historical_playtime_records.py` states the scope, as
`library_sessions` does for sessions:

- `library_records(library)` — records of this library, whose tracked game
  is of this library too, `alive()` (the record's mark and the
  `PlayerGame`'s).
- `readable_records(library)` — the row path the list and the API share:
  game, platform, device, and the runs prefetched.

#709 creates `games/reads/historical_playtime.py` for the sums. Its sums read
`library_records`; the first of the two to merge owns the function, and the
other rebases onto it. This is stated on #709.

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

The existing keyset tests then cover the new mode without change.

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
#709's statistics count by containment; a stats link that needs containment
states its own field when one is added.

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

Default `-when,created`. `apply_sort` puts an unknown `when` last.

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

**Row actions.** Edit and Remove need #706's routes. Whichever of #706 and
#1097 merges second adds the Actions column: Edit links to the restate form
and Remove to its confirm page, both through `action_url` with the origin.
This is stated on #706.

## API

`historical_playtime_router`, mounted at `/api/historical-playtime`.

- `GET /` — `filter`, `sort`, `page`, the envelope `SessionListOut` has:
  `items`, `count`, `page`, `page_size`, `num_pages`. A bad filter or an
  unknown sort key answers 400 and logs, as the session list does.
- `GET /{id}` — the row, 404 outside the library or removed.

`HistoricalPlaytimeOut`: `id`, `player_game_id`, `game`, `playthrough_ids`
(sorted), `duration_seconds`, `when` (canonical temporal text or null),
`when_lower`, `when_upper`, `provenance`, `device`, `emulated`, `note`,
`created_at`. No write endpoint: writes are #706's form.

## Tests

- Filter: every field, each modifier a widget offers; `when` overlap, a
  decade, an open range and unknown; `search`; both relations; removed
  records and records under a removed `PlayerGame` never match.
- Registry: the keyset tests pass with the new mode; `filter_for_model`
  resolves it; the builder page renders it.
- Contract: `ts/elements/filter-tree/fixtures.json` gains a
  `historicalplaytime` model and cases (a leaf, a `when` range, `NOT`, a
  `game_filter` relation); `FILTER_FOR_MODEL` in
  `tests/test_filter_tree_contract.py` gains the filter.
- Presets: save, list and load under the new mode; a stored `sessions`
  preset still loads on the Sessions tab.
- Sorts: every key orders; the sort-header parity test covers the table.
- API: list, filter, sort, 400s, detail, 404, another library's record.
- Pages: both tabs in `test_paths_return_200`; the tabs render with the
  right `aria-current`; the Library card reads "Playtime" and counts both.
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
- `library_records` is shared with #709, as stated above.

## Not here

Row actions until #706 is merged; the union list (#1100); the review facet
and "Convert all shown" (#1098); the split presentation (#710); reverse
relations into this filter.
