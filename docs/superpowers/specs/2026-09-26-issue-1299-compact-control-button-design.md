# ControlButton sizes

`ControlButton` is the one builder for a button. A glyph button inside
another control uses it too, at a small size.

## The sizes

`ControlButton` and `control_button_class()` take `size`:

| Size | Box | Use |
|---|---|---|
| `"control"` | `min-h-control px-3`, 42px | the default |
| `"compact"` | `size-8 p-0`, 32px square | a glyph in a 42px field box |
| `"row"` | `size-6.5 p-0`, 26px square | a glyph in a 36px picker row |

Size is a separate part of `control_button_class()`, not a part of a variant
string. Each size string is a literal, because Tailwind reads only literal
class names. `plain` has no size.

A row action takes `-my-0.75`. It then uses 20px of the row height, which is
one text line, and the row stays 36px. A 32px button also fits in a row, but
it touches the row edges and looks too large.

## The corners

`SHAPE_CLASSES` does not change. Codegen publishes it to TS as
`BUTTON_SHAPE_CLASSES`, and the day cells, the search field and `PageTabs`
read it by shape. `COMPACT_SHAPE_CLASSES` gives the corners of the two glyph
squares for each shape: `rounded`, `rounded-s`, `rounded-e`, or none. 8px is
the nearest token to the 12px-on-42px proportion. The component refuses a
caller class that states a corner.

## The ghost tone

The ghost look has a still part and a tone. `_GHOST_TONE_CLASSES` gives the
tone for each size and color. Each entry is one full string, thus no two
classes set one property. A test checks this for all combinations.

- At the control size, the tone does not change.
- A glyph square rests at `text-body` and hovers
  `bg-neutral-quaternary-medium`. A highlighted picker row is
  `bg-neutral-tertiary-medium`, and a hover in that color does not show.
- A red ghost hovers `bg-danger-soft` with danger text and border, at all
  sizes.

## The buttons

| Button | Look |
|---|---|
| SearchSelect clear × | ghost, compact |
| Calendar toggles and the date-time copy button | ghost, compact |
| Filter builder comparison-row remove | ghost red, compact |
| Filter +/− | ghost, row |
| Preset remove | ghost red, row |
| Year picker toggle | filled, control; blue with a year, gray without |

These builders keep a raw `Button`, because they are not box buttons:

- The menu items, the listbox options and the match-mode rows.
- Glyphs at text size: the popover reveal and trigger, the `TruncatedText`
  reveal and the `Pill` ×.
- The filter chips.
- The temporal field disclosure, which looks like a text link.
- `AvatarButton`, the 40px account circle.

TS builds two buttons with `createElement`: the toast dismiss and the
calendar fallback. They are also glyphs at text size.

## The guard

`tests/test_button_guard.py` walks the syntax tree of `common/` and `games/`.
It refuses a `Button` call, under any imported name, and
`Element("button", …)` outside `ControlButton.render` and the builders above.
It also refuses an allow list entry that names no builder.
