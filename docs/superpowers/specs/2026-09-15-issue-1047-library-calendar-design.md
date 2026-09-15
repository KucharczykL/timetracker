# The zone a library counts days in

Issue #1047. Member 2 of the wave stack (#700, #1047, #702, #704). Land it
only with `gh stack merge`. Do not merge it alone.

## The problem

A session is one instant. Its calendar day depends on the zone that reads the
instant. Today two readers answer that day in two ways:

- `PlayerSession.day_zone` is stored per row, and `effective_day` is a stored
  generated column over it. A later change of the display zone moves nothing.
- The dormancy clock resolves the viewer's `DISPLAY_TIME_ZONE` on every read
  and truncates the start instant in it. With no viewer it reads UTC.

They agree until the viewer changes zone. Then the same session sits on two
days. On the production dump of 2026-09-12, a move from Europe/Prague to UTC
puts 124 sessions on another day, 10 in another month and 5 in another year.

## The decision

A library counts days in one zone: its calendar's `day_zone`. The stored
`effective_day` is the answer. No reader computes a day from a zone of its own.

Changing `DISPLAY_TIME_ZONE` is the act that changes the calendar. It is
automatic. It restates every recorded day in the same transaction, and reports
what moved after the fact. A time zone setting that changes the clock but not
the calendar is half a setting.

## The calendar aggregate

- Aggregate `calendar`. The aggregate id is the library's id, one calendar per
  library.
- Event `library.calendar.day_zone_changed`, payload `{"day_zone": <IANA name>}`.
- Command `SetCalendarDayZone(day_zone)`, type `library.calendar.set_day_zone`.
  It refuses a zone that Python's tzdata or PostgreSQL's does not know, through
  `known_zone` in `games/commands/playersession.py`. It answers `Unchanged`
  when the calendar already states the zone.
- Projection `LibraryCalendar(library, day_zone)`, one row per library, in the
  `CURRENT_STATE` family. Its primary key is the aggregate id.

The projector handles `day_zone_changed` in two steps. It writes its own row.
Then it rewrites `day_zone` on every Timed and Corrected `PlayerSession` row of
the library, and the database regenerates `effective_day`. Duration-only rows
hold no zone and do not move. `started_at_zone` and `ended_at_zone` record
where the clock stood and do not move.

This is the first projector that writes rows the event does not name. #1054
left open whether the restatement is one event per session or one per library.
It is one per library, because the act is automatic: a per-session shape writes
thousands of events on every change of the setting.

## The trigger's contract

The contract is the event. A reader that must react to a calendar change is a
projector that handles `library.calendar.day_zone_changed`. #1054's
restatement is the `LibraryCalendar` projector's session rewrite. #748's
Journal rebuild is the Journal projector handling the same event. There is no
signal and no reactor registry. Replay reproduces every reaction in order.

## One transaction

`run_in_transaction` opens the transaction it retries and refuses to nest. The
rule stays. The settings write and the event append are two writes that must
land together, so they become one operation:

- `dispatch` exposes its inner operation as `append_command`, which builds
  and appends inside a transaction a caller already holds. It does not
  authorize. `dispatch` authorizes, validates the key, and runs
  `append_command` under `run_in_transaction`, as it does today.
- `retried_transaction` is a decorator over `run_in_transaction`. It states on
  the function that the function is re-runnable and touches only the database.
- `change_user_setting` and `change_site_setting` stop opening their own
  `transaction.atomic()` for `DISPLAY_TIME_ZONE`. The decorated function
  appends the command and writes the preference row.

Every path that changes the effective zone runs it. A personal set or clear
acts as the owner, authorized before the transaction as `dispatch` does. A
site-level change acts as the operator, for every library whose owner inherits
the site value, without `authorize`: a site setting is already an operator's
act, and the operator is the actor the event records, as the backfill's
`append_one` records its own. A change that leaves the effective zone equal
appends nothing. A refused zone refuses the setting, and nothing is saved.

The settings snapshot is not cleared on write; it expires after five seconds.
The calendar row is the truth. The request's activated zone lags it by at most
that window.

## The delta report

Before the rewrite, in the same transaction, one query per scope counts the
Timed and Corrected rows whose `timezone(new_zone, started_at)::date` differs
from `effective_day` in day, month and year. This is a new read over the
projection. The 124, 10 and 5 above came from the census, which compares the
process zone with the display zone over legacy rows in Python; the rehearsal
measures the projection figure and this document records it. The decorated settings function
answers them as `CalendarDelta`. The settings API returns them beside the
resolved setting, and the toast reads:

```text
Days now counted in UTC: 2,807 sessions, 124 moved to another day, 10 to
another month, 5 to another year.
```

A site-level change logs one line per library and returns the totals.

## The readers

- `calendar_day_zone(library)` in `games/reads/` is the one read of the zone.
- `activity_clock(library)` takes its zone from it. `default_activity_clock()`
  goes. Without a clock, `annotated_for_filtering` states the two aliases
  through `.alias()` with expressions that compile and refuse to execute, as
  `UnscopedSum` does for playtime: filter validation compiles, and a read that
  names `activity` without a clock raises `UnscopedActivityRead`. Tests that
  read the alias state a clock. The clock's move onto `effective_day` and the
  game-to-run narrowing stay with #702's surface 9.
- The preflight census's secondary column reads it.
- `CreateSession` and `CorrectSessionTiming` refuse a `day_zone` that differs
  from the calendar, with a sentence naming the calendar's zone. Reset-to-now
  uses the calendar's zone. The statement keeps its `day_zone` because the
  event carries it and the conversion states it. A statement with no
  `day_zone` at all, filled by the command, was considered and set aside: it
  changes every caller and test of #691 and #692 for a guard the refusal gives.
- No live write path dispatches `CreateSession` today. #702's surfaces seed
  `day_zone` from `calendar_day_zone(library)`, never from the request's
  activated zone, and the refusal above is what makes a wrong seed loud. A
  second reader of a library records in the owner's calendar.
- Until #702, the legacy reads group in the request's activated zone. That is
  the owner's display zone, which the trigger keeps equal to the calendar.

## Migration

Migration `0005` appends one `day_zone_changed` per library through
`append_one`, which projects it, naming the owner's effective
`DISPLAY_TIME_ZONE`, the zone #700 seeded every row with. Its gate refuses
when any Timed or Corrected row's `day_zone` differs from its library's
calendar, and when `rebuild_projections(mode=CHECK)` reports a difference. It
reads real models, as `0004` does, and names its columns with `.only()` for
the same reason.

## Proof

- A change from Europe/Prague to UTC and back reproduces every `effective_day`
  exactly, and the replay check is clean. One test on a seeded library. One
  rehearsal on the 2026-09-12 dump, with the per-scope delta written here.
- Determinism holds within one tzdata generation: `timezone(text, timestamptz)`
  is immutable to PostgreSQL but reads its tzdata.
- Full `make check`.

## Baked-in assumption

Every row's `day_zone` equals its library's calendar. A later per-session
restatement would still fit the column, but the equality gate would become a
per-row rule.

## Out of scope

The clock's read move (#702), the Journal projector (#748), screens beyond the
existing setting control, and the fixture's session rows (#772).
