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
| Never played | no completion | no day at all |

A run whose completion is stated carries no word. It is not unfinished, so no
clock speaks about it.

**Never played is a scope addition.** #1033 names two words. Two words cannot
cover a run at a game nobody has played yet, and #679 gives every tracked game a
run from the moment the library tracks it, so that run is the common case rather
than the odd one. Calling it Dormant would say a game tracked this morning went
quiet. The third word says what is true: no day is known. The verdict goes into
#1033 and into the wave design, which names two words, not only here.

**The third word is not `Unplayed`.** `PlayerGameStatus` already spells that, and
Game detail prints a status beside these rows. Two columns reading `Unplayed`
about one game, one of them a person's statement and the other a clock's silence,
say the same word about different things.

## The last played day

The read takes a run and answers a day, or nothing.

1. The latest live session at the run's game, as the library sees sessions.
2. Where the game has no such session, the run's own `started_lower`.
3. Neither: nothing, which is Never played.

The order is a preference, not a maximum: a game with sessions never reads its
start day, even where the start is the later of the two. #1033 states the
fallback this way.

A dayless start reads as Never played. The act is stated and the day is not, and
this read answers days.

**Both sides answer a day, never an instant.** A session states a timestamp and
a start states a date, so the session side reads `TruncDate` in the viewer's
zone and the comparison is `>= boundary_day` on both. One space, one operator:
a session at 23:30 local and a start on the same date read alike, and no
threshold day is one hour long twice a year. Comparing the timestamp against a
midnight instant instead would disagree with the date side at the boundary, and
would name a midnight that does not exist in a zone whose transition is at 00:00.

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
| `zone` | the viewer's `DISPLAY_TIME_ZONE` |
| `boundary_day` | today in that zone, minus that many days |

A day at or after `boundary_day` is recent, and that is the whole comparison.
One clock is resolved per request and both the badge word and the recency
sentence read it, so a threshold changed a second ago cannot move one and leave
the other.

## The two annotations

The method belongs to a **queryset**, not to a manager:
`PlaythroughQuerySet.annotated_for_filtering(clock=None)`, reached through
`objects = Manager.from_queryset(PlaythroughQuerySet)()`. `with_filter_aliases`
reads the method off a queryset it was handed — `for_validation` gives it
`model._default_manager.none()` — so a manager-only method is invisible to it,
and `library_runs()` would have nothing to chain. The queryset declares no
`alive()` and no `for_library()`, so every read still states its own scope, and
`GameQuerySet.annotated_for_filtering` is the shape to copy.

| alias | is |
|---|---|
| `last_played_day` | a correlated `Subquery`: the live sessions at the run's game, newest first, one row, truncated to a day in the clock's zone |
| `activity` | a `Case`: null where the completion is stated, else one of the three words |

The subquery states the library itself, as `game__library` against the run's own
`library` column. It therefore needs no library argument, and one run never
reads another library's sessions.

`activity` reads `last_played_day` first and `started_lower` second, in the order
the table above states. The clock states the threshold and the zone alone. A
null clock reads the registry default in UTC, which is what a filter compiled
for validation gets, and what the several test harnesses get that build a
context from `with_filter_aliases(model._default_manager.all())`. Neither knows
a viewer, and the validation context executes nothing.

**The method is idempotent.** It answers `self` where `activity` is already an
annotation. Django's `add_annotation` refuses an alias that names a model field
and nothing else: a second annotate silently replaces the first, so a caller
that reached an already-annotated queryset would swap one clock for another with
no error. The guard makes the second call a statement of the same fact.

**Two reads annotate, and neither builds on the other.**

| read | feeds | annotates |
|---|---|---|
| `library_runs()` | the Playthrough list's rows, the Playthrough API, both filter-context builders | yes |
| `numbered_for()` | Game detail's rows | yes |
| `live_ordinary_runs()` | the commands | no |

`numbered_for()` filters `Playthrough.objects` itself rather than narrowing
`library_runs()`, so it cannot inherit the alias; the list page reads its numbers
from it and its rows from `library_runs()`, and Game detail reads both from it.
Dropping either annotate leaves one screen blank. `live_ordinary_runs()` stays
plain, because commands read it and a write path resolves no display setting.

`library_runs()` is also the one thing that puts the alias on a filter path:
nothing in the filter chain calls `with_filter_aliases`, whose only use outside
tests is the validation context. The API list pays the subquery too, and its
`limit=0` is unbounded while its schema states no condition; the read it uses may
drop the alias where measurement says the cost is real.

## The filter

`PlaythroughFilter.activity`, a `ChoiceCriterion` over the three words. Its
`FilterField` states a handler, and **the handler delegates**:
`criterion.to_q("activity")`.

The delegation is the point. `ChoiceCriterion` is a set criterion: its value is
a list and its modifiers are `Modifier.for_multi()`, so a handler that built
`Q(activity=<word>)` itself would read one word out of a list and ignore the
modifier that says whether to include it or exclude it. Delegating gives the
alias every set behaviour the criterion already has, `_not_in_q` included.

The handler exists only to keep `field_metadata` off the column. A `lookup`
resolves a model field or raises, by design — a mis-typed lookup must fail loudly
rather than render an empty picker — and `activity` names no column. A handler
skips that resolution, which is the one exemption already in the machinery.

A plain alias comparison is also what makes the field composable. `aggregate_to_q`
and `relation_to_q` compile a nested `PlaythroughFilter` against
`context.queryset_for(Playthrough)`, which is `library_runs()`, and that
queryset carries the alias. A `Q` that named the sessions itself would compile,
but the clock would have nowhere to enter: a field handler reads the criterion
alone.

`common/criteria.py` gains one field: `FilterField.choices`. A handler field
resolves no column, so `_static_choices` answers the widget nothing and the
panel `FilterSelect` would render with no options and no `search_url`.
`field_metadata` prefers the declared choices and falls back to the column's.

A handler field is also reported as not nullable, so the picker offers no
`IS_NULL`. Nothing is lost: the question it would ask — is this run finished — is
`is_completed`, which the filter already states.

`EXCLUDES` on the alias keeps a completed run, because `_SetCriterion._not_in_q`
ORs `activity__isnull=True` into the Q itself. It is not ORM negation that keeps
the row: Django adds a null guard for a negated nullable *column*, and `activity`
is a `Case`, whose nullability it does not know. "Not playing" therefore means
dormant, never played or finished, and a test pins it.

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
| Never played | a `Pill` reading `Never played`, nothing beside it |
| completed | `-` |

The column is added to `playthrough_tabledata`, which drops columns by label and
keys its sort map by label, so both callers are read when it lands.

The recency sentence reads the same day the word read, in the viewer's zone:
`today`, `yesterday`, `N days ago`, `N months ago`, `N years ago`. The column
carries no sort key.

## The words beside the statuses

A condition is a clock's answer about one run. A status is a person's statement
about a game. All three words meet a status that sounds like them, and none of
them moves it:

| condition | the status it sounds like | why they differ |
|---|---|---|
| Dormant | Abandoned | the clock counts days; only a person abandons a game |
| Playing | Played | Played says a verdict is not stated yet, and stays true for years |
| Never played | Unplayed | Unplayed is stated at track time; the condition means no day is known, which a session at an untouched status also ends |

A row may read status Played and condition Dormant, or status Unplayed and
condition Playing, and both pairs are correct. `docs/vocabulary.md` records the
three pairs under Settled, and `docs/STATUSES.md` names the difference where it
lists Abandoned.

Two places say the projection declares no manager: `CLAUDE.md`, and the
docstring of `filter_queryset_for_library` in `games/filters.py`. It declares one
now, holding the alias method alone, and both lines say so.

## Verification

| what | how |
|---|---|
| the three words | a table over session recent, session old, no session, each against a start day present, absent, dayless, and against a stated completion |
| the threshold | 30 by default; a personal 7 moves a run from Playing to Dormant with no other change |
| the boundary | a session at 23:30 local on `boundary_day` and a start on that date read alike, in a zone whose offset moves that week |
| the filter | each word narrows the list to the rows the read gives it, two words at once narrow to their union, and `EXCLUDES` keeps the completed rows |
| composition | a nested `PlaythroughFilter` inside `playthrough_count` compiles and executes; a blob naming `activity` passes eager validation, which is what fails if the alias method sits on the manager |
| the facet | the quick-bar contract test, which counts one rendered widget per facet and so fails on an optionless picker, and the round trip from bar to URL to bar |
| the alias | annotating twice states one clock, not the second |
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
