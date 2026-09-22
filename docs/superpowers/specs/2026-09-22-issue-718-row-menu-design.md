# The row's menu, and Finish in the tray

A table shows two lists of acts. The selection line shows what a selection can
do; the row's menu shows what one row can do. An act in one list stays in the
other.

## The slot

The menu is not a column. `make_row` states it, and `StyledTable` draws one
trailing cell in each row and one trailing header cell. That header cell shows
no label. It states an accessible name and a `data-priority` one above the
highest the view declared, so `<responsive-table>` drops it last and the acts
stay on a small screen. The slot is in no view's `Column` list.

Five tables show a menu: the session, historical playtime and playthrough
lists, and the two sections of Game detail.

## The trigger

`EllipsisTrigger` is one ghost button, read by the quick filter bar's overflow,
the library's summary rows, and each row menu. A vertical glyph marks the acts
of one row; a horizontal glyph marks an overflow in a line of controls.
`ellipsis.html` does not change, because `TruncatedText` reads it as the reveal.

`RowActionMenu` builds the panel and knows no act; the caller states the items.
No module under `common/components/` imports `games.bulk_actions`, because that
import closes a cycle. The panel takes the width of its longest item and stops
at the edge of the screen.

## What a row offers

A session offers Finish and Reset while it runs, then Edit, Move to playthrough,
Record as historical playtime while it is Duration-only, and Remove. A
playthrough offers Started today or Completed today, then Edit and Remove. A
record offers Edit and Remove. A gated act is absent, never disabled.

An item reads in the words of the act it shares with the line. Three dots mean
the act asks a question first, and a destructive item colours its glyph red.
Move has no route of its own: the item gives one row to the same act.

## The tray

Each act applies to many rows. The line shows them in declaration order, and
the destructive act is last.
The acts that do not fit move into one horizontal trigger, rightmost first, and
return when the width returns. The element measures the room in the selection
line, because the controls row takes the width of its content and shrinks as
each act leaves. The line is hidden until the mode starts, so it measures at
the first show.

## Finish

`FINISH_SESSION` is a `BulkAction` over sessions, on the shared scope and
resolve in `games/bulk_sessions.py`. One batch ends each row at one instant: the confirmation stamps it into
the choice, and each chunk carries it. A new instant in each chunk gives a
different fingerprint, and the runner then counts every finished row as refused.
The inverse states the timing again with no end, which is the row running.

## The title

`BulkAction.title` is an `ActTitle`: one clause for one row, one for more. An
empty half is refused where the act is declared.

## What the shape prevents

A row shows no act without scripting: only `ts/elements/drop-down.ts` removes
the panel's `hidden`. No page shows one row's facts, which is #1258.

An act is declared twice, as a route and as a `BulkAction`. A rule the command
gains reaches both; a rule the screen gains reaches one.
