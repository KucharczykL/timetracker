# The stacked cell's summary on the other selectable tables

The summary is the second line of the identity cell, below `md` alone.
[#711](https://github.com/KucharczykL/timetracker/issues/711) built it and
[#715](https://github.com/KucharczykL/timetracker/issues/715) feeds it on the
session list. The four other selectable tables feed it too. The wave is
[Selectable tables](2026-09-19-selectable-tables-wave-design.md).

## What a summary carries

Some of the row's dropped data columns, in one line, joined with commas, at
most four, ordered most-identifying first. The line is clipped, so the order
decides what a narrow screen keeps.

Four kinds of column state no part. `Created` is audit metadata. `Actions` is a
control, and the one column that outlives the drop on a phone. A value another
part states already is arithmetic, not news: the days to finish are the span's.
Free text of no bounded length would take the whole line, which is why a note
stays a column.

A part that states nothing is not stated: an unknown day and an absent device
each add no part, because a slot that reads `Unknown` is a slot the clip takes
from a fact.

## The cell must be able to clip

`overflow-hidden text-ellipsis` clips nothing on its own. The width that makes
it clip is `SHRINKABLE_COLUMN_CLASS`, and `TableRow` states that class only on a
first column that declares `shrinkable`. A summary under any other first column
widens the table instead, and the phone scrolls sideways.

So a table that states a summary declares a shrinkable first column, and
`StyledTable` refuses one that does not, in DEBUG, beside the cell-count guard
it keeps already.

## What each table states

| Table | Identity cell | Summary |
|---|---|---|
| Playthrough list | the run's name | game, span, activity |
| Game detail, Playthroughs | the run's name | span, activity |
| Historical playtime list | the game | when, duration, device |
| Game detail, Historical playtime | the day | duration, provenance, runs, device |

Activity is one part, the word and the recency together: `Playing today`,
`Dormant 3 months ago`. A run that states a completion states no activity, and
no part. A record states the first run it names, and `and N more` for the rest,
never a comma-joined list inside a comma-joined line.

## The span

One temporal value states both endpoints, so the grammar is the one
`present_temporal_value` states already: a range of two known days joins with
` – `, a known start beside an **open** end reads `since 5 Mar 2026`, and an
open start beside a known completion reads `until 2 Apr 2026`. The open
endpoint is what picks those words; an unknown one reads `Unknown` instead.

A run states two values, not one, and either may itself be a range or unknown.
Two of those joined read as one wrong range, so the summary states `Started …`
and `Completed …` as separate parts there. The test is each value's own
`is_range` and `is_unknown`.

## One rule, one builder

`row_summary()` states the comma rule beside `make_row`: a screen reader speaks
a comma as a pause and a middle dot as a word. Five tables call it; none states
a separator of its own. A summary is text and a cell is a node, so each part is
derived beside the cell it repeats, and a test reads both.

One builder answers both record tables. `historical_playtime_tabledata` takes
`exclude_columns`, `sortable` and a caption, as `playthrough_tabledata` takes
the first two, and Game detail calls it rather than building rows beside it.
One column list serves both pages, so Game detail takes the list's drop order,
where `Device` drops before `Duration` and `Provenance` rather than after them.
The list's cells win throughout — the toned provenance badge, the shared badge,
the row keys — the `When` column is shrinkable, because it leads the table Game
detail renders, and the column is headed `Playthroughs` on both pages.

## Proof

Each builder's summary and each rule that states no part are read directly. A
table whose first column cannot clip is refused, and a test states that. One
browser test at 375 px reads the Playthrough list, whose identity cell states
the least, and finds the game named while the `Game` column is gone.

## What the summary is not

Wrapping the line, a per-row disclosure and a phone that scrolls sideways were
drawn at 375 px against this table and refused. The line stays one line.

The summary shows below `md`, and the drop is measured. Between those two
widths a part may repeat a column that is still on screen.
