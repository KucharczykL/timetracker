# A button states its own shape

Issue: [#1170](https://github.com/KucharczykL/timetracker/issues/1170).

A button's corners are part of its look. `ControlButton` states them with
`shape`: `full`, `start`, `end` or `square`. No variant holds a rounding
and no call site states one.

## Why a parameter and not a class

The stylesheet orders two classes that set one corner, not the call, so a
caller class cannot replace a baked one and the call site cannot read
which wins. `ControlButton` refuses a class that states a corner: a rule
in a document becomes stale, a refusal does not.

It reads every spelling, because Tailwind gives one property many: a
prefix for a breakpoint, a state or an arbitrary selector, the important
marker, and the bare `rounded`. A prefixed one gets its own sentence,
since `shape=` states one set of corners for every state and width.

A refusal that fires only when a button is built is a 500 on the first
page to render one, so `tests/test_control_button_shape_guard.py` walks
the syntax tree for it, on the component's predicate.

Both raise `TypeError`, not `CommandRejected`: that convention answers a
command a person states, this a developer misusing a builder, where the
reader is the stack trace.

**A shape states corners, never a radius.**
[#411](https://github.com/KucharczykL/timetracker/issues/411) decided the
radius by tier, so a control needing another is another component. A word
such as `pill` would put two facts on one axis.

## Why the button states it and not the row

A joined row rounds its two outer ends only, and a selector keyed on DOM
position fails two times: a `method="post"` member renders a form around
its button, and a split button's caret sits inside `Dropdown`'s wrapper.

A selector reaches the children the markup admits; a parameter reaches
the button.

## A place states a shape

`shaped()` gives each member of a row the shape its place gives it. The
row counts; no member and no call site holds an index. `ButtonGroup`
counts what it renders, not what it was given: a skipped entry is not an
end.

`SplitButtonDropdown` counts its primary and caret the same way, so a
third element reshapes all three.

## The calendar states its own square

The date range picker paints its day cells in the client. The four day
variants are generated square, and `SHAPE_CLASSES` is published beside
them on its key type, so a key renamed in Python fails `tsc`. Only the
client can state the corner: a range is data that wraps across week rows,
so the run's ends are not the grid's ends.

A day variant stays complete for fill, dimming and geometry: a rounding
merged into an if/else branch reaches only that branch.

## Tests

`tests/test_components.py` walks every variant against every shape, and
states the table's own values and every refused spelling. Rows of one, two
and three members state that the ends round and the middle does not.

`ts/elements/date-range-picker.test.ts` picks days on a rendered grid and
reads the corners back, driving the derivation rather than the table.
