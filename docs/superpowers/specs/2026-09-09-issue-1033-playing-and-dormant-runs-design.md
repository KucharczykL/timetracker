# Playing and Dormant runs

An unfinished run states a condition. A clock counts the condition. No event,
no column and no migration store it.

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

The method is idempotent. `add_annotation` replaces a duplicate alias without an
error, which would replace one clock with another.

`library_runs()` and `numbered_for()` annotate. `live_ordinary_runs()` does not:
commands read it, and a write path resolves no display setting. A null clock
reads the registry default in UTC.

## The filter

`PlaythroughFilter.activity` is a `ChoiceCriterion`. Its `FilterField` states a
handler, and the handler delegates to `criterion.to_q("activity")`. Delegation
keeps the modifier and the list. The handler keeps `field_metadata` off a column
that does not exist.

`FilterField.choices` gives a handler field its own options, because
`_static_choices` reads a column.

`EXCLUDES` keeps a completed run: `_SetCriterion._not_in_q` ORs
`activity__isnull=True` into the Q.

`QuickFacet("activity", "Activity")` renders a panel `FilterSelect`.

## The screens

`playthrough_tabledata` states an `Activity` column. Game detail and the
Playthrough list read one renderer. The cell prints a `Pill` and the recency
beside it, or `-` for a completed run. The column has no sort key.

## The words beside the statuses

A condition is counted. A status is stated. Neither moves the other.
`docs/vocabulary.md` records the three pairs. `docs/STATUSES.md` names the
difference beside Abandoned.
