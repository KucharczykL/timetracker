# A compact ControlButton

`ControlButton` is the one builder for a button. A glyph button inside another
control uses it too, at the compact size.

## The size

`ControlButton` and `control_button_class()` take `size`:

- `"control"`: the default. `min-h-control px-3`, as today.
- `"compact"`: `size-8 p-0`, a 32px square that holds one glyph.

Size is its own part of `control_button_class()`. Today `CONTROL_SIZE_CLASS`
is inside the filled, segmented, outline and ghost strings. It comes out of
them, and the function adds the string for the size. Each size string is a
literal, so Tailwind generates it. `plain` stays outside sizing.

A 32px button fits in the 42px field box (`FIELD_CONTAINER_CLASS` and the
SearchSelect box have no vertical padding problem). It fits in a 36px picker
row when the caller adds `-my-1.5`: the button then takes 20px of the row,
one text line, and the row stays 36px. This was measured in the browser.
The border does not add to a fixed `size-8`.

## The corners

`SHAPE_CLASSES` does not change: codegen publishes it to TS as
`BUTTON_SHAPE_CLASSES`, and the day cells, the search field and `PageTabs`
read it by shape. `COMPACT_SHAPE_CLASSES` gives the compact corners for all
four shapes: `rounded`, `rounded-s`, `rounded-e`, none. 8px on 32px is the
proportion of 12px on 42px. The component still refuses a caller class that
states a corner.

## The ghost tone

The ghost look splits into a still part and a tone. The tone depends on size
and color, from one table:

- Control, any color but red: today's ghost tone.
- Compact, any color but red: `text-body` at rest, `hover:text-heading` and
  `hover:bg-neutral-quaternary-medium`. A highlighted picker row is
  `bg-neutral-tertiary-medium`, so a tertiary hover would not show on it.
- Red, both sizes: a full tone of its own with `hover:text-fg-danger-strong`,
  `hover:bg-danger-soft` and a danger hover border.

Each entry is one complete string, so no two classes set one property.
`games/views/catalog_section.py` already renders a red ghost button; it now
gets the danger hover, which is intended.

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

What changes on the page: the +/− glyphs take the body text size; the
date-time copy arrow takes the body font; the date-time field is 16px wider;
the gray year toggle takes the filled gray surface; its chevron loses `ms-2`,
because the button gap is already there.

`_CLEAR_BUTTON_CLASS`, `_ROW_ACTION_*`, `_FIELD_ICON_BUTTON_CLASS` with its
comment, and the inline toggle classes go.

## The buttons that stay

These keep their own builders:

- The menu item family: `DropdownLinkItem`, `DropdownActionItem`,
  `DropdownCheckItem`, the `ListboxPanel` option, `_mode_row`.
- Glyphs sized to text: `_popover_reveal`, the `Popover` trigger, the
  `TruncatedText` reveal, the `Pill` ×.
- The filter chip template.
- `AvatarButton`, the account trigger, a 40px circle. It moves out of
  `AccountMenu` into its own component.
- TS `createElement("button")`: the toast dismiss and the calendar fallback.
  The guard does not read TS.

## The guard

A test walks the syntax tree of `common/` and `games/`. It refuses a call to
`Button`, under any imported name, and `Element("button", …)`, outside
`ControlButton.render` and the builders above.

## Documentation

CLAUDE.md "Buttons are ControlButton" and the `ControlButton` docstring say
there is no size parameter. Both change. `tests/test_control_height.py`
requires `min-h-control` from every variant; it now asks it of the control
size.

## Tests

- Compact renders `size-8` with `rounded`, and no `min-h-control`.
- `COMPACT_SHAPE_CLASSES` covers every `ButtonShape`; `BUTTON_SHAPE_CLASSES`
  in TS keeps its keys.
- A red ghost has the danger tone; a gray one does not; no ghost string sets
  one property twice.
- Each moved button renders the `ControlButton` classes.
- The guard.
- e2e: a picker row with actions is 36px high; the clear × and the field
  toggles are 32px; the date-time field does not overflow its column.
