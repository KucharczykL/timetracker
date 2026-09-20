# A button states its own shape

Issue: [#1170](https://github.com/KucharczykL/timetracker/issues/1170).

A button's corners are part of its look. `ControlButton` states them with
`shape`: `full`, `start`, `end` or `square`. No variant holds a rounding,
and no call site states one by class.

## Why a parameter and not a class

The stylesheet orders two classes that set one corner, not the call, so a
caller class cannot replace a baked class and the call site cannot read
which one wins. `ControlButton` refuses a caller class that states a
corner. A rule in a document becomes stale; a refusal does not.

The refusal reads every spelling, because Tailwind gives one property
many: a prefix for a breakpoint, a state or a whole arbitrary selector,
the important marker, and the bare `rounded`. A prefixed one gets its own
sentence, because `shape=` states one set of corners for every state and
width.

A refusal that fires only when a button is built is a 500 on the first
page to render one, so `tests/test_control_button_shape_guard.py` walks
the syntax tree for it, sharing the component's predicate.

**A shape states corners, never a radius.**
[#411](https://github.com/KucharczykL/timetracker/issues/411) decided the
radius by tier, so a control that needs another radius is another
component. A word such as `pill` would put two facts on one axis.

## Why the button states it and not the row

A joined row rounds its two outer ends only, and a parent selector keyed
on DOM position fails two times here: a `method="post"` member renders a
form around its button, and a split button's caret sits inside the wrapper
`Dropdown` builds.

A selector reaches the children the markup admits. A parameter reaches the
button.

## A place states a shape

`shaped()` gives each member of a row the shape its place gives it. The
row counts; no member and no call site holds an index. `ButtonGroup`
counts the members it renders, not the members it was given: a skipped
entry is not an end.

`SplitButtonDropdown` counts its primary and its caret the same way, so a
third element there reshapes all three.

## The calendar states its own square

The date range picker paints its day cells in the client. The four day
variants are generated square, and `SHAPE_CLASSES` is published beside
them on its key type, so a key renamed in Python fails `tsc`.

Only the client can state the corner: a range is data, and it wraps across
week rows, so the run's ends are not the grid's ends.

A day variant stays complete for fill, dimming and geometry: a rounding
merged into one branch of an if/else reaches only that branch.

## Tests

`tests/test_components.py` walks every variant against every shape, and
states the table's own values and every refused spelling. Rows of one, two
and three members state that the ends round and the middle does not,
through the builder and through `shaped()`.

`ts/elements/date-range-picker.test.ts` picks days on a rendered grid and
reads the corners back, so it drives the derivation, not the table.
