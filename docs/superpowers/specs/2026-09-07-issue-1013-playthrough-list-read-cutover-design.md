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
the builder page to `/filter/playthrough/`.

The mode word does not change. `MODE_PARSERS["playthroughs"]`,
`MODE_SORTS["playthroughs"]`, `QUICK_FACETS["playthroughs"]` and the preset
mode all keep the word #687 gave them.

## The fields

| field | reads | criterion |
|---|---|---|
| `game` | `player_game__game__id` | UUID set |
| `name` | `name` | string |
| `started` | `started_lower`, `started_upper` | date |
| `completed` | `completed_lower`, `completed_upper` | date |
| `is_started` | `start_recorded_at` | bool |
| `is_completed` | `completion_recorded_at` | bool |
| `days_to_finish` | both bounds, as date arithmetic | int |
| `note` | `note` | string |
| `start_note` | `start_note` | string |
| `completion_note` | `completion_note` | string |
| `created_at` | `created_at__date` | date |

`search` reads the game name, the run name and the three notes.
`game_filter` descends to `Game` through `player_game__game__id`.

`kind` is no field. The page reads ordinary runs, and #700 owns the bucket a
person can ask for.

`renamed_fields = {"ended": "completed"}` carries a bookmarked `?filter=` and
a preset an operator did not migrate.

## An endpoint is an interval

Each endpoint states a day, a month, a year or a range, and the two generated
bound columns hold what that means: the earliest day the value can name and
the latest. A filter compares against those two columns, so it states what is
certain about a value at any precision.

| the person asks | the filter reads |
|---|---|
| equals `2025-03-04` | `lower <= 2025-03-04 <= upper` |
| between two days | `lower <= end AND upper >= start` |
| after `2025-03-04` | `lower > 2025-03-04` |
| before `2025-03-04` | `upper < 2025-03-04` |
| is null | `lower IS NULL` |

Equality overlaps: a run stated as `2025` answers a question about a day in
2025, because that run may well have finished on that day. Ordering is
certain: a run stated as `2025` is after March only where the earliest day it
can name is after March.

`IS_NULL` is one act with no known day, and the two markers separate that from
an act that never happened. A person who wants "no completion at all" asks
`is_completed = false`.

No qualifier reaches the filter. #893 and #977 own asking about `~` and `?`.

## Days to finish

`games/reads/playthrough_endpoints.days_to_finish` answers
`completed_upper - started_lower`, in days, where both are known. Equal bounds
read 1. A negative span reads nothing.

The filter states the same rule in SQL, without an annotation: every
comparison is date arithmetic against `started_lower`.

| the person asks | the filter reads |
|---|---|
| equals `N` | `completed_upper = started_lower + (N - 1) days`, `N >= 1` |
| greater than `N` | `completed_upper > started_lower + (N - 1) days` |
| less than `N` | `completed_upper < started_lower + (N - 1) days`, and the span is not negative |
| between `A` and `B` | both bounds of that interval |
| is null | either bound is null, or the span is negative |

One test drives the Python read and the filter over the same rows and asserts
the same set both ways, so the two cannot drift.

## Scoping

`Playthrough` declares no manager, so every read states its own scope, and the
row can name another library's `PlayerGame`. Both scoping tables in
`games/filters.py` gain a `Playthrough` entry that states `library`,
`player_game__library`, a null `removed_at` and the ordinary kind. `PlayEvent`
leaves both tables, `MODE_PARSERS` and `_FILTER_LIST_URL`.

`GameFilter.playthrough_filter` names `PlaythroughFilter` and descends through
`player_game__game__id`. The `playthrough_count` aggregate counts
`player_games__playthroughs`.

`aggregate_to_q` reduces every related row unless the criterion carries a
scope, which counts a removed run, an imported one and a run naming another
library's tracked game. `AggregateSpec` gains `scoped: bool = False`. Where it
is set, the reducer takes the context queryset for the related model as its
condition, which is the same scope a criterion scope resolves through. Only
`playthrough_count` sets it; the filter audit (#765 to #767) owns whether the
other six follow.

## The page

`list_playthroughs` reads live ordinary runs of the library, selects the
tracked game and its catalog row, applies the filter, applies the sort and
paginates. It then numbers the page: `numbered_for(library, player_game_ids)`
takes the tracked games the page holds and counts a number across every live
ordinary run of each one. A number therefore reads the same on the list page
as on Game detail, under any filter, sort or page. This is one extra query for
each page.

`games/views/playthrough_rows.py` builds the rows, and gains the sort terms
the header needs. `create_playthrough_tabledata` and `_legacy_actions` go, and
with them the last translation from a row to a run on a screen.
`runs_for_rows` stays for the API, which #1015 owns.

Game detail's Playthrough section links `View all`, filtered to that game.

## Sorts

| key | reads |
|---|---|
| `name` | `player_game__game__sort_name` |
| `started` | `started_lower` |
| `completed` | `completed_lower` |
| `days` | the span, annotated |
| `created` | `created_at` |

`ended` becomes `completed`, which is the word the column, the command and the
screen already use. The default sort stays `-created`.

The span annotation states the read layer's rule, so a sort and a filter agree
about which run took longer.

## Quick facets

Game, Started, Completed, Days to finish, Note, Created. The bar edits a flat
criterion for each, and anything else degrades it to the read-only pill, which
is the behaviour every other mode has.

## Presets

Migration 0047 rewrites `ended` to `completed` in a playthroughs-mode preset
and in the `playthrough_filter` subtree of a games-mode preset, forward and
backward, following 0046. A preset naming a field the projection does not hold
is left alone: `renamed_fields` reads the old word, and a preset that still
fails to parse renders the mode's existing warning rather than a page that
answers 500.

## Bound columns as operands

The comparison picker offers a column of the same kind to compare against.
`_maybe_group_for` excludes every generated temporal column, because a catalog
temporal projection holds parts of a value, not a date a person compares.
Playthrough's four bound columns are dates, and comparing them answers real
questions, so an allowlist admits exactly those four:

| column | reads |
|---|---|
| `started_lower` | Started (earliest) |
| `started_upper` | Started (latest) |
| `completed_lower` | Completed (earliest) |
| `completed_upper` | Completed (latest) |

The allowlist carries the words, so the model needs no `verbose_name` and the
catalog picker is unchanged.

## Widget metadata for a handler field

A field mapped to a handler resolves no column, so the picker reads no
nullability and offers no `is null` for `started` or `completed`.
`metadata_lookup` exists for the case where the query path is not a column;
today it is refused beside a handler. It is allowed there, and resolves the
column the widget describes — `started_lower` for `started`. The refusal
stated only that a handler skips resolution, which is the very reason the
widget needs the lookup.

## Encoding

#656 left the URL encoding of a qualifier symbol to the wave that writes the
filter. It resolves here: no canonical temporal string enters `?filter=`. A
value is a plain ISO day, and a qualifier is no operand. A `%` a person types
into a text criterion is percent-encoded by `filter_url` and by the client
serializer, and escaped by Django before it reaches `LIKE`. One test states
the round trip through both.

## The statistics links

`games/views/stats_links.py` constructs `PlaythroughFilter` at its six sites.
Its parity fixture states a legacy row and converts the library, so a link
count and the stat it links from still agree while `stats_data.py` reads legacy
rows. #1014 moves the queries and takes the conversion out of the fixture.

## The contract

`tests/test_filter_tree_contract.py` maps `"playthrough"` to
`PlaythroughFilter`, and `ts/elements/filter-tree/fixtures.json` states cases
over the projection's fields. The vitest serializer writes the canonical JSON,
and the pytest side asserts each case is equivalent to the Python filter's
`to_q()`, so the TypeScript serializer cannot drift from the new field set.

## Tests

- Each modifier against each precision, for both endpoints, including a value
  stated as a month and one stated as a range.
- The two markers, against an act with no day.
- `days_to_finish` parity, the read against the filter.
- Scoping: another library's run, a removed run and an imported one reach
  neither the page nor `playthrough_count`.
- Numbering: the number a filtered, sorted, paginated page prints equals the
  number Game detail prints.
- Every sort key, and the header parity guard.
- The quick bar round trip, including `completed`.
- `?filter=` naming `ended`, through `renamed_fields`.
- Migration 0047, forward and backward, over a preset of each mode.
- The `%` round trip, Python and TypeScript.
- The builder page for the playthrough mode answers 200 and offers the four
  bound columns.

## Out of scope

| what | who |
|---|---|
| statistics queries | #1014 |
| the API bodies and the segmented endpoint screen | #1015 |
| `removed_at` as a picker operand | #977 |
| asking about a qualifier | #893, #977 |
| a bucket a person can filter by | #700, #701 |
| `PURCHASE_SORTS["finished"]`, `GAME_SORTS["finished"]` | #1026 |
| taking `games_playevent` away | #771 |

## Rollback

One revert. The filter class, the page, the sorts, the facets and the contract
move together, and migration 0047 states its own backward step.
