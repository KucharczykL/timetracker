# Day facets read the library calendar

A filter that compares a timestamp's day reads that day in the library's
calendar zone, never in the active zone.

## The problem

Django's `__date` lookup and `TruncDate` resolve in the active zone. Every
other day-grained reader asks `calendar_day_zone(library)`. Inside a request
the active zone is the viewer's display zone. Outside a request it is
`settings.TIME_ZONE`. The two zones sit on different dates for some hours of
every day.

## The zone enters through the context

`FilterQueryContext` carries a required, keyword-only `day_zone`, a
`ZoneThunk` read through `calendar_zone()`. A filter that names no day facet
costs no calendar query. `filter_query_context_for_library(library)` states
`cache(lambda: calendar_day_zone(library))`. `for_validation()` states `UTC`
and refuses to execute.

`FilterField.to_q(attr_name, criterion, context)` takes the context.
`OperatorFilter.to_q(context)` passes it. `FieldHandler` stays
`Callable[[_Criterion], Q]`: a handler reads the row. A day facet compiled
with no context raises `FilterQueryContextRequired`.

Production builds a context in one place. A test builds one through
`tests/filter_contexts.py` with a stated zone.

## A field names the column whose day it compares

`FilterField` has a third axis beside `lookup` and `handler`: `day_of`, the
timestamp column. `__post_init__` refuses it beside either other axis. Field
metadata resolves `metadata_lookup or day_of`, so the kind, the nullability
and the quick bar do not change.

`DateCriterion.to_q_on(expression)` builds one lookup expression per
modifier. `NOT_EQUALS` states `IsNull` beside the negation, because a negated
expression drops NULL rows and a negated keyword lookup keeps them. A test
holds `to_q_on(F(column))` and `to_q(column)` to the same rows for every
modifier.

A `day_of` field compiles to `TruncDate(F(column), tzinfo=context.calendar_zone())`.
The nine `created_at` and `updated_at` fields use it.

`_field_comparison_to_q` takes `day_zone`. At `granularity="date"` it
truncates each datetime operand and leaves a date operand as it is. The
`__isnull` guards stay on the column paths. The quantifier refusal runs before
the predicate build, so a statement error wins over a missing context.

## A session's day is the row's own

`PlayerSessionFilter.started` and `.ended` read the row's `day_zone`.
`session_day_of(column)` is declared beside the model and `effective_day` is
generated from it. The two fields are handlers over that expression, with
`metadata_lookup` naming the instant column. A Duration-only row answers NULL.

## `TIME_ZONE` defaults to UTC

Nothing a library reads depends on it. `TZ` in the environment overrides it.

## Stored filters do not move

The keys `created_at`, `updated_at`, `started` and `ended` keep their names
and their JSON. Only the compiled predicate changes.

## Not covered

A UTC day, a read inside a request, a test that pins `TIME_ZONE`, and the
browser.
