# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repo.

## Environment: drive everything through `make`

**Run `make <target>`. No `direnv exec .` wrap** (re-enters shell, re-runs
`uv sync` for ~70 packages), **and no raw `uv run` / `pnpm` / `pytest` around
Makefile.** No target exists? Add one or extend one — that is how this file grows.
Focused runs already covered:

```
make test ARGS="tests/test_filters.py -k relation -x"
make test-fast ARGS="tests/test_filters.py -k relation -x"
make test-e2e ARGS="-k widgets"
```

`ARGS` scopes every pytest target. A word holding `/` is a path and replaces
the directory `test-fast` and `test-e2e` pin; a bare flag and its value narrow
that directory as before.

**`make check` run anywhere — no Nix shell needed.** Makefile version-proofs both
interpreters, because getting either wrong produces failures that look like the
code's fault:

- **Python 3.14** — `ensure-python` finds or provisions it; `uv` pins interpreter.
- **Node ≥ 26** — `ts/date-time-presentation.ts` uses `Temporal`, arrives in Node
  26. On Node 24 it `undefined`, date/time formatters return `null`, ~11 vitest
  assertions fail. `PATH` already has 26 → used as-is; else pnpm fetches pinned
  version. `ensure-node-runtime` verifies what JS commands *actually* run on
  (`pnpm exec`, not `PATH`), so offline first run fails with reason instead of
  wall of null assertions. `ensure-node-deps` adds that *this project's* pinned
  deps installed into that runtime, not whatever global tsc `pnpm exec` would
  fall back to.

Every node invocation in Makefile goes through `pnpm`: single switch redirecting
whole JS toolchain onto right runtime. New node-using target must depend on
**`ensure-node-deps`**, which pulls runtime gate in behind it. One exception:
`npm` target itself, depends on `ensure-node-runtime` alone — gating target that
*creates* install behind check for that install would make it refuse to run in
the one state it repairs.

Real browser for e2e found from system; shell vendors none. `e2e/conftest.py`
discovers in order: `E2E_CHROME` (explicit path — missing file errors), then
`google-chrome`/`chromium`/`chrome` on `PATH`, then well-known Windows/macOS
install locations. So `make test-e2e` works on normal Chrome install, no
`playwright install`; set `E2E_CHROME` only for non-standard path.

**Verification gate:** before declaring done / pushing / opening PR, run full
`make check` (lint + format-check + mypy + ts-check + vitest + entire pytest
suite **including `e2e/`**) and confirm green. Never verify with hand-picked
subset of test files — that is how removed-widget e2e breakage reaches CI. `ARGS`
is
for iterating, never for the gate.

**While iterating, use `make check-fast`** — same aggregate minus `e2e/`, which is
83% of suite's serial wall time (~70s vs ~6.5 min). Explicitly **not** the gate:
only full `check` catches e2e breakage.

Suite runs parallel (pytest-xdist), because browser page loads dominate: 2507
tests take ~55s at 16 workers against ~370s serial. `PYTEST_WORKERS` defaults to
half the cores, capped at 16 — past that, contention starts flaking
timing-sensitive e2e tests. **CI takes one worker per vCPU**, capped same way,
because runner has nothing else on it: measured on `ubuntu-latest` (4 vCPU),
three runs each, serial 1491s against 696-797s at 4 workers. Halve it there if
flaky failure appears. Set `PYTEST_WORKERS=0` when debugging — parallel output
interleaves and `-x` stops only the worker that hit it.

**Several worktrees at once share one lock.** A suite takes every core it is
given, so two of them at once exhaust the machine rather than finishing
sooner. Wrap every pytest target — `check`, `check-fast`, `test`, `test-fast`,
`test-e2e`, and a focused `test ARGS=…` alike — in the lock the whole
checkout shares:

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check
```

Waiting is the point; never lower `PYTEST_WORKERS` to run beside another
worktree instead. One worktree alone needs no lock. `make dev` and `e2e/`
still exclude each other, whichever worktree each runs in.

### Python 3.14 is a hard prerequisite

`pyproject.toml` pins `requires-python = ">=3.14,<4"`, and code **depends on
3.14-only syntax** — most notably **PEP 758** unparenthesized `except A, B:`
("catch both types", not Python-2 `except A as B` binding). Pinned **ruff
0.16.x** infers target 3.14 from `requires-python` and *formats to* that bare
form, so source cannot parse on older interpreter without fighting formatter.

**`SyntaxError` in `except …` / "`make check` red on `main`" report almost always
means environment running wrong Python**, not that `main` broken. Check
`python --version` first — must be 3.14.x.

Outside Nix (Windows, restricted cloud boxes), either route works:

- **conda-forge**: `conda create -n timetracker python=3.14`, then install `uv`,
  Node 26 + `pnpm@10.33.0`, run same `make` targets from activated env.
- **uv-managed**: `uv python install 3.14` then `uv sync`. **Watch uv's own
  version**: uv bakes interpreter list into binary, so uv 0.8.x can only offer
  **3.14.0rc2** — passes `>= 3.14` check yet cannot run project (pydantic calls
  `typing._eval_type(..., prefer_fwd_module=True)`, kwarg added in 3.14 *final*,
  so `import ninja` dies with `AssertionError`). Get an `rc`? Upgrade uv
  (`pip install --upgrade uv` works where `uv self update` firewalled) and
  reinstall. pnpm must be on `PATH` separately; Node 26 itself need not be, since
  pnpm fetches it.

Either way e2e suite needs **system Chrome/Chromium** and, on Linux, the
`LD_LIBRARY_PATH` greenlet/`pytest-playwright` want (Nix shell sets this; bare
conda/uv env may need it exported). Non-Nix setups best-effort; **CI runs Nix
path**, so verify against `make check` before pushing when possible.

## Commands

| Task | Command |
|------|---------|
| Install dependencies | `make init` (Python via uv + npm packages, loads platform fixtures) |
| Development server | `make dev` (Django runserver + Tailwind watcher + `tsc --watch`) |
| Production-like dev | `make dev-prod` (Caddy + Gunicorn/Uvicorn + Django-Q cluster) |
| Run tests | `make test` (pytest; also runs vitest via its `test-ts` prereq) |
| Run a subset of tests | `make test ARGS="tests/test_filters.py -k relation -x"` (same for `make test-fast` / `make test-e2e`; a path in `ARGS` replaces the directory those two pin) |
| Run TypeScript tests | `make test-ts` (vitest over `ts/**/*.test.ts`) |
| Squash the migration history | `make squash-migrations ARGS="games 0006"` (Django's tool; old files stay until the deployment records the squash, see [Squashing](docs/migration-squash.md)) |
| Make / apply migrations | `make makemigrations` (`ARGS="games --name edition_name"` names the file) / `make migrate` (`ARGS="games 0001_squashed_0006_remove_session"` targets one) |
| CSS (Tailwind) | `make css` |
| Django shell | `make shell` |
| Create superuser | `make createsuperuser` |
| Dev login (superuser + prefill) | `make devlogin` (idempotent `admin`/`admin`; pairs with `DEV_LOGIN_PREFILL`) |
| Format / lint Python | `make format` / `make lint` / `make lint-fix` |
| Type check (mypy) | `make typecheck` |
| Lint prose (docs + code comments) | `make vale` (terminology; see [Vocabulary](docs/vocabulary.md)) |
| Codegen element types (TS props) | `make gen-element-types` |
| Codegen icon nodes | `make gen-icons` (after editing `games/templates/icons/*.html`) |
| Lint + format check + mypy + vale + ts-check + vitest + tests | `make check` (CI runs exactly this) |
| Same aggregate minus `e2e/`, for iterating | `make check-fast` (**not** the verification gate) |
| Run every test except `e2e/` | `make test-fast` |
| Sync uv.lock | `uv sync` (after editing pyproject.toml) |
| Verify the UUID identity map | `make audit-uuid-identity` (read-only; fails on any violation) |
| Render every read-only page as one user to files | `make render-pages ARGS="--user NAME --out DIR"` (read-only; run at two commits on one database and `diff -r`; lists whole, CSRF and version footer normalised) |
| Benchmark commands, replay, reads, and per-event cost | `make bench` (~2 min, seeds three events a game, dispatches 600 historical playtime records and removes the scratch library; `ARGS="--library <id> --gate"` times the six reads and checks replay on a real library, where the 20 ms read budget is judged; **not** in `make check`) |
| Replay every library and fail on a differing row | `make verify-replay-parity` (read-only; **not** in `make check`) |
| Convert one library's review population and judge every statistics figure | `make verify-reclassification-parity ARGS="--user NAME --confirm NAME"` (writes; scratch restore only; without `--confirm` it reads and prints; **not** in `make check`) |
| Destroy one user's library and every row in it | `make purge-library ARGS="--user NAME --confirm NAME"` (names the user twice on purpose) |
| Load platform fixtures / sample data | `make loadplatforms` / `make loadsample` |
| Regenerate sample data (anonymized prod) | `make anonymize-sample` (see Testing) |
| Dump games data | `make dumpgames` |
| Fetch a dump of the deployed database | `make fetch-dump` (→ `.dumps/`; needs `PROD_SSH_HOST`/`PROD_DB_CONTAINER` in `.env`) |
| Restore the newest dump into a scratch database | `make restore-dump` (prints its `DATABASE_URL`; `DUMP=<path>` picks another) |
| Restore, migrate, and drop it on success | `make verify-dump` (`KEEP=1` keeps the copy — the pre-deploy rehearsal) |
| Drop a scratch database a restore left | `make drop-dump` (`DUMP_DB=<name>` names it) |
| Compare the deployment's schema against a fresh `migrate` | `make verify-baseline` (`KEEP=1` keeps both; the gate on editing the baseline, and the rehearsal for a squash) |
| Split one change across dependent PRs | `gh stack init` / `add` / `submit`, then `gh stack merge` (atomic; see below) |

## Architecture

Django 6+ monolith (v1.7.0), single app (`games/`), tracks video game purchases,
play sessions, stats. HTMX for interactivity over pure-Python server-side
component system, plus Django Ninja REST API. **pydantic** declared runtime dep,
not just Ninja's transitive one: event vocabulary (`games/events/vocabulary.py`)
validates every event payload with `TypeAdapter`.

```
games/          — Django app: models, views, templates, forms, signals, tasks, API,
                  filters, writes/ (the command-backed write path for PlayerGame)
common/         — Shared utilities: time formatting, component system, criteria, layout, icons
timetracker/    — Django project: settings, URL root, ASGI/WSGI
tests/          — Pytest tests
e2e/            — Playwright browser tests (run via `make test-e2e`)
contrib/        — One-off scripts (exchange rate import)
docs/           — Additional documentation
```

### Models (in `games/models.py`)

- **Game** — catalog row: `name`, `platform` (FK), `year_released`, `sort_name`, `wikidata`. Holds no status and no mastered flag: both live on `PlayerGame`
- **Platform** — `name`, `group`, `icon` (slug, auto-generated from name)
- **Purchase** — ownership type, prices, currency conversion (`converted_price`, `price_per_game` is a `GeneratedField`), M2M to Game. `num_purchases` counts linked games. DLC/SeasonPass/BattlePass must have `related_game` (reverse accessor `game.addon_purchases`)
- **Device** — `name`, `type` (PC/Console/Handheld/Mobile/SBC/Unknown)
- **ExchangeRate** — cached FX rates per currency pair per year
- **FilterPreset** — saved filter config; `mode` (games/sessions/purchases/playthroughs/historical_playtime/devices/platforms), `find_filter`, `object_filter`, `ui_options` (all JSON). Follows Stash's SavedFilter pattern
- **PlayerGame** — first projection: one row per catalog game a library tracks, written only by `PlayerGames` projector. Its `removed_at` is projector's, stated by `RemovePlayerGame` command, separate from catalog row's. States library's `status` (six `PlayerGameStatus` words) and `mastered`, and since #678 D2 only place either stated or read. Both `UUIDv7Field` defaults opted out (pk is event's `aggregate_id`); `game` is `RESTRICT`, so projection row never collateral; #1017 registers it, so `audit_library_ownership` reports a `PlayerGame` naming another library's Game
- **Playthrough** — second projection: one row per run at a tracked game, written
  only by `Playthroughs` projector, which shares `CURRENT_STATE` family with
  `PlayerGames`. Game tracked since #679 gets one from moment library tracks it —
  `TrackGame` returns both creation events under one `correlation_id` — but rows
  #676 backfilled have none, and #684 owns supplying it. #684 reads only legacy
  `PlayEvent` rows, so a game holding none took an empty default run; #1038
  dates such a run, stating a `started` from the earlier of the library's own
  two records — earliest #676 status day and earliest live session day — and
  never a completion. Both passes ran once, out of migrations the history reset
  replaced: what they left behind is the events.
  Nothing reads #1038's `source_metadata`, which names the record and, for a
  status day, the status: three of the four admitted statuses end a run rather
  than open one, and a status day froze in the server zone while a session day
  reads in the viewer's, so those two populations are findable no other way.
  Both endpoints
  `TemporalValueField` with generated lower- and upper-bound columns beside each,
  plus marker naming the act (`start_recorded_at`, `completion_recorded_at`) and
  note of their own: null date is only unknown day, so marker's null is act that
  never happened, and `games/reads/playthrough_endpoints.py` reads pair as one
  `StatedEndpoint`. #681 states both with
  `StartPlaythrough`/`CompletePlaythrough` in `games/commands/playthrough.py`,
  which refuse second statement of stated endpoint and completion that certainly
  precedes start. #1010 adds three commands beside them:
  `CorrectPlaythroughStart`/`CorrectPlaythroughCompletion` state better day or
  note for endpoint already stated — refused where none is, ahead of value
  comparison, because unstated endpoint holds the very values a "played before"
  correction states — and neither moves marker, so replay keeps instant act was
  recorded; `DescribePlaythrough` states `name`, `note`, or both, `None` for fact
  it does not state, and every stated value stripped in `__post_init__`, ahead of
  fingerprint. Its `removed_at` is projector's, so absent from
  `REMOVABLE_MODELS`: #1011 states it with `RemovePlaythrough`, clears it with
  `RestorePlaythrough`. Both refuse lifecycle act under removed `PlayerGame`, and
  both answer `Unchanged` for state row already holds, ahead of that refusal.
  Removal alone refuses taking last live ordinary run off tracked game, then
  reads `BLOCKING_REFERRERS`, registry of projections that name a run — one
  entry since #694, `PlayerSession.playthrough`, so run with live sibling and
  live sessions refused with sentence naming move; last-run rule runs first
  because for sole run only its sentence names remedy that works (#1048).
  Row of *another* library naming run (drift `audit_library_ownership`
  reports) refused after own-library rows with `RowUnreadable`, which
  boundary answers as defect (#1062, #1057); session naming foreign run
  refused by every session command alike, through `_session_run`, same way.
  Registry constructed only through `BlockingReferrer.on`, which refuses field
  that is not key to a run and model whose manager states no `alive()`. Both
  that lookup and sibling count scoped on library. Blank `name` reads as
  `Playthrough N`, derived at read time by
  `games/reads/playthrough_numbering.py` and stored nowhere, which is why taking
  name away refused on row no number counted across — only taking one away, so
  save that repeats blank a row was born with still states its note. #1012
  renders the first screen: Game detail lists every live ordinary run, numbered
  by `games/reads/playthrough_numbering.py`, and its edit and remove routes name
  the run rather than the legacy row. `Played N times` beside it counts only the
  runs whose completion is stated, which is the number the legacy row meant; the
  section badge counts every row it renders. #1013 gives the list page same
  rows: it reads projection, and so do filter (`PlaythroughFilter` over twelve
  fields, each endpoint compared as interval its two bound columns state),
  sorts, quick facets and saved presets, whose stored `ended` a one-time pass
  rewrote to `completed`. `playthrough_count` counts runs whose completion is
  stated, which is number `Played N times` prints. Since #1026 no finish is
  read out of a legacy row either: the Purchase
  list's Finished column and the `finished` sort on Game and Purchase read the
  projection, through three readers `games/reads/playthrough_completions.py`
  adds beside its four — `ranked_completions` orders a row's completed runs so
  the latest finish leads, and `reported_completion` and
  `reported_completion_day` answer what that one run states, each a correlated
  subquery, which is why a `game_filter` cannot narrow which run a bundle
  reports. Both list views annotate `completed_day` and the sort names only
  that alias. #771 takes the table. #1015 keyed the
  API on the run and took the bridge that mapped a legacy row to it. #1014
  gives the stats page the same rows:
  every finish it counts, dates and orders by comes from
  `games/reads/playthrough_completions.py`, whose four readers state one
  `PlaythroughFilter` per scope — the same object `stats_links.py` puts in the
  link beside each number, so stat and link compile one predicate. A year reads
  the interval the two generated bound columns state, all-time reads the marker;
  a Purchase reports one row, dated `completed_lower` of its earliest run in a
  year (its latest all-time, which no table prints today), and a row that
  reports no day sorts last and prints `-`. #1033 gives the projection a
  queryset holding `annotated_for_filtering` alone — no `alive()` and no
  `for_library()`, so every read still states its own scope. It registers two
  aliases a clock counts rather than a column states: `activity_day`, the last
  day the game was played, falling back to the run's own start day, and
  `activity`, one of `Playing`, `Dormant` and `Never played`, null for a run
  whose completion is stated. The threshold is `DORMANT_AFTER_DAYS`, a live
  user setting. Second call naming same clock is no-op `with_filter_aliases`
  needs; one naming another clock refused, because `add_annotation` would
  swap one for other in silence. Pair costs three correlated subqueries a
  row, so read opts in: `runs_with_condition()` is `library_runs()` with
  viewer's clock, read by list page and by filter; Game detail asks
  `numbered_for(..., with_condition=True)`; every other reader carries no
  alias, and `playthrough_tabledata` refuses row that reaches it without one.
  `activity` is only quick facet that names annotation rather than own
  column, so its `FilterField` states own `choices` and own `nullable`.
  A condition is counted; a status is stated, and neither moves
  the other — see [Vocabulary](docs/vocabulary.md)
- **PlayerSession** — third projection: one row per session a library records,
  written only by `PlayerSessions` projector, in `CURRENT_STATE` family beside
  other two. Names run, non-null, and reaches game only through it, so session
  and its run can never name different games. `timing_mode` is stated word,
  never shape read off row, and CHECK per mode binds it to columns it admits:
  **Timed** states start, optional end while running, no override;
  **Duration-only** states written calendar day and duration, no instants;
  **Corrected** states both instants plus duration that *replaces* elapsed
  time — where legacy `duration_total` *added* `duration_manual`, which is why
  #700 converts such a row from legacy total rather than its manual part.
  Three words are the timing payload's discriminator values, pinned by test
  so payload and column cannot drift.
  Three stored generated columns: `effective_day` coalesces written day with
  start read in `day_zone`; `effective_duration` takes stated duration over
  elapsed, zero while running; `sort_instant` gives all three modes one total
  order, inventing midnight UTC for written day, and is `get_latest_by`.
  Three zones are three facts: `started_at_zone`/`ended_at_zone` say where
  clock stood, NULL where nobody stated; `day_zone` is zone *library* counts
  days in, seeded from viewer's display zone, NULL exactly on Duration-only row
  whose day no zone converts. No CHECK can reach blank or unknown `day_zone` —
  generated column computes before any constraint, so it answers `DataError`,
  which is why `CreateSession` refuses zone neither Python's nor PostgreSQL's
  tzdata knows. Database admits **superset** of what command admits, never
  reverse: CHECK stricter than command turns forgotten refusal into defect
  reached after stream head is locked, and `answered()`'s backstop can only
  say nothing was saved — never sentence naming what person should state
  instead.
  `alive()` reads run's mark and tracked game's, **not** catalog game's:
  `blocking_referrer` reads `alive()` to refuse removing run sessions name, and
  catalog mark there would hide them from that check. Read layer states that
  mark itself, as `library_runs()` does. No `for_library()`:
  `library_sessions()` states the read scope. Contract is
  [PlayerSession](docs/superpowers/specs/2026-09-13-issue-689-playersession-aggregate-design.md)

  Five commands state one. `CreateSession` states whole timing through
  `TimingPayload`; #691's `EndSession` states end of running Timed row and is
  partial act — own payload of `ended_at` and `ended_at_zone`, no `day_zone`,
  which row holds. Handler `amend`s those two columns and reads no mode, so
  command reads it, under dispatch's lock. Refuses end before start, row that is
  not Timed, and end on row that states one; identical restatement answers
  `Unchanged`, same instant in other zone refused. Event's day is not row's:
  `effective_time` reads end, `effective_day` reads start. Finish button and
  API call it through `end_session`. Contract is
  [End a running Timed session](docs/superpowers/specs/2026-09-13-issue-691-session-end-design.md)

  #692's three corrections, one fact each. `CorrectSessionTiming` restates
  whole `TimingStatement` — any mode to any — through module functions
  `CreateSession` shares; `Unchanged` compares `columns_for_timing` with row,
  event dated by `stated_day_of`. `DescribeSession`: `None` unstated, `StatedDevice(None)`
  no device, one event per differing fact. `MoveSessionToPlaythrough` may name
  run at another game. Reset-to-now is `TimedTiming(now)` with row's `day_zone`.
  Contract is
  [Correct a session](docs/superpowers/specs/2026-09-14-issue-692-session-corrections-design.md)

  #694's `RemoveSession`/`RestoreSession` state projector's `removed_at`
  through `library.playersession.removed`/`.restored`, both payloads empty.
  Both resolve with `library_session()`, plain-manager resolve `_live_session`
  builds on, answer `Unchanged` for state row holds ahead of every refusal,
  then refuse under removed `PlayerGame` and under removed run with own
  sentences (`_refuse_under_a_removed_parent`). Every other session command
  resolves through `_live_session`, so removed session refuses end,
  correction, description and move alike. Remove route calls first; restore
  has no route until #695. `RestoreSession` also refuses while a live record
  was made from the session (#1098). Contract is
  [Remove and restore a session](docs/superpowers/specs/2026-09-14-issue-694-session-removal-design.md)

  #1098's `ReclassifySessionAsHistoricalPlaytime` moves a written-down
  session's hours to a record in one command: `historicalplaytime.created`
  carrying the session as `reclassified_from`, then
  `playersession.reclassified`, which projects `removed_at` alone. Session and
  every record made from it: at most one live, kept by `RestoreSession`,
  `RestoreHistoricalPlaytime` and the reclassify itself.
  `UndoSessionReclassification` decides by marks alone -- never reclassified
  refused, already undone `Unchanged`, record restated since refused whole,
  removed parent refused -- then appends each event still to happen. Library
  page's Playtime section reviews Duration-only rows of
  `REVIEW_THRESHOLD_HOURS` or longer; since #713 its button states that
  review as a selection and the bulk runner acts on it (below). Contract is
  [Reclassify a session](docs/superpowers/specs/2026-09-18-issue-1098-session-reclassification-design.md)

  #700 converted every legacy `Session` row into these events, under the
  row's own id, with one imported-history bucket per game whose rows named
  no run. The pass ran once, out of a migration since squashed; what it left
  behind is the events. Contract is
  [Convert legacy Sessions](docs/superpowers/specs/2026-09-14-issue-700-session-conversion-design.md)

  #702's cutover: every session write is a command and every read the
  projection. `games/writes/playersession.py` is request-free half —
  `record_session`, `restate_session` (timing, then description of differing
  facts, then move, one `correlation_id`), `end_session`, `reset_session`
  (refuses row not running), `remove_session`, `clone_session` (game's latest
  live ordinary run, calendar zone) — each under `answered("session")`.
  `SessionForm` is plain `Form` that derives mode from what is filled: start
  alone Timed, day and duration Duration-only, start, end and duration
  Corrected; start beside duration with no end, and day beside instant, refused
  naming shapes that work. Run picked after game through
  `<playthrough-select>`, which refills from `GET /api/playthrough/?game=` and
  hides when game holds one run; session on game nothing tracks refused on
  run. Bucket takes no new session; `MoveSessionToPlaythrough` is only way in
  or out. Resume keyed on game (`games:resume_session`). Read surfaces:
  `library_sessions` and `game_sessions` in `games/reads/player_sessions.py`;
  `PlayerSessionFilter` (below); stats scope year on `effective_day`, order
  first and last play by `sort_instant`, superlatives read
  `effective_duration`; `stats_links` emit `day__between`; navbar resumes page
  `(sort_instant, id)`; dormancy clock asks when *run* was last played, so run
  whose play sits in bucket reads Never played until moved. Contract is
  [Switch Session writes and every read surface](docs/superpowers/specs/2026-09-15-issue-702-session-cutover-design.md)

  #1047's calendar: one zone per library, stated by
  `library.calendar.day_zone_changed` and projected to `LibraryCalendar`, a
  row keyed on the library. Its projector rewrites `day_zone` on every Timed
  and Corrected session, so `effective_day` regenerates; Duration-only rows
  and the endpoint zones do not move. Changing `DISPLAY_TIME_ZONE` is the act:
  `change_user_setting` and `change_site_setting` append
  `SetCalendarDayZone` beside the setting's row under one
  `retried_transaction`, and answer a `CalendarDelta`. Every reader asks
  `calendar_day_zone(library)`: the dormancy clock, the parity command, and
  `CreateSession`/`CorrectSessionTiming`, which refuse a day zone the
  calendar does not state. Without a clock the two condition aliases resolve
  and refuse to compile. Migration 0005 seeds one calendar per library; 0004's
  gates keep reading the setting, because the table comes after them. Member
  2 of the wave stack. Contract is
  [The zone a library counts days in](docs/superpowers/specs/2026-09-15-issue-1047-library-calendar-design.md)

  #704's gates, member 4 of the wave stack, lift the deployment constraint:
  `tests/test_projection_replay_gate.py` replays one command stream through
  every event type of the four families (a Corrected row included), empties
  and rebuilds five tables, repeats every command under its key; the
  two-dated-claimers conversion case reconciles clean. Stats page's session
  figures -- count, longest, most sessions, highest average -- are readers in
  `games/reads/session_figures.py`, grouped on the session table, ties broken
  by value, `sort_name`, game key, session key; the day figures -- distinct
  days, first and last play, `games_in_scope` -- are
  `games/reads/play_figures.py`, which counts a record on its day when it
  names exactly one (`when_lower == when_upper`) and orders by day,
  `sort_name`, game key and no row key, so a reclassification moves no
  answer; the two record scopes are `records_in_scope` and `one_day_records`
  in `games/reads/historical_playtime_records.py`. `games_in_scope` and the
  purchase count take a record wholly in scope, and
  `games_played`/`games_in_month` say the same through
  `GameFilter.historical_playtime_filter` and `Modifier.WITHIN` ("is wholly
  within", offered where a handler reads two bound columns; `BETWEEN` on one
  is overlap; the date widget carries it in a hidden input). An empty
  relation serializes as `{}` and means "has one". The game list narrows its
  Playtime column by both legs a filter states (`GameFilter.narrowing`).
  `compute_stats` calls them all, `make bench` times them.
  `readable_sessions()` is the row path list and API share; `games_for_list()`
  in `games/views/game.py` builds the game list's queryset so the bench times
  the served plan. Ran on the 2026-09-12 dump: replay clean, 0 of 4,649 figures
  differ, every read inside 20 ms; page diff attributed in the wave review.
  Contract is
  [Pass the Session replay, statistics and budget gates](docs/superpowers/specs/2026-09-15-issue-704-session-gates-design.md)
- **HistoricalPlaytime** — fourth projection: playtime a library states
  without sittings, written only by `HistoricalPlaytimes` projector.
  `library.historicalplaytime.created`/`.restated` carry one whole-statement
  payload, `created` with an optional `reclassified_from` beside it, and a
  restatement overwrites every column and stamps `restated_at`;
  `.removed`/`.restored` move `removed_at`. Names a `PlayerGame` and one or more of its runs through
  `HistoricalPlaytimeRun`, a join whose row ids the payload carries so a
  replay reproduces them; projector replaces the set whole. `when` is
  envelope's `effective_time`, null unknown, with generated
  `when_lower`/`when_upper` and index `(library, when_lower, id)`. Provenance
  CHECKed: `estimated`, `manually_entered`, `externally_measured`. `release`
  and `source` reserved, typed `None`. Database admits superset of what
  command admits. `alive()` reads own mark and `player_game`'s; join's derives
  from record's. Commands `Record`/`Restate`/`Remove`/`RestoreHistoricalPlaytime`
  take `HistoricalPlaytimeStatement`, normalised before fingerprint; devices
  resolve through `library_device` in `games/commands/scope.py`, the one
  resolver. Join's `playthrough` is second `BLOCKING_REFERRERS` entry.
  The Playtime page's Historical tab lists live records through
  `readable_records` and `HistoricalPlaytimeFilter`, mode
  `historical_playtime`. `games/reads/historical_playtime.py` sums the
  records by containment; `games/reads/playtime.py` adds them to sessions.
  Game detail and the Historical list record, restate, remove and restore
  one through `games/views/historical_playtime_entry.py`, whose form
  narrows provenance and device choices and leaves every other rule to the
  command
  ([entry](docs/superpowers/specs/2026-09-17-issue-706-historical-playtime-entry-design.md)).
  #1099's gates: `make verify-reclassification-parity` converts a library's
  review population and judges every `StatsData` key by the rule
  `games/stats_parity.py` states for its source group; `make bench`
  dispatches 600 records between the session command and the reads. Ran on
  the 2026-09-19 dump: replay clean, 0 of 199 changed figures unattributed,
  every read inside 20 ms
  ([gates](docs/superpowers/specs/2026-09-19-issue-1099-historical-playtime-gates-design.md)).
  Contract is
  [HistoricalPlaytime aggregate](docs/superpowers/specs/2026-09-17-issue-705-historical-playtime-aggregate-design.md);
  wave is
  [Historical Playtime](docs/superpowers/specs/2026-09-17-historical-playtime-wave-design.md)

**Nothing user removes is destroyed** (#944). Eight removable models — Game,
Edition, Release, Platform, Device, Session, Purchase, FilterPreset —
each carry nullable `removed_at`, listed in `REMOVABLE_MODELS` in
`games/removal.py`. `remove(instance)` stamps it, `restore(instance)` clears it,
both use `UPDATE` rather than `save()`, so stamp revalidates nothing and fires no
`post_save`. What signal would have done, `_AFTER_STAMP` does by hand: removed
Game recounts its purchases. Playtime is no stored total, so a removed Session
needs nothing beyond its mark.
`for_library()`/`visible_to()` call `.alive()`, so removed row leaves every list,
form, filter and API response at once; plain manager still sees it. Purchase live
while any of its games is, or while it names none. Edition and Release read
ancestors' marks as well as own, so removed Game hides both and restoring it
leaves separately removed child out (#966). Only whole-library purge destroys
anything.

**Removing offers Undo** (#695). Every remove view hands an `UndoOffer`, the
sentence and the restore route with the row's key, to `confirm_and_remove` or
`confirm_and_apply`, which queues one notice through `common/notices.py` after
the act succeeds; the toast's Undo form posts to that route. Nine POST-only restore routes, `restore_<entity>` and the reclassification's undo, share
`restore_and_return()`; a refusal is an error message on the page the person
stands on; the game route's error carries a "Try again" action, because its
stamp clears before its command. `<toast-stack>` appends the page as `?origin=`
when it takes the toast, so the restore lands back where Undo was pressed. A
foreign `extra_tags` value is logged and the toast shows without its action. A game's restore clears the
catalog stamp first and states `RestorePlayerGame` second, the removal's order
reversed. The preset picker gets its restore URL from the API's DELETE answer.
Contract is [Undo a removal](docs/superpowers/specs/2026-09-16-issue-695-undo-removal-design.md).

**One act on many rows is declared, not routed** (#713). An act is a value in
`games/bulk_actions.py`, and making the value declares it: `__post_init__`
refuses a name twice declared and an `inverse_aggregate` no `EventSpec` speaks
about. It states scope, resolve, run and inverse, beside the aggregate the
inverse takes -- one act may write two, as the reclassification writes a
created record beside the reclassified session, and an Undo reading both would
hand a record's key to a command that reads sessions. Each act's own half lives
beside it (`games/bulk_reclassification.py`), imported at the foot of the
table. `games/views/bulk.py` runs any of them: one route, two POSTs told apart
by a submission token that **is** the batch's correlation id, so a batch
spanning chunks stays one batch. A chunk is the rows one request acts on inside
`CHUNK_BUDGET` and is no transaction -- each row is its own dispatch, keyed
from the token and the row, so a token posted twice acts once. The tally rides
the progress form and counts four things apart: moved, already so, refused, and
gone since the confirmation. A defect ends the batch; the rows done stay done
and keep their Undo. The log names every row left alone, the ones a Stop or a
defect never reached included. `<continuing-batch>` posts the waypoint's form
on connect, so only Stop is pressed. The Undo reads the act's name out of the
batch's `source_metadata` and its rows out of `batch_aggregate_ids` in
`games/reads/events.py`, one of the two reads that answer from events rather
than a projection, and runs as a batch of its own. An act's scope is its own
base narrowed by the statement's filter, never the filter alone, and an
unreadable filter refuses rather than widening the act --
`apply_structured_filter` fails open, which a list may do and an act may not.
Contract is
[The bulk runner](docs/superpowers/specs/2026-09-20-issue-713-bulk-runner-design.md).

**Multi-game Purchase is *unsplittable* bundle** — one price, whole-purchase
refund (e.g. Humble Bundle). Independently-refundable multi-item orders (e.g.
Steam cart) modeled as **separate single-game purchases**: add-purchase form's
"separate price per game" mode (≥2 games) creates them, and row's **Split** action
breaks existing bundle into per-game purchases (price split evenly as starting
point). That why per-game refund/price need no through-model — each refundable
unit is its own Purchase.

**Unset platform/device is NULL**: `Game.platform`, `Purchase.platform`,
`PlayerSession.device` nullable, stay NULL when unset — no sentinel rows (#290
removed them). "Unspecified" (platform) and "No device" are render-layer labels
only. The two catalog FKs use `on_delete=SET_NULL` and the projection's
`RESTRICT`; exclude-mode set criteria match NULL rows
(`_SetCriterion._not_in_q`), and conditional `UniqueConstraint` keeps (name, year)
unique among platformless games.

**GeneratedField constraint**: `price_per_game` and the projection's
`effective_day`, `effective_duration` and `sort_instant` are computed by the
database and cannot be written from application code.

### Key patterns

**Layout system** (`common/layout.py`): views call `render_page(request, content,
title=...)` instead of Django's `render()`. Assembles full HTML document via
`Page()` — analogous to FastHTML's `fast_app()`: `<head>`, navbar, toast
container, FOUC-prevention script, and **JS includes** (calls
`collect_media(content)`, emits `<script>` tags automatically, so views do **not**
pass `scripts=` for component-owned JS). `scripts=` remains only for page-specific
glue not owned by reusable component (e.g. `add_*.js`). Navbar shows
today's/last-7-days playtime from `model_counts` context processor.

**Playtime reads** (`games/reads/playtime.py`, #697, #709): every playtime
figure sums two sources, sessions and historical playtime records, and comes
from this module: per Game, all-time, per year, per day window, per platform,
per month, and per game in a day window. Sessions come through
`library_sessions()` (`games/reads/player_sessions.py`: four removal marks,
library on session, run and tracked game). Records come through
`library_records()` (`games/reads/historical_playtime_records.py`: three
removal marks, library on record and tracked game), summed in
`games/reads/historical_playtime.py`, which no application module outside
`games/reads` imports. Both scopes refuse a missing library with
`UnscopedRead`. A record counts in a period only when `when_lower` and
`when_upper` both lie inside it (containment), so an unknown, open or
too-wide `when` counts in all-time alone. `DayInterval`
(`games/reads/days.py`) states every period, for both sources. Python figures
answer `PlaytimeBreakdown(tracked, historical)` with `.total`; the
playthrough page's range sum reads `game_tracked_between`, because a record
is not a sitting. Expressions stay one number: `playtime_by_game` is zero
when unplayed (the `playtime` alias `GameQuerySet.annotated_for_filtering`
registers, which refuses a second library, and the stats games card's total).
`playtime_sort_key` is NULL without playtime. A game whose only session is
running therefore sorts with the unplayed ones, because telling them apart
would run each subquery twice. `playtime_matching` sums matching sessions
only, and the game list's column header then says so. An annotation named
through `F()` is compiled again, so annotate a half beside a total only
where a page renders it: the stats games card reads its rows capped, then
takes the halves in a second query over those keys, and a test in
`tests/test_sorting.py` pins the ranking query at two scans per source
table. `STATS_SOURCES` in `games/views/stats_data.py`
classifies every `StatsData` key once, and a test holds it complete. Game
detail's averages and play range, `games/reads/session_figures.py` (longest
session, highest average) and `GameFilter`'s `session_playtime_hours` read
`effective_duration` outside the module. A sum with no library compiles for
validation and raises `UnscopedPlaytimeRead` if executed. No queryset and no
`Q` crosses the interface. A stored comparison naming `playtime` is refused
through `Game.RETIRED_COMPARISON_COLUMNS`.

**Component system** (`common/components/`): FastHTML-style **lazy node tree**.
Components are `Node` objects that render to HTML only when asked (`str(node)` /
`Page()`), so `Page()` can walk finished tree and collect each component's JS.
Submodules re-exported via `common/components/__init__.py`:

- **`core.py`** — node layer. `Node` (base; `__html__`/`__str__` return
  `SafeString`), `Element` (single class for *any* HTML element), `Safe`
  (pre-rendered/trusted HTML), `Fragment` (ordered children, no wrapper tag — use
  instead of `str(a)+str(b)`), `BaseComponent` (implement `render()`, declare
  `media`), `Media` (declarative JS deps with order-preserving dedup merge;
  `collect_media()` sums them over tree, `node.with_media(...)` attaches them).
  `_render_element()` is `@lru_cache`-memoized (4096). Attribute values always
  escaped. **Children: every string child escaped — `SafeText`/`mark_safe`
  included; only `Node` children (so `Safe`) render unescaped.** `randomid()`
  generates stable hash-based IDs.
- **`primitives.py`** — generic HTML. Plain leaf builders (`A`, `Button`, `Div`,
  `Span`, `Table`, `Form`, `H1`, …) **generated from whitelist** via
  `_html_element(tag)` factory — not hand-written per tag. Builders that add
  classes/behaviour written out:
  `ControlButton()` (one polymorphic button/link builder: `href=` renders `<a>`,
  `method="post"` renders `<form>`+submit, default `<button>`), `ButtonGroup()`,
  `Input()`, `Checkbox()`, `Radio()`, `Pill()`, `Icon()`, `Popover()`,
  `TruncatedText()`, `SearchField()`, `PageHeading()` (badge heading; plain `<h1>`
  is generated `H1`), `Modal()`, `ConfirmPage()` (full-page POST confirmation —
  canonical removal affordance; `details` is block slot beside `message`, which
  renders inside `<p>`), `StyledTable()`, `TableRow()`, `TableTd()`,
  `TableHeader()`, `ContentContainer()` (page-body width container,
  `w-full max-w-7xl self-center` — every list/detail/stats body sits in one),
  `paginated_table_content()`, `AddForm()`, `YearPicker()`,
  `CsrfInput()`/`ModuleScript()`/`StaticScript()`.
- **`domain.py`** — `GameLink()`, `GameStatus()`, `GameStatusSelector()`
  (`<drop-down behavior="select">` PATCH dropdown), `SessionDeviceSelector()` (ditto), `LinkedPurchase()`,
  `NameWithIcon()`, `PriceConverted()`, `PurchasePrice()`
- **`filters.py`** — filter widget layer: criterion-blob parse helpers
  (`_*_from_field`, `_choice_from_raw`, `parse_filter_dict`), widget builders
  (`StringFilter`, `NumberFilter`, `_bool_control`, the `FilterSelect` adapters),
  `field_widget`/`field_widget_templates` (single per-field dispatcher quick bar +
  nested builder render through), builder's comparison-row/chip/relation
  templates, and `FilterFieldPicker`
- **`quick_filter.py`** — `QuickFilterBar()`, `QUICK_FACETS`, `is_quick_editable`
  (see Filter system below)
- **`search_select.py`** — combobox family, all built on shared `_combobox_shell`
  and wired by `ts/elements/search-select.ts`: `SearchSelect()` (form combobox;
  with `host_dropdown=True`, set by `SearchSelectWidget` form adapter, lives in
  `<drop-down behavior="inline-combobox">` so its panel shares the one attachMenu
  open/close/position/dismiss engine, #348), `FilterSelect()` (include/exclude
  with pinned Any/None modifiers; `layout="panel"` is GitHub-label-picker
  personality for hosting inside dropdown dialog, #315), `ComboboxDropdown()`
  (generic "Label ▾" trigger + dialog), `PresetSelect()`/`LoadPresetDropdown()`
  (fetch-on-open preset picker, #297), `SearchSelectOption`
- **`date_range_picker.py`** — `DateRangePicker()`/`DateRangeField()`/
  `DateRangeCalendar()` custom element (wired by `ts/elements/date-range-picker.ts`)
- **`temporal_field.py`** — `TemporalField()`, native controls for date at any
  precision: shape select, then four number inputs and qualifier pair per
  endpoint. Whole value round-trips with scripting off; `<temporal-field>` (#965)
  only enhances it, hiding number inputs for segmented date, whole-decade box,
  open-start box, three-way end-shape radio group, and disclosure that closes as
  well as opens. Precision never picked from menu; derived from which parts
  person filled.
  Its posted names and their draft keys live in `timetracker/temporal.py`
  (`TemporalDraftData`, `temporal_input_name()`), which `TemporalWidget` in
  `games/forms.py` reads back. **Widget renders to text, so element's `Media`
  never bubbles** — hosting view threads
  `scripts=ModuleScript("dist/elements/temporal-field.js")`, as
  `purchase.py`/`playthrough.py` already do for date picker. Both hosting pages in
  `games/views/game.py`: Add Game and Edit Game, which host same Editions area and
  so draw one field per Release row. Grammar, wire and no-script contract in
  [Temporal](docs/temporal.md)

**Filter system** (`games/filters.py` + `common/criteria.py`): Stash-inspired
structured filtering.

- `common/criteria.py` defines typed criterion classes — `StringCriterion`,
  `IntCriterion`, `FloatCriterion`, `DateCriterion`, `BoolCriterion`,
  `MultiCriterion`, `ChoiceCriterion` — each with `modifier` (`Modifier` enum:
  EQUALS, NOT_EQUALS, INCLUDES, EXCLUDES, GREATER_THAN, LESS_THAN, BETWEEN,
  IS_NULL, …) and `to_q(field_name)` method. `OperatorFilter` provides AND/OR/NOT
  sub-filter composition and JSON serialization.
- `games/filters.py` defines `GameFilter`, `PlayerSessionFilter`,
  `PurchaseFilter` (all `@dataclass` subclasses of `OperatorFilter`) and
  `FindFilter` (sort/pagination). Filters serialize to/from JSON and travel in
  `?filter=` query parameter; `parse_game_filter()` / `parse_session_filter()`
  / `parse_purchase_filter()` deserialize. Key `from_json` does not know is
  refused as `FilterError`, never dropped. `FilterPreset` stores named
  configurations.
- `PlayerSessionFilter` speaks projection words: `timing_mode`, `is_running`
  (Timed with no end, through `bool_running_handler`), `day` (`effective_day`),
  `started`/`ended` (instants' dates, null on Duration-only row),
  `duration_hours` (`effective_duration`), `created_at`, `game` (through run),
  `device`, `emulated`, `note`, `search`, `game_filter`, `device_filter`. Mode
  key stays `sessions`; model key is `playersession` wherever one is spelled
  (`FILTER_MODE_MODELS`, builder URL, fixtures' `"model"`). `GameFilter`'s
  session aggregates cross `player_games__playthroughs__sessions`;
  `aggregate_to_q` always scopes subquery through `context.queryset_for`, so
  shared catalog game counts one library's rows. Comparison operand reaches
  game through `ProjectionModel.comparison_through`, declared to-one path walk
  follows as one named hop; `games.E011` refuses path that resolves nowhere.
- **Quick filter bar** (#197/#315, `common/components/quick_filter.py` +
  `ts/elements/quick-filter-bar.ts`) is **THE one filter tier** above every list
  view — GitHub-style row of ghost "Label ▾" dropdown facets directly above table.
  Flat FilterBar family gone (#315), as is free-text search UI (`search` criterion
  remains server-side inside `?filter=` JSON; no `?search_string=` fallback).
  - Facets are own-model leaf fields of any `QUICK_FACET_KINDS` kind
    (set/number/date/string/bool; flat aggregates like `session_count` count as
    number, and `activity` names a queryset alias rather than a column, so its
    `FilterField` states its own `choices` and `nullable`), rendered via
    `field_widget(layout="panel")` with `quick-` name prefix
    inside form whose Apply button (or Enter in inline input) serializes them and
    navigates. Clear is plain link to bare list URL. Set → panel `FilterSelect`;
    date → `DateRangePanel`; number/string/bool → stacked widget embedded as-is.
    Per-mode facet lists live in `QUICK_FACETS`.
  - Row anatomy: collapsible facets, then "⋯" priority-plus overflow menu
    (ResizeObserver-driven, continuous, no breakpoints — facets that don't fit are
    MOVED into it, same DOM nodes so widget state survives), then non-collapsible
    furniture — Load-preset picker (`preset_api_url`, load-only) and
    Apply | Clear [| Advanced filter…] ButtonGroup (`builder_url` gates third
    segment). `apply_url` overrides every derived list URL (#304
    synthetic-harness constraint).
  - Editable only when every top-level filter key is facet field with dict
    criterion (`is_quick_editable`); operator keys, `*_filter` relations,
    `field_comparisons`, `search`, or any non-facet leaf degrade it to read-only
    "Advanced filter active" pill with Edit-in-builder/Clear links. Bar's
    serializer emits only flat facet criteria, so its own output always
    round-trips back to editable. Anything facets can't express lives in nested
    builder, reached via "Advanced filter…" — every filterable mode has builder
    page, including devices/platforms (#336).

**Views** (`games/views/`): function-based, decorated with `@login_required`,
organized by domain entity:

- `session.py`, `game.py`, `purchase.py`, `playthrough.py`, `platform.py`,
  `device.py`, `settings.py`, `library.py` — CRUD per entity
- `general.py` — `stats()`, `stats_alltime()`, `index()`, `model_counts` and
  `global_current_year` context processors
- `returns.py` — route classification (`READ_ONLY` / `ORIGIN_AWARE` /
  `CONFIRMATION` / `IN_PLACE`, guarded for completeness against route table) plus
  `origin_from()` and `return_url()`, app-bound half of `common/returns.py`
- `removal.py` — `confirm_and_remove()`: GET renders `ConfirmPage`, POST stamps
  `removed_at`, queues the Undo notice and returns to origin. Every `remove_*`
  view is one call to it, over `confirm_and_apply()`, which same module keeps
  for any other confirmed POST; `restore_and_return()` is the POST-only undo
- `stats_data.py` — `compute_stats(year)` → `StatsData` TypedDict; pure computation
- `stats_content.py` — renders stats page content from a `StatsData`
- `stats_links.py` — pure filter-link builders for stats rows/counts (#65);
  parity-tested so each builder's queryset count equals stat it links from
- `auth.py` — custom `LoginView`, renders via `render_page()`

Filter presets have no classic views — they live on Ninja API; picker UI is shared
combobox dropdown (#297).

**Signals** (`games/signals.py`):
- `pre_save` on Purchase: snapshots old price/currency for change detection
- `post_save` on Purchase: sets `needs_price_update` if price/currency changed
- `m2m_changed` on Purchase.games: updates `num_purchases` from live games
  (`games.removal` recounts after stamp, which fires no signal)

**Background tasks**: django-q2 cluster (1 worker, 60s timeout, 120s retry, ORM
broker) runs `games.tasks.convert_prices()` on schedule, fetching rates from
`cdn.jsdelivr.net/npm/@fawazahmed0/currency-api` and converting purchase prices to
resolved site `DEFAULT_CURRENCY`.

**HTMX toast middleware** (`games/htmx_middleware.py`): converts Django messages
into one `HX-Trigger` header carrying every queued message as a `show-toast`
list; skipped if `HX-Redirect` present. `<toast-stack>` (`ts/elements/toast-stack.ts`, placed by `Page()`,
built by `ToastStack()` in `common/components/toast.py`) listens and renders;
`ts/toast.ts` keeps `window.toast` and `fetchWithHtmxTriggers`.

**REST API** (`games/api.py`): Django Ninja routers mounted at `/api/`:
- `GET /api/games/search` — search games for autocomplete
- `PATCH /api/games/{id}/status` — update game status
- `GET/POST /api/playthrough/`, `GET/PATCH/DELETE /api/playthrough/{id}` — the
  path id is the run's, and every body the projection's but the creation's,
  which names the catalog game it records a run at (#1015). The list
  takes `limit`/`offset`, `limit=0` unbounded, 100 by default. `started` and
  `completed` are canonical temporal values in both directions, refused with 422
  where the grammar does not know the spelling; each is answered beside its two
  bound columns and the marker naming the act. A key a body does not know is
  refused with 422 as well, so the old `ended` cannot pass unread. PATCH states
  the endpoints the request names and no others: a note-only PATCH records no
  act, and a named key is the act, dated or not
- `GET /api/session/`, `GET /{id}` — projection rows through
  `library_sessions`: `playthrough_id`, `game` through run, `timing_mode`,
  instants with zones, `stated_day`, `stated_duration_seconds`, `day`,
  `duration_seconds`
- `PATCH /api/session/{id}` — body `extra="forbid"`: `timing` (one whole
  statement told apart by shape) is a correction, `note`/`device_id`/`emulated`
  a description, `playthrough_id` a move; named key is the act, omitted key
  states nothing. Device outside library answers 404
- `POST /api/session/` — body `extra="forbid"`: `playthrough_id` and one whole
  `timing` statement, `device_id`, `note` and `emulated` beside them. Answers
  201 and the row. An `Idempotency-Key` header absorbs a repeat, measured at
  the route because the plain `ValueError` no answer maps would read as a
  defect. A run or device the library does not hold answers 404; every other
  rule keeps the command's sentence at 409
- `PATCH /api/session/{id}/device` — `DescribeSession(StatedDevice(...))`
- `GET /api/historical-playtime/`, `GET /{id}` — live records through
  `readable_records`: `filter`/`sort`/`page` as the session list, `when` as
  canonical text beside its two bounds, `playthrough_ids`. No write endpoint
- `GET /api/presets/` — user's presets for a mode, shaped as combobox options
  (`limit=0` = unbounded)
- `POST /api/presets/` — upsert on (user, mode, name); 201 create / 200 update
- `DELETE /api/presets/{id}` — remove owned preset (404 for non-owner). DELETE is
  transport's word; row stays and `removed_at` set; answers 200 with
  `restore_url`, where the picker's Undo toast posts

### Templates

Few HTML templates remain; bulk of UI is Python components.

- `games/templates/icons/<slug>.html` — SVG icon snippets; **source** for icon
  codegen (`manage.py gen_icons` → committed
  `common/components/icons_generated.py`), not loaded at runtime
- `games/templates/` — minimal partials for HTMX responses where needed

### Frontend stack

- **HTMX** — partial page updates
- **Alpine.js** (vendored) — three `x-mask` inputs in the session, purchase and
  settings forms, nothing else; the toasts and both domain selectors are custom elements
- **Flowbite** — its CSS theme and semantic tokens still in use; legacy
  `flowbite.min.js` bundle is vendored static asset only
- **Tailwind CSS** — compiled from `common/input.css` → `games/static/base.css`
- All third-party JS served locally from `games/static/js/` (no CDNs), so pages
  and browser tests work offline
- **Custom JS** authored in TypeScript under `ts/`, compiled to
  `games/static/js/dist/` (gitignored, build-only): `ts/toast.ts`
  (`window.toast` and `window.fetchWithHtmxTriggers`),
  `ts/elements/toast-stack.ts` (the toasts' store and DOM),
  `ts/elements/search-select.ts`, `ts/utils.ts` (shared helpers — `onSwap`,
  `toISOUTCString`, …)
- **Widget initialization**: widget JS registers with `onSwap(selector,
  initializeElement)` from `ts/utils.ts` — port of FastHTML's `proc_htmx` built on
  `htmx.onLoad`, running initializer once per matching element on page load and
  inside every htmx-swapped fragment. Never hand-roll
  `DOMContentLoaded`/`htmx:afterSwap` listeners with per-element guard flags.

### Interactive components: custom elements + TypeScript

New interactive components are **custom elements**, not inline JS in Python.
Component that needs behavior emits semantic tag via `custom_element("tag",
Props(...))` (light DOM, server-rendered inner markup built with htpy-style node
builders). Behavior lives in `ts/elements/<tag>.ts` (vanilla DOM,
`customElements.define`); native `connectedCallback` replaces `onSwap` (fires on
parse *and* htmx swap). Server↔client contract is one Python `TypedDict` per
element registered with `register_element(...)` in
`common/components/custom_elements.py`; `manage.py gen_element_types` codegens
`ts/generated/props.ts` so renaming a prop fails `tsc`.

- **Build:** `tsc` per-module compiles `ts/` → `games/static/js/dist/`. `make ts` =
  codegen + compile; `make ts-check` (in `make check`) = codegen + `tsc --noEmit -p
  tsconfig.check.json`; `make dev` runs `tsc --watch`. Docker builds CSS + TS in
  Node stage. Run `make ts` after editing any `.ts` so e2e/local serving sees fresh
  output. **Two tsconfigs:** emit `tsconfig.json` **excludes** `ts/**/*.test.ts`;
  `tsconfig.check.json` re-includes them and adds `@types/node` (scoped there, so
  browser emit stays node-free).
- **htpy-style markup:** builders take kwargs attributes and `[]` children —
  `Div(class_="x", hx_get="/y")[child1, child2]` (`class_`→`class`, `hx_get`→
  `hx-get`, `True`→`name="name"`, `False`/`None`→omitted). Runtime-built attribute
  collection goes in single positional slot: `Div(attrs_list, class_="x")`. Still
  walkable `Element` tree, so `Media` bubbles. `attributes=`/`children=` kwargs
  rejected (`TypeError`).
- **Do NOT** author HTML/JS as Python f-strings or add new inline Alpine `x-data`
  blobs. Alpine remains only for trivial pre-existing toggles.
- **Tables bubble cell media:** `StyledTable` returns node tree, so custom element
  in table cell has its `Media` collected automatically — no manual
  `collect_media` step.

### Deployment

Multi-stage Dockerfile (uv builder → Node assets stage → slim runtime), Caddy as
reverse proxy on port 8000, Gunicorn with UvicornWorker (ASGI), Supervisor managing
Caddy + Gunicorn + django-q2. `make dev-prod` mimics production locally. CI/CD via
`.github/workflows/build-docker.yml`: `test` job runs `make check`, then
`build-and-push` builds + pushes image on `main`.

**Package manager (pnpm), not npm.** Node 26 does not bundle Corepack: Nix shell
provides `pnpm_10`, while CI and Docker explicitly install `pnpm@10.33.0` declared
in `package.json`'s `packageManager` field. To bump pnpm, update that field and
every explicit install command — `scripts/bootstrap-cloud-env.sh` reads the field,
so needs no edit. pnpm disables dependency lifecycle scripts by default (opt in via
`onlyBuiltDependencies`, which lives in **`pnpm-workspace.yaml`** — pnpm 10 no
longer reads the `pnpm` field in `package.json` and warns on every invocation
when it finds one). One dependency on that list: `@vvago/vale` ships
platform binary its postinstall downloads. pnpm links `bin` before running that
script, so plain `pnpm install` leaves no `vale` — `make npm` and CI step both
follow it with `pnpm rebuild @vvago/vale`. Docker stages keep `--ignore-scripts`
and never fetch it; nothing there lints.

### Database

PostgreSQL 18 required. Development uses `make ensure-postgres` (normally via Nix
shell) to provision ignored loopback-only cluster; deployments supply
`DATABASE_URL`. Every connection must use UTF-8, `builtin` locale provider, and
`C.UTF-8` — full contract in [Database contract](docs/database.md). Migrations
live in `games/migrations/`. Note the `GeneratedField`s (above).

### Configuration

All configurable Django settings read through `config()` in
`timetracker/config.py`, never bare `os.environ` in `settings.py`. Full reference:
`docs/configuration.md`.

- **Resolution priority** (highest first): `NAME__FILE` (opt-in file secret) →
  `NAME` env var → `.env` → `settings.ini` (`[timetracker]` section) → in-code
  default. Missing + no default = `ImproperlyConfigured`.
- `config(name, *, default, cast, allow_file, required_in_prod)`: `cast` handles
  `bool`/`list`/`int`/`Path`/callable; `allow_file=True` honors `NAME__FILE`
  (contents `.strip()`-ed); `required_in_prod=True` hard-fails when missing and
  DEBUG off.
- `DEBUG` defaults `True`, turned off with `DEBUG=false`. `PROD` is **deprecated
  alias** kept for one release.
- `SECRET_KEY` required in production (insecure default only in DEBUG); supports
  `SECRET_KEY__FILE`.
- `APP_URL` accepts one full URL or comma-separated list; `ALLOWED_HOSTS` and
  `CSRF_TRUSTED_ORIGINS` derived from all of them. `ALLOWED_HOSTS` can be
  overridden directly (e.g. `ALLOWED_HOSTS=*` behind reverse proxy);
  `CSRF_TRUSTED_ORIGINS` always derived from `APP_URL`.
- `TIME_ZONE` reads `TZ` (defaults `Europe/Prague` in debug, `UTC` in prod).
- Django Admin, Debug Toolbar, and `django_extensions` are `DEBUG`-only.
- `DEV_LOGIN_PREFILL` (**dev/staging only**, off by default): `username:password`
  prefills login form and sends `X-Robots-Tag: noindex` — login still POSTs and
  authenticates (not a bypass). `make dev` sets `admin:admin`; `make devlogin`
  provisions that superuser. Parsed once (lru_cache) via `prefill_credentials()` in
  `games/dev_login.py`; malformed values fail safe. All three prefill branches
  flag-guarded, so production inert.
- **Container/entrypoint-only** flags (`CREATE_DEFAULT_SUPERUSER`, `STAGING`,
  `LOAD_SAMPLE_DATA`) live in `entrypoint.sh`, not Python config. Container runs
  as uid 1000 (no root, no PUID/PGID remap); mounted data dirs must be writable by
  that uid.

## Testing

Tests live in `tests/`; run with `make test`. Pytest settings in `pyproject.toml`
under `[tool.pytest.ini_options]`. Tests use PostgreSQL databases created by Django
from `DATABASE_URL`; pytest-xdist gives each worker own test database. Most files
named after what they cover; less obvious ones are `test_paths_return_200.py`
(smoke-tests every list/view URL), `test_rendered_pages.py` (HTML output of pages),
`test_signals.py` (game removal cascade, raw fixture loads, …), and
`test_anonymize_sample.py` (fixture anonymizer's rollback safety, determinism,
invariants, round-trip).

**`games/fixtures/sample.yaml.gz`** (the `make loadsample` seed) is **generated,
anonymized production snapshot** — gzip-compressed (~147 KB vs 1.6 MB raw), do not
hand-edit. Regenerate with `make anonymize-sample` against dedicated restored
production PostgreSQL database (then `make migrate`). It randomizes prices,
game↔purchase links, and dates (per-game offset), clears free-text notes/names, and
sanitizes audit timestamps — all inside rolled-back transaction, so source DB
untouched. Output **byte-deterministic** per `--seed`. Fixture keeps prod pks, so
load it into empty dev DB.

**UI assertion is not database assertion.** A custom element may update its own
DOM before the PATCH it sent through `fetchWithHtmxTriggers` lands, so the
rendered number can be ahead of the row. Before reading ORM in e2e test, wait on
something *server-rendered* — the htmx section that swaps in after write commits.

**TypeScript unit tests** (vitest) live beside their modules as `ts/**/*.test.ts`,
run with `make test-ts` and automatically by `make test`/`make check`. pnpm script
passes Node 26's `--no-experimental-webstorage` so jsdom, not Node's experimental
global, provides `localStorage`. vitest resolves NodeNext-style `.js` specifiers to
sibling `.ts`, so no compile step needed. Filter-tree serializer
(`ts/elements/filter-tree/`, #188) covered this way plus **cross-language
contract** (`tests/test_filter_tree_contract.py`): vitest writes
`fixtures.canonical.json` (serializer's output for shared `fixtures.json` cases,
gitignored) and pytest test asserts each is `to_q()`-equivalent to source filter,
so TS serializer cannot drift from Python backend. Contract `skipif`-skips when
artifact absent; `make check`/`make test` order `test-ts` first.

**Browser/E2E tests** live in `e2e/` and run with `make test-e2e`
(`pytest-playwright` driving real Chromium against pytest-django's `live_server`).
`e2e/conftest.py` sets `DJANGO_ALLOW_ASYNC_UNSAFE` and prefers system
Chrome/Chromium (see env section); otherwise `uv run playwright install
chromium` once. All JS vendored, so tests run fully offline. Bare `make test`
collects `e2e/` too, so it needs browser as well. Key files: `test_widgets_e2e.py`
(onSwap lifecycle, FilterSelect/RangeSlider/add-purchase),
`test_search_select_e2e.py` (single-select edge cases on synthetic page).

## Conventions for AI assistants

- **Never write to `GeneratedField`s** (`price_per_game`, `effective_day`,
  `effective_duration`, `sort_instant`).
- **One act, one verb** — event type, its command and its projection column share
  one verb, and column is `<act>_at`: nullable `DateTimeField` whose null is live
  state. See [Naming](docs/event-retention.md#naming).
- **Some words are refused** — projector *replays* events; row it leaves is
  *projection*. `make vale` enforces list over docs and code comments, and
  [Vocabulary](docs/vocabulary.md) says why each word refused and how to add one.
  Code out of scope, so identifier or flag name containing refused word is fine.
  Check grades by meaning: domain sense — word next to event, projector, or row it
  writes — is **error** with one named replacement, every other sense is
  **warning** that prints without failing build, because there right word depends
  on what joined. `fold` is the one exception: error at both levels, no literal
  sense survived.
- **Name variables with complete words** — unabbreviated identifiers in Python and
  TypeScript (`template` not `tpl`, `event` not `e`, `element` not `el`,
  `removeButton` not `removeBtn`, `option`/`value` not single letters in loops).
  Applies to new code and code you touch.
- **Name compound types explicitly** — if `tuple`/`dict`/other compound value
  passed between functions or appears in multiple signatures, give it name
  (`TypedDict`, `NamedTuple`, `type` alias) rather than repeating structural
  annotation, even for small types: `LabeledOption = tuple[str, str]`,
  `RangeValues(min, max)`.
- **Name primitive roles too** — when bare `str`/`int` stands for domain concept
  (id, key, token, field name), give it PEP 695 transparent alias (`type
  SortKey = str  # e.g. "sort_name"`) so signatures say *which* string goes where.
  Zero-cost, no wrapping. Use `NewType` only when you want checker to reject
  cross-assignment and will wrap every literal.
- **Use `render_page()` not `render()`** for all full-page HTTP responses (import
  from `common.layout`).
- **Build UI with Python components** from `common.components`, not raw HTML
  strings or Django templates. Build with `Div()`, `Span()`, `Element("tag", ...)`,
  etc.; use `Fragment(a, b, ...)` to group siblings (never `str(a)+str(b)`, which
  flattens tree and drops media); wrap trusted pre-rendered HTML in `Safe(html)`.
  Plain strings — `SafeText` included — auto-escaped as children.
- **Builders take htpy form only** — static attributes as kwargs, children via `[]`:
  `Builder(class_="x", hx_get="/y")[child1, child2]`. Dynamic attributes (runtime
  `list[(name, value)]` or `Mapping`) go through single positional slot. Generic
  and six styled builders (`Input`, `Checkbox`, `Radio`, `Pill`, `ControlButton`,
  `SearchField`) **do not accept `attributes=`/`children=`** — passing either
  raises `TypeError`. Semantic params keyword-only (`ControlButton(color="red")`,
  `Checkbox(name=…, checked=…)`, `Pill(label=…)`). Reach for named builder a tag
  has; if tag has none, add it to whitelist in `primitives.py` and export from
  `__init__.py`. Low-level `Element(tag,
  attributes, children)` keeps positional args — node machinery and codegen target,
  not call-site builder.
  Single-content-slot components support `[]` too (`Modal(id)[content]`,
  `DropdownActionItem(data_x="")[label]`); multi-slot or sibling-composing ones
  (`Popover`, `GameStatus`, `PageHeading`, `Icon`) keep own
  `children=`/`attributes=` params. Badge page heading is `PageHeading`, not `H1`.
  Node layer owns attribute merging (`normalize_attributes`): `class`/`style`
  accumulate, other attributes first-wins, so caller `class_` appends to builder's
  baked class and duplicate-attribute HTML impossible.
- **JS-bearing components declare `Media`, they don't rely on the view** — give
  component `class Media: js = (...)` or `return node.with_media(Media(js=...))`.
  `Page()` collects and emits it. Never re-add `scripts=ModuleScript(...)`
  threading in view for component that can declare own dependency.
- **Filter views** accept `?filter=<JSON>`; free-text search rides inside it as
  `search` criterion (no `?search_string=`). New criteria go in
  `games/filters.py`; new criterion *types* go in `common/criteria.py`.
- **Mutating links carry their origin** — build every link to mutating view with
  `action_url(name, *args, origin=request.get_full_path())`, never bare
  `reverse()`, and end every mutating view with `redirect(return_url(request,
  fallback=...))`. New route must be classified in `games/views/returns.py` or
  completeness guard fails. Origin travels only in `?origin=` query parameter —
  never session, never form body — and is validated against `READ_ONLY` route set,
  so it can never name mutating target. It is `origin` rather than `next` because
  Django's auth views own `next`.
- **No route mutates on GET** — removal answers GET with `ConfirmPage` and acts on
  POST at same URL (which is what lets `?origin=` ride through confirmation for
  free); write them as one `confirm_and_remove()` call. Anything else that changes
  state is POST-only.
- **Signals handle side-effects** — do not manually recalculate
  `Purchase.num_purchases`.
- **Playtime is read, never stored** — read playtime through
  `games.reads.playtime`, never `Sum("effective_duration")` or
  `Sum("duration")` at a new call site; a new figure is a function in that
  module, and it states which of the two sources it takes.
- **Buttons are `ControlButton`** — colors: `blue` (primary), `red` (destructive),
  `gray` (secondary), `green` (positive); variants: `filled` (default),
  `segmented` (ButtonGroup members), plus colorless single-look toggles that ignore
  `color` — `outline` (bordered dropdown toggle), `ghost` (transparent until hover;
  quick-facet triggers), `plain` (navbar nav-link). No size parameter and no
  `icon=` flag: buttons compact by default and upsize inside `@container` ancestor
  ≥28rem (form/modal/confirm containers declare `@container`); icon+text layout
  (`inline-flex items-center gap-2`) baked in. Never wrap button in `A(href=…)` —
  pass `href=` to `ControlButton`; `method="post"` renders no-JS `<form>` submit.
- **Read settings via `config()`** from `timetracker/config.py`, never bare
  `os.environ.get` in `settings.py`. Declare `cast`/`allow_file`/`required_in_prod`
  explicitly. Container-bootstrap flags belong in `entrypoint.sh`.
- **No styling-at-a-distance; elements carry their own classes**: `input.css` is
  document bootstrapping only (Tailwind import, theme, fonts, resets) — no
  form/component styling and no selectors that reach across DOM (`#id
  descendant`, `form input:disabled`) to style something a component owns.
  Element's appearance, **including state** (`disabled:`, `has-[:disabled]:`,
  `focus:`), comes from utility classes emitted by its own component.
- **Forms render via `FormFields`/`AddForm`, never `form.as_div()`**:
  `FormFields(form, *, extras=...)` (in `primitives.py`) renders label + control +
  errors + row layout; native controls get classes from `PrimitiveWidgetsMixin`
  (`games/forms.py`, which stamps `INPUT/SELECT/TEXTAREA_CLASS` incl. `disabled:`
  variants by widget type, skipping SearchSelect + checkbox). Every form on this
  path, including login. `extras` appends node into named field's row.
- **Disabled form controls share one look** via constants in `primitives.py` —
  `DISABLED_CONTROL_CLASS` (`disabled:opacity-50 disabled:cursor-not-allowed`, on
  control itself) and `DISABLED_WITHIN_CLASS` (the `has-[:disabled]:` wrapper
  variant, for composites like `SearchSelect`). Reuse these; don't hand-roll
  per-control disabled style.
- **Disabling composite widgets**: composite widget carries its `id` on wrapper
  `<div>`, which has no `disabled` state — setting `.disabled` on it is no-op.
  Disable inner control (for `SearchSelect`, the `[data-search-select-search]`
  input); wrapper fades itself via `DISABLED_WITHIN_CLASS`.
- **Platform icons** are SVG snippets in `games/templates/icons/<slug>.html`,
  compiled to `Element` node trees by `make gen-icons` (committed
  `common/components/icons_generated.py`; drift-guarded in `make check`). Add/edit
  snippet, run `make gen-icons`, reference by slug in `Platform.icon`. `Icon(name,
  attributes=...)` returns node: `class` merges onto svg, `title` becomes `<title>`
  child. Never edit `icons_generated.py` by hand.
- **Inline Alpine.js** remains only as three `x-mask` inputs
  (`games/forms.py`, `games/settings_forms.py`), each with the empty `x-data`
  scope the plugin needs. New
  behavior goes in custom element.
- **Nothing destroys a record** — call `remove()`/`restore()` from
  `games/removal.py`, never `instance.delete()`, and write confirmation as one
  `confirm_and_remove()` call. New removable model needs `removed_at`, place in
  `REMOVABLE_MODELS`, and builder in `tests/test_removable_models.py`, which fails
  until it has one. `delete` is Django's word, not library's: see
  [Vocabulary](docs/vocabulary.md), which `make vale` enforces.
- **A private catalog graph is stated, not patched row by row** — call
  `state_catalog_graph` from `games/catalog_writes.py`, never
  `Edition.objects.create()` and never per-row verb. It takes one Game's whole
  desired graph, refuses it against desired end state, and writes it in one
  transaction; row caller does not mention is left alone, and removal stated by
  mark on row. Each refusal carries caller's own key for row that caused it. One
  submit of Game form goes through `games/catalog_submit.py`, which writes Game's
  columns, its wikidata reference, graph and flat mirror in one transaction and
  answers every refusal onto field or row that stated it; PlayerGame command stays
  outside, because `run_in_transaction` refuses to nest. One thing that states
  graph from a person is `CatalogGraphForm` in `games/catalog_form.py`, hosted by
  Add Game and Edit Game alike. No standalone Edition or Release routes. Contract
  is [Catalog](docs/catalog.md).
- **A PlayerGame fact is stated as a command** — call `record_facts()` /
  `track_game()` from `games/writes/playergame.py`, or their request-shaped
  wrappers in `games/views/playergame_writes.py`. `Game` holds no status and no
  mastered column: command is only way to state either fact, and projection is
  only place to read it. In tests, `create_tracked_game()` from
  `tests/tracked_games.py` (and its `e2e/` twin) states the words on the row the
  autouse hook seeds.
- **A refused command becomes an answer** — wrap dispatch in `answered(subject)`
  from `games/writes/answers.py`. One clause per refusal; caller handles three
  shapes: `CommandRejected` or mapped `CommandConflict` becomes `CommandFailed`
  carrying sentence and status code, and so does `RowUnreadable`, at
  `DEFECT_STATUS` with `REFUSED_BY_AN_UNREADABLE_ROW` and ERROR record with
  traceback, because row is wrong, not statement (#1057);
  `CommandNotPermitted` becomes `Http404`, which
  view lets rise; unmapped conflict re-raised as itself rather than given sentence
  that might be wrong. New conflict type goes in `CONFLICT_ANSWERS`,
  `ANSWERED_DIRECTLY` or `NOT_ANSWERED`, or `tests/test_command_answers.py` fails,
  which walks every module whose exceptions reach boundary — `vocabulary`,
  `references`, `envelope` and `projection` beside dispatch's own. Never
  translate one at call site.
- **Database refusal is backstop, not path** — `answered()` catches every
  `django.db.Error`, logs constraint name and failing row, and answers
  `REFUSED_BY_DATABASE` with status 500, because transaction rolled back and
  nothing was recorded. It is there so forgotten refusal is sentence rather than
  traceback; it is not licence to let schema do refusing. Every rule person can
  act on belongs in command, which alone can say *what to state instead*.
- **A rejection carries two sentences** — `raise CommandRejected(message,
  sentence=…)`. Argument explains refusal to whoever reads log or traceback and may
  name id or issue; `sentence` is only thing person shown. Boundary never reads
  `str(error)`, so raise site that states no `sentence` is answered with `REFUSED`
  and logged, rather than leaking. Write one for every new raise site. One
  exception: refusal whose cause is row, not statement — state constraint
  forbids, foreign row ownership audit reports, zone tzdata lost — raises
  `RowUnreadable(message)` from `games/events/dispatch.py` — sibling of
  `CommandRejected`, not subclass, so no rule's handler and no
  `pytest.raises(CommandRejected)` takes it, and `Refusal.raises` refuses it
  at mypy — and writes no sentence; boundary owns it. Argument names row, its
  library, and for foreign reference the referring model, field and library
  keys, because boundary's record is the only log. Scope miss a site wraps
  into one is caught by own class (`PlaythroughNotHeld`), never bare
  `CommandRejected`, so later rule is not relabelled defect.
- **A command scopes a resolve by calling one** — resolve UUID command carries with
  `library_row` from `games/commands/scope.py`, never `Model.objects.get(...)`
  inside a `build`. It applies `library=context.library` itself, so no caller holds
  library to forget, and takes caller's two sentences as `Refusal`. Read wider than
  one library names read layer's verb — `Game.objects.visible_to(library)`, listed
  in `SCOPING_VERBS`. `tests/test_command_scope_guard.py` walks `games/commands/`
  and fails on bare manager `.get()`; it cannot see dropped `library=` in
  `filter()`, so read that counts or may answer `None` still states own scope.
- **No dispatch inside a transaction** — `run_in_transaction` opens transaction it
  retries and refuses to nest, so view that dispatches carries no
  `@transaction.atomic` and calls no helper that does. `games.E008` refuses
  `ATOMIC_REQUESTS`. Test that POSTs through such view needs
  `@pytest.mark.django_db(transaction=True)`.
- **Nothing opens a server-side cursor** — never `QuerySet.iterator()` or
  `aiterator()`. Cursor belongs to one connection, and pooler in transaction or
  statement pooling mode hands next `FETCH` a different one. Page with
  `keyset_pages()` from `common/keyset.py`, keyed on fields that lie in one index,
  last field unique. `tests/test_iterator_guard.py` walks syntax tree of `games/`,
  `common/`, `timetracker/`, `contrib/` and `scripts/` and fails on new call.
  `DISABLE_SERVER_SIDE_CURSORS` exists for reads inside Django that cannot be
  rewritten, not for ours.
- **One change too large for one PR becomes a stack, not a merge order** — use
  `gh stack` (`github/gh-stack`, installed). `gh stack init`/`add` build the
  chain, `submit` opens the PRs, `sync`/`rebase` keep it current, and
  **`gh stack merge` is atomic**: every member up to the one you pick lands in
  one all-or-nothing operation, so `main` never carries half a change. Pick the
  merge-commit method, as everywhere else. Never hand-roll a stack by setting
  one PR's base to another branch and retargeting later — a base branch deleted
  on merge auto-closes its child, and GitHub refuses to reopen a PR whose base
  is gone. An issue delivered this way says so in its own body; #702 is the
  worked example.

- **A projector writes through the event** — handlers call
  `self.project(Model, event, **columns)` / `self.amend(Model, event, **columns)`,
  or `self.library_rows(Model, event)` for a library-wide write; never a
  manager (`tests/test_projector_scope_guard.py` walks `games/projectors/`).
  The helpers read identity and library off the envelope:
  `project` writes `library_id` itself and refuses a handler naming it; `amend`
  filters on `(pk, library_id)` and raises `ProjectionRowMissing` for an absent
  or foreign row. Every projection is unique on `(id, library)` through
  `library_identity_constraint()` in its own `Meta` — the upsert's conflict
  target — and `games.E012` refuses one without it.

- **A reference out of a projection is registered** — foreign key from projection
  table into library-scoped model goes in `AUDITED_PROJECTION_REFERENCES` in
  `games/projections.py`, through `ProjectionReference.on`, or `games.E009` refuses
  it at `manage.py check`; `games.E010` refuses entry the walk no longer finds.
  Registry is what `audit_library_ownership` reads, and what swap's refusal
  sentence reads when rebuild stopped by SQLSTATE 23503. Nothing else audits such
  key: shadow table copies no foreign key, and rebuild's diff scoped to one
  library.