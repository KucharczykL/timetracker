# Library calendar (#1047) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One zone per library, stated by a calendar event, changed automatically by the display-zone setting inside one retried transaction, with the moved days reported after.

**Architecture:** New `calendar` aggregate (event, command, projector, projection row). `dispatch` splits into `append_command` plus the transaction. The display-zone setting write and the event append run under one `retried_transaction`. Readers ask `calendar_day_zone(library)`; the dormancy clock loses its UTC default.

**Tech Stack:** Django 6, PostgreSQL 18, pydantic event payloads, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-issue-1047-library-calendar-design.md`

## Global Constraints

- Branch `feat/issue-1047-library-calendar`, member 2 of the wave stack on top of `feat/issue-700-session-conversion`. `gh stack submit --auto --remote origin`. Never merged alone.
- Every target through `make`. Gate is full `make check`; iterate with `make check-fast` and `make test ARGS=...`.
- Vocabulary: `make vale` over docs and comments. Event, command and column share one verb: `set_day_zone` / `day_zone_changed` / `day_zone`.
- Comments ≤ 7 words unless pleaded. Complete-word identifiers. Named compound types.
- No dispatch inside a transaction; `run_in_transaction` keeps refusing to nest. No `QuerySet.iterator()`.
- Tests that build state through commands carry `@pytest.mark.django_db(transaction=True)`; tests whose replay diff must be clean carry `@pytest.mark.untracked_games` (see `tests/test_playersession_conversion.py`).

---

### Task 1: `append_command` and `retried_transaction`

**Files:**
- Modify: `games/events/dispatch.py` (`dispatch`, lines 312-380)
- Modify: `games/events/retry.py` (after `run_in_transaction`)
- Test: `tests/test_command_dispatch.py`, `tests/test_event_retry.py`

**Interfaces:**
- Produces `append_command(command, *, actor, library, idempotency_key, correlation_id=None, source_metadata=None, wiring=DEFAULT_WIRING) -> CommandResult`. Runs `validate_idempotency_key`, `canonical_command_input`, `idempotent_append`, and maps the outcome to `CommandResult`. Does **not** call `authorize` and opens no transaction; raises `RuntimeError` when `transaction.get_connection(alias).in_atomic_block` is false (lock_stream requires a transaction, `games/events/append.py:249`).
- `dispatch` becomes: `authorize(actor, library)`; resolve `correlation_id` once; `run_in_transaction(partial(append_command, ..., correlation_id=resolved), policy=wiring.retry_policy)`.
- Produces `retried_transaction[**P, T](function: Callable[P, T], *, policy: RetryPolicy = DEFAULT_RETRY_POLICY) -> Callable[P, T]`: `functools.wraps`; on call hands `partial(function, *args, **kwargs)` to `run_in_transaction`. Usable bare (`@retried_transaction`) and with a policy.

**Tests:**
- `test_append_command_inside_a_held_transaction_appends`: `with transaction.atomic(): append_command(...)` appends and projects.
- `test_append_command_refuses_without_a_transaction`.
- `test_dispatch_still_refuses_nesting` (existing behavior; keep green).
- `test_retried_transaction_reruns_on_a_sequence_conflict`: mirror the existing `run_in_transaction` retry test with the decorator.
- `test_retried_transaction_refuses_nesting`.

**Gotchas:** `correlation_id` must resolve once per dispatch, outside the retried operation, as the comment at `dispatch.py:331` says. Keep `authorize` outside the transaction: the docstring's reason (no `FOR UPDATE` for a command that cannot commit) still holds.

- [ ] Write the five tests; run `make test ARGS="tests/test_command_dispatch.py tests/test_event_retry.py -x"`; expect the new ones to fail.
- [ ] Implement; run again; green.
- [ ] Commit `feat: expose append_command and a retried_transaction decorator`.

### Task 2: The calendar event, command, projection and projector

**Files:**
- Create: `games/events/calendar.py`
- Create: `games/commands/calendar.py`
- Create: `games/projectors/calendar.py`
- Modify: `games/models.py` (new `LibraryCalendar` after `PlayerSession`)
- Modify: `games/events/dispatch.py` (`CommandName.CALENDAR_SET_DAY_ZONE = "library.calendar.set_day_zone"`)
- Modify: `games/projectors/__init__.py` (import the module so it registers, as the others do)
- Create: `games/migrations/0005_library_calendar.py` via `make makemigrations ARGS="games --name library_calendar"` (schema only here; Task 5 adds the `RunPython`)
- Create: `games/reads/calendar.py`
- Test: `tests/test_calendar.py`

**Interfaces:**
- `games/events/calendar.py`: `CalendarDayZoneChangedPayload(TypedDict)` with `day_zone: ZoneText` under `@with_config(STRICT_SCHEMA)`; `CALENDAR_DAY_ZONE_CHANGED = EventSpec("library.calendar.day_zone_changed", aggregate_type="calendar", payload=...)`, registered on `DEFAULT_EVENT_TYPES`; builder `calendar_day_zone_changed(library_id: uuid.UUID, day_zone: ZoneName) -> NewEvent`.
- `games/models.py`: `class LibraryCalendar(ProjectionModel)` with `id = UUIDv7Field(primary_key=True, editable=False, default=NOT_PROVIDED, db_default=NOT_PROVIDED)` (the library's id) and `day_zone = CharField(max_length=64)`; `Meta.constraints = [UniqueConstraint(fields=["library"], name="games_librarycalendar_one_per_library")]`.
- `games/commands/calendar.py`: `@dataclass(frozen=True, slots=True) class SetCalendarDayZone(Command)` with `day_zone: str`, `command_name = CommandName.CALENDAR_SET_DAY_ZONE`. `build`: strip; `_check_zones(day_zone)` from `games/commands/playersession.py` (import the function; no cycle, reviewer-verified); read `LibraryCalendar.objects.filter(library=context.library).first()`; row stating the same zone → `Unchanged`; else `[calendar_day_zone_changed(context.library.pk, day_zone)]`.
- `games/projectors/calendar.py`: `class LibraryCalendars(Projector)`, `family_name = ProjectorFamily.CURRENT_STATE`, handles `CALENDAR_DAY_ZONE_CHANGED` with `_day_zone_changed`: `self.project(LibraryCalendar, event.aggregate_id, library_id=event.library_id, day_zone=zone)`, then `self.target.model(PlayerSession)._default_manager.filter(library_id=event.library_id, timing_mode__in=(TIMED, CORRECTED)).update(day_zone=zone)` — removed rows included, Duration-only excluded.
- `games/reads/calendar.py`: `calendar_day_zone(library: UserLibrary) -> ZoneInfo`: the row's zone, else the owner's effective `DISPLAY_TIME_ZONE` (`resolve_str_for_user`). `type ZoneName = str` reused from the command module.

**Tests (`tests/test_calendar.py`):**
- Command: unknown zone refused with a sentence; blank refused; same zone → `Unchanged`; first change on a library with no row appends; second different zone appends.
- Projector: row written; Timed and Corrected rows rewritten, removed ones too; Duration-only row untouched; `started_at_zone`/`ended_at_zone` untouched; `effective_day` regenerated (a 00:30 Prague start reads the previous day in UTC).
- Read: `calendar_day_zone` answers the row, and the owner's setting when no row.
- Replay: `rebuild_projections(mode=CHECK)` clean after a change (`untracked_games`, state built through `TrackGame`/`CreatePlaythrough`/`CreateSession` via `dispatch`).
- `games.checks`: `manage.py check` passes with the new projection (explicit pk, `library` column).

**Gotchas:** `project()` refuses a missing column: name `library_id` and `day_zone`, nothing else. `amend` refuses a missing row, which is why the row is written with `project`. The rebuild's shadow swap keys on `library_id` (`games/events/rebuild.py:280`), so the abstract `library` FK stays beside the pk.

- [ ] Tests first; `make test ARGS="tests/test_calendar.py -x"`; fail.
- [ ] Implement; `make makemigrations ARGS="games --name library_calendar"`; green; `make typecheck`.
- [ ] Commit `feat: state the zone a library counts days in`.

### Task 3: The delta read and the settings trigger

**Files:**
- Modify: `games/reads/calendar.py` (add `CalendarDelta`, `calendar_delta`, `calendar_sentence`)
- Modify: `timetracker/settings_commands.py`
- Modify: `games/api.py` (`update_user_setting` ~1019, `update_site_setting` ~1079, `SettingOut` ~931)
- Test: `tests/test_calendar.py`, `tests/test_settings_commands.py`, `tests/test_settings_api.py`

**Interfaces:**
- `class CalendarDelta(NamedTuple)`: `day_zone: str`, `sessions: int`, `day_moved: int`, `month_moved: int`, `year_moved: int`; `__add__` sums counts (site-level totals; zones equal).
- `calendar_delta(library, day_zone) -> CalendarDelta`: over `PlayerSession.objects.alive().filter(library=library, timing_mode__in=(TIMED, CORRECTED))`, annotate `new_day = Cast(Func(Value(day_zone), F("started_at"), function="timezone"), DateField())`; day: `exclude(new_day=F("effective_day"))`; month: exclude rows where both `ExtractYear` and `ExtractMonth` agree; year: `ExtractYear` differs. Four counts, one query each.
- `calendar_sentence(delta) -> str`: `Days now counted in UTC: 2,807 sessions, 124 moved to another day, 10 to another month, 5 to another year.`
- `SettingMutation` gains `calendar: CalendarDelta | None = None` (sixth field, defaulted).
- `settings_commands.py`:
  - Extract the body of `change_user_setting`'s atomic block into `_write_user_setting(user, key, value) -> SettingMutation` and `change_site_setting`'s into `_write_site_setting(key, value) -> SettingMutation` (pure database; `_request_display_currency_if_changed` stays inside them).
  - `change_user_setting(user, key, value)`: `DISPLAY_TIME_ZONE` → `_change_user_display_zone(user, value, idempotency_key=uuid.uuid4())`; every other key → `with transaction.atomic(): return _write_user_setting(...)`.
  - `@retried_transaction def _change_user_display_zone(user, value, *, idempotency_key) -> SettingMutation`: `mutation = _write_user_setting(...)`; if the effective zone changed: `authorize(user, user.library)` was called by the caller before the transaction; `delta = calendar_delta(library, new_zone)`; `append_command(SetCalendarDayZone(new_zone), actor=user, library=user.library, idempotency_key=f"calendar:set_day_zone:{idempotency_key}")`; return `mutation._replace(calendar=delta)`.
  - `change_site_setting(key, value, *, actor: User | None = None)`: `DISPLAY_TIME_ZONE` requires `actor` (else `ValueError("a calendar change records who changed it")`); `_change_site_display_zone(value, actor=actor, idempotency_keys={library.pk: uuid.uuid4() for inheriting libraries})` decorated; inheriting = libraries whose owner has no personal `display_time_zone`; per library in pk order: delta, `append_command(..., actor=actor)`, log one line; return totals.
  - Clear on either level goes through the same functions: `old_effective != new_effective` decides.
- `games/api.py`: `SettingOut.calendar: CalendarDeltaOut | None = None`; both endpoints pass `mutation.calendar`; when present, `messages.success(request, calendar_sentence(delta))` in place of the plain "saved" line. `update_site_setting` passes `actor=request.user`.

**Tests:**
- `calendar_delta` on seeded rows: one row moves day only, one moves month, one moves year, one moves nothing; Duration-only and removed rows not counted.
- `change_user_setting` to a new zone appends one event, rewrites rows, returns the delta; to the same zone appends nothing and `calendar is None`; a refused zone (`Not/AZone`) raises and leaves the preference unchanged and no event; a clear that falls back to a different site default appends; a clear that falls back to the same zone appends nothing.
- `change_site_setting` with two libraries, one owner holding a personal override: only the inheriting library gets an event, its actor is the operator; no `actor` → `ValueError`.
- No `NestedTransactionNotSupported` from either path (regression of the E008 rule).
- API: PATCH `/api/settings/user/DISPLAY_TIME_ZONE` answers `calendar` and the toast message; site endpoint likewise. Both `transaction=True`.

**Gotchas:** Generate idempotency keys before the decorated call; a retry must reuse them. `_write_user_setting` must stay re-runnable: it already is (reads, writes, `on_commit`). Existing tests that call `change_user_setting(user, "DISPLAY_TIME_ZONE", ...)` now append an event: `tests/test_date_time_rendering_paths.py:87`, `tests/test_playtime_parity.py:240`, `tests/test_playersession_conversion.py:474` need `transaction=True` if they lack it, and `untracked_games` where a replay diff is asserted.

- [ ] Tests first; run the three test files; fail.
- [ ] Implement; green; `make typecheck`.
- [ ] Commit `feat: change the calendar when the display zone changes`.

### Task 4: Readers and the session commands' refusal

**Files:**
- Modify: `games/reads/playthrough_activity.py` (`activity_clock`, remove `default_activity_clock`, add `UnscopedActivityRead`, `UnscopedActivityDay`, `UnscopedActivity`)
- Modify: `games/models.py` (`PlaythroughQuerySet.annotated_for_filtering`, ~1595-1630)
- Modify: `games/reads/playtime_parity.py` (`display_zone` → `calendar_day_zone`)
- Modify: `games/commands/playersession.py` (`CreateSession.build`, `CorrectSessionTiming.build`, reset-to-now)
- Test: `tests/test_playthrough_activity.py`, `tests/test_playthrough_filter.py`, `tests/test_playersession_command.py`, `tests/test_playtime_parity.py`

**Interfaces:**
- `activity_clock(library)`: zone from `calendar_day_zone(library)`.
- `annotated_for_filtering(clock=None)`: with a clock, unchanged. Without: `.alias(activity_day=UnscopedActivityDay(), activity=UnscopedActivity())`, both `Expression` subclasses whose `as_sql` raises `UnscopedActivityRead("An activity read was executed without a clock; state one.")`, mirroring `UnscopedSum` (`games/reads/playtime/source.py:25`). `_activity_clock` stays `None` for that queryset; a later call with a clock is refused as today.
- `CreateSession.build` and `CorrectSessionTiming.build`: after `_check_zones`, `if ZoneInfo(day_zone).key != calendar_day_zone(context.library).key: raise CommandRejected(f"... states {day_zone!r}; this library counts days in {calendar}.", sentence=f"This library counts days in {calendar}.")`. Reset-to-now uses `calendar_day_zone(context.library).key`.
- `games/preflight/session.py` needs no change: `report_zones` already reads `activity_clock(library).zone`.

**Tests:**
- Clock zone follows the calendar; changing the calendar moves `boundary_day` across midnight.
- `FilterQueryContext.for_validation()` compiles a `PlaythroughFilter` naming `activity`; executing a Playthrough read that names `activity` without a clock raises `UnscopedActivityRead`; one that names no alias executes.
- `CreateSession` with `day_zone="Asia/Tokyo"` on a UTC calendar is refused with the sentence; `CorrectSessionTiming` likewise; reset-to-now states the calendar's zone.
- Fix the existing tests that state `Europe/Prague`/`Asia/Tokyo` through a command on a UTC user (`grep -rn 'day_zone=' tests`, ten sites): set the owner's zone with `set_user_setting` first, or state `UTC`.
- `tests/test_playthrough_filter.py:507` (activity facet) must state a clock on its resolver.

**Gotchas:** `games/backfill/playersession.py::display_zone_name` keeps reading the setting: migration 0004 runs before the calendar table exists. Say so in a ≤7-word comment.

- [ ] Tests first; fail.
- [ ] Implement; `make check-fast` green.
- [ ] Commit `feat: read every day zone from the calendar`.

### Task 5: Migration 0005's seed and gate

**Files:**
- Modify: `games/migrations/0005_library_calendar.py` (append `RunPython(seed_calendars, noop, elidable=True)` after `CreateModel`)
- Create: `games/backfill/calendar.py`
- Test: `tests/test_calendar.py`

**Interfaces:**
- `games/backfill/calendar.py`: `seed_library(library, *, minted_at) -> bool` appends `calendar_day_zone_changed(library.pk, zone)` through `append_one` with `idempotency_key=f"backfill:1047:calendar:day_zone:{library.pk}"`, `actor=library.user`, `command_input={"day_zone": zone}`, `source_metadata={"backfill": {"issue": 1047}}`, `recorded_at=minted_at`; zone from `display_zone_name` in `games/backfill/playersession.py`. `calendar_mismatches(library) -> list[Mismatch[CalendarMismatchCode]]`: Timed/Corrected rows whose `day_zone` differs from the row; `rebuild_projections(mode=CHECK)` difference. `MismatchCode` enum with `ROW_ZONE`, `REPLAY`.
- Migration function mirrors `0004`: imports inside, `UserLibrary.objects.only("id", "user_id").order_by("pk")`, one `minted_at`, `emit_report` with `ReportPrefixes("LIBRARY_CALENDAR_RECONCILIATION_JSON=", "Library calendar reconciliation:")`, `failure_sentence(..., subject="Library calendar seed")`, `RuntimeError` on any mismatch.

**Tests:**
- Seed creates one row per library naming the owner's zone; a second run appends nothing.
- A row whose `day_zone` differs from the owner's zone refuses the migration by name.
- Tripwire: `MigrationExecutor(connection).migrate([("games", "0004_playersession_conversion")])` then `[("games", "0005_library_calendar")]` (pattern at `tests/test_playersession_conversion.py:1346`).

- [ ] Tests first; fail.
- [ ] Implement; green.
- [ ] Commit `feat: seed every library's calendar in migration 0005`.

### Task 6: Dump rehearsal, docs, stack

- [ ] `DUMP=/home/lukas/git/timetracker/.dumps/timetracker-2026-09-12.dump DUMP_DB=tim1047_restore make restore-dump`; `DATABASE_URL=... make migrate`; read the reconciliation line; `make audit-uuid-identity`.
- [ ] In `make shell` against it: `change_user_setting(owner, "DISPLAY_TIME_ZONE", "UTC")`, record the delta; change back to `Europe/Prague`; assert every `effective_day` equals a snapshot taken before; `rebuild_projections(mode=CHECK)` clean. Write the per-scope figures into the spec's "Proof" section. Drop the scratch database.
- [ ] `CLAUDE.md`: one bullet under PlayerSession for the calendar (event, automatic trigger, `calendar_day_zone`, clock reads it). `docs/superpowers/specs/2026-09-12-session-wave-design.md`: "Delivered." paragraph under #1047.
- [ ] Issue bodies: #1047, #1054, #748 — replace "must not restate silently" with the automatic decision and link the spec; #1054: the shape is one library-wide event, handled by the `LibraryCalendars` projector; #748: register as a Journal projector handling `library.calendar.day_zone_changed`.
- [ ] Full `make check` green; `gh stack submit --auto --remote origin`; PR body names the stack and the delta; Kaneo task.
- [ ] Commit `docs: record the library calendar as delivered (#1047)`.

## Self-review

- Spec coverage: decision (T2, T4), aggregate (T2), trigger contract (T2 projector), one transaction (T1, T3), delta (T3), readers (T4), migration (T5), proof (T6), issue corrections (T6). Covered.
- Type consistency: `CalendarDelta` defined in T3 and read by the API in T3; `calendar_day_zone` defined in T2 and read in T3, T4, T5; `append_command` defined in T1 and called in T3 and (through `append_one`, unchanged) T5.
