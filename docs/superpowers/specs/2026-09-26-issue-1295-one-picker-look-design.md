# One picker look

`SearchSelect`, `FilterSelect` and `PresetSelect` look and behave as one
control. They differ only in content: filter rows have + and −, preset rows
have a remove button, and filter pills show ✓ or ✗. A picker list looks like
a dropdown menu. Pickers and menus use one panel and one hover model.

## The panel

`DropdownPanel` builds every dropdown panel: menus, listboxes, the combobox
dialog, the column picker, the two overflow panels and the picker lists. The
panel is the surface. It has the overlay colors, the border, the shadow and
the blur. It does not scroll. Its one child, `[data-menu-scroll]`, scrolls.
The children, `content_attributes` and `content_class` go to this scroller.

The blur is on a `::before` layer of the panel. If the panel scrolls, the
layer scrolls away, and a dark panel loses its blur. The blur cannot go on
the panel itself: a `backdrop-filter` makes the panel the containing block of
its `fixed` submenus.

attachMenu writes the available height to the panel `max-height`. The
scroller shrinks to that height. A picker writes its row limit on the
scroller, thus the list shows the smaller of the two heights.

## The picker list

In the field and drop-down layouts, the list is a `DropdownPanel`, and its
scroller is the listbox. In the dialog layout, the dialog is the panel, and
the listbox is in the dialog scroller. The element shows and hides the panel
through its `hidden` attribute in all layouts. The pills are in the field box
in all layouts.

## The row

`_option_row(option, kind, *, selected, actions)` builds every row. `RowKind`
sets the hook that the element reads: `OPTION`, `MODIFIER` or `CREATE`. The
actions follow the label. With actions, the label truncates.

A row and a menu item use one shape, `DROPDOWN_ITEM_SHAPE`, and one active
look, `DROPDOWN_ITEM_ACTIVE`. A menu item shows the active look on hover and
on focus. A row shows it only on `data-[search-select-highlighted]`, thus one
row is active at a time. Tailwind reads only literal class names, so each
state spells the look, and a test pins each spelling.

A row action is 24px square with `-my-1`, so the row height does not change.
The remove action has a red hover.

## Pointer follow

`followPointer(container, itemSelector, activate)` gives menus and pickers
one hover model. Only a mouse `pointermove` activates an item. A move at the
last position does nothing, because a list that scrolls under a still cursor
sends such a move. `activate` does not scroll: a menu focuses with
`preventScroll`, and a picker highlights without `scrollIntoView`. Keyboard
steps scroll.

## The pill

`Pill(kind=…)` builds every pill. The kind replaces the tone: brand for none
and `include`, danger for `exclude`, warning for `modifier`. `include` shows
✓ and `exclude` shows ✗, before the label and outside the label slot. Screen
readers read the glyph. The label always truncates.
