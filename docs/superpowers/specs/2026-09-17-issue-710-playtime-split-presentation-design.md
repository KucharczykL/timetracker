# Tracked and historical playtime, stated separately

Issue: [#710](https://github.com/KucharczykL/timetracker/issues/710).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).

## Purpose

A playtime total sums sessions and records. Where it includes a record, the
figure states how much of it each source gave.

## The component

`PlaytimeSplit(breakdown, presentation, *, id_scope=None, popover=True,
link=None)` in `common/components/domain.py`.

It states the total, and beneath it `142 h tracked · 100 h historical` in micro
text. Each half is a `DurationText`, so each carries its own spoken form, and
the separator is `aria-hidden`.

A zero historical half omits the second line and the component answers the bare
`Duration` or `DurationText` node: no wrapper, no added class. A figure of
sessions alone therefore renders what it rendered before the split existed.

The two lines are blocks, not a flex column. `Popover` renders `self-start`, so
a column pins the total to the left edge while the line beneath it honours the
host's alignment.

`popover=False` states the total as text. One surface passes it: Game detail's
`hours` stat is itself a popover, and a second one inside it gives one stat two
tooltips. `id_scope` is required with a popover and refused without one, and
`link` beside `popover=False` is refused, because `DurationText` renders no
anchor.

`PlaytimeBreakdown` lives in `games/reads/sums.py`, which carries no filter
vocabulary into `common.components`.

## The surfaces

**Game detail.** The `hours` stat, as the value inside `_stat_popover`, whose
`details` slot keeps the duration alternates of the whole figure.
`_stat_popover` takes `two_line`, which only this stat passes and only with a
historical part: it states `items-baseline`, so the icon stays on the first
line. `_game_header` takes the breakdown. Every other header stat reads
sessions alone.

**The stats page.** The `Hours` row, the month rows and the platform rows. The
month and platform figures keep the filter link they carry, which the component
forwards.

**The stats games card.** `games_by_playtime(library, *, year, limit)` in
`games/reads/playtime.py` answers `GameByPlaytime(game, playtime)` rows.
`games_by_playtime_queryset` answers the ranking query unexecuted, so a test
reads its plan. `compute_stats` states three queries: the capped rows, the
count `View all` prints, and the halves over the keys it kept. The ranking
query scans each source table twice, because the filter names the annotation
and recompiles both halves.

**The navbar.** `Today` and `Last 7 days`, with no link: the session list shows
no record, so the link opened a page summing less than the figure it came from.
[#1105](https://github.com/KucharczykL/timetracker/issues/1105) restores it.

**The Library page.** The Playtime card states the library's playtime, titled
`Tracked sessions and historical records`, with no link for the same reason.
`StatisticCard` takes a node value and a stated `spoken` label, because
`_value_node` renders the value as a child rather than a string.

## Not here

A per-run playtime column: a record naming several runs over-sums added to each
and reads zero left out.
[#1119](https://github.com/KucharczykL/timetracker/issues/1119) states it as
run rows. The link predicates: #1105. A stated session count on a record:
[#1106](https://github.com/KucharczykL/timetracker/issues/1106).

## Tests

- `tests/test_duration_component.py`: the rules, including that a zero
  historical half renders exactly a `Duration`.
- `tests/test_historical_playtime_pages.py`: every surface.
- `tests/test_stats.py`: the rows, the count, the halves, the classification.
- `tests/test_sorting.py`: the ranking query's plan.
- `tests/test_library_ui_components.py`: the card's node value and spoken
  label.
