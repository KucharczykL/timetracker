# The zone a library counts days in

Issue #1047. Member 2 of the wave stack (#700, #1047, #702, #704). Land it
only with `gh stack merge`.

## The problem

A session is one instant. Its calendar day depends on the zone that reads the
instant. Before this design two readers answered that day: the row's stored
`day_zone` under the generated `effective_day`, and the dormancy clock, which
read the viewer's `DISPLAY_TIME_ZONE` on every read and UTC with no viewer.
After a change of the display zone the same session sat on two days.

## The decision

A library counts days in one zone: its calendar's `day_zone`. The stored
`effective_day` is the answer, and no reader computes a day from a zone of
its own. Changing `DISPLAY_TIME_ZONE` is the act that changes the calendar.
It is automatic: it restates every recorded day in the same transaction and
reports what moved after the fact.

## The calendar aggregate

- Aggregate `calendar`; the aggregate id is the library's id.
- Event `library.calendar.day_zone_changed`, payload `{"day_zone": <IANA name>}`.
- Command `SetCalendarDayZone(day_zone)`, type `library.calendar.set_day_zone`.
  It refuses a zone either tzdata does not know, through `known_zone`, and
  answers `Unchanged` for the zone the calendar already states.
- Projection `LibraryCalendar(library, day_zone)`, `CURRENT_STATE` family.

The projector `LibraryCalendars` writes its row, then rewrites `day_zone` on
every Timed and Corrected `PlayerSession` row of the library, removed rows
included; the database regenerates `effective_day`. Duration-only rows hold no
zone and do not move, and the endpoint zones record where the clock stood and
do not move. It is the first projector that writes rows the event does not
name: one library-wide event, because the act is automatic and a per-session
shape writes thousands of events on every change of the setting.

The contract for a reader that reacts to the change is the event itself: a
projector handling `library.calendar.day_zone_changed`, as this one does and
#748's Journal rebuild will. No signal, no reactor registry; replay reproduces
every reaction in order.

## One transaction

`run_in_transaction` refuses to nest, and the rule stays. `append_command`
builds and appends inside a transaction the caller holds, without
authorizing; `dispatch` is `authorize`, then `append_command` under
`run_in_transaction`. `retried_transaction` decorates a function with it. For
`DISPLAY_TIME_ZONE`, `change_user_setting` and `change_site_setting` run their
database half and the calendar command under one decorated function.

A personal set or clear acts as the owner, authorized before the transaction.
A site-level change acts as the operator, without `authorize`, for every
library whose owner inherits the site value. A change that leaves the
calendar's zone equal appends nothing; a refused zone refuses the setting.
Idempotency keys are minted before the retried call. The settings snapshot
expires after five seconds; the calendar row is the truth.

## The delta report

Before the rewrite, in the same transaction, `calendar_delta` counts the live
Timed and Corrected rows whose `timezone(new_zone, started_at)::date` differs
from `effective_day` in day, month and year. The settings functions answer the
counts as `CalendarDelta`, the settings API returns them as `calendar` beside
the resolved setting, and the toast reads:

```text
Days now counted in UTC: 2,663 sessions, 9 moved to another day, 0 to
another month, 0 to another year.
```

A site-level change logs one line per library whose calendar moved and
returns the totals. The zone control reloads the page after a save, so the
toast is left in the message store for the page it lands on rather than
riding a response the browser discards. A refusal the command raises reaches
the person as the command's sentence, through `answered`.

## The readers

- `calendar_day_zone(library)` is the one read: the row, or the owner's
  display zone before a row exists. A stored name tzdata can no longer read
  falls back the same way, logged, and the next change of the setting
  restates it, because the trigger compares the stored name itself.
- `activity_clock(library)` takes its zone from it. Without a clock,
  `annotated_for_filtering` states `activity_day` and `activity` through
  `.alias()` with expressions that resolve and refuse to compile: validation
  resolves them, and a query naming either raises `UnscopedActivityRead`. The filter
  context builds each scope lazily, so a list that never names runs never
  reads the clock.
- `CreateSession` and `CorrectSessionTiming` refuse a `day_zone` off the
  calendar: "This library counts days in X." #702's surfaces seed it from
  `calendar_day_zone(library)`, and the refusal makes a wrong seed loud.
- Until #702, the legacy reads group in the request's activated zone, which
  the setting change keeps equal to the calendar within the snapshot's
  five-second window.

## Migration

Migration `0005` creates the table and appends one `day_zone_changed` per
library through `append_one`, naming the owner's effective display zone, the
zone `0004` seeded every row with. Its gate refuses a Timed or Corrected row
whose `day_zone` differs from the calendar and any replay difference. Each
migration's replay gate names the projection tables its own schema holds,
because a later table does not exist when it runs; `0004`'s census and parity
checks read the setting for the same reason.

## Proof

- One test changes a seeded library from Europe/Prague to UTC and checks the
  replay. On the 2026-09-12 dump, migration 0005 seeded the one library with
  no mismatch; the change to UTC moved 9 of the 2,663 Timed and Corrected
  sessions (the dump holds no Corrected row) to another
  day and none to another month or year; the change back moved the same 9;
  every `effective_day` matched the snapshot taken before; and the replay
  check reported no difference after either change.
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
