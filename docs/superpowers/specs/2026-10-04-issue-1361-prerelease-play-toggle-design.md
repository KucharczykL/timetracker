# A toggle that hides prerelease play

Issue [#1361](https://github.com/KucharczykL/timetracker/issues/1361).
Wave: [Access and Purchases](2026-09-28-access-and-purchases-wave-design.md),
section "Edition". Builds on
[#1354](2026-10-03-issue-1354-session-release-design.md).

## The fact

Prerelease play is a session or a historical playtime record whose
Release is of an Edition of kind `prerelease`
(`release__edition__kind=EditionKind.PRERELEASE`). A row that names no
Release is not prerelease play. Nothing infers a Release.

## The setting

`SHOW_PRERELEASE_PLAY` is a user-scoped registry setting
(`timetracker/settings_registry.py`). A user holds one library, so it is
the library's setting; `DORMANT_AFTER_DAYS` is the precedent of a
registry setting a library read resolves through `library.user`. The
registry gives the settings page, the live-save PATCH, the site default
and `settings.ini` export for free; `UserLibraryPreferences` has none of
them for a plain value. The value lives in `UserPreferences.extra_preferences`,
as `DORMANT_AFTER_DAYS` does: no column, no migration.

- Values are strings, `"show"` and `"hide"`, default `"show"`. Not a
  bool: Django renders an option value with `str()` (`"True"`), and
  `live-setting-fields.ts` writes back `String(resolved.value)`
  (`"true"`), so a bool SELECT goes blank after every save. Strings
  round-trip unchanged.
- Widget `SettingWidget.SELECT`, choices `("show", "Show")`,
  `("hide", "Hide")`, with the usual "Use site default (…)" option.
  No `cast`. The validator accepts the two words and refuses every
  other value. An env typo then fails every resolve, as an invalid
  `DORMANT_AFTER_DAYS` already does.
- Placed after "Dormant after". Label "Show prerelease play". Help
  text: "Sessions and records on a demo, beta or test count in
  statistics and show in lists."

## The reader

`games/reads/prerelease_play.py`:

A leaf module: it imports `games.models` and the resolver, never
`games.filters`, so `games/filters.py` imports it at module level.

- `PRERELEASE_PLAY: Q` — the predicate; valid on both models, which
  both name `release`. `outside_playthrough_dates`' `unless=`
  (`games/filters.py`) uses it too.
- `shows_prerelease_play(library) -> bool` — resolves the setting for
  `library.user` (one `auth_user` read on a library not reached through
  `request.user`, as `activity_clock` pays).
- `shown_play(library) -> Q` — `Q()` when shown, `~PRERELEASE_PLAY`
  when hidden.

Verified: `exclude(release__edition__kind=...)` compiles to
`NOT (kind = 'prerelease' AND kind IS NOT NULL)` over two LEFT JOINs, so
a row with no Release stays. `filter(~Q(...))` is the same on a
single-valued path.

## Two scopes

The incumbent keeps its meaning, every live row the library holds; its
docstring (and `game_sessions`') stops saying "counts".

| Sessions | Records | Meaning |
|---|---|---|
| `library_sessions` | `library_records` | every live row |
| `shown_sessions` | `shown_records` | filtered by `shown_play` |

Row paths:

- `readable_sessions` (every row): the edit page, the API's one-row
  GET and PATCH read-back. New `listed_sessions` (shown): the Sessions
  list and the API list.
- `readable_records` (every row): the record form. `listed_records`
  (shown, with the runs prefetch): the Historical list, Game detail,
  the API list. The API's one-row GET reads `readable_records` plus the
  same prefetch (`with_run_rows`).
- `game_sessions` stays every row: `game_session_days`, resume and the
  seed read it. Game detail reads `shown_sessions` narrowed to the game.
- `game_records` goes; its one caller, `game_historical_playtime`, reads
  `shown_records` narrowed to the game. So Game detail's header
  Playtime (`game_playtime`) hides both halves alike.

## Who reads the shown scope

A rule of thumb: a figure, a list a person reads, or a count printed
beside a link to such a list.

- `games/reads/playtime.py`: `_sessions` and `playtime_between_each`
  (navbar), so every playtime figure, the Games list's Playtime column
  and sort, and `played_years` (stats year picker). `game_tracked_between`
  alone reads every row: the seed is its only caller.
- `games/reads/historical_playtime.py` (every function, the per-game
  one included), and
  `records_within`/`records_in_scope`/`one_day_records`.
- `games/reads/session_figures.py`, `games/reads/play_figures.py`.
  `has_sessions` has no caller outside its test and goes.
- The filter context: `filter_query_context_for_library` and
  `filter_queryset_for_library` scope `PlayerSession` and
  `HistoricalPlaytime` to the shown scope. Through it: the Games list's
  session aggregates and its bulk scopes, the Devices list's session
  filter, the builder's count, every `stats_links` target, the API
  lists' subfilters, and `played_copies` (`total_year_games`).
- The Sessions list, the Historical list, Game detail's sessions and
  historical sections and overview metrics.
- Bulk scopes over those lists: `session_scope`, `record_scope`,
  `conversion_scope` (narrowed there, not in `convertible_sessions`).
- `organization_counts`.
- `reviewable_sessions`: its three readers (the Library page's waiting
  count and the list it links to, `conversion_scope`'s review, and
  `verify_reclassification_parity`'s population) all compare against
  shown figures. `conversion_scope` narrows `convertible_sessions` to
  the shown scope; `convertible_sessions` itself stays every row for
  `conversion_resolution`.
- `benchmark_reads` times `listed_sessions`.

## Who does not read it

- Resolves and edits: `session_resolution`, `record_resolution`,
  `conversion_resolution`, `_library_session`, the record form, the
  API's one-row GET and PATCH. A person picked or named the row.
- Acts and their previews: resume, `clone_session`, departure counts
  (`game_departures`, `device_departures`), the playthrough write's
  counts, `calendar_delta`.
- The new-run seed (`_seeded_run`): stored text must not vary with a
  view setting.
- The navbar's resume list and `session_count` flag, `played_releases`
  (filter options; a prerelease Release then matches no listed row).
- The run's numbering, completion, `activity`/`activity_day`,
  `outside_playthrough_dates`, the backlog. A run played only on a demo
  can read Playing while its sessions are hidden; activity is the run's
  fact, not a figure.

Reclassifying a hidden session copies its Release to the record, so the
record stays hidden and the total stays unchanged.

## Cost

With the setting off, each session or record subquery gains two LEFT
JOINs. With it on, `Q()` adds nothing. The bench resolves the setting
as any read does, so the hidden case is timed on a scratch restore
(`make restore-dump`): state "hide" for the user there through
`make shell`, then `make bench ARGS="--library <id> --gate"`. Every
read stays inside 20 ms or the spec says why.

## Tests

- `shown_play` both ways; no Release, full, prerelease; sessions and
  records.
- With the setting off: playtime figures, navbar, `played_years`, day
  figures, games played, `total_year_games`, session figures; the
  backlog unchanged.
- Lists: Sessions, Historical, Game detail; API list hidden, one-row
  GET found.
- `stats_links` parity with the setting off; list page count equals
  `filter_queryset_for_library` count.
- Bulk session scope excludes hidden rows; resolution finds a picked
  hidden row. Reclassification keeps a hidden total unchanged.
- Seed and resume ignore the setting.
- Registry: `EXPECTED_KEYS`/`USER_KEYS` (`test_settings_registry.py`),
  the admin page's `SITE_SETTING_KEYS` (`test_admin_settings_page.py`);
  validator refuses another word; the select round-trips in live save.
- `make verify-reclassification-parity` holds with the setting off.

## Follow-up issues to file

- The new-run seed reads a demo session's day as the run's start. A
  rule like #1358's (full editions only) would fit.
