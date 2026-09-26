# A compact ControlButton

`ControlButton` is the one builder for a button. A glyph button inside another
control uses it too, at the compact size.

## The size

`ControlButton` has a `size` parameter:

- `"control"`: the default. The height is `min-h-control` (42px) and the
  button has horizontal padding.
- `"compact"`: a 32px square with no padding. It holds one glyph.

A 32px button fits in the 42px field box. It also fits in a 36px picker row
when the caller adds `-my-1.5`: the button then takes 20px of the row height,
which is the height of one text line, and the row stays 36px. This was
measured in the browser.

The size sets the corners. `shape="full"` gives `rounded-base` (12px) at the
control size and `rounded` (8px) at the compact size, which is the same
proportion. `SHAPE_CLASSES` is keyed by size and shape. The component refuses
a caller class that states a corner, as before.

`control_button_class()` takes `size` too, so a caller that cannot call the
component gets the same string.

## Ghost with a color

The `ghost` variant ignores `color`, except `color="red"`. A red ghost button
shows `text-fg-danger-strong` and `bg-danger-soft` on hover. The preset remove
button and the comparison-row remove use it.

## The buttons that move

| Button | Now |
|---|---|
| SearchSelect clear × | ghost, compact |
| Filter +/− row actions | ghost, compact, `-my-1.5` |
| Preset remove | ghost red, compact, `-my-1.5` |
| Calendar toggle of the date, date range and date-time fields | ghost, compact |
| Date-time copy button | ghost, compact |
| Filter builder comparison-row remove | ghost red, compact |
| Year picker toggle | filled, control; blue when a year is set, gray when not |

The class constants that these buttons replace go: `_CLEAR_BUTTON_CLASS`,
`_ROW_ACTION_*`, `_FIELD_ICON_BUTTON_CLASS` and the inline toggle classes.

## The buttons that stay

These are not box buttons, and they keep their own builders:

- The menu item family: menu items, listbox options, the match-mode rows.
- Glyphs sized to text: the info and truncation reveal glyphs, the pill ×,
  the toast dismiss, and the popover trigger, which wraps content of the
  caller.
- Filter chips and calendar day cells. The day cells already take their
  classes from `control_button_class()`.
- The account avatar trigger, a 40px circle. It moves out of `AccountMenu`
  into its own component, `AvatarButton`.

## The guard

A test walks `common/` and `games/` and refuses a call to the raw `Button`
builder outside `ControlButton` and an allow list of the builders above. A new
button therefore uses `ControlButton`, or it names itself in that list.

## Tests

- `size="compact"` renders a 32px square with `rounded`, and no `min-h-control`.
- A red ghost button has the danger hover; a gray one does not.
- Each moved button renders the `ControlButton` classes.
- The guard test.
- e2e: a picker row with actions is 36px high; the clear × and the field
  toggles are 32px.
