# Playing and Dormant runs

A clock counts a condition for every unfinished run. No event, column or
migration stores it.

## The three words

| word | the clock says |
|---|---|
| Playing | the last played day is not older than the threshold |
| Dormant | the last played day is older than the threshold |
| Never played | no day is known |

A run whose completion is stated has none.

## The last played day

The read answers one day, or nothing:

1. the latest live session at the run's game;
2. the run's own `started_lower`;
3. nothing.

The session side reads `TruncDate` in the viewer's zone. Both sides answer a
day, compared with `>= boundary_day`.

The subquery states `game__library` against the run's `library` column, so one
library's sessions move no other condition.

`Session` states no run, so the recency is the game's. #700 and #701 narrow it.

## The threshold

`DORMANT_AFTER_DAYS` is a `SettingDefinition`: scope `USER`, apply timing
`LIVE`, widget `SELECT` over 7, 14, 30, 60, 90, 180, 365, default 30. Its key
is absent from `USER_PREFERENCE_FIELD_BY_KEY`, so a personal value lands in
`extra_preferences`.

`activity_clock(library)` answers the threshold, the viewer's zone, and
`boundary_day`: today in that zone minus the threshold.

## The two annotations

`PlaythroughQuerySet.annotated_for_filtering(clock=None)` registers two
aliases:

| alias | is |
|---|---|
| `activity_day` | a `Coalesce` of the newest live session day and `started_lower` |
| `activity` | a `Case`, null where the completion is stated |

`with_filter_aliases` reads the method off a queryset; `for_validation` passes
`none()`. The queryset states no `alive()` and no `for_library()`, so every
read states its own scope. A null clock reads the registry default in UTC.

A second call naming the same clock is a no-op, because `with_filter_aliases`
calls the method again. A second naming another clock is refused, because
`add_annotation` replaces an alias in silence.

The aliases cost three correlated subqueries a row, so each read asks for them:
`runs_with_condition()` is `library_runs()` with the viewer's clock, and
`numbered_for(..., with_condition=True)` does the same for Game detail.
`library_runs()` and `live_ordinary_runs()` carry no alias.

## The filter

`PlaythroughFilter.activity` is a `ChoiceCriterion`. Its `FilterField` states a
handler that delegates to `criterion.to_q("activity")`, keeping the modifier
and the list.

`FilterField.choices` and `FilterField.nullable` give a handler field its own
options and presence test, because `_static_choices` and `_lookup_is_nullable`
read a column.

`EXCLUDES` keeps a completed run: `_SetCriterion._not_in_q` ORs
`activity__isnull=True` into the Q, and `IS_NULL` asks for those runs.

`QuickFacet("activity", "Activity")` renders a panel `FilterSelect`.

## The screens

`playthrough_tabledata` states an `Activity` column, rendered once for Game
detail and the Playthrough list. The cell prints a `Pill` and the recency
beside it, the `Pill` alone where no day is known, or `-` for a completed run.
A row that carries no alias is refused. The column has no sort key and ranks
below Note.

## Conditions and statuses

A condition is counted. A status is stated. Neither moves the other, and `Never
played` is not the `Unplayed` status. `docs/vocabulary.md` and
`docs/STATUSES.md` record the three pairs.
