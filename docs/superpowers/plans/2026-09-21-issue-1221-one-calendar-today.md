# One calendar today implementation plan

**Goal:** Move the navbar's day window and the three year readers onto the
library's calendar, pay for the calendar read by loading the user and the
library in one query, and guard the rule with a syntax-tree walk.

**Spec:** `docs/superpowers/specs/2026-09-21-issue-1221-one-calendar-today-design.md`
— read it first; every "why" lives there.

**Tech stack:** Django 6 / Python 3.14 / PostgreSQL 18, pytest + pytest-xdist.

## Global constraints

- Run everything through `make`. Never `direnv exec .`, never bare `uv run` / `pytest`.
- Iterate with `make check-fast`; the gate before "done" is the full `make check`, e2e included.
- Wrap every pytest target in the shared lock: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make …`.
- Name variables with complete words. Comments explain intent, never history.
- Tests first, red before green, per task.

---

### Task 1: One query for the user and its library

**Files:**
- Create: `timetracker/auth_backends.py`
- Modify: `timetracker/settings.py` (add `AUTHENTICATION_BACKENDS`)
- Test: `tests/test_auth_backend.py`

**Interfaces produced:**
- `LibraryModelBackend(ModelBackend)` — `get_user(user_id)` returns the user
  with its library already loaded, `None` for an unknown id, and honours
  `user_can_authenticate`.

**Tests (red first):**

| test | asserts |
|---|---|
| `test_a_request_loads_its_user_and_library_together` | a logged-in `client.get("/tracker/library")` runs no `games_userlibrary` statement of its own; assert over `CaptureQueriesContext` SQL |
| `test_the_backend_answers_none_for_an_unknown_id` | `get_user(uuid-that-is-not-a-user)` is `None` |
| `test_a_user_with_no_library_still_loads` | delete the library row, `get_user(pk)` returns the user; accessing `.library` raises as before |

**Gotchas:**
- `client.force_login` uses `settings.AUTHENTICATION_BACKENDS[0]`; naming one
  backend keeps that unambiguous.
- `select_related` on a reverse one-to-one is valid and measured: one
  statement for both rows.
- The library page budget stays 23 in this task — a query freed here is spent
  in Task 2. Do not touch the budget number.

---

### Task 2: The navbar counts the library's days

**Files:**
- Modify: `games/views/general.py` (`model_counts`)
- Test: `tests/test_navbar_calendar_day.py`
- Modify: `tests/test_library_page_isolation.py` (docstring only)

**Interfaces produced:** none; `model_counts` keeps its signature.

**Shape:** compute the day inside the `library is not None` branch, from
`calendar_today(library)`. The anonymous branch needs no day: both figures
are `PlaytimeBreakdown(0, 0)`.

**Tests (red first):**

| test | asserts |
|---|---|
| `test_the_navbar_counts_today_on_the_library_calendar` | library on a zone provably on another date now; a session written for the calendar's today is counted in the navbar's "today" figure |
| `test_the_navbar_last_seven_days_ends_on_the_calendar_day` | the same library; a session on the calendar's today falls inside the seven-day window |
| `test_the_library_page_evaluates_each_summary_count_once` (existing) | still 23 |

**Gotchas:**
- Pick the zone the way `tests/test_playthrough_companion_status.py` does —
  `Pacific/Kiritimati` / `Pacific/Niue`, whichever is on another date right
  now — so the test fails at every hour rather than two a night.
- State the zone through `SetCalendarDayZone`, not by writing the row.
- Changing the calendar rewrites `day_zone` on every Timed and Corrected row,
  so state the zone before writing the session, or assert on the value the
  projector left.
- A test that posts through a view needs `@pytest.mark.django_db(transaction=True)`.

---

### Task 3: The year readers

**Files:**
- Modify: `games/views/general.py` (`index`, `global_current_year`)
- Modify: `common/time.py` (`available_stats_year_range`)
- Modify: `games/views/stats_data.py` (its one caller)
- Test: `tests/test_year_readers.py`

**Interfaces produced:**
- `available_stats_year_range(today: date) -> range` — the day is stated, not
  read from a clock. `common/` keeps no `games` import.

**Tests (red first):**

| test | asserts |
|---|---|
| `test_the_year_range_starts_at_the_day_it_is_given` | `available_stats_year_range(date(2031, 2, 3))` starts at 2031 and ends after 2000 |
| `test_the_landing_redirect_names_the_library_year` | `DEFAULT_LANDING_PAGE` set to the stats page; the redirect's year is `calendar_today(library).year` |
| `test_the_global_year_is_the_library_year` | the context processor's value equals `calendar_today(library).year` for a viewer with a library |
| `test_the_global_year_falls_back_without_a_library` | an anonymous request still publishes a year |

**Gotchas:**
- `compute_stats` already holds the library; pass `calendar_today(library)`
  where it calls the range.
- `stats_dropdown_year_range` is a `StatsData` key with a parity entry in
  `games/stats_parity.py` — the value's shape must not change.

---

### Task 4: The guard

**Files:**
- Create: `tests/test_calendar_clock_guard.py`

**Interfaces produced:** none.

**Shape:** walk the syntax tree of every `.py` under `games/`, `common/`,
`timetracker/`, `contrib/` and `scripts/`, skipping `migrations/`. Fail on a
`Call` whose function name is `localdate`, `today` on `date`/`datetime`, or
an attribute access resolving to either. Allowlist by `(path, function name)`:
`games/reads/calendar.py` and `global_current_year`.

**Tests:**

| test | asserts |
|---|---|
| `test_no_module_reads_a_day_from_the_process_clock` | the walk finds nothing outside the allowlist |
| `test_the_walk_sees_a_planted_call` | a synthetic source string with `localdate()` is reported, so a guard that silently matches nothing fails |
| `test_every_allowlist_entry_is_still_used` | an entry the walk no longer needs fails, the way `games.E010` refuses a stale registration |

**Gotchas:**
- `games/checks.py` names `timezone.localdate` inside a `frozenset` without
  calling it; the walk looks at `Call` nodes, so it must not report that.
- `games/events/benchmark_workload.py` builds a day from an explicit zone —
  `datetime.now(tz=…).date()` — which is not one of the refused names.

---

### Task 5: The gate

- `make format`, `make format-check`, `make lint`, `make typecheck`, `make vale`.
- Full `make check` under the shared lock; confirm the exit code from the log
  rather than grepping for a success line.
- Commit, push, open the PR naming `Closes #1221`, then check CI.
