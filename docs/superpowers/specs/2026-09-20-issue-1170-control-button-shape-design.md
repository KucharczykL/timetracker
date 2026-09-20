# ControlButton states its own shape

Issue: [#1170](https://github.com/KucharczykL/timetracker/issues/1170).

A button's corners are part of its look. Today two of the five variants
bake no rounding, so ten call sites state it by hand, and forgetting
renders a square button with no error.

## The rake, both directions

`variant="outline"` and `variant="segmented"` emit no `rounded-*`. A
standalone outline caller must remember `rounded-base`. Two agents have
forgotten it. `SelectionToggle` carries a comment warning about it, which
is the tell that the default is wrong rather than merely undocumented.

`filled`, `ghost` and `plain` bake `rounded-base`. A filled caller that
wants a partial shape must therefore neutralize it: the navbar's Log game
button carries `rounded-s-base rounded-e-none`, and the split button's
filled caret carries `rounded-e-base rounded-s-none`. Whether an override
of that kind wins is decided by stylesheet order, not class order.

Both directions are the same defect. A caller cannot state a corner
without knowing which variant it picked.

## The parameter

`shape` is a parameter and not a caller `class_`, for the same reason
`align` is one: the utilities collide, and Tailwind breaks that tie by
stylesheet order.

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
rounds unless told otherwise. `plain` returns before the base and the
alignment, which its navbar layout contradicts; it still takes its shape,
so the rule holds for every variant.

**The invariant:** for each pair of a variant and a shape, the emitted
`rounded-*` classes are exactly the classes `_SHAPE_CLASSES` states for
that shape. One class for three shapes, none for `square`. A test walks
every pair.

## A member's place states its shape

`ButtonGroup` rounds its members from the parent:

```text
[&>*:first-child]:rounded-s-base
[&>*:last-child]:rounded-e-base
```

The code calls this the one documented exception to the rule that an
element carries its own classes, because a member cannot know its own
position. A shape parameter makes that reason false. `ButtonGroup` builds
its children in a loop and counts them, and so does `PageTabs`.

```python
def group_shape(index: int, count: int) -> ButtonShape:
    """A member's shape from its place in the row."""
    if count == 1:
        return "full"
    if index == 0:
        return "start"
    if index == count - 1:
        return "end"
    return "square"
```

`ButtonGroup` counts the members it renders, not the members it was
given: an entry with no slot is skipped, and a skipped entry is not an
end. `PageTabs` states the same shapes in the class it already composes
per tab, because its tabs are anchors and not buttons.

`_GROUP_ENDS_CLASS` keeps `inline-flex rounded-base shadow-xs`, which
rounds the group's own shadow. Its four child selectors go, the two
`_button` descendant ones included: a `method="post"` member renders a
form around a button, and the shape now rides on that button, which is
the box that holds the border.

## The split button

Both carets take `shape="end"`. The filled one drops `rounded-s-none`,
because a shape replaces the rounding rather than overriding it. Both
primaries take `shape="start"`: the Played N times button on Game detail
and the navbar's Log game button.

## What this fixes on screen

The Played N times button rounds `rounded-s-lg` on the left and its own
caret `rounded-e-base` on the right — 16px against 12px on one control.
[#411](https://github.com/KucharczykL/timetracker/issues/411) retired
`rounded-lg` and named the segmented edges, but missed this site.
`shape="start"` states 12px, so the halves agree.

`tests/test_rendered_pages.py` states the old value and moves with it.

## The call sites

Ten sites state rounding today. Each one drops the class:

| Site | Today | Shape |
|---|---|---|
| `common/layout.py` Log game | `rounded-s-base rounded-e-none` | `start` |
| `games/views/game.py` Played N times | `rounded-s-lg` | `start` |
| `common/components/custom_elements.py` outline caret | `rounded-e-base` | `end` |
| `common/components/custom_elements.py` filled caret | `rounded-e-base rounded-s-none` | `end` |
| `common/components/custom_elements.py` value selector | `rounded-base` | default |
| `common/components/custom_elements.py` sheet dismiss | `rounded-base` | default |
| `common/components/sectioned_page.py` section nav | `rounded-base` | default |
| `common/components/library_kit.py` row actions | `rounded-base` | default |
| `common/components/primitives.py` `SelectionToggle` | `rounded-base` | default |
| `common/components/temporal_field.py` copy button | `rounded-base` | default |

Two of the `rounded-base` rows are redundant today. The sheet dismiss
and the row actions are `ghost`, which bakes that class already. They
state a class that changes nothing, which is its own reason to take it
away.

Every other caller of `control_button_class()` — the date picker's day
cells, the year picker's cells, the toast's action — names its arguments
by keyword and takes the `full` default, so its class string does not
change.

## Tests

`tests/test_components.py` walks every variant and shape and states the
invariant above. Nothing today would catch a square button or a colliding
pair.

It also states a group of one, two and three members: the single member
rounds both ends, the first rounds the start, the middle rounds nothing,
the last rounds the end. A `method="post"` member states its shape on the
button inside its form. `PageTabs` states the same shapes.
