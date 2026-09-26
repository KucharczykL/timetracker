# One picker look

Every picker looks and behaves like one control. `SearchSelect`,
`FilterSelect` and `PresetSelect` differ only in content: filter rows carry
+ and −, preset rows carry a remove button, filter pills show ✓ or ✗. A
picker's list looks like the app's dropdown menus.

## Decisions

1. **Pills sit inside the field box, in every picker.** The box grows as
   pills wrap. `_ComboboxLayout.pills_in_box` and `_PANEL_PILLS_CLASS` go.
   Nothing reads the pills' position: every reader scopes to
   `[data-search-select-pills]`.
2. **Every list sits on the menu surface.** Rows are inset and rounded.
3. **One active row.** Mouse movement moves the keyboard highlight, so one
   row is lit. No row has a `hover:` style. The active row takes the menu
   item's active look: `bg-neutral-tertiary-medium` and heading text.

## The list

Every layout wraps the listbox in one element, `[data-search-select-surface]`.
The wrapper carries the visibility (`[data-menu]` and `hidden` when a
`<drop-down>` hosts it, the `.hidden` class otherwise). The element toggles
the wrapper, never the listbox.

- **Standalone and drop-down:** the wrapper is the menu surface:
  `OVERLAY_SURFACE_CLASS`, `p-2`, border, `rounded-base`, `shadow-sm`, and a
  stacking context for its `before:` blur. It does not scroll, so the blur
  covers the whole list. It is a flex column. attachMenu writes the viewport
  room to the wrapper's `max-height`; the listbox keeps its `items_visible`
  cap, `min-h-0` and `overflow-y-auto`. The list therefore shows the smaller
  of the two.
- **Dialog:** the dialog already is the menu surface, so the wrapper is plain
  and always visible.

The listbox takes `scroll-py-2`, so a scrolled-to row keeps a gap from the
edge. The group header and the no-results line take the row padding.

## The row

The menu item and the picker row share one look, declared in
`custom_elements.py`:

- `DROPDOWN_ITEM_SHAPE`: `px-4 py-2`, `rounded-base`, resting `text-body`,
  `cursor-pointer`.
- `DROPDOWN_ITEM_ACTIVE`: `bg-neutral-tertiary-medium text-heading`.

A menu item applies the active look on `hover:` and `focus:`. Its own
utilities (`block w-full text-left no-underline focus:outline-hidden
aria-disabled:*`) stay on `DROPDOWN_ITEM_CLASS`. A focused item then reads
`text-heading` in both themes, as a hovered one does; `dark:focus:text-white`
goes. `tests/test_admin_settings_page.py` pins the string and changes with it.

A picker row applies the active look on `data-[search-select-highlighted]:`.

`_option_row(option, layout, kind, *, selected=False, actions=())` builds
every row. `kind` is a `RowKind`: `OPTION`, `MODIFIER` or `CREATE`. It
decides the hook the element reads: `data-search-select-option` with
`data-value` and a label slot, `data-search-select-modifier-option`, or
`data-search-select-create`. `actions` is a trailing slot. With actions, the
row is a flex row and the label truncates. These classes go:
`_FILTER_OPTION_ROW_CLASS`, `_FILTER_OPTION_LABEL_CLASS`,
`_FILTER_MODIFIER_ROW_CLASS`, `_PRESET_OPTION_ROW_CLASS`,
`_DIALOG_OPTION_ROW_CLASS`, and the highlighted variants of the actions.

A row action is one look, `_ROW_ACTION_CLASS`: 24px square with `-my-1`, so
the row stays 2.25rem high; `rounded-base`; body text; on hover, heading text
and `bg-neutral-quaternary-medium`, which differs from the resting and the
active row in both themes. Remove adds a red hover.

## Hover

The element listens for `pointermove` on the listbox, mouse pointers only.
A move whose position differs from the last one highlights the row under the
pointer, without scrolling. A keyboard step or a new set of rows records the
pointer position, so a resting pointer never takes the highlight back and a
list never scrolls under it.

## The pill

`Pill()` builds every pill. `kind` is none, `"include"`, `"exclude"` or
`"modifier"`, and it replaces the tone: brand soft; brand soft with ✓;
`bg-danger-soft text-fg-danger-strong`, struck through, with ✗;
`bg-warning-soft text-fg-warning`. The glyph stays outside the label slot.
The label is always a slot that truncates.

## Tests

- **pytest.** One row look across the three widgets; `RowKind` stamps the
  right hook; actions follow the label; `Pill` with each kind; pills inside
  the box in both FilterSelect layouts; the surface wrapper in each layout.
  `test_panel_pills_row_hides_when_empty` goes.
- **vitest.** A mouse move highlights the row under it; a touch move does
  not; ArrowDown under a resting pointer keeps the keyboard row; a hover
  never scrolls.
- **e2e.** Screenshots of a form picker, a facet, the preset picker and the
  time zone picker, both themes; a long list scrolled in dark mode keeps its
  blur.
