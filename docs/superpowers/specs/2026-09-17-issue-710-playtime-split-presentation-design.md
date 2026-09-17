# Present tracked and historical playtime separately

Date: 2026-09-17

Issue: [#710](https://github.com/KucharczykL/timetracker/issues/710)
Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601)
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md)

## Purpose

A playtime figure now sums two sources. A person who sees `242 h` cannot tell
whether the library tracked those hours as sittings or whether somebody typed
them in. This issue states the split wherever a total includes historical
playtime, and states the plain total everywhere else.

Nothing is computed here. #709 already answers `PlaytimeBreakdown(tracked,
historical)` from every figure that Python reads. This issue is presentation,
one component, and five surfaces.

## What #709 leaves

- `total_playtime`, `game_playtime`, `game_playtime_between`,
  `playtime_by_platform`, `playtime_by_month` and `playtime_between_each`
  answer `PlaytimeBreakdown`, whose `total` is derived.
- `tracked_summed_by_game(library, year=…)` and
  `historical_summed_by_game(library, within=…)` are the two per-game halves,
  each NULL for a game that has no row in that source.
- The stats top-10 card annotates `total_playtime` alone. The #709 review
  removed the two halves from that query: each half is a correlated subquery,
  Django compiles an annotation again wherever `F()` names it, and
  `filter(total_playtime__gt=0)` repeats it once more, so the halves cost six
  subplans per visible game for output nothing rendered.
- Every list column, sort key and filter states one number and stays that way.
  A column sorts one way.

## The component

`PlaytimeSplit` in `common/components/domain.py`, beside `Duration`.

### Two lines, not one

The wave states one line, `242 h · 142 h tracked · 100 h historical`. This
issue renders two: the total in the surface's own type, and the split beneath
it in micro text.

The one-line form was mocked at the real widths of all five surfaces before
this choice. In the account menu, whose panel is `w-72` with a label on the
left, it wraps to three lines and the two figures break apart. In the Library
card, whose value is `text-type-title`, a title-size total followed by two
body-size figures reads as three unrelated numbers. Two lines survive every
surface unchanged, keep the total at the prominence each surface already gives
it, and read as a footnote to it, which is what the split is.

A `layout=` parameter, inline on wide surfaces and stacked on narrow ones, was
rejected: it buys one better line on two surfaces and costs a decision at
every call site, forever.

### No split when there is nothing to split

The second line is omitted when the historical part is zero. The component
then renders exactly what the surface rendered before this issue, which is why
`render_pages` can attribute every differing file: a library with no record
sees no change at all.

### One popover per figure

The total is today's `Duration`: a popover trigger whose panel states the same
value under the other duration profiles, and a link when the surface has one.
The two parts are `DurationText`, visible text plus their own `sr-only` words.

Three popovers per figure was rejected. The stats page would carry thirty
panels whose content is the profile table three times over, and each needs its
own `id_scope` because `Popover` hashes its content for its DOM id.

Putting the split inside the existing popover panel was rejected as well: the
outcome of this issue is that a person *sees* how much was tracked, and a
panel is reached by hover.

A screen reader hears the total, then the parts: "242 hours. 142 hours
tracked, 100 hours historical."

### `PlaytimeBreakdown` moves to `games/reads/sums.py`

The component takes the breakdown, not two `timedelta` arguments, because a
compound value passed between modules gets a name.

It cannot take it from `games/reads/playtime.py`. That module imports
`games.filters`, so a component importing it would pull the filter vocabulary
into every module that imports `common.components`, and put `common` one
edit away from a cycle with `games`.

`games/reads/sums.py` already holds what every playtime sum shares — `ZERO`,
`Playtime`, `PlaytimeSum`, `UnscopedSum` — and imports only Django and
`games.reads.unscoped`. `PlaytimeBreakdown` belongs there, and
`playtime.py` re-exports it, as its `__all__` already names it.

## The surfaces

### Game detail headline

The `hours` stat in the header row. `_stat_popover` already takes a `details`
slot for the profile alternates rather than nesting a second popover, so the
split renders as the stat's value and the alternates stay where they are.

Its figure is `game_playtime(library, game)`, which already answers a
breakdown. Every other header stat reads sessions and does not change: a
record states no sitting, so it moves no session count, no average and no play
range.

### The stats page, every playtime row

The `Hours` row, the twelve month rows, the platform rows and the game rows
all state the split.

The wave lists the totals and the top-10 rows only. This issue takes every
playtime row on the page instead, because a page that states a split for two
figures and a bare total for twenty-four teaches that the bare ones have no
historical part, which is false. The month and platform rows already carry a
breakdown from #709 and render `.total` today.

### The stats game rows, and the query that feeds them

`_two_col_table` calls `list(items)` on the card's queryset, which is every
game the library can see that has any playtime, and then renders
`_LIST_CAP` of them. The card therefore loads the whole played library to
print five rows, and the key that holds it is named `top_10_games_by_playtime`
while the cap is five and the queryset is unbounded.

The halves come back as a second query over the keys the card renders:

1. `compute_stats` reads the card's rows itself, ordered and sliced to the cap,
   and counts the rest for the "View all" affordance.
2. One further query annotates `tracked` and `historical` over those keys
   alone, and the rows carry a `PlaytimeBreakdown`.

The plan of the query over every visible game does not grow, and a test
asserts that by counting `games_playersession` and `games_historicalplaytime`
scans, as `tests/test_sorting.py` already does for the sort keys.

Two consequences, both stated rather than worked around:

- The key is renamed. `top_10_games_by_playtime` becomes `games_by_playtime`,
  a list, beside `games_by_playtime_count`. The incumbent name states a cap it
  does not hold and a bound it does not have; a second name beside it would
  leave the lie in place. Eleven references in four files.
- `stats_content` renders a list rather than slicing a queryset. Its "View
  all" link reads the count key.

A per-game reader in Python over the rendered rows was rejected: it answers
the same numbers in twenty queries rather than one.

### The navbar figures

`Today` and `Last 7 days` state the split and carry no link.

Both link to the day-filtered session list today. That list cannot show a
record, so the link opens a page that sums less than the figure it came from,
and the person has no way to see why. #709 recorded this and left the decision
here.

The link goes away until #1105 gives the stats and navbar links a predicate
that counts a record by containment, as the statistic does. #1105 restores it.
An affordance that lies is worse than one that is absent for a release, and the
figures stay where they are.

The stats page's links state the same gap and stay where they are. #709 left
this issue the navbar decision alone and gave every other link to #1105, which
repairs them together with one predicate. Removing four kinds of link here and
restoring them there would be the same work twice, and the stats links at
least state a year or a month that the destination honours.

The two `filter_url` calls in `model_counts` go with the links.

### The Library page's Playtime card

The card states the library's whole playtime with the split beneath it. Its
`title` becomes "Tracked sessions and historical records".

It states a count of sessions plus records today, which #1097 left for this
issue. Adding two populations of different things into one number answers no
question a person asks.

`StatisticCard`'s `value` widens from `str | int` to accept a node. Every
other card keeps passing an integer.

## Not this issue's

- **The Playthroughs table.** #1119 owns presenting a game's runs, as rows
  whose gutter braces a record naming several of them and on a year axis. The
  wave gives this issue a per-run playtime column that adds a record's hours to
  each run it names. A column cannot state that: added to every run, it sums
  past the game's total; left out, a game whose whole playtime is one shared
  record reads zero against every run. #1119 states it structurally. This
  issue leaves the table alone and adds no column that can over-sum.
- **Game detail's Historical playtime section header.** It keeps its count
  badge and states no playtime. The wave gives it the split. That section
  renders only on Game detail, whose headline states the same game's split
  three rows above, and the section's own sum is the historical part by
  definition. Every other section on the page carries a count badge.
- **The link predicates** under the stats "View all", the month rows, the
  top-10 rows and the platform rows: #1105.
- **A stated session count on a record**: #1106.

## Amendments to the wave

Recorded in the wave design document as part of this issue:

1. The split renders on two lines, not one.
2. The Historical playtime section header keeps its count badge.
3. The per-run column moves to #1119, with the run-row shape.
4. Every playtime row on the stats page states the split, not the totals and
   the game rows alone.

## Verification

- A figure whose historical part is zero renders exactly what it renders
  today, on every one of the five surfaces. This is the `render_pages`
  invariant: a library with no record produces no differing file.
- A figure with a historical part states the total, the tracked part and the
  historical part, and the three are consistent: `tracked + historical ==
  total`, asserted against the reader rather than against typed-in numbers.
- The component renders one popover, and the spoken form states the total
  first and then each part.
- The stats page states the split on the `Hours` row, every month row, every
  platform row and every game row, and the classification in `STATS_SOURCES`
  still names every `StatsData` key.
- The stats card's first query plans the same number of source scans as it
  does today; the halves arrive in one further query.
- The navbar figures carry no link, and the account menu renders at 390 px
  with no horizontal scroll.
- The Library card states a duration, and the other three cards still state
  integers.
- The full `make check` gate passes, `e2e/` included.

## Mockups

- [Three split layouts across five surfaces](assets/2026-09-17-issue-710-playtime-split/split-layouts.html)
  — the one-line, two-line and hybrid forms at each surface's real width.
