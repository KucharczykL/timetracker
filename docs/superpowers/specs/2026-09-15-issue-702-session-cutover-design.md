# Switch Session writes and every read surface

Issue: [#702](https://github.com/KucharczykL/timetracker/issues/702).
Wave review: [Session delivery wave](2026-09-12-session-wave-design.md).
Depends on #700 and #1047; members 3 to 6 of stack #1072, ahead of #704.

## Purpose

Every Session write becomes a command and every Session read reads the
projection. After this issue, nothing outside migrations, the backfill,
the preflight census and the sample-fixture tooling imports `Session`.

The commands exist (#689, #691, #692, #694), the projection is populated
(#700), and the zone a library counts days in is stated (#1047). This
issue is the wiring: forms, views, filters, sorts, the API, statistics,
the navbar, the dormancy clock, the ownership audit, and the tests that
walk them.

## Three decisions

**The form derives the mode from what is filled.** No mode control. A
start with no duration is Timed; a day and a duration with no instants is
Duration-only; a start, an end and a duration is Corrected. Two shapes
have no home and are refused with a sentence that names the shapes that
work: a start and a duration with no end, and a day beside an instant.
This mirrors `TemporalField`, whose precision is derived from the parts a
person fills. The legacy form's manual duration *added* to elapsed time;
after this issue a duration beside two instants *replaces* it, which is
what the Corrected mode means, and the sentence on the field says so.

**The filter speaks projection words.** `SessionFilter` is restated on
`PlayerSession`: `timing_mode` (choice), `is_running` (Timed with no end),
`day` (`effective_day`), `started` and `ended` (the instants' dates, null
on a Duration-only row), `duration_hours` (`effective_duration`),
`created_at`, `game`, `device`, `emulated`, `note`, `search`,
`game_filter`, `device_filter`. The four dying fields
(`duration_manual_hours`, `duration_calculated_hours`, `is_manual`,
`is_active`) are replaced, not aliased; `timestamp_start`,
`timestamp_end` and `duration_total_hours` are renamed so the filter holds
one vocabulary, matching Playthrough's `started`/`completed`. Saved presets
are not migrated: production holds none naming a session field (#767
keeps the registry).

**The run is picked after the game.** The game `SearchSelect` stays. A
run `<select>` beside it lists that game's live ordinary runs, defaulting
to the latest, hidden when the game holds one. A small custom element
refills it after each game pick from `GET /api/playthrough/?game=<id>`,
a query the list route gains. Without JavaScript the select lists every
live ordinary run grouped by game. The imported-history bucket is not
offered: `MoveSessionToPlaythrough` is the only way in or out of it.

## Members

Four members, cut by coupling so each is green on `make check` alone.
The stack lands atomically, so the read/write window between members
never runs anywhere real.

1. **Reads** — `SessionFilter` and its context scope, the list view and
   its row, sorts, quick facets, `GameFilter`'s session aggregates, the
   playtime `SOURCE` flip, statistics, navbar figures, links and resumes,
   the list and get API routes, the TypeScript fixtures and the
   cross-language contract test.
2. **Writes** — the form and its derivation, the run picker, the four
   creation surfaces, clone, finish, reset, remove, both PATCH routes,
   the device selector, `mark_as_played`, and the e2e files that write.
3. **Detail** — Game detail's session table, badge and metrics, the
   playthrough page's range sum and seeded days, the dormancy clock, the
   ownership audit, the library page.
4. **Sweep** — a guard test over the import of `Session`, the remaining
   e2e, the docs.

Reads come first: the projection holds every legacy row, the commands
and `tests/session_rows.py` already build rows, and the write member's
e2e then reads a list that shows what it wrote.

## Reads

### The read scope

`library_sessions(library)` from `games/reads/player_sessions.py` is the
one scope: four removal marks, the library on the session, its run and
its tracked game. `filter_query_context_for_library` maps `PlayerSession`
to it, so every nested filter, aggregate scope and relation subquery
resolves from it. `Session` leaves that table.

### The filter

`game` reads `playthrough__player_game__game__id`; `search` walks the
same path to the game's name and platform, and the device's name and
type; `game_filter` names that path as its parent field; `device_filter`
is unchanged. `is_running` is `timing_mode = timed AND ended_at IS NULL`,
so a Corrected row is never running. `started` and `ended` compare
`__date`, and a Duration-only row is null on both, which is the truth: it
has no instant.

`GameFilter`'s aggregates cross `player_games__playthroughs__sessions`
and take the context scope, so a shared catalog game counts one
library's sessions. `session_count` and `session_average` (over
`effective_duration`) stay. `manual_playtime_hours` and
`calculated_playtime_hours` go; `session_playtime_hours` arrives as a
scoped sum over `effective_duration`, and either old figure is that sum
scoped by `timing_mode`. `QUICK_FACETS["games"]` keeps `playtime_hours`
and `session_count`; `QUICK_FACETS["sessions"]` becomes `game`, `device`,
`day`, `timing_mode`, `duration_hours`.

### Playtime

`SOURCE` in `games/reads/playtime/__init__.py` binds to the projection.
`projection.py` gains `summed_by_game_matching`, which applies the
filter's `to_q` under the library's context. `legacy.py` loses its
`summed_by_game_matching`, because a `SessionFilter` in projection words
cannot compile against the legacy table, and so satisfies `PlaytimeSource`
rather than `FullPlaytimeSource`. `verify-playtime-parity` already
excludes that member; its reason string changes. #772 removes the legacy
source.

### List, sorts, row

The list reads `library_sessions` with the run, its tracked game, the
game, the platform and the device selected. Sorts: `name` on the run's
game's `sort_name`, `date` on `sort_instant`, `duration` on
`effective_duration`, `device`, `created`. Default `-date,created`.

`session_time_range` takes a `PlayerSession`: a Duration-only row renders
its day alone; a Timed or Corrected row renders start and end as today,
each in its own stored zone under the "own" preference. The duration cell
shows `effective_duration` and a badge naming the mode where it is not
Timed. The name cell shows the run's display name beside the game only
when the game holds more than one live ordinary run; numbering comes from
`numbered_for`. Finish and reset appear only on a running Timed row.

### Statistics and navbar

`compute_stats` scopes a year on `effective_day__year`, groups days on
`effective_day`, and takes superlatives over `effective_duration`; first
and last play read `sort_instant`. `stats_links` builders emit
`day__between`, and the parity tests that pin each builder to its stat
move with them. `model_counts`'s today and last-seven-days figures already
go through the playtime package; their links name `day`. `session_count`
reads `library_sessions(...).exists()`. `recent_session_resumes` pages
`library_sessions` by `(sort_instant, id)`, descending, behind
`playersession_sort_order`, distinct per game through the run.

### The API, read half

`SessionOut` is the projection: `id`, `playthrough_id`, `game` (through
the run), `device`, `timing_mode`, `started_at`, `ended_at`, both zones
and their labels, `stated_day`, `stated_duration_seconds`, `day`,
`duration_seconds`, `note`, `emulated`, `created_at`. `GET /api/session/`
and `GET /{id}` read `library_sessions`. `/api/devices/search` orders by
`Max("player_sessions__sort_instant")`. `/api/timezones/search` stays.

### The TypeScript contract

`fixtures.json` rewrites every session case in the new vocabulary, and
`tests/test_filter_tree_contract.py` keeps mapping `"session"` to
`SessionFilter`, so the serializer and the backend cannot drift.

## Writes

### The form

`SessionForm` becomes a plain `Form`: `game`, `playthrough`, `started_at`
with its zone row, `ended_at` with its zone row, `day`, `duration`,
`device`, `note`, `emulated`, `mark_as_played`. `clean()` derives one
`TimingStatement` or raises the refusal onto the field that caused it.
`day_zone` is `calendar_day_zone(library)`, never a preference read
inside the command. Edit seeds the fields from the row's mode.

### The write path

`games/writes/playersession.py` holds the request-free half, following
`games/writes/playthrough.py`: `record_session` dispatches
`CreateSession`; `restate_session` dispatches `CorrectSessionTiming`, then
`DescribeSession`, then `MoveSessionToPlaythrough` when the run changed,
under one `correlation_id`, each through `answered("session")`, with
`Unchanged` absorbed. `mark_as_played` stays a companion dispatch under
its own `correlation_id`, as #683 settled.

Finish is `EndSession(now, browser zone)`. Reset is `CorrectSessionTiming`
with `TimedTiming(now, day_zone=<the row's>, started_at_zone=<the
browser's>)`, offered only on a running row. Remove is `RemoveSession`
behind the confirm page; no restore route, which #695 owns. Clone is
`CreateSession` with `TimedTiming(now, day_zone=calendar)` on the source's
run, device and emulated copied, note empty. `returns.py` classifies every
route that changes.

### The API, write half

`PATCH /{id}/device` dispatches `DescribeSession(StatedDevice(...))`.
`PATCH /{id}` takes a body with `extra="forbid"`: `timing` (one whole
statement, told apart by shape: Timed, Duration-only or Corrected) is a
correction; `note`, `device_id`, `emulated` are a description;
`playthrough_id` is a move. A named key is the act; an omitted key states
nothing. No POST: #1074 owns it.

## Detail, clock, audit

Game detail's session table, badge and metrics read `library_sessions`
narrowed to the game through the run. "Without manual" becomes "timed":
the average is over `effective_duration` where the mode is not
Duration-only, which is what the old exclusion of a zero
`duration_calculated` meant. The playthrough page's range sum, the last
playtime read outside the package, becomes `playtime_between` over
`effective_day`; its seeded start and end days read the run's sessions.

The dormancy clock asks when the *run* was last played: the latest
`effective_day` of the run's own sessions, library stated on the
subquery, then the run's start day. No zone is computed; `effective_day`
already is the day the library counts.

`audit_library_ownership` counts `PlayerSession` rows by library and drops
the hand-written `Session.device` loop; `AUDITED_PROJECTION_REFERENCES`
holds that key and `cross_library_violations` reports it. The library
page counts `library_sessions`.

## Sweep

A guard test walks `games/`, `common/` and `timetracker/` and fails on an
import of `Session` outside an allow list: `models.py`, `removal.py`,
`migrations/`, `backfill/`, `preflight/`, `anonymize_sample`,
`scrub_staging`, `load_sample_data`. #772 empties the list. `Session`
stays in `REMOVABLE_MODELS` until then; nothing calls `remove()` on one.

## Out

- `POST /api/session/` — #1074.
- A restore route — #695.
- Preset migration — #767.
- The sample fixture and the legacy table — #772; `load_sample_data`
  already runs the conversion pass after it replays the fixture.
- The bulk move, the organizer — #714, #715, #716.

## Verification

Each member: full `make check`. The stack: `make verify-dump` on the
newest dump, then `make verify-playtime-parity ARGS="--all-libraries"`
and `make verify-replay-parity`, which #704 gates on.
