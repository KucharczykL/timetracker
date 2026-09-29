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

`FilterQueryContext` carries a required, keyword-only `day_zone`. It is a
thunk, `Callable[[], ZoneInfo]`, read once and cached: a filter that names
no day facet costs no calendar query, and a read that builds several
contexts (a statistics render builds about five) stays inside the 20 ms
budget. `filter_query_context_for_library(library)` states
`cache(lambda: calendar_day_zone(library))`. `for_validation()` states `UTC`
and refuses to execute, as it does today.

`FilterField.to_q(attr_name, criterion, context)` takes the context.
`OperatorFilter.to_q(context)` passes it at the one call site; the relation,
aggregate and `_extra_q` descents already carry it, so a nested filter sees
the same zone. `FieldHandler` stays `Callable[[_Criterion], Q]`: a handler
reads the row, not the context. A day facet compiled with no context raises
`FilterQueryContextRequired` from the leaf.

Production builds a context in one place. A test builds one with a stated
zone, or the constructor refuses it. Every test that compiles a day facet
through a bare `to_q()` gains a context.

## A field names the column whose day it compares

`FilterField` has a third axis beside `lookup` and `handler`: `day_of`, the
datetime column whose calendar day the criterion compares. `__post_init__`
refuses `day_of` beside either other axis. Field metadata resolves
`metadata_lookup or day_of`, so the kind, the nullability and the quick bar
do not change. A `day_of` field states no `choices` and no `nullable`; the
column answers both.

`DateCriterion.to_q_on(expression)` builds one lookup expression per
modifier over any day expression: `Exact`, `GreaterThan`, `LessThan`, a
bounds pair for `BETWEEN` and `WITHIN`, `IsNull` for the presence pair. The
value stays the ISO string `_coerce_date` keeps; the lookup preps it.
`DateCriterion.to_q(field_name)` keeps its keyword form for a plain date
column. A test holds the two forms to the same rows for every modifier.

A `day_of` field compiles to `TruncDate(F(column), tzinfo=context.day_zone())`.
The nine `created_at` and `updated_at` fields use it.

`_field_comparison_to_q` takes the zone. At `granularity="date"` it
truncates each datetime operand with `TruncDate(…, tzinfo=zone)` and leaves
a date operand as it is. The left operand stops using the `__date` lookup.
The `__isnull` guards stay on the column paths.

## A session's day is the row's own

`PlayerSessionFilter.started` and `.ended` read the row's `day_zone`, the
column `effective_day` is generated from. `session_day_of(column)` is
`Cast(Func(F("day_zone"), F(column), function="timezone"), DateField())`,
declared once beside the model. The two fields are handlers over that
expression, with `metadata_lookup` naming the instant column. The column is
nullable, so the presence pair is offered and the handler answers it. A
Duration-only row states no instant and answers NULL, as today. Neither
field is a quick facet.

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
