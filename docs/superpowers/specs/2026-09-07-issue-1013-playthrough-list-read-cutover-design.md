# Read Playthroughs on the list page

The Playthrough list page reads the `Playthrough` projection, and so does
everything that orders and narrows it: the filter, its relations, the sort
keys, the quick facets and the saved presets. No screen reads
`games_playevent` after this issue. The legacy table stays until #771.

## Why these move together

`games/views/playthrough.py` builds one queryset. The filter, the sorts and
the quick facets all name columns on the model that queryset reads, and the
nested builder ships a field registry derived from the filter class. Moving
the page without the filter leaves a page that cannot answer `?filter=`, and
moving the filter without the page leaves a filter no view reads. The
statistics links construct the same filter class, so they travel too — the
statistics *queries* are #1014.

## The filter names its model

`PlayEventFilter` becomes `PlaythroughFilter` over `Playthrough`. The name is
derived, not chosen: `filter_for_model` resolves a model key to
`Model.__name__ + "Filter"`, so a filter over `Playthrough` answers to one
name. `FILTER_MODE_MODELS["playthroughs"]` states `"playthrough"`, which moves
the builder page to `/tracker/playthrough/filter`.

The mode word does not change. `MODE_PARSERS["playthroughs"]`,
`MODE_SORTS["playthroughs"]`, `QUICK_FACETS["playthroughs"]` and the preset
mode all keep the word #687 gave them.

## The fields

| field | reads | criterion |
|---|---|---|
| `game` | `player_game__game__id` | UUID set |
| `name` | `name` | string |
| `started` | `started`, `started_lower`, `started_upper` | date |
| `completed` | `completed`, `completed_lower`, `completed_upper` | date |
| `is_started` | `start_recorded_at` | bool |
| `is_completed` | `completion_recorded_at` | bool |
| `days_to_finish` | both bounds, as date arithmetic | int |
| `note` | `note` | string |
| `start_note` | `start_note` | string |
| `completion_note` | `completion_note` | string |
| `created_at` | `created_at__date` | date |

`search` reads the game name, the run name and the three notes. A blank-named
run renders as `Playthrough N`, which is counted at read time and stored
nowhere, so that text answers no search. A person searches the game or a note.

`game_filter` descends to `Game` through `player_game__game__id`.

`kind` is no field. The page reads ordinary runs, and #700 owns the bucket a
person can ask for.

`renamed_fields = {"ended": "completed"}` carries a bookmarked `?filter=` and
a preset an operator did not migrate.

## An endpoint is an interval

Each endpoint states a day, a month, a year, a decade or a range, and the two
generated bound columns hold what that means: the earliest day the value can
name and the latest. Both ends are inclusive. A range can leave one end open,
and that end's bound column is null while the endpoint itself states a value.
An absent lower bound is every day before the other end; an absent upper bound
is every day after it.

Every comparison first states that the endpoint holds a value
(`started IS NOT NULL`), then reads the bounds, with an absent bound reading as
unbounded rather than as no match.

| the person asks | the filter reads |
|---|---|
| equals `X` | `lower <= X` and `X <= upper` |
| between `A` and `B` | `lower <= B` and `A <= upper` |
| not equals `X` | `lower > X` or `upper < X` |
| not between `A` and `B` | `lower > B` or `upper < A` |
| after `X` | `lower > X` |
| before `X` | `upper < X` |
| is null | the endpoint states no value |
| is not null | the endpoint states a value |

Equality overlaps: a run stated as `2025` answers a question about a day in
2025, because that run may well have finished on that day. Ordering is
certain: that run is after March only where the earliest day it can name is
after March. Negation is certain in the same way: a run is *not* that day only
where no day it can name is that day.

A run whose act is recorded with no day therefore answers neither the equality
nor its negation. That is the honest answer, and the two markers are how a
person asks the other question: `is_completed = false` is no completion at
all, while `completed is null` is no known completion day, act or no act.

No qualifier reaches the filter. #893 and #977 own asking about `~` and `?`.

The three-valued hole in `relation_to_q`'s `ALL` quantifier
(`common/criteria.py`, `related.filter(~sub.to_q(...))`) predates this issue
and stays. #765 to #767 own it.

## Days to finish

`games/reads/playthrough_endpoints.days_to_finish` counts the days a run
touched, both ends included: `completed_upper - started_lower`, plus one. A
same-day run reads 1, a run finished the next day reads 2, and a run stated as
one month at both ends reads 31. A negative span and a missing bound read no
answer, and the count never reads 0.

The read counted differently until now. It answered the plain difference, with
a floor: a same-day run read 1 and so did a run finished the next day, because
the legacy column read that way. Two spans on one number is a wrong answer, and
no arithmetic states it, so it is corrected here rather than filtered around.
Every run longer than a day now reads one higher than it did. The legacy
column keeps its own arithmetic, which nothing reads after this issue; #771
takes it.

The filter states the same rule in SQL, without an annotation: every
comparison is date arithmetic against `started_lower`.

| the person asks | the filter reads |
|---|---|
| equals `N` | `completed_upper = started_lower + (N - 1) days` |
| greater than `N` | `completed_upper > started_lower + (N - 1) days` |
| less than `N` | `completed_upper < started_lower + (N - 1) days`, and the span is not negative |
| between `A` and `B` | both bounds of that interval |
| not equals `N` | the value is known and is not `N` |

Every row states that both bounds are known and the span is not negative, so a
run with no answer matches no comparison, and `N` below 1 matches nothing. The
field offers no `is null`: it names no column, so the widget can state none,
and a person asks `is_started` or `is_completed` instead.

One test drives the Python read and the filter over the same rows and asserts
the same set both ways, so the two cannot drift.

Three things change for a person. Every run longer than a day reads one day
more. `days_to_finish = 0` matched every unstarted row against the legacy
persisted column and now matches nothing, because zero is no answer the read
gives. A sort by days puts the rows with no answer at the end, in both
directions, where the persisted column put the zeros first.

Migration 0047 rewrites no number a preset asks for. A count means what the
screen prints, a comparison can ask for a bound or a pair of them, and shifting
an integer states an intent the preset never carried.

## Scoping

`Playthrough` declares no manager, so every read states its own scope, and the
row can name another library's `PlayerGame`. Both scoping seams in
`games/filters.py` learn the projection: `filter_query_context_for_library`
gains an entry, and `filter_queryset_for_library` gains a second special case
beside `Game`, because it otherwise calls `model.objects.for_library`, which
`Playthrough` does not answer. `games/api.py` reaches that function with a
model key a client states, so neither seam is optional. Both state `library`,
`player_game__library`, a null `removed_at` and the ordinary kind.

`PlayEvent` leaves both seams, `MODE_PARSERS` and `_FILTER_LIST_URL`.

`GameFilter.playthrough_filter` names `PlaythroughFilter` and descends through
`player_game__game__id`.

## The count of playthroughs

`TrackGame` states a run, and `RemovePlaythrough` refuses the last one, so
every tracked game holds at least one run. A count of runs would therefore
read 1 for a game nobody has played, and `playthrough_count = 0` would match
nothing.

`playthrough_count` counts the runs whose completion is stated. That is the
number `Played N times` already prints on Game detail, and it is what the
legacy count meant, because a legacy row mostly recorded a finish.

`aggregate_to_q` reduces every related row unless the criterion carries a
scope. `AggregateSpec` gains `base_scope: OperatorFilter | None`: a static
sub-filter the spec states, resolved the same way a criterion scope is, so it
runs through `context.queryset_for(Playthrough)` and takes the library, the
kind and the removal mark with it. Where a criterion states a scope of its
own, the two hold together. `playthrough_count` states
`base_scope=PlaythroughFilter(is_completed=…)` and is the only spec that
states one; the other six keep today's reach, and the filter audit (#765 to
#767) owns whether they follow.

The accessor is two hops, `player_games__playthroughs`. The aggregate drift
guard in `tests/test_filters.py` resolves an accessor with
`Model._meta.get_field`, which answers a field name and refuses a path, so it
learns to walk one.

## The page

`list_playthroughs` reads live ordinary runs of the library, selects the
tracked game and its catalog row, applies the filter, applies the sort and
paginates. It then numbers the page: `numbered_for(library, player_game_ids)`
takes the tracked games the page holds and counts a number across every live
ordinary run of each one. A number therefore reads the same on the list page
as on Game detail, under any filter, sort or page. This is one extra query for
each page, and it reads every run of the games the page names, not only the
rows rendered.

`display_name` refuses a live ordinary row it did not number, so the page's
scope must state the same four things `numbered_for` states. They are stated
once, in one place, and both reads take it.

`games/views/playthrough_rows.py` builds the rows. Game detail renders the
same builder and states no `?sort=`, so a sort key on every column would give
that page four headers that reload it and change nothing. The caller states
whether its columns sort. The list page sorts; the section does not.

`create_playthrough_tabledata` and `_legacy_actions` go, and with them the last
translation from a row to a run on a screen. `runs_for_rows` stays for the API,
which #1015 owns.

Game detail's Playthrough section links `View all`, filtered to that game.

## Sorts

| key | column | reads |
|---|---|---|
| `name` | Game | `player_game__game__sort_name` |
| `started` | Started | `started_lower` |
| `completed` | Completed | `completed_lower` |
| `days` | Days to finish | the span, annotated |
| `created` | Created | `created_at` |

The Playthrough column carries no sort key: a number is counted across one
game's runs, so ordering every row by it means nothing.

`ended` becomes `completed`, which is the word the column, the command and the
screen already use. The default sort stays `-created`.

The span annotation states the read layer's rule, so a sort and a filter agree
about which run took longer. `Annotations` in `games/sorting.py` is typed as a
dictionary of `Aggregate`, which a span expression is not, so the alias widens
to the expression base class. The comment above `PLAYTHROUGH_SORTS`, which
states that every key is a direct field path or a persisted column, is
rewritten in the same edit.

## Quick facets

Game, Started, Completed, Days to finish, Note, Created. The bar edits a flat
criterion for each, and anything else degrades it to the read-only pill, which
is the behaviour every other mode has.

## Presets

Migration 0047 rewrites `ended` to `completed`, forward and backward,
following 0046. It walks two places, and only those two: the criterion blob of
a playthroughs-mode preset with the `playthrough_filter` subtree of a
games-mode preset, and the stored sort string. `ended` is a common word, so
the walk is scoped rather than applied at any depth as 0046 could safely be.

The sort string needs its own step. `renamed_fields` is read by
`from_json` over the criterion blob alone, while a sort travels in
`find_filter["sort"]` and is matched against `PLAYTHROUGH_SORTS` by
`parse_sort_terms`. A preset holding `sort=-ended` that no migration rewrites
loads with an unknown-sort toast every time and falls back to `-created`. The
migration rewrites the token and keeps its `-`.

A preset naming a field the filter no longer holds is not refused: `from_json`
walks the dataclass fields and never reads a leftover key, so the criterion is
dropped and the filter answers more rows than it did, with no message. A
`field_comparisons` entry naming a retired column does raise, and
`apply_structured_filter` turns that into the mode's existing warning. Neither
path answers 500. The migration is what keeps a preset meaning what it said.

## Comparison operands

The picker walks one hop from the model to collect a column a person can
compare a field against. On a projection that hop follows the `library`
foreign key into every reverse relation of `UserLibrary`, which offers 55
columns that answer nothing about a run. A projection's `library` is scoping,
not data: the walk never follows it, on any projection.

What is left is the run's own columns and `player_game__*`. The `game__*`
columns today's picker offers on the legacy model go, because a run reaches
its game in two hops. Comparing a run against its game's columns is for the
filter audit (#765 to #767).

Four generated columns are added back. `_maybe_group_for` excludes every
column generated from a temporal value, and the catalog's bounds are excluded
for the same reason they always were: nobody has scoped them in. Playthrough's
four are scoped in here, through an allowlist that carries both the column and
the words, because `_own_comparable_columns` otherwise reads the field's
`verbose_name` and prints `Started Lower`.

| column | reads |
|---|---|
| `started_lower` | Started (earliest) |
| `started_upper` | Started (latest) |
| `completed_lower` | Completed (earliest) |
| `completed_upper` | Completed (latest) |

## Widget metadata for a handler field

A field mapped to a handler resolves no column, so the picker reads no
nullability and offers no `is null` for `started` or `completed`.
`metadata_lookup` exists for the case where the query path is not a column, and
two gates keep it away from a handler: `FilterField.__post_init__` refuses the
pair, and `field_metadata` resolves a column only where the handler is absent.
Both learn the same rule — a handler field states its widget's column through
`metadata_lookup`, and nothing else changes about it. `started` names
`started_lower`, `completed` names `completed_lower`.

`days_to_finish` names no column and gains nothing here, which is why it
offers no `is null`.

## Encoding

#656 left the URL encoding of a qualifier symbol to the wave that writes the
filter. It resolves here: no canonical temporal string enters `?filter=`. A
value is a plain ISO day, and a qualifier is no operand. A `%` a person types
into a text criterion is percent-encoded by `filter_url` and by the client
serializer, and Django parameterizes the `LIKE`, so nothing escapes. One test
states the round trip through both.

## The statistics links

`games/views/stats_links.py` constructs `PlaythroughFilter` at its six sites.
The all-time link reads `is_completed = true`, which is the act, not the day: a
completion recorded with an unknown day is a finish. The per-year link reads
`completed` between that year's ends, which overlaps, so a run stated as a
whole year answers for every year it touches.

Its parity fixture states a legacy row and converts the library, which gives
day-precision endpoints with both markers set — the one shape where the marker
and the bound agree and an overlap is exact. The fixture therefore cannot see
either divergence, and #1014, which moves the statistics queries, inherits both
definitions and owns proving them.

## The contract

`tests/test_filter_tree_contract.py` maps `"playthrough"` to
`PlaythroughFilter`, and `ts/elements/filter-tree/fixtures.json` states cases
over the projection's fields. The vitest serializer writes the canonical JSON,
and the pytest side asserts each case is equivalent to the Python filter's
`to_q()`, so the TypeScript serializer cannot drift from the new field set.

## Tests

- Each modifier against each shape, for both endpoints: a day, a month, a
  year, a decade, a range, a range with an open start and one with an open end.
- An act recorded with no day matches neither an equality nor its negation, and
  answers `is null`.
- The two markers, against an act with no day.
- `days_to_finish` parity, the read against the filter, over spans of -1, 0, 1,
  2 and 30 and over a month-precision endpoint. The read answers 1, 2 and 31
  for a same-day run, a next-day run and a month-to-month run, and the row on
  the screen prints what the read answers.
- Scoping: another library's run, a removed run and an imported one reach
  neither the page nor `playthrough_count`.
- `playthrough_count` reads 0 for a tracked game nobody finished, and equals
  the `Played N times` number.
- Numbering: the number a filtered, sorted, paginated page prints equals the
  number Game detail prints.
- Every sort key, the header parity guard, and Game detail rendering no sort
  header.
- The quick bar round trip, including `completed`.
- `?filter=` naming `ended`, through `renamed_fields`.
- Migration 0047, forward and backward, over a preset of each mode and over a
  preset holding `sort=-ended`.
- The `%` round trip, Python and TypeScript.
- The builder page for the playthrough mode answers 200, offers the four bound
  columns, and offers no `library__*` column.

## Out of scope

| what | who |
|---|---|
| statistics queries | #1014 |
| the API bodies and the segmented endpoint screen | #1015 |
| comparing a run against its game's columns | #765 to #767 |
| the `ALL` quantifier's three-valued hole | #765 to #767 |
| `removed_at` as a picker operand | #977 |
| asking about a qualifier | #893, #977 |
| a bucket a person can filter by | #700, #701 |
| `PURCHASE_SORTS["finished"]`, `GAME_SORTS["finished"]` | #1026 |
| taking `games_playevent` away | #771 |

## Rollback

One revert. The filter class, the page, the sorts, the facets and the contract
move together, and migration 0047 states its own backward step.
