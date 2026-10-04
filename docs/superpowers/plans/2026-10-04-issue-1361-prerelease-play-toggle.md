# Plan: a toggle that hides prerelease play (#1361)

Spec: `docs/superpowers/specs/2026-10-04-issue-1361-prerelease-play-toggle-design.md`.
TDD per task. Iterate with `make test ARGS=…` under the shared lock.

## Task 1 — the setting

- `timetracker/settings_registry.py`: `PRERELEASE_PLAY_CHOICES`
  (`("show", "Show")`, `("hide", "Hide")`), `_validate_prerelease_play`,
  `SettingDefinition("SHOW_PRERELEASE_PLAY", …)` after
  `DORMANT_AFTER_DAYS`, default `"show"`, SELECT, no cast.
- Tests: `tests/test_settings_registry.py` (`EXPECTED_KEYS`,
  `USER_KEYS`, validator refuses `"true"`), `tests/test_admin_settings_page.py`
  `SITE_SETTING_KEYS` after `DORMANT_AFTER_DAYS`.
- Gotcha: check `tests/test_settings_commands.py` and any ini export
  test for a pinned list.

## Task 2 — the reader

- New leaf `games/reads/prerelease_play.py`: `PRERELEASE_PLAY`,
  `shows_prerelease_play`, `shown_play`. Imports only `games.models`,
  `timetracker.settings_resolver`.
- `games/filters.py` `outside_playthrough_dates` `unless=` reads
  `PRERELEASE_PLAY`.
- Tests `tests/test_prerelease_play.py`: `shown_play` default `Q()`;
  with `set_user_setting(user, "SHOW_PRERELEASE_PLAY", "hide")` hides a
  session on a prerelease Release, keeps no-Release and full-Release
  rows; same for records. Fixture helpers: find how #1354 tests build a
  held Release on a prerelease Edition (`tests/test_session_release*.py`).

## Task 3 — scopes and row paths

- `games/reads/player_sessions.py`: `shown_sessions`, `listed_sessions`;
  docstrings say "holds" not "counts".
- `games/reads/historical_playtime_records.py`: `shown_records`;
  `records_within` reads it; delete `game_records`; fix
  `readable_records` docstring.
- `games/reads/historical_playtime_page.py`: `with_run_rows(library,
  records)`; `listed_records` = shown + prefetch.
- `games/reads/historical_playtime.py`: every `library_records` →
  `shown_records`; `game_historical_playtime` reads shown narrowed.
- `games/reads/playtime.py`: `_sessions`, `playtime_between_each` read
  shown; `game_tracked_between` reads `library_sessions` (seed).
- `games/reads/session_figures.py`, `play_figures.py`: shown; delete
  `has_sessions` + its tests.
- Tests: figure readers with setting off (playtime total, navbar
  windows, `played_years`, day figures, games played, session figures).

## Task 4 — filter context and bulk scopes

- `games/filters.py` `filter_queryset_for_library` and
  `filter_query_context_for_library`: `PlayerSession` → `shown_sessions`,
  `HistoricalPlaytime` → `shown_records`.
- `games/bulk_sessions.py` `session_scope`, `games/bulk_removal.py`
  `record_scope`: shown base. Resolutions unchanged.
- `games/bulk_reclassification.py`: `reviewable_sessions` and
  `conversion_scope` narrow by `shown_play`; `convertible_sessions`
  unchanged.
- `games/reads/session_organization.py`: shown.
- Tests: stats_links parity with setting off (extend
  `tests/test_stats_links.py` parametrisation or add one case);
  `total_year_games` off; bulk scope excludes hidden, resolution finds a
  hidden key; backlog unchanged.

## Task 5 — views and API

- `games/views/session.py` list → `listed_sessions`; edit/resume
  unchanged.
- `games/views/game.py` `view_game`: `shown_sessions(library)` narrowed
  to the game for metrics and section.
- `games/api.py`: session list → `listed_sessions`; one-row GET/PATCH
  stay `readable_sessions`; record list `listed_records`, one-row GET
  `with_run_rows(library, readable_records(library))`.
- `games/events/benchmark_reads.py` → `listed_sessions`.
- Tests: Sessions list, Historical list, Game detail (header playtime,
  sections), API list hides / one-row finds, seed and resume ignore the
  setting, list count equals `filter_queryset_for_library` count.

## Task 6 — settings page

- Settings page renders the select; e2e or existing live-setting test
  that a string SELECT round-trips (find the test covering
  `DORMANT_AFTER_DAYS` live save and extend).

## Task 7 — bench and parity

- Scratch restore, set "hide", `make bench ARGS="--library <id> --gate"`;
  record numbers in the PR body.
- `make verify-reclassification-parity` on scratch with "hide".

## Then

Docs sweep (delete this plan, spec timeless, CLAUDE.md lines for
`shown_sessions`/`shown_records` and the setting), file follow-up issue
(seed reads demo day), full `make check`, draft PR, five-agent review.
