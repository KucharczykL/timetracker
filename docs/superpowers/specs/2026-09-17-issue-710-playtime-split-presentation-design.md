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
text. Each half is a `DurationText`, carrying its own spoken form; the separator
is `aria-hidden`.

A zero historical half omits the second line and answers the bare `Duration` or
`DurationText`: no wrapper, no added class. A figure of sessions alone renders
what it rendered before the split existed.

The lines are blocks, not a flex column. `Popover` renders `self-start`, which a
column pins left of a line honouring the host's alignment.

`popover=False` states the total as text, for a host that owns a popover
already. `id_scope` is required with a popover and refused without one; `link`
beside `popover=False` is refused, because `DurationText` renders no anchor.

`PlaytimeBreakdown` lives in `games/reads/sums.py`, which carries no filter
vocabulary into `common.components`.

## The surfaces

**Game detail.** The `hours` stat, inside `_stat_popover`, whose `details` slot
keeps the alternates of the whole figure. `_stat_popover` takes `two_line` —
only this stat, only with a historical part — which states `items-baseline` so
the icon stays on the first line. `_game_header` takes the breakdown; every
other header stat reads sessions alone.

**The stats page.** The `Hours` row, the month rows and the platform rows. The
month and platform figures keep the filter link they carry, which the component
forwards.

**The stats games card.** `games_by_playtime(library, *, year, limit)` in
`games/reads/playtime.py` answers `GameByPlaytime(game, playtime)` rows.
`games_by_playtime_queryset` answers the ranking query unexecuted, so a test
reads its plan. `compute_stats` states three queries: the capped rows, the
halves over the keys it kept, and the count `View all` prints, which ranks
every played game again. The ranking query scans each source table twice,
because the filter names the annotation and recompiles both halves. Over 860
games the three read in 16 ms against 17 ms for the one query that
materialised every row.

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
