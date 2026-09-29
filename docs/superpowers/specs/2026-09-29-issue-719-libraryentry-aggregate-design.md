# The LibraryEntry aggregate

Issues: [#719](https://github.com/KucharczykL/timetracker/issues/719),
[#720](https://github.com/KucharczykL/timetracker/issues/720),
[#722](https://github.com/KucharczykL/timetracker/issues/722), member M1 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
Charter: [LibraryEntry](2026-08-09-timetracker-overhaul-design.md#libraryentry).
After: [A device's access ends](2026-09-28-issue-1275-device-access-end-design.md),
[Catalog](../../catalog.md).

## Purpose

A library says that it has a game: one route of access to one Release,
with an access word, a format and the day it was acquired. That fact is a
`LibraryEntry`. One library can hold several entries on one Release. Two
entries with the same words are two copies.

## The opening endpoint

An opening endpoint is an act that the creation states. A correction moves
the day. Nothing voids it. The marker admits no null.

- `games/endpoint_fields.py`: `EndpointColumns` and
  `OpeningEndpointColumns` are siblings under `EndpointColumnsBase`. Only
  the first states `unstated_columns()`, so a void of an opening endpoint
  is a type error. `opening_marker()` admits no null.
- `games/events/endpoint.py`: `OpeningEndpointEvents` holds `corrected`.
- `games/endpoints.py`: `OpeningEndpoint`. `ENDPOINTS` lists both shapes.
  `games.E014` refuses a nullable opening marker.
- `Projector.opening_columns` answers the creation's columns.
  `project_corrected` moves the day.
- `correct_opening_endpoint` takes one sentence and answers `Unchanged`
  for the same statement.

## Storage

Table `games_libraryentry`. Only the `Entries` projector writes it.
Columns: `id`, `library`, `player_game` (RESTRICT), `release` (RESTRICT),
`access`, `format`, `note`, the endpoint `acquisition`, `created_at`,
`removed_at`. Two CHECKs admit only the known words. A partial index
covers live rows on `(library, release)`. `alive()` reads the entry's
mark and the tracked game's. The reference kind `libraryentry` is
`PROJECTED`.

## Events

Stream `library.libraryentry`, eight types: `created` (`player_game` as a
bare id, `release` as a Reference, the words, both notes; the day is
`effective_time`), `access_changed`, `format_changed`, `note_changed`,
`release_changed`, `acquisition_corrected`, `removed`, `restored`.

## Commands

`games/commands/libraryentry.py`. Each refusal has a sentence.

| Command | Rule |
|---|---|
| `RecordEntry` | The Release resolves through `visible_row`. A removed Release, Edition or Game is refused. The game is the Release's. A removed `PlayerGame` is refused. An untracked game is tracked in the same dispatch. |
| `DescribeEntry` | `None` states nothing. One event per changed fact. A new Release must be live and of the same game. A removed entry or `PlayerGame` is refused after `Unchanged`. |
| `CorrectEntryAcquisition` | `Unchanged` for the same statement, then the two refusals. |
| `RemoveEntry` | `Unchanged` if removed. Then the removed `PlayerGame`, the referrer registry, and a foreign referrer (`RowUnreadable`). |
| `RestoreEntry` | `Unchanged` if live. A removed `PlayerGame` or Release is refused. |

## Scope and references

`LIBRARY_PATHS` in `games/projections.py` gives a catalog row its path to
a library. `games.E015` refuses a path that does not end at a library.
`library_path_of` reads the concrete column first.
`ProjectionReference.library_path` carries the path, and the ownership
audit joins through it. `visible_row` in `games/commands/scope.py` resolves
a shared row or the library's own through that path. `TrackGame` uses it.
`library_entry_row` refuses an entry whose `PlayerGame` or private Release
is another library's with `RowUnreadable`. `entry_game_violations` reports
an entry whose Release is not its game's.

## Referrer registry

`games/reads/referrers.py`. `BlockingReferrer.on` takes `target`.
`referrers_of(target)` reads the tuple at each call. `blocking_referrer`,
`foreign_referrer` and `rows_naming` take any projection row.

## Writes, reads, API

`record_entry` answers `RecordedEntry` (the entry id, and whether the
game was tracked) from `dispatched_events`. `restate_entry` sends the
description first, whose refusals include the correction's. `library_entries` reads five marks. Routes: `GET`,
`POST /api/entries/`; `GET`, `PATCH /api/entries/{id}`. The schema refuses
an unknown word and a present null with 422. A PATCH states `acquired`
and `acquisition_note` together, or 422.

## Limits

- No screen, no filter, no removal route.
- No end of access (M2). No purchase names an entry (P1).
- An entry does not move to another game.
