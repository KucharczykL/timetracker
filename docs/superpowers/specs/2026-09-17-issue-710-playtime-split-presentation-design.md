# Tracked and historical playtime, stated separately

Issue: [#710](https://github.com/KucharczykL/timetracker/issues/710).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).

## Purpose

A playtime total sums sessions and records. Where it includes a record, the
figure states how much of it each source gave.

## The component

`PlaytimeSplit(breakdown, presentation, *, id_scope=None, popover=True,
link=None)` in `common/components/domain.py`.

It states the total and, beneath it, `142 h tracked · 100 h historical` in
micro text. Each half is a `DurationText`, carrying its own spoken form; the
separator is `aria-hidden`.

The lines are two blocks of one element. Siblings would become two flex items
in a host that is a flex row, and a flex column would pin the total left of
them, because `Popover` renders `self-start`.

A zero historical half omits the second line and answers the bare `Duration`
or `DurationText`: no wrapper, no added class. A figure of sessions alone
renders what it rendered before the split existed.

`PlaytimeHalves` is the second line alone, for a host that states its own
rows or owns the popover already. Game detail composes it.

`PlaytimeBreakdown` lives in `games/reads/sums.py`, which carries no filter
vocabulary into `common.components`.

## The surfaces

**Game detail.** The `hours` stat, inside `_stat_popover`, whose `details` slot
keeps the alternates of the whole figure. `_stat_popover` takes `two_line` —
only this stat, only with a historical part — which states `items-start`, so
the value keeps the line the other stats sit on. `_game_header` takes the breakdown; every
other header stat reads sessions alone.

**The stats page.** The `Hours` row, the month rows and the platform rows,
whose filter links the component forwards.

**The stats games card.** `games_by_playtime(library, *, year, limit)` in
`games/reads/playtime.py` answers `GameByPlaytime(game, playtime)` rows.
`games_by_playtime_queryset` answers the ranking unexecuted, so a test reads
its plan. A game the halves query no longer holds leaves the card, that query
being the later read; the count is a third and may exceed the rows. `compute_stats` states three queries: the capped rows, the
halves over the keys it kept, and the count `View all` prints, which ranks
every played game again. The ranking query scans each source table twice,
because the filter names the annotation and recompiles both halves.

The three read no slower than the one query they replace, which materialised
every played game: median of 30 samples over 834 games and 300 records. A
library holding no record times the ranking alone, so seed records first.

**The navbar.** `Today` and `Last 7 days`, with no link: the session list shows
no record, so the link opened a page summing less than the figure it came from.
[#1105](https://github.com/KucharczykL/timetracker/issues/1105) restores it.

**The Library page.** The Playtime card states the library's playtime, titled
`Tracked sessions and historical records`, with no link for the same reason.
`StatisticCard` takes a node value and a stated `spoken` label, because
`_value_node` renders the value as a child rather than a string.

## Not here

A per-run playtime column: a record naming several runs over-sums added to
each and reads zero left out.
[#1119](https://github.com/KucharczykL/timetracker/issues/1119) states it as
run rows. The link predicates: #1105. A session count on a record:
[#1106](https://github.com/KucharczykL/timetracker/issues/1106).

## Tests

- `tests/test_duration_component.py`: the rules, including that a zero
  historical half renders exactly a `Duration`.
- `tests/test_historical_playtime_pages.py`: every surface.
- `tests/test_stats.py`: the rows, the count, the halves, the classification.
- `tests/test_sorting.py`: the ranking query's plan.
- `tests/test_library_ui_components.py`: the card's node value and spoken
  label.
