# A button states its own shape

Issue: [#1170](https://github.com/KucharczykL/timetracker/issues/1170).

A button's corners are part of its look. `ControlButton` states them with
`shape`: `full`, `start`, `end` or `square`. No variant string holds a
rounding, and no call site states one by class.

## Why a parameter and not a class

Two classes that set the same corner are ordered by the stylesheet, not by
the call. A caller class thus cannot replace a baked class, and the call
site cannot read which one wins. `ControlButton` refuses a caller class
that states a corner, so the parameter is the only way in. A rule in a
document becomes stale. A `TypeError` on the stack of the caller that
forgot does not.

The refusal reads every spelling, because Tailwind gives one property
many: a breakpoint or state prefix, a whole arbitrary selector as a
prefix, the important marker, and the bare `rounded`. A prefixed one gets
its own sentence — `shape=` states one set of corners for every state and
every width, so it cannot replace a corner that applies to one of them.

**A shape states corners, never a radius.**
[#411](https://github.com/KucharczykL/timetracker/issues/411) decided the
radius by tier: a control takes `rounded-base`, a chip takes `rounded`. A
control that needs a different radius is a different component. A word
such as `pill` would put two facts on one axis.

## Why the button states it and not the row

A joined row rounds its two outer ends only. A parent selector keyed on
DOM position is the obvious mechanism, and it fails two times here. A
`method="post"` member renders a form around its button, so the selector
reaches the form and needs a second pair to reach the button. A split
button's caret sits inside the wrapper `Dropdown` builds, so no selector
on that row reaches it at all.

A selector reaches the children the markup admits. A parameter reaches the
button.

## A place states a shape

`shaped()` gives each member of a row the shape its place gives it. The
row counts; no member and no call site holds an index. `ButtonGroup`
counts the members it renders and not the members it was given, because an
entry with no slot is skipped, and a skipped entry is not an end.

`SplitButtonDropdown` states both ends of the row it builds: its primary's
start as well as its caret's end. A caller that had to remember the start
would render a primary rounded on four corners with a notch at the join,
and nothing would say so.

## The calendar states its own square

The date range picker paints its day cells in the client. The four day
variants are generated square, `SHAPE_CLASSES` is published beside them,
and the client states the corner. Each table is published on its key
type, not on `str`, so a key renamed in Python fails `tsc` rather than
resolving to nothing at run time.

Only the client can. A range is defined by data, and it wraps across week
rows, so the run's ends are not the grid's ends.

A day variant stays complete for fill, dimming and geometry. Merging the
rounding into one branch of an if/else is what left selected and
adjacent-month cells square.

## Tests

`tests/test_components.py` walks every variant against every shape, and
states that the emitted classes are exactly the classes `SHAPE_CLASSES`
holds — beside the values that table holds, because the walk compares
against the table itself. It also states every spelling of a caller class
that is refused, and that a caller class stating no corner still reaches
the element.

Rows of one, two and three members state that the ends round and the
middle does not, through the builder as well as through `shaped()`. A
`method="post"` member states its shape on the button inside its form,
and a tab row states its own ends.

`ts/elements/date-range-picker.test.ts` picks days on a rendered grid and
reads the corners back: at each end of a run, between them, outside one,
across a week row, on a run of one, and on the provisional run under the
pointer. The shape there is derived from the picked dates, so the test
drives the derivation and not the table.
