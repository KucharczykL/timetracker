# One picker look

Every picker looks and behaves like one control. `SearchSelect`,
`FilterSelect` and `PresetSelect` differ only in content: filter rows carry
+ and −, preset rows carry a delete button, filter pills show ✓ or ✗. A
picker's list looks like the app's dropdown menus.

## Decisions

1. **Pills sit inside the field box, in every picker.** The box grows as
   pills wrap. `_ComboboxLayout.pills_in_box` and `_PANEL_PILLS_CLASS` go.
2. **Every list uses the menu surface.** The surface is
   `OVERLAY_SURFACE_CLASS` with `p-2`, a border and `rounded-base`, as a
   `<drop-down>` menu has. A form picker's popup takes it too, in place of its
   own `bg-neutral-secondary-medium` box. Rows are inset and rounded.
3. **One active row.** Mouse hover moves the keyboard highlight, as
   `<drop-down>` menus do (`pointerover`, mouse pointers only). No row has a
   `hover:` style. The active row takes the menu item's active look:
   `bg-neutral-tertiary-medium` and heading text.

## The row

The menu item and the picker row share one look, declared once in
`custom_elements.py` beside `DROPDOWN_ITEM_CLASS`:

- `DROPDOWN_ITEM_SHAPE`: padding, `rounded-base`, resting `text-body`,
  cursor.
- `DROPDOWN_ITEM_ACTIVE`: `bg-neutral-tertiary-medium text-heading`.

A menu item applies the active look on `hover:` and `focus:`, because focus
is its active state. A picker row applies it on
`data-[search-select-highlighted]:`, because the highlight is its active
state. `DROPDOWN_ITEM_CLASS` is rebuilt from the two, so its output does not
change.

`_option_row(option, layout, *, selected, actions=())` builds every row of
every picker: value rows, filter value rows, filter modifier rows and preset
rows. `actions` is a trailing slot. `FilterSelect` puts + and − in it and
`PresetSelect` puts delete. These classes go: `_FILTER_OPTION_ROW_CLASS`,
`_FILTER_OPTION_LABEL_CLASS`, `_FILTER_MODIFIER_ROW_CLASS`,
`_PRESET_OPTION_ROW_CLASS`, `_DIALOG_OPTION_ROW_CLASS` and the highlighted
variants of the action buttons. The row keeps every `data-*` hook the element
and the filter serializer read.

A row action is one button look, `_ROW_ACTION_CLASS`: 24px square,
`rounded-base`, body text, and a heading text with a
`bg-neutral-secondary-strong` fill on hover. That fill reads on a resting row
and on the active row. Delete adds a red hover, because it removes.

## The pill

`Pill()` builds every pill. It takes `kind`: none, `"include"`, `"exclude"`
or `"modifier"`. Include prefixes ✓. Exclude prefixes ✗ and adds the red,
struck-through look. Modifier adds the amber look. The filter pill builders
call `Pill()` and keep their `data-*` hooks. Every pill truncates a long label
(`max-w-full`, `truncate`).

## The layouts

`_ComboboxLayout` keeps three values: standalone, drop-down and dialog. All
three put the pills in the box. The standalone and drop-down lists take the
menu surface. The dialog list sits on the dialog, which already is the menu
surface. Its list takes no surface of its own.

The list's `max-height` counts its padding, so `items_visible` rows still
show.

## Tests

- **pytest.** One row class across the three widgets' rows; `actions` renders
  after the label; one pill builder with each `kind`; pills inside the box in
  both FilterSelect layouts; `DROPDOWN_ITEM_CLASS` renders unchanged.
- **vitest.** A mouse `pointerover` on a row highlights it and clears the
  previous one; a touch `pointerover` does not.
- **e2e.** Screenshots of a form picker, a facet, the preset picker and the
  time zone picker compare side by side; one row is lit after hover then
  arrow key.
