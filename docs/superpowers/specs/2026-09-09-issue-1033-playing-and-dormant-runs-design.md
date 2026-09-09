# Playing and Dormant runs

A clock counts a condition for every unfinished run. No event, no column and no
migration store it.

## The three words

| word | the clock says |
|---|---|
| Playing | the last played day is not older than the threshold |
| Dormant | the last played day is older than the threshold |
| Never played | no day is known |

A run whose completion is stated has no condition.

`Never played` is not `Unplayed`. `PlayerGameStatus` states `Unplayed`, and Game
detail prints a status beside these rows.

## The last played day

The read answers one day, or nothing:

1. the latest live session at the run's game;
2. the run's own `started_lower`;
3. nothing.

Both sides answer a day. The session side reads `TruncDate` in the viewer's
zone. The comparison is `>= boundary_day` on both sides.

The subquery states `game__library` against the run's own `library` column. One
library's sessions do not move another library's condition.

`Session` states no run. The recency is the game's. #700 and #701 narrow it to
the run.

## The threshold

`DORMANT_AFTER_DAYS` is one `SettingDefinition`: scope `USER`, apply timing
`LIVE`, widget `SELECT` over 7, 14, 30, 60, 90, 180 and 365, default 30. The
key is absent from `USER_PREFERENCE_FIELD_BY_KEY`, so a personal value lands in
`extra_preferences`.

`activity_clock(library)` answers the threshold, the viewer's zone, and
`boundary_day`, which is today in that zone minus the threshold.

## The two annotations

`PlaythroughQuerySet.annotated_for_filtering(clock=None)` registers two aliases:

| alias | is |
|---|---|
| `activity_day` | a `Coalesce` of the newest live session day and `started_lower` |
| `activity` | a `Case`, null where the completion is stated |

The method is on the queryset. `with_filter_aliases` reads it off a queryset,
and `for_validation` hands it `model._default_manager.none()`. The queryset
states no `alive()` and no `for_library()`, so every read states its own scope.

A second call that names the same clock is a no-op, because
`with_filter_aliases` calls the method again. A second call that names another
clock is refused: `add_annotation` replaces a duplicate alias without an error,
and the read could not say which threshold it answered. A null clock reads the
registry default in UTC.

The aliases cost three correlated subqueries a row, so each read asks for them.
`runs_with_condition()` is `library_runs()` with the viewer's clock, and the two
screens that print the word read it. `numbered_for(..., with_condition=True)`
does the same for Game detail. `library_runs()` and `live_ordinary_runs()` carry
no alias.

## The filter

`PlaythroughFilter.activity` is a `ChoiceCriterion`. Its `FilterField` states a
handler, and the handler delegates to `criterion.to_q("activity")`. Delegation
keeps the modifier and the list. The handler keeps `field_metadata` off a column
that does not exist.

`FilterField.choices` gives a handler field its own options, and
`FilterField.nullable` gives it its own presence test, because `_static_choices`
and `_lookup_is_nullable` both read a column.

`EXCLUDES` keeps a completed run: `_SetCriterion._not_in_q` ORs
`activity__isnull=True` into the Q. `IS_NULL` asks for those runs directly.

`QuickFacet("activity", "Activity")` renders a panel `FilterSelect`.

## The screens

`playthrough_tabledata` states an `Activity` column. Game detail and the
Playthrough list read one renderer. The cell prints a `Pill` and the recency
beside it, the `Pill` alone where no day is known, or `-` for a completed run. A
row that carries no alias is refused, because a dash there would print an
unfinished run as finished. The column has no sort key, and it ranks below Note,
so it drops first when the table runs out of room.

## The words beside the statuses

A condition is counted. A status is stated. Neither moves the other.
`docs/vocabulary.md` records the three pairs. `docs/STATUSES.md` names the
difference beside Abandoned.
