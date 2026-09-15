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

- `dispatch` exposes its inner operation as `append_command`, which does
  everything `dispatch` does except open the transaction. `dispatch` is
  `append_command` under `run_in_transaction`.
- `retried_transaction` is a decorator over `run_in_transaction`. It states on
  the function that the function is re-runnable and touches only the database.
- `change_user_setting` and `change_site_setting` stop opening their own
  `transaction.atomic()` for `DISPLAY_TIME_ZONE`. The decorated function
  appends the command and writes the preference row.

Every path that changes the effective zone runs it: a personal set, a personal
clear that falls back to a different site default, and a site-level change for
every library whose owner inherits the site value. A change that leaves the
effective zone equal appends nothing. A refused zone refuses the setting, and
nothing is saved.

## The delta report

Before the rewrite, in the same transaction, one query per scope counts the
Timed and Corrected rows whose `timezone(new_zone, started_at)::date` differs
from `effective_day` in day, month and year. The decorated settings function
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
  goes; `annotated_for_filtering` refuses a missing clock rather than invent
  UTC. The clock's move onto `effective_day` and the game-to-run narrowing stay
  with #702's surface 9.
- The preflight census's secondary column reads it.
- New sessions seed `day_zone` from it, never from the request's activated
  zone. A second reader of a library records in the owner's calendar.
- Until #702, the legacy reads group in the request's activated zone. That is
  the owner's display zone, which the trigger keeps equal to the calendar.

## Migration

Migration `0005` appends one `day_zone_changed` per library, naming the
owner's effective `DISPLAY_TIME_ZONE`, the zone #700 seeded every row with.
Its gate refuses when any Timed or Corrected row's `day_zone` differs from its
library's calendar, and when `rebuild_projections(mode=CHECK)` reports a
difference.

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
