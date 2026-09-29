# Day facets read the library calendar

A filter that compares a timestamp's day reads that day in the library's
calendar zone, never in the active zone.

## The problem

Django's `__date` lookup and `TruncDate` resolve in the active zone. Every
other day-grained read of a library's rows asks `calendar_day_zone(library)`. Inside a request
the active zone is the viewer's display zone. Outside a request it is
`settings.TIME_ZONE`. The two zones sit on different dates for some hours of
every day.

## The zone enters through the context

`FilterQueryContext` carries a required, keyword-only `day_zone`, a
`ZoneThunk`. `calendar_zone` is a cached property over it. A filter that
names no day predicate costs no calendar query. `filter_query_context_for_library(library)` states
`cache(lambda: calendar_day_zone(library))`. `for_validation()` states `UTC`
and refuses to execute.

`FilterField.to_q(attr_name, criterion, context)` takes the context and
hands it to a handler: `FieldHandler` is
`Callable[[_Criterion, FilterQueryContext | None], Q]`. A handler over the
row ignores it. A day facet compiled with no context raises
`FilterQueryContextRequired`.

Production builds a context in one place. A test builds one through
`tests/filter_contexts.py` with a stated zone.

## A day facet is a handler

`calendar_day_handler(column)` builds the handler for a timestamp column:
`DateCriterion.to_q_on(TruncDate(F(column), tzinfo=context.calendar_zone))`.
The nine `created_at` and `updated_at` fields use it, with `metadata_lookup`
naming the column, so the kind, the nullability and the quick bar do not
change.

`DateCriterion.to_q_on(expression)` builds one lookup expression per
modifier from `ORDERED_LOOKUPS`. `NOT_EQUALS` states `IsNull` beside the
negation, because a negated expression drops NULL rows and a negated keyword
lookup keeps them. A `None` value is refused: a keyword lookup read it as
`IS NULL`, an expression would compare to it. A test holds
`to_q_on(F(column))` and `to_q(column)` to the same rows for every modifier.

`_field_comparison_to_q` takes the zone thunk and reads it at `date` or
`year` granularity only. `date` truncates each datetime operand with
`TruncDate`; `year` extracts with `ExtractYear`; both in the calendar zone.
A date operand stays as it is. The `__isnull` guards stay on the column
paths. The quantifier refusal runs before the predicate build, so a
statement error wins over a missing context.

## A session's day is the row's own

`PlayerSessionFilter.started` and `.ended` read the row's `day_zone`.
`session_day_of(column)` is declared beside the model, over a closed
`SessionInstantColumn`, and `effective_day` is generated from it. The two fields are handlers over that expression, with
`metadata_lookup` naming the instant column. A Duration-only row answers NULL.

## `TIME_ZONE` defaults to UTC

No library day read depends on it. `TZ` in the environment overrides it.

## A library with no calendar

`calendar_day_zone` reads the owner's display zone and logs a warning. An
unreadable display zone logs an error and reads UTC.

## Stored filters do not move

The keys `created_at`, `updated_at`, `started` and `ended` keep their names
and their JSON. Only the compiled predicate changes.
