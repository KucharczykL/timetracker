# ControlButton states its own shape

Issue: [#1170](https://github.com/KucharczykL/timetracker/issues/1170).

A button's corners are part of its look. Today two of the five variants
bake no rounding, so ten call sites state it by hand, and forgetting
renders a square button with no error.

## The rake

`variant="outline"` and `variant="segmented"` emit no `rounded-*` class.
A standalone outline caller must remember `rounded-base`. Two agents have
forgotten it. `SelectionToggle` carries a comment warning about it, and
so does the copy button on the Game form, which is the tell that the
default is wrong rather than merely undocumented.

`filled`, `ghost` and `plain` bake `rounded-base`. A caller that wants a
partial shape must therefore state the corners it wants beside the ones
it does not: the navbar's Log game button carries `rounded-s-base
rounded-e-none`, and the split button's filled caret carries
`rounded-e-base rounded-s-none`.

These two are not the same defect. The compiled sheet orders every
shorthand `rounded-*` before every longhand group, so `rounded-base
rounded-e-none` wins by design and the navbar button looks right. What is
wrong there is that the caller had to know which variant it picked to
know how many classes to write. The outline case is worse: the button is
simply square, and nothing says so.

One rule answers both. A caller states the corners it wants, and never
the variant's opinion of them.

## The parameter

`shape` is a parameter and not a caller `class_`, because a caller class
cannot reliably replace a baked one. Two classes for the same corner are
ordered by the stylesheet, not by the call.

```python
type ButtonShape = Literal["full", "start", "end", "square"]

_SHAPE_CLASSES: dict[ButtonShape, str] = {
    "full": "rounded-base",
    "start": "rounded-s-base",
    "end": "rounded-e-base",
    "square": "",
}
```

`control_button_class()` appends exactly one entry, and no variant string
holds a `rounded-*` any more. `full` is the default, so every variant
rounds unless told otherwise. An empty shape appends nothing rather than
an empty word, so a `square` button carries no trailing space.

**`shape` states corners, never a radius.**
[#411](https://github.com/KucharczykL/timetracker/issues/411) decided the
radius by tier: controls take `rounded-base`, chips take `rounded`. A
control that wants another radius is a different component, not a fifth
word. A word such as `pill` would put two facts on one axis, and every
rule stated about a shape would then need an exception.

`plain` returns before the base class and the alignment, because its
layout contradicts both. It still takes its shape, so the rule holds for
every variant. No page renders `plain` today: the navbar link its
docstring names is a `ControlLink` carrying `_NAV_LINK_CLASS`, and the
only callers left are two tests. The shape guarantee for that one variant
is therefore a guarantee about tests. Taking the variant away is a
separate question, filed as
[#1177](https://github.com/KucharczykL/timetracker/issues/1177).

## Why the button states it and not the row

`ButtonGroup` rounds its members from the parent:

```text
[&>*:first-child]:rounded-s-base
[&>*:last-child]:rounded-e-base
```

The code calls this the one documented exception to the rule that an
element carries its own classes, because a member cannot know its own
position.

The mechanism has already failed twice. A `method="post"` member renders
a form around its button, so the selector hits the form and a second pair
of selectors was added to reach the button inside it. The split button's
caret sits inside the `<drop-down>` wrapper that `Dropdown` builds, so no
selector on the split's own row can reach it at all — which is why that
caret states `rounded-e-base` by hand today.

A selector reaches a child the markup lets it reach. A parameter reaches
the button. That is the argument, and it holds even where a loop could
have counted.

The cost of stating it per button is that nothing stops one member
disagreeing with its neighbours. The builders below never let a caller
state it, so the disagreement has no way in.

## A member's place states its shape

```python
def shaped[T](members: Sequence[T]) -> Iterator[tuple[ButtonShape, T]]:
    """Each member of a joined row, with the shape its place gives it."""
    last = len(members) - 1
    for index, member in enumerate(members):
        if last == 0:
            yield "full", member
        elif index == 0:
            yield "start", member
        elif index == last:
            yield "end", member
        else:
            yield "square", member
```

No call site holds an index or a count. An empty row yields nothing, and
the group renders as it does today. A row of one yields `full`, which is
what both selectors give it today.

`ButtonGroup` states the shapes of the members it renders, not of the
members it was given: an entry with no slot is skipped, and a skipped
entry is not an end, so it filters before it iterates. `PageTabs` states
the same shapes in the class it already composes per tab, because its
tabs are anchors and not buttons.

`_GROUP_ENDS_CLASS` keeps `inline-flex rounded-base shadow-xs`, which
rounds the group's own shadow, and loses its two child selectors. The two
`_button` descendant selectors are not in that constant — `ButtonGroup`
composes them into its own `Div` — and they go with it. The form around a
post member carries `inline-flex` and nothing else: no border, no
background, no shadow, and the group clips nothing. The border and the
focus ring both live on the button inside it, which now carries its own
radius.

`PageTabs` moves in the same change, not after it. Its tabs take every
corner they have from those selectors, so removing them alone ships
square tabs.

Pagination is a fourth joined row, and it already states
`rounded-s-base` and `rounded-e-base` per link by hand. Its links are not
buttons and it keeps what it has.

## The split button states both its ends

`SplitButtonDropdown` takes a `ControlButton` as its primary and states
that button's shape itself, the way `ButtonGroup` states its members'.
The caret takes `end`, the primary takes `start`, and neither is a
caller's to remember. A caller that forgot would render a primary rounded
on all four corners with a notch where the caret meets it — the same
silent failure this issue is about, moved rather than removed.

Stating a shape on a built button is a clone that rebuilds the class
attribute, which is how `ControlButton` already answers `[]`.

## The calendar states its own square

The date range picker paints its day cells client-side, from four
complete class strings that codegen publishes. It squares a selected
run's joined edges by adding `rounded-none`, `rounded-e-none` and
`rounded-s-none` to those strings.

That last mechanism is the one rounding in the codebase that wins by
alphabetical order alone: `rounded-none` beats `rounded-base` because the
two set the same property and `n` sorts after `b`. Rename the token and
the track squares in silence.

So the calendar states its corners the same way everything else does.
The four day variants are generated with `shape="square"`, `_SHAPE_CLASSES`
is published beside them, and the client adds the one shape it has already
worked out from the range. A range is defined by data and not by position
in the row — it wraps across week rows, so the run's ends are not the
grid's ends — and the client is the only thing that knows where it ends.

This narrows the calendar's own rule. A day variant is published complete
for fill, dimming and geometry, and states no corner. The rule exists
because merging rounding into one branch of an if/else is what left
selected and adjacent-month cells square; the client adding exactly one
shape to every cell keeps that property, and a test states it.

## No caller states a corner

`ControlButton` refuses an attribute whose class holds `rounded-`. The
parameter is then the only way to state a corner, and the rule is checked
rather than written down. A table in a spec goes stale; a `TypeError` on
the stack of the caller that forgot does not.

## What this fixes on screen

The Played N times button on Game detail rounds `rounded-s-lg` on the
left and its own caret `rounded-e-base` on the right — 16px against 12px
on one control. #411 retired `rounded-lg` and named the segmented edges,
but missed this site. `shape="start"` states 12px, so the halves agree.

Every other change emits the same classes it emits today. The order
moves: `rounded-base` leaves the middle of a variant string and joins at
the end.

## The call sites

Ten sites state rounding today. Each one drops the class:

| Site | Today | Shape |
|---|---|---|
| `common/layout.py` Log game | `rounded-s-base rounded-e-none` | `start`, from the split |
| `games/views/game.py` Played N times | `rounded-s-lg` | `start`, from the split |
| `common/components/custom_elements.py` outline caret | `rounded-e-base` | `end`, from the split |
| `common/components/custom_elements.py` filled caret | `rounded-e-base rounded-s-none` | `end`, from the split |
| `common/components/custom_elements.py` value selector | `rounded-base` | default |
| `common/components/custom_elements.py` sheet dismiss | `rounded-base` | default |
| `common/components/sectioned_page.py` section nav | `rounded-base` | default |
| `common/components/library_kit.py` row actions | `rounded-base` | default |
| `common/components/primitives.py` `SelectionToggle` | `rounded-base` | default |
| `common/components/temporal_field.py` copy button | `rounded-base` | default |

Two of the `rounded-base` rows are redundant today. The sheet dismiss and
the row actions are `ghost`, which bakes that class already. They state a
class that changes nothing, which is its own reason to take it away.

Every other caller of `control_button_class()` — the year picker's cells,
the toast's action — names its arguments by keyword and takes the `full`
default.

## How it lands

Four members of one stack, on top of
[#1168](https://github.com/KucharczykL/timetracker/pull/1168).

1. The parameter, the invariant test, and the six standalone sites. The
   split button's four sites take shapes as callers, for now.
   `ButtonGroup` states `shape="square"` on its members and keeps its
   selectors, because a segmented member that took the `full` default
   would round in the middle of a row. The refusal lands last here, once
   no caller states a corner. This member carries the one visible change.
2. The split button states its primary's shape and its caret's.
3. `ButtonGroup` and `PageTabs` state their members' shapes, the four
   selectors go, and the stale comments are rewritten.
4. The calendar states its own square.

## Tests

`tests/test_components.py` walks every variant and shape and states that
the emitted `rounded-*` classes are exactly the classes `_SHAPE_CLASSES`
states for that shape. It also states that a caller class holding a
rounding is refused.

A group of one, two and three members: the single member rounds both
ends, the first rounds the start, the middle rounds nothing, the last
rounds the end. A `method="post"` member states its shape on the button
inside its form. `PageTabs` states the same shapes.

A split button states `start` on its primary and `end` on its caret, for
a primary the caller built with neither.

`ts/elements/date-range-picker.test.ts` states that every day cell
carries exactly one rounding, for a day inside a run, at each end of one,
and outside one.

Three tests hold the old rule.

`tests/test_rendered_pages.py` states `rounded-s-lg` for the Played N
times button and states `rounded-s-base` instead.

`tests/test_components.py` builds an outline button with a caller class
of `rounded-e-lg`. That call is refused once the refusal lands, so the
test states `shape="end"`.

`tests/test_date_range_picker.py` states that every day variant is
rounded, and states that every one is square.
