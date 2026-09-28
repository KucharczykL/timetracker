# Which facets the quick bar shows inline

The quick filter bar keeps its facets in one row. The facets that do not
fit go into the `⋯` menu. This spec states which facets stay in the row.
It applies to every list mode.

## The rule

A facet is **applied** when the page's filter holds its key. The server
puts `data-quick-facet-applied` on the facet's `<drop-down>`. A value that
the person changed but did not apply does not count, because Apply loads
a new page.

`layoutOverflow` fits the facets in this sequence: the applied facets,
then the idle facets, each group in declared order. The facets that fit
stay in the row. The row and the menu both show their facets in declared
order.

Thus an applied facet goes into `⋯` only after all idle facets. The
relative order of the facets does not change. A key whose criterion
removes no rows also marks its facet applied. The mark shows the keys of
the filter, which are the keys that Clear removes.

## The mark

An applied facet's trigger shows a brand dot in its top-right corner. The
label keeps its usual color. The trigger text also has "(applied)" for
screen readers. The dot is absolutely placed, so it adds no width.

The `⋯` trigger has the same dot, `invisible` when it is off. Its
`aria-label` is "More filters", or "More filters, some applied" when the
menu holds an applied facet.

The mark does not show the value. A value summary needs a summarizer for
each kind and each modifier, and it makes the triggers wider.

## The orders

| Mode | Order |
|---|---|
| sessions | Game, Day, Playthrough, Outside dates, Device, Timing, Duration |
| purchases | Type, Purchased, Refunded, Ownership, Price, Infinite, Created, Name |
| historical_playtime | Game, When, Provenance, Device, Duration, Created |
| games | Status, Platform, Year, Playtime, Mastered, Sessions, Purchases, Total price, Name |
| playthroughs | Activity, Game, Started, Completed, Days to finish, Created, Note |
| devices | Name, Type, Created |
| platforms | Name, Group, Created |

The first facets are the facets that people use most, and the facets that
other pages link to. The Library page links to Playthrough, Outside dates
and Refunded. The stats page links to Purchased, Refunded and When.

A name or note facet is last, because the search field also searches that
column. The facet stays, because it can state `is empty` and the other
string modifiers. On devices and platforms, Name stays first, because all
three facets fit on a desktop row.

## Limits

- No person can pin a facet. A stored order for each person would feed the
  same sequence.
- Nothing counts which facets people apply.
- A filter that the facets cannot state still shows the read-only pill
  (#1249).
