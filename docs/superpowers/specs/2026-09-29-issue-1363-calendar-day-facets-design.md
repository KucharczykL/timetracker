# Day facets read the library calendar

Issue #1363. A filter that compares a timestamp's day reads that day in the
library's calendar zone, never in the active zone.

## The problem

Django's `__date` lookup and `TruncDate` resolve in the active zone. Every
other day-grained reader asks `calendar_day_zone(library)`. Inside a request
the middleware activates the viewer's display zone, which equals the calendar
in practice. Outside a request the active zone is `settings.TIME_ZONE`, and
the two zones sit on different dates for some hours of every day.

## The zone enters through the context

`FilterQueryContext` carries `day_zone: ZoneInfo`. The field is required.
`filter_query_context_for_library(library)` sets it from
`calendar_day_zone(library)`. `FilterQueryContext.for_validation()` sets `UTC`
and refuses to execute, as it does today. `OperatorFilter.to_q(context)`
hands the zone to each leaf. A day facet compiled with no context raises
`FilterQueryContextRequired`.

Production builds a context in one place. A test builds one with a stated
zone, or the constructor refuses it.

## A field names the column whose day it compares

`FilterField` has a third axis beside `lookup` and `handler`: `day_of`, the
datetime column whose calendar day the criterion compares. `__post_init__`
refuses `day_of` beside either other axis. Field metadata reads the column
through `metadata_lookup`, so the kind, the nullability and the quick bar do
not change.

`DateCriterion.to_q_on(expression)` builds one lookup expression per
modifier over any day expression: `Exact`, `GreaterThan`, `LessThan`, a
bounds pair for `BETWEEN` and `WITHIN`, `IsNull` for the presence pair.
`DateCriterion.to_q(field_name)` is `to_q_on(F(field_name))`. One modifier
table serves both.

A `day_of` field compiles to `TruncDate(F(column), tzinfo=context.day_zone)`.
The nine `created_at` and `updated_at` fields use it.

A field comparison at `granularity="date"` truncates each datetime operand
with `TruncDate(…, tzinfo=context.day_zone)`. The left operand stops using
the `__date` lookup.

## A session's day is the row's own

`PlayerSessionFilter.started` and `.ended` read the row's `day_zone`, the
column `effective_day` is generated from. `session_day_of(column)` is
`Cast(Func(F("day_zone"), F(column), function="timezone"), DateField())`,
declared once beside the model. The two fields are handlers over that
expression, with `metadata_lookup` naming the instant column. A Duration-only
row states no instant and answers NULL, as today.

## `TIME_ZONE` defaults to UTC

After this change nothing a library reads depends on `settings.TIME_ZONE`.
Its default is `UTC` under `DEBUG` too. `TZ` in the environment still
overrides it. `docs/configuration.md` states the new default.

## Stored filters do not move

The keys `created_at`, `updated_at`, `started` and `ended` keep their names
and their JSON. Only the compiled predicate changes. Presets and the API need
no migration.

## Tests

- A `created_at` facet finds a row by the calendar's day under
  `timezone.override` of a zone on another date.
- A field comparison at `granularity="date"` reads the calendar zone the same
  way.
- `started` and `ended` agree with `day` on every Timed and Corrected row.
- `test_created_at` seeds and asserts through the calendar. The `UTC` pin
  leaves `test_date_granular_same_day_behavior`.
  `test_created_at_filter_is_date_granular` runs against a displaced calendar.
- The six test contexts state a zone through one shared helper.
- The suite passes with the process clock on either side of the calendar.

## Documentation

The `# compared via __date` comments, the "not covered: ORM `__date`" clause
in CLAUDE.md and the matching line in the #1221 spec are removed.
