# Read playtime from the Session projection

Date: 2026-09-14

Issue: [#697](https://github.com/KucharczykL/timetracker/issues/697), part
of the [session delivery wave](2026-09-12-session-wave-design.md), over the
[PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md).
Absorbs #698. The charter is
[the overhaul design](2026-08-09-timetracker-overhaul-design.md); the issue
body links a branch that no longer exists, and the file lives on `main`.

## What this issue delivers

Playtime becomes a read, never a stored total, and every playtime figure comes
from one place. Four things ship:

1. **One scope.** `library_sessions(library)` in
   `games/reads/player_sessions.py` is the only statement of which
   `PlayerSession` rows a library counts. Every projection reader states it,
   this issue's and #702's alike.
2. **One interface with two sources.** The package `games/reads/playtime/`
   exposes every per-Game, all-time, per-year, per-day-window, per-platform and
   per-month playtime figure. A `PlaytimeSource` protocol names those figures;
   `legacy.py` answers them from `Session`, `projection.py` from
   `PlayerSession`. The package's public functions answer from the legacy
   source until #702 changes one line.
3. **Every caller moves onto the interface now.** Game detail, the
   `playtime_hours` filter, the game list's column and both playtime sorts,
   the stats page and the navbar. None of them names a session table again.
4. **The retirement of `Game.playtime`**: the column, its `post_save`/
   `post_delete` signal in `games/signals.py`, and the `Session` entry of
   `_AFTER_STAMP` in `games/removal.py`.

A read-only parity command, `verify_playtime_parity`, compares the two sources
figure by figure through the protocol. #700's reconciliation and #704's gate
run it.

## Why the public functions answer from the legacy source

`PlayerSession` is empty everywhere until #700 converts the legacy rows.
Production holds no row, and neither does the anonymized sample fixture:
`games/fixtures/sample.yaml.gz` carries 2,807 `games.session` records, 4,244
`games.libraryevent` records, and not one `library.playersession.*` event.
Every screen still writes the legacy table, because #702 has not merged.

A caller pointed at the projection today prints zero for every game. So the
callers move onto the interface here, the interface answers from the legacy
source, and every figure a person sees is unchanged by construction. #702
changes which source the package delegates to; no caller changes with it.
The parity command compares exactly the two implementations a caller can be
handed, which is the strongest statement "equal before and after" can have.

## What the data says

A throwaway probe over the anonymized production fixture, loaded through
`load_sample_data`, checked the "before" side of the acceptance rule:

| check | result |
|---|---|
| `Sum(duration_total)` against `Sum(duration_calculated + duration_manual)` | equal on every one of 859 games |
| stored `Game.playtime` against the sum of the game's live sessions | **one game differs**: the column holds 16:04:54, the sessions sum to 7:04:54 |
| removed sessions | 2, both zero duration, so no removal explains the gap |
| `duration_manual IS NULL` | 0 rows |

The anonymizer shifts both instants of a session by the same offset and
leaves `duration_manual` and `playtime` alone, so the 9-hour gap is
production's. The stored total was already wrong for at least one game: its
detail page states 16 hours while the game list and the stats page state 7.
That is the defect a stored total invites, and the reason this issue keeps
none.

Two consequences. **"Equal before and after" is measured against the
query-time legacy sum**, not against the column; the column is the one figure
that changes, and the rehearsal records every game where it does. And the
per-year totals of the fixture are identical in UTC and Europe/Prague, so the
fixture cannot stand in for the zone delta the wave review measured on the
dump (124 sessions on another day, 10 in another month, 5 in another year).

## The scope

```python
def library_sessions(library: UserLibrary) -> PlayerSessionQuerySet
```

In `games/reads/player_sessions.py`, beside `playthrough_runs.py`, in the
shape of `library_runs()`: every condition stated, none inferred. It states
`library=library` and `playthrough__library=library`, because a projection row
may name another library's run — the drift `audit_library_ownership` reports.
It states all four removal marks: the session's own, its run's, its
`PlayerGame`'s, and the catalog game's. `alive()` holds the first three; the
fourth is stated here because #689 kept it out of `alive()`, so that
`blocking_referrer` keeps seeing the sessions of a removed game.

It does **not** narrow on the run's `kind`. `library_runs()` keeps only
ordinary runs because the pages number them; a session in the imported-history
bucket is still playtime, and #700 puts two production sessions there.

A second scope on another reader is the defect this function exists to
prevent: four marks restated per call site drift one site at a time. #702's
list, filter, API and audit readers state this function, and PlayerSession
gains no `for_library()` of its own.

## The interface

```python
type DayInterval = tuple[date, date]   # first and last day, both inclusive
# YearScope is imported from games.reads.playthrough_completions

class PlatformPlaytime(NamedTuple):
    platform_id: int | None     # None is the unspecified-platform bucket
    platform_name: str | None
    playtime: timedelta

class MonthPlaytime(NamedTuple):
    month: date                 # first day of the month
    playtime: timedelta

class PlaytimeSource(Protocol):
    def game_playtime(self, library: UserLibrary, game: Game) -> timedelta: ...
    def summed_by_game(
        self, library: UserLibrary | None, *, year: YearScope = None
    ) -> Combinable: ...
    def total_playtime(self, library: UserLibrary, year: YearScope = None) -> timedelta: ...
    def playtime_between(self, library: UserLibrary, days: DayInterval) -> timedelta: ...
    def playtime_by_platform(
        self, library: UserLibrary, year: YearScope = None
    ) -> list[PlatformPlaytime]: ...
    def playtime_by_month(self, library: UserLibrary, year: int) -> list[MonthPlaytime]: ...
    def played_years(self, library: UserLibrary) -> list[int]: ...

class FilteredPlaytimeSource(Protocol):
    def summed_by_game_matching(
        self, library: UserLibrary, session_filter: SessionFilter, *, year: YearScope = None
    ) -> Combinable: ...

class FullPlaytimeSource(PlaytimeSource, FilteredPlaytimeSource, Protocol): ...
```

`legacy.py` and `projection.py` implement these as module-level functions, and
`games/reads/playtime/__init__.py` binds `SOURCE: FullPlaytimeSource = legacy`.
mypy checks a module against a protocol member by member, `self` stripped, and
rejects a mismatch with a per-member diff — verified under this project's
configuration with mypy 1.20.2. No runtime signature test repeats that check.

**A capability a source lacks is absent, not refused.** `SessionFilter` speaks
the legacy table's fields until #702 restates it, so `projection.py` has no
`summed_by_game_matching` yet. It satisfies `PlaytimeSource` and not
`FullPlaytimeSource`, so `SOURCE = projection` is a mypy error on the flip line
until #702 writes the function. No stack member can flip the source while the
game list's session sub-filter would fail at runtime. The parity command is
typed against `PlaytimeSource` and compares both modules.

**The sum and the figure are two things.** A source answers the *sum*: NULL
for a game with no counted session, as `Sum` answers. The package states the
NULL policy once, over `SOURCE`:

| public function | answers | read by |
|---|---|---|
| `playtime_by_game(library, *, year)` | `Coalesce(sum, 0)`: never NULL | the `playtime_hours` filter, stats top games |
| `playtime_sort_key(library)` | the sum: NULL when unplayed | `GAME_SORTS["playtime"]` |
| `playtime_matching(library, session_filter)` | the sum: NULL when unplayed | the list column and `GAME_SORTS["filtered_playtime"]` |
| `game_playtime`, `total_playtime`, `playtime_between`, `playtime_by_platform`, `playtime_by_month` | never NULL | detail, stats, navbar |

`apply_sort` orders NULL last in both directions (`games/sorting.py:199-203`),
so an unplayed game sorts last whether ascending or descending, as today; a
`Coalesce` there would move it first on an ascending sort. The list column
renders `game.filtered_playtime or timedelta(0)` (`games/views/game.py:206`),
so it prints zero from the sum as it does today. `playtime_matching` with no
session filter reads `SOURCE.summed_by_game`, so the column with no filter is
the total, as an empty `Q` makes it today.

No queryset and no `Q` crosses the interface. The two tables name every
column differently — `timestamp_start` against `effective_day`, `game`
against `playthrough__player_game__game`, `duration_total` against
`effective_duration` — so a queryset handed out would carry its source's
vocabulary into the caller, which is the dependency this design removes.
`playtime_by_game` returns an expression correlated on the outer Game's `pk`;
its source is invisible to the `Game` queryset it annotates.

**Days.** The legacy source reads `timestamp_start__year`, `TruncMonth` and a
midnight range under the active zone, as the callers do today. The
projection source reads `effective_day`, frozen in `day_zone`. Both read a
year and a day, never an instant, because a Duration-only row has none.

**`session_filter`.** The legacy source compiles the filter with
`to_q(filter_query_context_for_library(library))`, as `list_games` does today.
A `SessionFilter` crosses the interface, never a compiled `Q`, which would
carry the legacy table's field names into the caller.

**`library=None`.** Only `summed_by_game` takes it, for the filter validation
context, which compiles a lookup and never executes it. Each source states
its own empty queryset for `None` — `Session.objects.none()`,
`PlayerSession.objects.none()` — rather than passing `None` on:
`Session.objects.for_library(None)` compiles `game__library IS NULL`, which is
the shared catalog's sessions, not nothing.

**Imports.** `GameQuerySet.annotated_for_filtering()` is called without
arguments by `with_filter_aliases` (`common/criteria.py:1360`), so it cannot
take the source as a parameter the way `PlaythroughQuerySet` takes its clock.
It imports `games.reads.playtime` inside the method: the package imports the
models, and a module-level import would cycle.

## The callers

| caller | today | through the interface |
|---|---|---|
| Game detail hours popover (`games/views/game.py:805`) | `game.playtime` | `game_playtime(library, game)` |
| `playtime_hours` filter (`games/filters.py:158`) | the column | alias `playtime` registered by `GameQuerySet.annotated_for_filtering(library)` as `playtime_by_game(library)` |
| game list column (`filtered_playtime`, `games/views/game.py:166-177`) | legacy subquery with the compiled session `Q` | annotation `playtime_matching(library, game_filter.session_filter)` |
| `GAME_SORTS["playtime"]` (`games/sorting.py:95`) | `Sum("sessions__duration_total")`, blind to the library and to the session's own mark | `SortSpec("total_playtime")`; `list_games` registers `total_playtime` with `.alias()` as `playtime_sort_key(library)` |
| stats total hours (`games/views/stats_data.py:310`) | `sessions.total_duration_unformatted()` | `total_playtime(library, year)` |
| stats top games (`stats_data.py:281`) | `Game.objects.filter(sessions__in=sessions)` summed | `Game.objects.visible_to(library)` annotated with `playtime_by_game(library, year=year)`, kept above zero |
| stats per platform (`stats_data.py:290`) | dict rows keyed `platform_name`, `platform_id`, `playtime` | `playtime_by_platform(library, year)` |
| stats per month (`stats_data.py:362`) | dict rows keyed `month`, `playtime` | `playtime_by_month(library, year)` |
| navbar today and last seven days (`games/views/general.py:65`) | midnight ranges | `playtime_between(library, days)`; no call without a library, the figures are zero |

`.alias()` rather than `.annotate()` for `playtime` and `total_playtime`:
`tracked_by()` runs under every game list, and an annotated subquery would be
selected whether or not a filter or sort reads it.

`Coalesce` is load-bearing on the filter. `duration_hours_to_q` maps `IS_NULL`
to `= 0` and `NOT_NULL` to its negation (`common/criteria.py:2872`), so today
`IS_NULL` and `EQUALS 0` both match every unplayed game. Without `Coalesce`
the sum is NULL there and both stop matching.

**Top games.** A game the legacy source does not count has a zero figure and
is dropped by the positive-figure condition, so the set is the one
`sessions__in=sessions` produces today, and the projection source extends it
to shared catalog games the library tracks. `tracked_by(library)` is not the
set: it drops a library game without a live `PlayerGame`.

**`StatsData` types.** `top_10_games_by_playtime`,
`total_playtime_per_platform` and `month_playtimes` are typed `Any` today,
which is what hides a change of row shape. They become
`QuerySet[Game]`, `list[PlatformPlaytime]` and `list[MonthPlaytime]`, and
`games/views/stats_content.py:372-425` reads attributes instead of dict keys.
`stats_links.sessions_for_platform(platform_id, …)` keeps its argument, and
the unspecified-platform bucket stays `platform_id=None`.

Tests that pass unchanged, as the in-suite evidence that no figure moved:
`tests/test_stats_links.py` (including the unspecified-platform bucket at
lines 193-212), the stats and navbar tests, and `tests/test_rendered_pages.py`.
One test is restated: `tests/test_sorting.py:228` sorts a bare
`Game.objects.all()` by `-playtime`, which has no `total_playtime` alias to
order by; it sorts `tracked_by(library)` with the alias registered.

**Statistics classification.** The charter requires every `StatsData` field to
carry a classification entry before its read path changes. This issue changes
four; their entries follow the charter's contribution policy:

| `StatsData` field | charter family | Sessions | Historical Playtime |
|---|---|---|---|
| `total_hours` | all-time totals; year totals | yes | all-time: yes, visibly estimated; year: only when the fact's precision lies wholly within the year |
| `top_10_games_by_playtime` | per-Game totals | yes | yes, visibly estimated |
| `total_playtime_per_platform` | platform playtime | yes, through the run's game | only with an explicit recorded Release or device dimension; never inferred |
| `month_playtimes` | month totals | yes | only when the fact's precision lies wholly within the month |

This issue ships the Sessions column only. The Historical Playtime column is
#710's to implement, as a further `PlaytimeSource` member, and each value that
includes it renders the charter's tracked-and-estimated breakdown. The stats
links stay Session filters, which reproduce a Session-only value.

Two playtime reads stay where they are, because their inputs are the legacy
vocabulary #702 restates: `GameFilter`'s scoped session aggregates
(`session_average`, `manual_playtime_hours`, `calculated_playtime_hours`) and
`_get_formatted_playtime_for_game_sessions_in_range` in
`games/views/playthrough.py`, which asks between two instants that a
Duration-only row does not have. #702 adds each to the interface when it
restates it, rather than composing a sum at the call site.

## Parity, stated per mode, zone and mark

Legacy `duration_total` is `COALESCE(end - start, 0) + duration_manual`
(`games/models.py:1208`). `effective_duration` is
`COALESCE(stated_duration, ended_at - started_at, 0)` (`games/models.py:1799`).

| legacy shape | mode after #700 | legacy figure | projection figure | equal |
|---|---|---|---|---|
| end set, manual 0 | Timed, finished | `end - start` | `ended_at - started_at` | yes |
| no end, manual > 0 | Duration-only | `manual` | `stated_duration` | yes |
| no end, manual 0 | Timed, running | 0 | 0 | yes |
| end set, manual > 0 | Corrected | `elapsed + manual` | `stated_duration` | yes, **only because** #700 states `stated_duration` as the legacy `duration_total` |
| `duration_manual IS NULL` | refused by #700 | NULL, skipped by `Sum` | — | no production row |

The Corrected row is the trap: legacy **adds** the manual value, the
projection **replaces** elapsed time. #689 owns that sentence; #700's test
asserts the arithmetic; this issue's parity command covers it with a synthetic
row, because production holds none and the fixture holds one.

A year or a day is read differently on the two sides. Legacy reads under
`timezone.override(DISPLAY_TIME_ZONE)`, which `TimezoneActivationMiddleware`
activates for every request outside `/api/settings/`
(`common/middleware.py:48-54`); `DISPLAY_TIME_ZONE` is a per-user setting
(`timetracker/settings_registry.py:358-372`), and `CreateSession` takes
`day_zone` from its caller and resolves none itself. The projection reads
`effective_day`, generated once in `day_zone`. The two agree exactly when #700
seeds `day_zone` — and a Duration-only row's `stated_day` — from the library's
display zone, and the viewer has not changed that zone since. A viewer who
changes it afterwards moves the legacy figures and not the projection's; that
delta belongs to the restatement issue, not to parity.

The marks differ in two populations, both empty in production:

| hidden by | legacy `for_library` | legacy `Game.playtime` | `library_sessions` |
|---|---|---|---|
| the session's own mark | yes | yes | yes |
| the catalog game's mark | yes | no | yes |
| the run's mark | — | — | yes; unreachable while #1011 refuses removing a run with live sessions |
| the `PlayerGame`'s mark | — | — | yes; production holds one removed `PlayerGame`, over no live game |

One legacy trait neither source copies: `Game.playtime` and
`GAME_SORTS["playtime"]` sum a catalog game's sessions across libraries, while
`Session.for_library` requires `game__library=library`; the sort reads a plain
reverse join, so it also counts a removed session. Production has one library,
and its two removed sessions are zero-duration and unended, so no figure or
rank moves there; the interface is library-scoped by construction, including
its legacy source.

## What is removed

- `Game.playtime` (`games/models.py:327`), by migration `0003`, which drops
  the column and re-adds a zero one on the way back. Dropping a column is
  not the trap that dropping a table was: `flush` still truncates every table
  it knows.
- `recalculate_playtime` and `update_game_playtime` in `games/signals.py`,
  and the import in `games/removal.py` with the `Session` entry of
  `_AFTER_STAMP`. Removing a session stamps its mark and nothing else. #772's
  body lists the same entry and loses that line.
- `tests/test_signals.py::RawFixtureLoadTest::test_playtime_from_the_fixture_survives_the_load`,
  `tests/test_removal.py::test_removing_a_session_drops_the_playtime`,
  `tests/test_api.py::test_session_patch_recalcs_playtime_via_signal`, and
  the `other_game_playtime` field of `LibraryState` in
  `tests/test_retention.py`. Each asserted the column; each is restated
  against the interface where the assertion still says something.
- The legacy sums in `list_games`, `stats_data` and `model_counts`, now inside
  `legacy.py`.
- The `Game.playtime` sentence in the `Duration` docstring of
  `common/components/domain.py`, and the comment on `games/api.py:694`.

## The fixture

The sample fixture holds `playtime` on all 859 `games.game` records, and
`load_sample_data` deserializes through Django's serializer, which refuses an
unknown field. The loader stays strict. The committed fixture loses the key
in the same commit as the column, by a one-time script: decompress, remove
the `playtime:` line of each `games.game` record at the text level, and
recompress with `compresslevel=9, mtime=0`, the settings `anonymize_sample`
writes with. The decompressed diff is exactly 859 removed lines, which is the
review evidence. The script is not committed; `anonymize_sample` emits the
model's fields, so a regeneration omits the key on its own.

## The parity command

`manage.py verify_playtime_parity`, behind `make verify-playtime-parity`,
copying `preflight_sessions`'s scope resolution (`--user`, `--library`,
`--all-libraries`, mutually exclusive) and its `--day-zone` override.
Read-only. Per library, under `timezone.override` of the library's display
zone, it asks both `PlaytimeSource`s:

- the all-time total;
- the total per year, over the union of both sources' `played_years`;
- the total per game, over the union of games either source reports;
- per platform and per month, for each of those years;
- today and the last seven days.

One line per figure, both values, and a final count of differing figures. A
differing figure exits non-zero. Before #700 every non-zero figure differs,
because the projection is empty; the command prints that plainly rather than
special-casing it.

## Deployment

Nothing here constrains deployment: every caller answers from the source it
read before, the projection source has no caller, and the parity command
reports.

## What this shape forecloses, and what undoing it costs

- **No stored per-game total.** Every read of a game's playtime pays a
  correlated subquery. #704's budget names the reads that grow and
  materialisation of the breaching cells as the remedy; that becomes a third
  `PlaytimeSource`, or a cache inside the projection one, and no caller
  changes. Undoing the decision outright is a projector in
  `ProjectorFamily.STATS`, which is #913's reopen condition.
- **The interface speaks figures, not querysets.** A new playtime figure is
  a protocol member and two implementations, never a sum at the call site. A
  caller that wants a figure the protocol lacks pays one method.
- **A day, not an instant.** Both sources key years and windows on a day. A
  read that wants "playtime between two instants" cannot be answered for a
  Duration-only row.
- **One source at a time.** `SOURCE` is a binding, not a setting: nothing
  serves half the figures from one table and half from the other, and no
  deployment can choose. The flip is one line in #702's stack, and mypy
  refuses it until the projection source holds every member.
- **The alias name `playtime` on `Game`.** A future column of that name would
  collide with the alias at query time.
- **`playtime` leaves the field-comparison operands of `Game`.**
  `comparable_columns` enumerates model columns, and a saved preset comparing
  `playtime` against another column stops parsing. Production holds three
  presets, all in playthrough mode.

## Rejected alternatives

- **A `PlaytimeTotal` projection.** Dropped by the wave review: a millisecond
  of benefit, unable to serve the sub-filtered aggregates, and the Journal
  materialises its own durations.
- **Readers that take a caller-scoped queryset.** Every caller would restate
  four marks and two library conditions, and the parity command would state a
  fifth copy. The rule drifts one call site at a time.
- **Moving the two column readers to a legacy sum and leaving the other
  callers alone.** #702 would then rewrite every caller once per surface, and
  the parity command would compare sums no caller runs.
- **Switching callers to the projection now.** They would print zero until
  #700.
- **Keeping the column until #702.** The acceptance rule says the column is
  gone, and the column already misstates one game.
- **`ignorenonexistent=True` in the loader.** It would accept any unknown key
  in any fixture from now on, hiding the next drift as well as this one.
- **Regenerating the fixture now.** No dump is present in `.dumps/`, and #772
  converts the fixture wholesale.
- **A runtime setting choosing the source.** A deployment that could serve
  the projection before #700 ran would print zero.
- **The projection source raising for a session filter it cannot compile.**
  The flip and that capability can land in separate stack members, and the
  game list would fail for any session sub-filter between them, caught only
  by a page test that happens to filter. An absent member fails `make
  typecheck` on the flip line instead.
- **One `Coalesce` for every read.** It would move unplayed games to the
  front of an ascending playtime sort; the sum and the figure stay separate.

## Verification

- `library_sessions` hides a session under each of the four marks, counts one
  under none of them, counts a session in the imported-history bucket, and
  never counts a row whose `library` differs from its run's.
- `legacy` satisfies `FullPlaytimeSource` and `projection` satisfies
  `PlaytimeSource` under `make typecheck`.
- For a legacy row of each mode and its projection twin, every figure of both
  sources is equal, including a Corrected twin stating the legacy total.
- The projection source reads `effective_day`: a Duration-only row lands on
  its written day, a Timed row on its start in `day_zone`, and neither moves
  under `timezone.override`.
- `playtime_by_game` is zero for an unplayed game, `playtime_sort_key` and
  `playtime_matching` are NULL for one, none counts another library's
  sessions at a shared game, and the legacy source honours a session filter.
- An unplayed game sorts last on both an ascending and a descending
  `playtime` and `filtered_playtime` sort.
- The `playtime_hours` filter answers as before for `GREATER_THAN`, `BETWEEN`,
  `EQUALS 0`, `IS_NULL` and `NOT_NULL` — `IS_NULL` and `EQUALS 0` match every
  unplayed game — from the game list and inside a nested `game_filter`; the
  alias is not selected when nothing reads it; with no library the legacy
  source compiles over `Session.objects.none()`.
- Every existing stats, stats-link, navbar and rendered-page test passes
  unchanged; `tests/test_sorting.py:228` alone is restated.
- Nothing names `Game.playtime`: no model field, no signal, no `_AFTER_STAMP`
  entry, no fixture key. `make loadsample` loads the committed fixture into an
  empty database with the loader strict.
- The parity command fails and names the year when a twin's day crosses a
  year boundary.
- `make verify-dump` migrates a restored copy, and the column-drift probe on
  that copy is recorded in the issue.
- The full `make check` gate passes.
