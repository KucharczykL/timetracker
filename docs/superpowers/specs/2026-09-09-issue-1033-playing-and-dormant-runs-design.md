# Playing and Dormant runs

An unfinished run says whether it is being played. The word comes from a clock,
not from a column: how long it has been since the game was played, against a
threshold the person owns. Game detail and the Playthrough list print the word
and the plain recency beside it, and the list filters by it.

Nothing is written. No event, no column, no migration.

## The three words

| word | the run states | the clock says |
|---|---|---|
| Playing | no completion | the last played day is `DORMANT_AFTER_DAYS` days ago or later |
| Dormant | no completion | the last played day is older than that |
| Unplayed | no completion | no day at all |

A run whose completion is stated carries no word. It is not unfinished, so no
clock speaks about it.

**Unplayed is a scope addition.** #1033 names two words. Two words cannot cover
a run at a game nobody has played yet, and #679 gives every tracked game a run
from the moment the library tracks it, so that run is the common case rather
than the odd one. Calling it Dormant would say a game tracked this morning went
quiet. The third word says what is true: no day is known.

## The last played day

The read takes a run and answers a day, or nothing.

1. The latest live session at the run's game, as the library sees sessions.
2. Where the game has no such session, the run's own `started_lower`.
3. Neither: nothing, which is Unplayed.

The order is a preference, not a maximum: a game with sessions never reads its
start day, even where the start is the later of the two. #1033 states the
fallback this way.

A dayless start reads as Unplayed. The act is stated and the day is not, and
this read answers days.

**Sessions are scoped as the app already scopes them.** `Session` holds no
library of its own, so `Session.objects.for_library()` reads `game__library`.
This read states the same thing, against the run's own library column. A run at
a shared catalog game therefore reads no session and falls to its start day.
That is the app's existing scope, not a rule this issue writes; a read that
named the game alone would let one library's sessions move another library's
badge.

**Sessions are not assigned to runs yet.** `Session` holds no reference to a
`Playthrough`; #700 and #701 own giving it one. The recency is the game's. A
game with one unfinished run reads one answer, and a game with several reads the
same answer for each. Narrowing to the run is a change inside
`games/reads/playthrough_activity.py`.

## The threshold

One `SettingDefinition` in `timetracker/settings_registry.py`.

| | |
|---|---|
| key | `DORMANT_AFTER_DAYS` |
| scope | `USER` |
| apply timing | `LIVE` |
| widget | `SELECT` over 7, 14, 30, 60, 90, 180, 365 |
| default | 30 |
| cast | `int` |
| validator | refuses a value off the list |

The key is absent from `USER_PREFERENCE_FIELD_BY_KEY`, so a personal value lands
in the `extra_preferences` bag. No model change and no migration, as
`DEFAULT_PAGE_SIZE` already does it. The settings page builds the row from the
registry, and the settings API validates through the same definition.

## The clock

`activity_clock(library)` answers three facts, read once per request:

| fact | is |
|---|---|
| `threshold_days` | `DORMANT_AFTER_DAYS`, resolved for the library's user |
| `boundary_day` | today in the viewer's `DISPLAY_TIME_ZONE`, minus that many days |
| `boundary_instant` | midnight of that day in that zone |

A day at or after `boundary_day` is recent. A session at or after
`boundary_instant` is recent. The two say one thing, which is why the SQL
compares a timestamp against an instant and a date against a date, and converts
neither.

## The two annotations

`Playthrough` gets its first manager, holding one method:
`annotated_for_filtering(clock=None)`. It declares no `alive()` and no
`for_library()`, so every read still states its own scope. `with_filter_aliases`
already calls that method by name, which is how the validation-only filter
context reaches the same aliases.

| alias | is |
|---|---|
| `last_played_at` | a correlated `Subquery`: the live sessions at the run's game, newest first, one row |
| `activity` | a `Case`: null where the completion is stated, else one of the three words |

The subquery states the library itself, as `game__library` against the run's own
`library` column. It therefore needs no library argument, and one run never
reads another library's sessions.

`activity` reads `last_played_at` first and `started_lower` second, in the order
the table above states. The clock states the threshold and the zone alone. A
null clock reads the registry default in UTC, which is what a filter compiled
for validation gets, and what the several test harnesses get that build a
context from `with_filter_aliases(model._default_manager.all())`. Neither knows
a viewer, and the validation context executes nothing.

Two reads apply the clock: `library_runs()`, which the list page, the
Playthrough API and both filter-context builders share, and `numbered_for()`,
which Game detail reads. `live_ordinary_runs()` does not, because commands read
it, and a write path resolves no display setting.

## The filter

`PlaythroughFilter.activity`, a `ChoiceCriterion` over the three words. Its
`FilterField` states a handler that compares the alias: `Q(activity=<word>)`.

A plain column comparison is what makes it composable. `aggregate_to_q` and
`relation_to_q` compile a nested `PlaythroughFilter` against
`context.queryset_for(Playthrough)`, which is `library_runs()`, and that
queryset carries the alias. A `Q` that named the sessions itself would compile,
but the clock would have nowhere to enter: a field handler reads the criterion
alone.

`common/criteria.py` gains one field: `FilterField.choices`. A handler field
resolves no column, so `_static_choices` answers the widget nothing and the
picker would render an empty set. `field_metadata` prefers the declared choices
and falls back to the column's.

`NOT_EQUALS` on the alias includes a completed run, because the alias is null
there and Django's negation keeps a null row. "Not playing" therefore means
dormant, unplayed or finished. This is stated rather than special-cased: the
person who wants unfinished runs alone states `is_completed` beside it.

The quick facet is `QuickFacet("activity", "Activity")`. `ChoiceCriterion` is
kind `set`, which is in `QUICK_FACET_KINDS`, so the panel `FilterSelect` renders
it and the bar's serializer round-trips it.

## The screens

`playthrough_tabledata` gains an **Activity** column, so Game detail and the
Playthrough list print it from one renderer.

| the run | the cell prints |
|---|---|
| Playing | a `Pill` reading `Playing`, then `last played 4 days ago` |
| Dormant | a `Pill` reading `Dormant`, then `last played 3 years ago` |
| Unplayed | a `Pill` reading `Unplayed`, nothing beside it |
| completed | `-` |

The recency sentence reads the same day the word read, in the viewer's zone:
`today`, `yesterday`, `N days ago`, `N months ago`, `N years ago`. The column
carries no sort key.

## The words beside the statuses

Dormant is a condition a clock computes about one run. **Abandoned** is a status
a person states about a game. Neither moves the other: a dormant run leaves the
status alone, and an abandoned game states no run condition.
`docs/vocabulary.md` records the pair under Settled, and `docs/STATUSES.md`
names the difference where it lists Abandoned.

`CLAUDE.md` says the projection declares no manager. It declares one now,
holding the alias method alone, and the line says so.

## Verification

| what | how |
|---|---|
| the three words | a table over session recent, session old, no session, each against a start day present, absent, dayless, and against a stated completion |
| the threshold | 30 by default; a personal 7 moves a run from Playing to Dormant with no other change |
| the filter | each word narrows the list to the rows the read gives it, and `NOT_EQUALS` keeps the completed rows |
| composition | a nested `PlaythroughFilter` inside `playthrough_count` compiles and executes; a blob naming `activity` passes eager validation |
| the facet | the quick-bar contract test, and the round trip from bar to URL to bar |
| presets | a saved playthroughs preset holding `activity` loads and applies |
| the setting | the registry test, the settings page row, and the API refusing 45 |
| the screens | both pages print the column, the badge word, the recency sentence, and `-` for a completed run |
| isolation | another library's sessions at a shared game move no badge and no filter answer |

Whole `make check`, `e2e/` included.

## Out of scope

- a game-level facet, across a game's runs: it asks what a game with one Playing
  run and one Dormant run is, which this issue does not answer
- a sort on the column
- the condition in an API body
- narrowing the recency from the game to the run: #700, #701
- a stored `playing` flag or a stated `stopped` endpoint: #1033 records why
  neither is built
