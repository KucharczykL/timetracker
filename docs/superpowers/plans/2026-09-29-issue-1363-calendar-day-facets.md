# Day facets read the library calendar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every filter that compares a timestamp's day compares it in the library's calendar zone, never the active zone.

**Architecture:** `FilterQueryContext` carries a cached zone thunk; a `FilterField(day_of=…)` axis compiles to `TruncDate(F(column), tzinfo=zone)` through a new `DateCriterion.to_q_on(expression)`; the two session facets read the row's own `day_zone` through the expression `effective_day` is generated from; field comparisons take the zone explicitly.

**Tech Stack:** Django 6 ORM lookup expressions (`django.db.models.lookups`), `TruncDate(tzinfo=)`, PostgreSQL `timezone()`.

**Spec:** `docs/superpowers/specs/2026-09-29-issue-1363-calendar-day-facets-design.md`

## Global Constraints

- Run everything through `make`; tests as `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS="…"`.
- Identifiers are complete words; compound and primitive-role types are named (`type ZoneThunk = Callable[[], ZoneInfo]`).
- Comments ≤ 7 words, no issue references. `make vale` over docs.
- No `to_q("x")` kwargs form is rewritten: `DateCriterion.to_q(field_name)` keeps its output.
- Stored filter keys (`created_at`, `updated_at`, `started`, `ended`) and their JSON do not change.
- Gate: full `make check`, then `TIMETRACKER_TEST_PROCESS_ZONE=<other direction>` for `make test-fast` and `make test-e2e`.

---

## File map

| File | Responsibility |
|---|---|
| `common/criteria.py` | `FilterQueryContext.day_zone`, `FilterField.day_of`, `FieldSpec.to_q(attr, criterion, context)`, `DateCriterion.to_q_on`, `_field_comparison_to_q(day_zone=)`, metadata `metadata_lookup or day_of` |
| `games/filters.py` | `filter_query_context_for_library` states the thunk; nine `day_of` fields; `session_day_handler` for `started`/`ended` |
| `games/models.py` | `session_day_of(column)` beside `PlayerSession.effective_day`, which uses it |
| `tests/filter_contexts.py` | `unrestricted_filter_context(zone)` for the six test contexts |
| `tests/test_filter_query_context.py` | new: context requires a zone; validation zone; thunk cached |
| `tests/test_date_criterion_expression.py` | new: `to_q_on` parity with `to_q` per modifier |
| `tests/test_calendar_day_facets.py` | new: facets read the calendar under a displaced active zone |
| `timetracker/settings.py`, `docs/configuration.md` | `TIME_ZONE` default UTC |
| `CLAUDE.md`, `docs/superpowers/specs/2026-09-21-issue-1221-one-calendar-today-design.md` | drop the "not covered: `__date`" clauses |

---

### Task 1: The context carries a cached zone

**Files:**
- Modify: `common/criteria.py:1393-1415` (`FilterQueryContext`)
- Modify: `games/filters.py:1119-1152` (`filter_query_context_for_library`)
- Create: `tests/filter_contexts.py`
- Modify: the six `UNRESTRICTED_FILTER_CONTEXT = FilterQueryContext(...)` sites — `tests/test_filters.py:86`, `test_filter_cross_entity.py:34`, `test_relation_algebra.py:33`, `test_session_fk_uuid.py:32`, `test_filter_tree_contract.py:41`, `test_playthrough_game_relation.py:37`
- Test: `tests/test_filter_query_context.py`

**Interfaces:**
- Produces: `type ZoneThunk = Callable[[], ZoneInfo]`; `FilterQueryContext(resolver, *, day_zone: ZoneThunk, authorization_scoped: bool = True)`; `FilterQueryContext.calendar_zone() -> ZoneInfo` (calls the thunk; Python's `functools.cache` on the thunk is the caller's, so `filter_query_context_for_library` wraps with `cache(lambda: calendar_day_zone(library))`); `FilterQueryContext.for_validation()` states `lambda: UTC`.
- Produces: `unrestricted_filter_context(zone: ZoneInfo) -> FilterQueryContext` in `tests/filter_contexts.py`, resolver `lambda model: with_filter_aliases(model._default_manager.all())`.

- [ ] Write `tests/test_filter_query_context.py`: (a) `FilterQueryContext(resolver)` without `day_zone` raises `TypeError`; (b) `for_validation().calendar_zone() == ZoneInfo("UTC")` and `ensure_execution()` raises; (c) a counting thunk wrapped in `cache` is called once across two `calendar_zone()` reads; (d) `filter_query_context_for_library(owned_library).calendar_zone() == calendar_day_zone(owned_library)` after `displace_calendar(owned_library)` (db, `transaction=True`).
- [ ] Run; expect `TypeError` on the constructor / missing attribute.
- [ ] Add `day_zone: ZoneThunk` as `field(kw_only=True)` after `authorization_scoped`; add `calendar_zone()`; state `lambda: UTC` in `for_validation`; state `cache(lambda: calendar_day_zone(library))` in `filter_query_context_for_library` (lazy import of `calendar_day_zone` beside the model imports there).
- [ ] Add `tests/filter_contexts.py`; replace the six definitions with `UNRESTRICTED_FILTER_CONTEXT = unrestricted_filter_context(ZoneInfo("UTC"))` (their rows are seeded in UTC today).
- [ ] `make test-fast ARGS="tests/test_filter_query_context.py tests/test_filters.py -x"`; commit `feat(filters): the query context carries the calendar zone`.

Gotcha: the dataclass is `frozen=True` with a defaulted field before the new one; `kw_only=True` avoids the ordering `TypeError`.

### Task 2: `DateCriterion.to_q_on(expression)`

**Files:**
- Modify: `common/criteria.py:553-590` (`DateCriterion`)
- Test: `tests/test_date_criterion_expression.py`

**Interfaces:**
- Produces: `DateCriterion.to_q_on(self, expression: Expression) -> Q`, one branch per modifier: `Exact`, `~Q(Exact)`, `GreaterThan`, `LessThan`, `Q(GreaterThanOrEqual) & Q(LessThanOrEqual)` for `BETWEEN`/`WITHIN`, `Q(LessThan) | Q(GreaterThan)` for `NOT_BETWEEN`, `IsNull(expression, True/False)`; same `FilterError` sentences as `to_q`. Values stay the ISO strings `_coerce_date` keeps.
- `to_q(field_name)` unchanged.

- [ ] Write the parity test: seed three `Purchase` rows with `date_purchased` on three days; for every modifier in `Modifier.for_dates()` plus `WITHIN`, build a `DateCriterion` and assert `set(Purchase.objects.filter(criterion.to_q("date_purchased")))` equals `set(Purchase.objects.filter(criterion.to_q_on(F("date_purchased"))))`. Add one case per bounds refusal: `BETWEEN` with `value2=None` raises `FilterError` from both forms.
- [ ] Run; expect `AttributeError: to_q_on`.
- [ ] Implement `to_q_on`; import the lookups from `django.db.models.lookups`.
- [ ] Run; commit `feat(criteria): a date criterion compiles over an expression`.

### Task 3: `FilterField.day_of` and the context at the leaf

**Files:**
- Modify: `common/criteria.py:997-1075` (`FilterField`), `:1690-1700` (leaf call), `:2876-2892` (metadata lookup)
- Modify: `tests/test_filter_field_metadata_lookup.py:53` (two-arg `to_q` call gains `FilterQueryContext.for_validation()`)
- Test: extend `tests/test_filter_field_metadata_lookup.py`

**Interfaces:**
- Produces: `FilterField(day_of: ORMLookup | None = None)`; `FilterField.to_q(self, attr_name, criterion, context: FilterQueryContext | None) -> Q`: handler → `handler(criterion)`; `day_of` → `criterion.to_q_on(TruncDate(F(day_of), tzinfo=context.calendar_zone()))`, `FilterQueryContextRequired("day facet requires query context")` when `context is None`, `FilterError` when the criterion is not a `DateCriterion`; else `criterion.to_q(lookup or attr_name)`.
- `__post_init__`: `day_of` with `lookup` or `handler` → `ValueError`; `choices`/`nullable` stay refused on any field without a handler, `day_of` included (the existing check already reads `self.handler is None`).
- Metadata: `lookup = field_spec.metadata_lookup or field_spec.day_of or field_spec.lookup or name`.
- `OperatorFilter.to_q` passes `context` at `descriptor.to_q(attr_name, criterion, context)`.

- [ ] Write tests: `FilterField(day_of="created_at", lookup="x")` raises; `FilterField(day_of="created_at", nullable=True)` raises; a filter with `fields = {"created_at": FilterField(day_of="created_at")}` and `created_at=DateCriterion(value="2026-03-05")`: `to_q()` (no context) raises `FilterQueryContextRequired`; `to_q(FilterQueryContext.for_validation())` string contains `TruncDate` and `UTC`; `field_metadata` reports kind `date`, not nullable.
- [ ] Run; expect `TypeError: unexpected keyword 'day_of'`.
- [ ] Implement; update the leaf call and the metadata resolution; fix `tests/test_filter_field_metadata_lookup.py:53`.
- [ ] `make test-fast ARGS="tests/test_filter_field_metadata_lookup.py tests/test_filters.py tests/test_filter_paths.py -x"`; commit `feat(criteria): a filter field names the column whose day it compares`.

### Task 4: Nine `created_at`/`updated_at` fields read the calendar

**Files:**
- Modify: `games/filters.py:182,183,360,474,475,687,749,843,930` — `FilterField("created_at__date")` → `FilterField(day_of="created_at")` (same for `updated_at`); the nine `# compared via __date` field comments → `# compared by calendar day`
- Modify: `tests/test_historical_playtime_filter.py:223-227` (`test_created_at` seeds and asserts through `calendar_today(owned_library)`)
- Modify: every test compiling a `created_at`/`updated_at` criterion through a bare `to_q()` (grep `created_at=DateCriterion\|"created_at": {` in `tests/`; today `tests/test_filters.py` and `tests/test_quick_filter_bar.py`) passes `UNRESTRICTED_FILTER_CONTEXT`
- Test: `tests/test_calendar_day_facets.py`

- [ ] Write `test_a_created_at_facet_reads_the_calendar_not_the_active_zone` (`transaction=True`): `displace_calendar(owned_library)`; create a `Game` and `update(created_at=library_noon(owned_library))`; under `timezone.override(ZoneInfo(other_displaced_zone(zone)))` compile `GameFilter(created_at=DateCriterion(value=calendar_today(owned_library).isoformat()))` through `filter_query_context_for_library(owned_library)` and assert the game is found, and that `DateCriterion(value=process_day().isoformat())` is not. Parametrize over the seven filter classes carrying `created_at` where seeding is cheap (Game, Purchase, Platform, Device at least).
- [ ] Run; expect the active-zone day to match instead.
- [ ] Swap the nine declarations; sweep the bare `to_q()` tests; fix `test_created_at`.
- [ ] `make test-fast ARGS="tests/test_calendar_day_facets.py tests/test_historical_playtime_filter.py tests/test_filters.py tests/test_quick_filter_bar.py -x"`; commit `feat(filters): created_at and updated_at compare on the library calendar`.

### Task 5: `started`/`ended` read the row's own zone

**Files:**
- Modify: `games/models.py:1836-1850` — add `def session_day_of(column: str) -> Cast` returning `Cast(Func(F("day_zone"), F(column), function="timezone"), models.DateField())` above `PlayerSession`, and make `effective_day`'s second `Coalesce` arm `session_day_of("started_at")`
- Modify: `games/filters.py:354-355` — `"started": FilterField(handler=session_day_handler("started_at"), metadata_lookup="started_at", label="Started")`, same for `ended`
- Add to `games/filters.py` (beside `duration_hours_handler`): `def session_day_handler(column: str) -> FieldHandler` returning `lambda criterion: criterion.to_q_on(session_day_of(column))` with a lazy `from games.models import session_day_of` inside and a `FilterError` for a non-`DateCriterion`
- Test: `tests/test_calendar_day_facets.py`

- [ ] Write tests (`transaction=True`, displaced calendar): (a) for a Timed and a Corrected row seeded at `library_noon`, `PlayerSessionFilter(started=DateCriterion(value=<day>))` and `PlayerSessionFilter(day=…)` match the same rows for `<day>` = the calendar day and for the process day; (b) a Duration-only row is matched by `started` `IS_NULL` and not by `EQUALS`; (c) `ended` `LESS_THAN` tomorrow matches the ended row.
- [ ] Run; expect the active-zone mismatch on (a).
- [ ] Implement; confirm `makemigrations --check` reports no change (the generated expression is unchanged).
- [ ] `make test-fast ARGS="tests/test_calendar_day_facets.py tests/test_session_date_filter.py tests/test_filters.py -k 'started or ended or session' -x"`; commit `feat(filters): a session's started and ended read its own day zone`.

Gotcha: `makemigrations` must be clean — the `GeneratedField` expression text is what the migration compares; keep `Cast(Func(...), DateField())` identical.

### Task 6: Field comparisons take the zone

**Files:**
- Modify: `common/criteria.py:2068-2115` (`_field_comparison_to_q(..., *, left_group, right_group, day_zone: ZoneInfo)`), `:1639-1646` (call passes `context.calendar_zone()`; `context is None` → `FilterQueryContextRequired` for `granularity != "raw"` only)
- Modify: `tests/test_filters.py:4419-4460` (`test_date_granular_same_day_behavior`: drop `@override_settings(TIME_ZONE="UTC")`, seed at `library_noon`/`+1h` and a cross-day pair, compile through `filter_query_context_for_library`), `:5593-5610` (`test_created_at_filter_is_date_granular`: displaced calendar, `library_noon`, context)
- Test: `tests/test_calendar_day_facets.py`

- [ ] Write `test_a_date_granular_comparison_reads_the_calendar`: displaced calendar; a session whose `started_at` and `ended_at` straddle the *process* midnight but not the *calendar* midnight; `FieldComparisonCriterion(left="started_at", right="ended_at", modifier=EQUALS, granularity="date")` matches under `timezone.override(other zone)`.
- [ ] Run; expect no match.
- [ ] Implement: `left_expression = TruncDate(F(left), tzinfo=day_zone)` when `left_group == "datetime"` else `F(left)`; the predicate becomes `Q(Exact(left_expression, right_expression)) & guards` etc. (reuse the same lookup classes as Task 2). A `date`-group operand stays `F(...)`. `year` granularity unchanged.
- [ ] Rewrite the two existing tests; `make test-fast ARGS="tests/test_filters.py -k 'granular or comparison' tests/test_calendar_day_facets.py -x"`; commit `feat(criteria): date-granular comparisons read the calendar zone`.

### Task 7: `TIME_ZONE` defaults to UTC

**Files:**
- Modify: `timetracker/settings.py:173` → `TIME_ZONE = config("TZ", default="UTC")`
- Modify: `docs/configuration.md:49` (`UTC`), `:95-97` (drop the dev/prod split sentence if present)

- [ ] `grep -rn "Europe/Prague" tests e2e | grep -i "settings\|TIME_ZONE"` — expect only literal `ZoneInfo("Europe/Prague")` constants.
- [ ] Change both files; `make test-fast ARGS="tests/test_settings_resolver.py tests/test_user_preferences_resolver.py tests/test_settings_landing.py"`; commit `config: TIME_ZONE defaults to UTC everywhere`.

### Task 8: Docs and comments

**Files:**
- Modify: `CLAUDE.md` "Never ask what day it is" bullet — drop "and ORM `__date` lookups, which read the active zone (#1363)"; add "A day facet compiles on the calendar zone the filter context carries (`FilterField(day_of=…)`)."
- Modify: `docs/superpowers/specs/2026-09-21-issue-1221-one-calendar-today-design.md` — drop "and an ORM `__date` lookup, which reads the active zone" from the not-covered sentence
- Modify: `common/criteria.py:904` docstring ("using the active timezone" → "in the context's calendar zone"), `:2084` docstring

- [ ] Edit; `make vale`; commit `docs: day facets read the calendar`.

### Task 9: Gate, PR

- [ ] `make format && make lint-fix && make lint`.
- [ ] `flock … make check` (one direction). Then the other: `TIMETRACKER_TEST_PROCESS_ZONE=<zone off the calendar's date now> flock … make test-fast` and `make test-e2e`. Between 10:00 and 11:00 UTC both Kiritimati and Niue qualify; otherwise one does, and the override refuses the other with a sentence naming the hours.
- [ ] Push; `gh pr create --base main` with the spec's sections as the body; note both directions ran.

---

## Self-review

- Spec coverage: context (T1), `to_q_on` (T2), `day_of` + leaf context + metadata (T3), nine fields + sweep + `test_created_at` (T4), sessions (T5), comparisons + the two pinned tests (T6), `TIME_ZONE` (T7), docs (T8), both directions (T9). Presets/API: no task, by design.
- Names: `ZoneThunk`, `calendar_zone()`, `day_of`, `to_q_on`, `session_day_of`, `session_day_handler`, `unrestricted_filter_context` are used consistently above.
