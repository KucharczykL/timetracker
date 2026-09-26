# One picker look

Every picker looks and behaves like one control. `SearchSelect`,
`FilterSelect` and `PresetSelect` differ only in content: filter rows carry
+ and −, preset rows carry a remove button, filter pills show ✓ or ✗. A
picker's list looks like the app's dropdown menus, and both share one panel
and one hover model.

## Decisions

1. **Pills sit inside the field box, in every picker.** The box grows as
   pills wrap. `_ComboboxLayout.pills_in_box` and `_PANEL_PILLS_CLASS` go.
   Nothing reads the pills' position: every reader scopes to
   `[data-search-select-pills]`.
2. **Every list sits on the menu surface.** Rows are inset and rounded.
3. **One active row.** Mouse movement moves the keyboard highlight, so one
   row is lit. No row has a `hover:` style. The active row takes the menu
   item's active look: `bg-neutral-tertiary-medium` and heading text.

## The dropdown panel

Every dropdown panel in the app is one builder, `DropdownPanel`. The panel is
the surface: `OVERLAY_SURFACE_CLASS`, `p-2`, border, `rounded-base`,
`shadow-sm`, a stacking context for its `before:` blur, and a flex column. It
does not scroll. Its one child, `[data-menu-scroll]`, is `min-h-0
overflow-y-auto` and holds the content.

Today the panel scrolls itself, and the blur layer is an absolute `::before`
inside the scrolled content. A dark panel therefore loses its blur below its
first screen. The blur cannot move onto the panel itself: a `backdrop-filter`
makes the panel the containing block of its `fixed` submenus.

attachMenu already writes the viewport room to the panel's `max-height`. The
scroller shrinks to fit, so no positioning code changes. A caller that caps its
content (a picker's `items_visible`) puts the cap on the scroller, and the list
shows the smaller of the two.

`DropdownMenuPanel`, `ListboxPanel`, `ComboboxDropdown`, the column picker, the
quick filter's overflow panel and the selection bar's overflow panel use the
builder. A hook that names where items go (`data-quick-overflow-items`,
`data-selection-overflow-items`) sits on the scroller.

## The picker list

A picker's list in the standalone and drop-down layouts is a `DropdownPanel`
whose scroller is the listbox. The standalone panel sits below the box
(`top-full`); the drop-down panel carries `[data-menu]` and `hidden`. In the
dialog layout the dialog already is the panel, so the listbox sits in the
dialog's scroller. The element reads and toggles the panel, never the listbox.

The listbox takes `scroll-py-2`. The group header and the no-results line take
the row padding.

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

## Pointer follow

One helper, `followPointer(container, itemSelector, activate)` in
`ts/pointer-follow.ts`, gives menus and pickers the same hover model. It acts
on `pointermove` from a mouse, and only when the position changed since the
last move. Scrolling under a still cursor, or a keyboard step, moves no item.
`activate` never scrolls: a menu focuses with `preventScroll`, a picker
highlights without `scrollIntoView`. Keyboard steps still scroll.

Today a menu activates on `pointerover` through `focus()`, which scrolls a
partly hidden item into view and lets the list creep under a still cursor.
The picker would inherit the same fault.

## The pill

`Pill()` builds every pill. `kind` is none, `"include"`, `"exclude"` or
`"modifier"`, and it replaces the tone: brand soft; brand soft with ✓;
`bg-danger-soft text-fg-danger-strong`, struck through, with ✗;
`bg-warning-soft text-fg-warning`. The glyph stays outside the label slot.
The label is always a slot that truncates.

## Tests

- **pytest.** One row look across the three widgets; `RowKind` stamps the
  right hook; actions follow the label; `Pill` with each kind; pills inside
  the box in both FilterSelect layouts; each panel site is a `DropdownPanel`.
  `test_panel_pills_row_hides_when_empty` goes.
- **vitest.** `followPointer`: a mouse move activates the item under it; a
  touch move and a move at the same position do not. A picker hover never
  scrolls; ArrowDown under a resting pointer keeps the keyboard row. A menu
  hover focuses with `preventScroll`.
- **e2e.** Screenshots of a form picker, a facet, the preset picker and the
  time zone picker, both themes. A long picker list and a long menu, scrolled
  in dark mode, keep their blur. Every existing dropdown e2e passes.
