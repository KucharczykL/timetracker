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

The second line is omitted when the historical part is zero, and the component
returns the bare `Duration` or `DurationText` node — no wrapper, no added
class. It then renders exactly what the surface rendered before this issue,
which is what lets `render_pages` attribute every differing file.

The component alone changes nothing for a library with no record. Two other
decisions in this issue do change such a page — the navbar loses its links and
the Library card states a duration instead of a count — and the verification
section names them.

### One popover per figure, and none where the surface owns one

`PlaytimeSplit(breakdown, durations, *, id_scope=None, popover=True, link=None)`.

By default the total is `Duration`: a popover trigger whose panel states the
same value under the other duration profiles, and a link where the surface
has one. The two parts are `DurationText`, visible text plus their own
`sr-only` words.

`link` is forwarded to `Duration`, which already takes it. The month rows and
the platform rows put their filter link on the figure itself, and this issue
leaves those links in place for #1105 to repair, so the component cannot hide
the argument. `link` with `popover=False` is refused rather than ignored:
`DurationText` renders no anchor, so a caller stating both has asked for
something the component does not render.

Three popovers per figure was rejected. The stats page would carry thirty
panels whose content is the profile table three times over, and each needs its
own `id_scope` because `Popover` hashes its content for its DOM id.

Putting the split inside the existing popover panel was rejected as well: the
outcome of this issue is that a person *sees* how much was tracked, and a
panel is reached by hover.

`popover=False` renders the total as `DurationText` and no trigger. One
surface passes it: Game detail's `hours` stat, where `_stat_popover` is itself
the `Popover` and puts the alternates in its `details` slot rather than
nesting a second one. A component that owned a `Duration` there would put
`<pop-over>` inside `<pop-over>` and give one stat two tooltips.

The argument states a fact about the host — whether it already owns a popover
— so no call site weighs anything, which is what separates it from the
rejected `layout=`. Four of the five surfaces take the default; Game detail
states the exception, and it states it because of the markup it sits in.

`id_scope` is what `Popover` needs for its DOM id, so it is required with a
popover and refused without one. Under `popover=False` nothing would read it.

Every `id_scope` in use today is kept verbatim —
`duration-stats-total-hours`, `duration-stats-month-<n>`,
`duration-stats-platform-<pk>`, `duration-stats-game-<pk>-playtime`,
`navbar-today`, `navbar-last-7` — and so is `popover-hours`. Three test
modules slice the rendered page on those strings.

### Two block lines, not a flex column

The two lines are block-level children of one wrapper, and the wrapper adds
no flex. `Popover` renders `<pop-over>` with `self-start` and
`inline-flex`, so inside a flex column the total would pin to the left edge
while the micro line below it inherited the host's alignment: right-aligned in
the account menu, right-aligned in the stats table's second column. As block
lines in a line box, both honour the host's `text-align` and the component
states no alignment of its own.

On Game detail the wrapper is a `Span` with `block` children, because
`_stat_popover` renders its value inside a `<span>` and a `<div>` there is
block-in-inline. The balance check in `tests/test_rendered_pages.py` counts
`<div>` only, so nothing else would catch it.

That stat's row is `flex gap-2 items-center`, so a two-line value centres the
icon against both lines and drops it half a line relative to the total. The
row states `items-baseline` instead, which is the one host change this
surface needs.

A screen reader hears the total, the popover's own reveal button where there
is one, and then the parts: "242 hours. More information, button. 142 hours
tracked, 100 hours historical." The button sits between them because
`Popover` renders it after its trigger; the split states no `aria-live` and
reorders nothing. The `·` between the parts is `aria-hidden`, or a reader
announces it as "middle dot".

### `PlaytimeBreakdown` moves to `games/reads/sums.py`

The component takes the breakdown, not two `timedelta` arguments, because a
compound value passed between modules gets a name.

No cycle forces the move. `common/components/domain.py` already imports
`games.models` at module scope, and `games/filters.py` imports
`common.criteria`, not `common.components`. The cost of importing
`games/reads/playtime.py` from a component is import weight: that module
pulls in `games.filters` and five read modules, and `common.components` is
imported by every page. A `TYPE_CHECKING` import would avoid even that —
`domain.py` already uses one for `DurationPresentation`, and the component
reads only `.tracked`, `.historical` and `.total`.

The move is housekeeping that happens to be free. `games/reads/sums.py`
already holds what every playtime sum shares — `ZERO`, `Playtime`,
`PlaytimeSum`, `UnscopedSum` — and `PlaytimeBreakdown` is the same kind of
value. `playtime.py` re-exports it, as its `__all__` already names it, so
every importer today keeps working: `games/views/stats_data.py`,
`tests/test_playtime_sources.py` and `tests/test_stats.py`. The component
then imports the value from the module that owns it and takes no read
machinery with it.

## The surfaces

### Game detail headline

The `hours` stat in the header row, as `PlaytimeSplit(..., popover=False)`.

The stat's value is `DurationText` today, inside the `Popover` that
`_stat_popover` builds, with `DurationAlternates` in its `details` slot. The
component replaces the value and touches neither: the alternates stay in
`details`, and the stat keeps its one popover.

The value sits in a `flex gap-2 items-center` row beside the stat's icon, so
the two lines need their own column inside that row. The split does not push
the icon.

`_game_header` takes `playtime: timedelta` today and is passed `.total`. It
takes the breakdown instead and hands `.total` to `DurationAlternates`, which
states the whole figure under the other profiles and not the halves.

Its figure is `game_playtime(library, game)`, which already answers a
breakdown. Every other header stat comes from `_game_overview_metrics`, which
reads sessions alone and does not change: a record states no sitting, so it
moves no session count, no average and no play range.

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

The halves come back as a further query over the keys the card renders. Three
queries where there is one today, each stating one thing:

1. The card's rows, ordered and sliced to the cap.
2. The count of every game with playtime, which is what "View all (N)" prints
   today — the total, not the remainder.
3. The halves over the sliced keys alone.

The count stays its own query rather than riding in as a window function. A
window would spare a round trip and cost the plan the rows-only query keeps,
which is the plan this section exists to hold still.

Each row answers the game and its `PlaytimeBreakdown`, as a `NamedTuple`
beside `PlatformPlaytime` and `MonthPlaytime` in `games/reads/playtime.py`.
The reader and the queryset builder live there too, because a new playtime
figure is a function in that module; `compute_stats` calls them and slices
nothing itself.

The annotated `Game` row goes away, and with it `GamePlaytime`. Three
assertions read `.total_playtime` (`tests/test_stats.py` lines 123, 144 and
258) and state `.playtime.total` instead; four more read `.id` or `.name` off
the row (`tests/test_stats.py` 136, 204, 286 and
`tests/test_library_api_isolation.py` 412) and state `.game.id` and
`.game.name`. `stats_content` is the only other reader — no link builder, no
API endpoint and no template names the row. A row shaped like the two the page
already renders is worth more than a queryset attribute nobody else reads.

The query over every visible game keeps the plan it has. A test pins that by
counting `games_playersession` and `games_historicalplaytime` scans in
`.explain()` output, the mechanism `tests/test_sorting.py` uses for the
`playtime` sort key. Two things the mechanism needs and does not yet have
here:

- A builder that answers the un-executed queryset, as `games_for_list()` does
  for the game list. The card's query is inline in `compute_stats` today and
  would otherwise never leave it. The name is `games_by_playtime_queryset`,
  beside the reader that consumes it.
- A stated baseline rather than "does not grow". The count today is two scans
  per table, not one: `filter(total_playtime__gt=…)` names the annotation, so
  Django compiles each `Coalesce(Subquery(...))` half once in the select list
  and once more in `WHERE`. The compiled SQL names `games_playersession`
  twice and `games_historicalplaytime` twice, and `ORDER BY` reads the column
  by position rather than repeating it. The test pins two and two; a later
  reading that differs is the finding.

Three consequences, all stated rather than worked around:

- The key is renamed. `top_10_games_by_playtime` becomes `games_by_playtime`,
  a list, beside `games_by_playtime_count`. The incumbent name states a cap it
  does not hold and a bound it does not have; a second name beside it would
  leave the lie in place. Eleven references in four code files, and three
  documents: this wave's design, `2026-07-20-stats-styledtable-migration-design.md`
  and `2026-09-14-issue-697-playtime-reads-design.md`.
- `STATS_SOURCES` classifies both keys. `games_by_playtime` keeps what the
  incumbent holds; `games_by_playtime_count` states `BOTH` as well, because a
  game enters that count through either source.
  `test_every_stats_key_states_its_sources_once` fails until both are named.
  `StatsSource`'s docstring says "which playtime sources a figure reads", and
  it widens: the count reads both sources and is not a playtime figure. It
  must not be classified as a session figure, or
  `test_a_contained_record_moves_only_the_playtime_figures` fails — a record
  does move this count.
- `_two_col_table` takes a total beside its items, as `_finished_table`
  already does, and keeps slicing for callers that hand it a queryset. It
  also serves the platform card, which passes no "View all" and must keep
  rendering every row it is given.

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

The two `filter_url` calls in `model_counts` go with the links. Nothing else
reads `today_url` or `last_7_url`, and no test asserts either href, so
`PlayerSessionFilter` and `filter_url` leave `games/views/general.py`
with them.

`model_counts` runs for an anonymous request too and states `timedelta(0)`
there today. It states `PlaytimeBreakdown(ZERO, ZERO)` instead, whose second
line is omitted, so the navbar renders one figure as it does now.

### The Library page's Playtime card

The card states the library's whole playtime with the split beneath it. Its
`title` becomes "Tracked sessions and historical records", and it carries no
link.

It states a count of sessions plus records today, which #1097 left for this
issue. Adding two populations of different things into one number answers no
question a person asks.

The link goes for the reason the navbar's goes: it opens the session list,
which cannot show a record, so it undercounts the figure it hangs from.
#1105 restores it with the rest.

`StatisticCard`'s `value` widens from `str | int` to `Child | int`, and
`_value_node` changes with it. `Child` is `Node | str` and does not admit an
integer, which every other card passes. `_value_node` renders `str(value)`
into both the link text and the `aria_label` today, so a node would reach the
page as escaped markup and the label would read as HTML. Two changes:

- The value renders as a child, not as a string. A node renders itself; a
  `str` or `int` still escapes as it does today.
- The spoken label is stated rather than derived. `StatisticCard` takes
  `spoken: str | None`, which the linked cards pass instead of letting
  `_value_node` build one from a node it cannot read. Five linked cards
  remain across the Library page's two grids, and the Playtime card is no
  longer one of them.

A node value inside a `Link` is refused rather than handled: `Duration`
contains a button, and its own contract forbids wrapping it in an anchor.
The cards that keep links keep passing scalars, and `total_spent_value` is one
of them — a formatted string, not an integer.

`SummaryRow` shares `_value_node` and keeps deriving its label from
`str(value)`: `SummaryValue.value` stays `str | int`, and the row passes no
`spoken`. Nothing in this issue puts a node in a summary row.

Three assertions read the card's spoken label and change with it:
`tests/test_playtime_page.py` on the real Library page,
`tests/test_library_page_isolation.py`, which asserts the same string as page
text, and `tests/test_library_ui_components.py` on the component. The
`data-statistic-card` attribute and every e2e selector are untouched.

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
5. The Library card's link goes with the navbar's, for the same reason, and
   #1105 restores both.

## Verification

- A figure whose historical part is zero renders exactly what it renders
  today on Game detail, the stats page and the Library card's value. The
  component returns the bare `Duration` or `DurationText` node when the
  historical part is zero — no wrapper, no changed class — or this fails on
  all three at once.
- The navbar and the Library card differ for every library, records or not,
  and the `render_pages` diff is read with that in mind. The navbar figures
  lose their link, which changes their markup unconditionally, and
  `model_counts` feeds every page, so every rendered file differs in those two
  lines. The Library card's value changes from a count to a duration and its
  link goes.
- Run on a library with no record, a differing file anywhere else is a
  finding. Run on the dump, Game detail of every recorded game and every
  stats page differ by design, and each is attributed to the figure that
  gained a split.
- A figure with a historical part states the total, the tracked part and the
  historical part, and the three are consistent: `tracked + historical ==
  total`, asserted against the reader rather than against typed-in numbers.
- The component renders one popover where it owns one and none on Game
  detail, and the spoken form states the total first and then each part.
- Every figure that carries a filter link today still carries it, the month
  and platform rows included.
- The stats page states the split on the `Hours` row, every month row, every
  platform row and every game row, and the classification in `STATS_SOURCES`
  still names every `StatsData` key.
- The stats card's first query plans the number of source scans the test pins
  off today's plan; the halves arrive in one further query.
- The stats game rows answer a row of their own, and no test reads
  `total_playtime` off a `Game`.
- The navbar figures carry no link, and the account menu renders at 390 px
  with no horizontal scroll.
- The Library card states a duration, carries no link, and renders its node
  as markup rather than as escaped text. The other three cards still state
  scalars, and the two that state counts still speak them.
- The full `make check` gate passes, `e2e/` included.

## Mockups

- [Three split layouts across five surfaces](assets/2026-09-17-issue-710-playtime-split/split-layouts.html)
  — the one-line, two-line and hybrid forms at each surface's real width.
