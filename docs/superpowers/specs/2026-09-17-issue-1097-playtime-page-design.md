# The Playtime page

Issue: [#1097](https://github.com/KucharczykL/timetracker/issues/1097).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Shared decisions: [parallel spec review](../../review/2026-09-17-historical-playtime-parallel-specs.md).

## Purpose

The Playtime page holds two lists. The Sessions tab is the session list. The
Historical tab lists Historical Playtime Records.

## Entry

No navbar entry names the page. Three entries reach it:

- the Library page's "Playtime" card, which links to the Sessions tab;
- the "Playtime" landing-page choice;
- the `index` redirect.

The card value is a row count: live sessions plus live records. Its `title`
says so. The value is a count, not a duration.

## Tabs

`PageTabs` is a row of links. The current link has `aria-current="page"`.
`PlaytimeTabs` states the two tabs. Each tab is its own route:

| tab | route name | mode |
|---|---|---|
| Sessions | `games:list_sessions` | `sessions` |
| Historical | `games:list_historical_playtime` | `historical_playtime` |

## Scope

`library_records` in `games/reads/historical_playtime_records.py` is the
scope. It states both libraries and three removal marks: the record's, the
`PlayerGame`'s and the catalog game's. The filter context, the builder, the
list and the API read this scope.

## Filter

`HistoricalPlaytimeFilter` has these fields: `game`, `provenance`, `device`,
`emulated`, `duration_hours`, `when`, `note`, `created_at`. It also has
`search`, `game_filter` and `device_filter`.

`when` uses overlap. A day matches a record whose interval can contain that
day. `is null` matches an unknown `when`. The wave's statistics use
containment.
Thus a list filter and a year figure can count different records.

The filter has no run field. A record's runs are a to-many relation, and
`check_comparison_through` refuses it.

The mode `historical_playtime` is in every per-mode table. Model key is
`historicalplaytime`. The builder's model menu comes from `BUILDER_MODES`.

## List

Columns: Name, When, Duration, Provenance, Runs, Device, Created. Runs is
not sortable. A record with two or more runs shows a "shared" badge.
`Externally measured` has its own badge colour, because importers write it.

The default sort is `-when,-created`. It agrees with `RECORD_ORDER`. An
unknown `when` sorts last.

The page has no Actions column. Game detail has no "View all" link to the
page.

A join row that names a run the page cannot name is a defect.
`record_run_labels` raises `RowUnreadable` for it. The list and the API read
only this library's join rows.

## API

- `GET /api/historical-playtime/` takes `filter`, `sort` and `page`. A bad
  filter or sort gives 400 and a log line.
- `GET /api/historical-playtime/{id}` gives 404 for a record outside the
  scope.

`when` is canonical temporal text, or null. `when_lower`, `when_upper` and
`playthrough_ids` are also in the response. The API has no write endpoint.

## Verification

- The cross-language filter contract covers the filter.
- Every hand-written list of pages includes the new route.
- The e2e suite opens the tabs from the Library card and applies a
  provenance facet.
