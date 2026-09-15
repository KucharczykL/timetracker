# Switch Session writes and every read surface

Issue: [#702](https://github.com/KucharczykL/timetracker/issues/702).
Wave review: [Session delivery wave](2026-09-12-session-wave-design.md).
Depends on #700 and #1047; members 3 to 5 of stack #1072, ahead of #704.

## Purpose

Every Session write becomes a command and every Session read reads the
projection. After this issue, nothing outside `models.py`, `removal.py`,
migrations, the backfill, the preflight census, the legacy playtime
source and the sample-fixture tooling imports `Session`.

The commands exist (#689, #691, #692, #694), the projection is populated
(#700), and the zone a library counts days in is stated (#1047). This
issue is the wiring: forms, views, filters, sorts, the API, statistics,
the navbar, the dormancy clock, the ownership audit, and the tests that
walk them.

## Decisions

**The form derives the mode from what is filled.** No mode control. A
start with no duration is Timed; a day and a duration with no instants is
Duration-only; a start, an end and a duration is Corrected. Two shapes
have no home and are refused with a sentence that names the shapes that
work: a start and a duration with no end, and a day beside an instant.
This mirrors `TemporalField`, whose precision is derived from the parts a
person fills. The legacy form's manual duration *added* to elapsed time;
a duration beside two instants now *replaces* it, which is what Corrected
means, and the field's help text says so.

**The filter is `PlayerSessionFilter`, in projection words.** The
builder resolves a filter class from the model's name
(`filter_for_model`: `"playersession" → PlayerSession →
PlayerSessionFilter`), the relation metadata emits the comparison
model's name, and `Session` leaves in #772, so the class is renamed
rather than the convention given an exception. The model key is
`playersession` wherever a key is spelled: `FILTER_MODE_MODELS`, the
builder URL, `model_field_registry`, the fixtures' `"model"`. The mode
key `sessions` stays. The relation attribute stays `session_filter`.
Fields: `timing_mode` (choice), `is_running` (Timed with no end), `day`
(`effective_day`), `started` and `ended` (the instants' dates, null on a
Duration-only row), `duration_hours` (`effective_duration`),
`created_at`, `game`, `device`, `emulated`, `note`, `search`,
`game_filter`, `device_filter`. The four dying fields
(`duration_manual_hours`, `duration_calculated_hours`, `is_manual`,
`is_active`) are replaced, not aliased; `timestamp_start`,
`timestamp_end` and `duration_total_hours` are renamed so the filter
holds one vocabulary, matching Playthrough's `started`/`completed`.
Saved presets are not migrated: production holds none naming a session
field (#767 keeps the registry).

**The run is picked after the game.** The game `SearchSelect` stays. A
run `<select>` beside it lists that game's live ordinary runs, defaulting
to the latest, hidden when the game holds one. A small custom element
refills it after each game pick from `GET /api/playthrough/?game=<id>`,
a query the list route gains, and each option shows the run's display
name, which `PlaythroughOut` gains through `numbered_for`. Without
JavaScript the select lists every live ordinary run grouped by game.

**The bucket takes no new session.** `CreateSession` refuses a run of
kind `imported_history` with a sentence naming the game's runs. Nothing
offers it, and clone and resume name the game's latest live ordinary
run, never the source's run: on the dump, a game's latest row can sit in
the bucket. `MoveSessionToPlaythrough` stays the only way in or out.

**Aggregates always take the context scope.** `aggregate_to_q` scopes
its subquery by `context.queryset_for(related_model)` whether or not a
scope filter is stated. Today only a stated scope narrows the subquery,
so an unscoped `session_count` over `player_games__playthroughs__sessions`
would count every library's rows on a shared catalog game, and
`purchase_count` already counts removed purchases. The change fixes both.

**A comparison operand can name the game.** `comparable_columns` reaches
one forward FK hop and one multi-valued hop; from `PlayerSession` the game
is three hops away, and five fixture cases compare a session against its
game's columns. `ProjectionModel` gains `comparison_through`, a declared
tuple of to-one paths the walk follows as one named hop; `PlayerSession`
declares `playthrough__player_game__game` as "Game". Introspection stays
the rule; the declaration adds a hop, never replaces one.

## Members

Three members, cut so each is green on `make check` alone. The stack
lands atomically, so no intermediate state runs anywhere real.

1. **Edges** — reads with their own tests and no write-then-read path
   across them: the dormancy clock, the ownership audit, the library
   page's count, the playthrough page's range sum and seeded days,
   `/api/devices/search`'s ordering, the remove-game confirm count.
2. **Cutover** — the filter and its context scopes, the list and its
   row, sorts, quick facets, `GameFilter`'s aggregates, the playtime
   `SOURCE` flip, statistics, navbar figures, links and resumes, Game
   detail's session table and metrics, the API, the TypeScript fixtures,
   the form and its derivation, the run picker, the creation surfaces,
   clone, finish, reset, remove, the device selector, `mark_as_played`.
   Writes and reads move together: a test that posts the form and reads
   a list crosses both, and a member that moved one side would leave it
   red. The wave review listed writes first for the same reason.
3. **Sweep** — the guard test over the import of `Session`, the wave
   review's correction, docs.

The member that moves a surface rewrites every test that reads or writes
it. Rows are seeded through `tests/session_rows.py`; a write is a command
or a posted form, never `Session.objects.create`.

## Reads

### The read scope

`library_sessions(library)` from `games/reads/player_sessions.py` is the
one scope: four removal marks, the library on the session, its run and
its tracked game. `filter_query_context_for_library` maps `PlayerSession`
to it, and `filter_queryset_for_library` gains a `PlayerSession` branch
returning it, since the queryset states no `for_library`. `Session`
leaves both.

### The filter

`game` reads `playthrough__player_game__game__id`; `search` walks the
same path to the game's name and platform, and the device's name and
type. `GameFilter.session_filter` and `DeviceFilter.session_filter`
resolve `PlayerSession` with lookups `playthrough__player_game__game__id`
and `device_id`. `is_running` compiles through a new handler,
`bool_running_handler`, to `timing_mode = timed AND ended_at IS NULL`, so
a Corrected row is never running. `started` and `ended` compare `__date`
in the request's active zone, as the legacy fields did; `day` reads the
library's calendar. A Duration-only row is null on both instants, which
is the truth.

`GameFilter`'s session aggregates cross
`player_games__playthroughs__sessions`. `session_count` and
`session_average` (over `effective_duration`) stay. `manual_playtime_hours`
and `calculated_playtime_hours` go; `session_playtime_hours` arrives as a
scoped sum over `effective_duration`, and either old figure is that sum
scoped by `timing_mode`. `QUICK_FACETS["games"]` keeps `playtime_hours`
and `session_count`; `QUICK_FACETS["sessions"]` becomes `game`, `device`,
`day`, `timing_mode`, `duration_hours`.

### Playtime

`SOURCE` in `games/reads/playtime/__init__.py` binds to the projection.
`projection.py` gains `summed_by_game_matching`, which applies the
filter's `to_q` under the library's context. `legacy.py` loses its
`summed_by_game_matching`, because a filter in projection words cannot
compile against the legacy table, and so satisfies `PlaytimeSource`
rather than `FullPlaytimeSource`; the parity command's reason for the
uncompared member changes. The playthrough page's range sum is a new
member, `game_playtime_between(library, game, days)`, which both sources
implement and the parity command compares. #772 removes the legacy source.

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
`effective_day`, and reads every session through the run's tracked game;
its three `Game.sessions` reads (the count, the games in scope, the
average) walk `player_games__playthroughs__sessions` under the library.
Superlatives change on purpose: the longest session and the highest
per-game average read `effective_duration`, so a Corrected row enters at
its override and a Duration-only row at its stated duration, where the
legacy read counted elapsed time alone. First and last play order by
`sort_instant` and render `effective_day`; `sort_instant` is never
rendered, since a Duration-only row's is midnight UTC. `stats_links`
builders emit `day__between`, and the parity tests that pin each builder
to its stat move with them. `model_counts`'s today and last-seven-days
figures already go through the playtime package; their links name `day`.
`session_count` reads `library_sessions(...).exists()`.
`recent_session_resumes` pages `library_sessions` by `(sort_instant, id)`,
descending, behind `playersession_sort_order`, distinct per game through
the run; resuming names the game's latest live ordinary run.

### The API, read half

`SessionOut` is the projection: `id`, `playthrough_id`, `game` (through
the run), `device`, `timing_mode`, `started_at`, `ended_at`, both zones
and their labels, `stated_day`, `stated_duration_seconds`, `day`,
`duration_seconds`, `note`, `emulated`, `created_at`. `GET /api/session/`
and `GET /{id}` read `library_sessions`. `/api/devices/search` orders by
`Max("player_sessions__sort_instant")` over live rows. `/api/timezones/
search` stays. `GET /api/playthrough/` takes `game` and answers
`display_name`.

### The TypeScript contract

`fixtures.json` rewrites every session case in the new vocabulary under
`"model": "playersession"`; the five game-column comparisons keep their
meaning through the declared hop. `tests/test_filter_tree_contract.py`
maps `"playersession"` to `PlayerSessionFilter`.

## Writes

### The form

`SessionForm` becomes a plain `Form`: `game`, `playthrough`, `started_at`
with its zone row, `ended_at` with its zone row, `day`, `duration`,
`device`, `note`, `emulated`, `mark_as_played`. `clean()` derives one
`TimingStatement` or raises the refusal onto the field that caused it.
`day_zone` is `calendar_day_zone(library)`, never a preference read
inside the command. Edit seeds the fields from the row's mode.

The creation surfaces all reach this form: the add form, add-for-game,
the Add Game and Add Purchase forms' "Submit & Create Session" buttons
(both redirect to add-for-game), Game detail's link, and the navbar's
resume, which clones.

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
`CreateSession` with `TimedTiming(now, day_zone=calendar)` on the game's
latest live ordinary run, device and emulated copied, note empty.
`returns.py` classifies every route that changes.

### The API, write half

`PATCH /{id}/device` dispatches `DescribeSession(StatedDevice(...))`.
`PATCH /{id}` takes a body with `extra="forbid"`: `timing` (one whole
statement, told apart by shape: Timed, Duration-only or Corrected) is a
correction; `note`, `device_id`, `emulated` are a description;
`playthrough_id` is a move. A named key is the act; an omitted key states
nothing. No POST: #1074 owns it.

## Edges

Game detail's session table, badge and metrics read `library_sessions`
narrowed to the game through the run. The per-session average is
restated faithfully: the legacy figure divided elapsed time by the rows
whose elapsed time was nonzero, so the new one averages
`ended_at - started_at` over rows where that span is nonzero. The
remove-game confirm page counts the same rows. The playthrough page's
range sum reads `game_playtime_between`; `add_playthrough`'s seeded start
and end days read the game's sessions through `library_sessions`, which
the legacy read did not scope.

The dormancy clock asks when the *run* was last played: the latest
`effective_day` of the run's own sessions, library stated on the
subquery, behind `playersession_run_day`, then the run's start day. No
zone is computed; `effective_day` is the day the library counts. The
narrowing is the one the Playthrough wave deferred here, and it has one
consequence: a run whose play #700 put in the bucket reads Never played
until the sessions are moved. On the 2026-09-12 dump the bucket holds one
row.

`audit_library_ownership` counts `PlayerSession` rows by library and drops
the hand-written `Session.device` loop; `AUDITED_PROJECTION_REFERENCES`
holds that key and `cross_library_violations` reports it. The library
page counts `library_sessions`.

## Sweep

A guard test walks `games/`, `common/` and `timetracker/` and fails on an
import of `Session` from `games.models` outside an allow list:
`models.py`, `removal.py`, `migrations/`, `backfill/`, `preflight/`,
`reads/playtime/legacy.py`, `reads/playtime_parity.py`,
`anonymize_sample`, `load_sample_data`. #772 empties the list. `Session`
stays in `REMOVABLE_MODELS` until then; nothing calls `remove()` on one.
The wave review's "purchase form's Submit & Create Session" is corrected
to both forms.

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
