# Every dropdown opens as a bottom sheet on a phone

Part of #1485. Issue #1559. It extends #516 and #1537 and uses
[Motion](2026-10-09-issue-1559-motion-design.md).

## Rule

Every `<drop-down>` opens its panel as a bottom sheet below `sm`
(640 px). There is no opt-out. `behavior="sheet"` (`BottomSheet`) keeps
its own controller. Above `sm`, nothing changes.

## Titles

Every build site states its title in Python. `Dropdown`,
`ComboboxDropdown`, `SelectDropdown` and `_assemble` require
`sheet: SheetSpec`; `behavior="sheet"` has its own path with no sheet.
`SplitButtonDropdown` requires `aria_label`.
`tests/html_answers.py` refuses a `<drop-down>` with no own sheet.

## Height

A sheet has its content height, up to 90 % of the visible height, and
rises above the keyboard. A **steady** sheet fills the screen: a level,
or a sheet whose content holds a `<drop-down>` or a search box.
`attachNarrowSheet` stamps `data-sheet-steady`. A steady sheet never
moves for the keyboard: the keyboard slides over it, and its body pads
its foot by the keyboard height. So a level slide never changes height,
and the keyboard never shows the page.

## First focus

`sheetFocus` names it: a menu's first enabled item, else its first
tabbable control; the selected option; the checked radio; the first
checkbox.

## Levels

A `<drop-down>` that opens inside an open dropdown sheet opens its own
sheet dialog as a **level** of that sheet. A dropdown inside a form
dialog stacks a plain sheet.

- A level is its own `<dialog>` in the modal layer, so its lent node
  stays in its own host and every `closest("drop-down")` lookup works.
- The level carries `data-sheet-level` before the layer opens it. A
  level does not cover: the sheet below keeps its dim, gets no depth
  step and no trail. A level is never `data-modal-over`, and its
  backdrop is transparent.
- **Header:** a three-column grid. The back control ("←" and the title
  below) leads; the title is centred; × ends it. The back control is
  named "Back to <title below>". It is hidden on a sheet that is not a
  level.
- **In:** the level slides in. The panel below then goes
  `visibility: hidden`. Focus moves to the level's `sheetFocus`.
- **Back:** the back control (`data-modal-cancel`) and a native `cancel`
  (Escape, the Android back gesture) close the level only.
  `ModalOptions.cancel` states this apart from `dismiss`.
- **Close:** × and the backdrop close the whole chain through
  `closeTogether`: the level slides down and lower backdrops fade. Only
  the top runs its leave; the layer then finishes every sheet, top first,
  and returns focus once. A menu item that acts closes the chain too.
  `closeAbove` finishes levels without focus.
- **Queue:** a step (cancel, dismiss, chain close) pressed during a leave
  queues and runs once it ends, so two quick backs go back two steps. A
  leaving modal acts on no press; a leaving panel takes no pointer.
- A level does not move hosts on resize; the first sheet does.
- A submenu opens through `presenter`. In a sheet, hover opens nothing.

## A form dialog from a sheet

A form-dialog link in a sheet closes the sheet first. `<form-dialog>`
waits with `whenSettled` until no modal leaves, then opens over the
page.

## Tests

Vitest covers the level stack, the heights and the behaviors. E2E at
390 px covers a row menu, a submenu level, the overflow, facet and
picker chain, a form dialog from a sheet menu, and the select
dropdowns.
