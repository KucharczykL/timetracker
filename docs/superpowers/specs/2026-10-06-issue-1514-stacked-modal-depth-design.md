# A stacked modal steps the ones below back and names them

Issue #1514, part of epic #1485. The design (depth cue and trail) was
approved from a mockup on 2026-10-05. On 2026-10-06 the person chose a
compact modal header (variant C below) so a covered dialog's title fits the
strip it shows. This spec states how the modal layer delivers both.

## Problem

Every modal is centred and as wide as its form. A modal opened over another
covers it exactly, so a nested Add game over Add session shows no change, and
a screen reader hears two dialogs with the same name.

## The compact header

`ModalPanelHeader` today is `py-3` with a control-size × (42 px): 66 px, the
title text starting about 25 px down. No step near the approved 1.4rem shows
any title. Every modal header becomes 44 px:

- `py-1.5`, the × a `ControlButton(size="compact")` (32 px), right padding
  `pr-1.5` so the × sits as close to the edge as its padding;
- the title stays `text-type-section` (the visible step is the header's own
  height, so the title size does not set it);
- `divided` keeps choosing the border and surface, and the undivided
  variant (the warning) loses its `pt-4` for the same `py-1.5`.

The form dialog, the warning and `BottomSheet` all build their header
through `titled_header`, so all three change.

## The stack

The layer (`ts/elements/modal-layer.ts`) stamps `data-modal-covered` /
`data-modal-over` in `markBackdrops()`, at open (before `focusInitial`),
close start and finish. A new `markStack()` runs at the same three points,
on window `resize`, and from a `ResizeObserver` over the shown panels and
headers (guarded with `typeof ResizeObserver !== "undefined"`, as
`section-nav.ts` does; jsdom has none). A finished panel is unobserved; the
observer and listener go when the stack empties. `markStack()` writes a
value only when it differs, so an observer callback that recomputes the
same layout writes nothing and cannot loop.

`refreshModalStack()` is exported and calls `markStack()`; a no-op when
nothing is shown, so `<form-dialog>` may call it after every `fill()` (a
re-presented page renames a dialog that a trail above may name).

### Marked parts

New `MODAL_ATTRIBUTES` roles, generated into
`ts/generated/modal-attributes.ts`:

- `panel` (`data-modal-panel`): the visible panel. `ModalPanel(...)` in
  `common/components/modal.py` builds the `Div` with the marker and the step
  classes; the form panel, the warning panel and the sheet's
  `[data-sheet-panel]` use it.
- `header` (`data-modal-header`): stamped by `ModalPanelHeader`.
- `trail` (`data-modal-trail`): the trail line, below.
- `depth` (`data-modal-depth`): stamped by the layer.

The layer finds a dialog's panel, header and trail only where
`nearestDialog(element) === dialog`, as it does for initial focus, so a modal
nested in another's DOM is never read as its ancestor's part.

### Depth and geometry

Over the **open** modals in opening order, top last (a leaving modal is not
counted, so the one below steps forward while the top leaves):

- depth `d` = open modals above. The layer stamps `data-modal-depth="<d>"`
  on the **panel** at `d ≥ 1`, absent at 0, so a nested panel cannot match
  an ancestor's stamp.
- scale `s(d) = 1 - .05·d`.
- strip `h` = the panel's header height (`offsetHeight`), 0 with no header.

The layer then computes, in px, from the top modal downwards:

1. **Room.** `--modal-reserve` on each panel = the sum, over the open modals
   below it, of `s(d)·h`. `ModalPanel` carries
   `mt-[var(--modal-reserve,0px)]`, and the form and warning panels' `max-h`
   subtracts it: `max-h-[calc(100dvh-2rem-var(--modal-reserve,0px))]`.
   For a centred panel within that cap, its top is at least `1rem +
   reserve`.
2. **Target.** The top panel's target is its own `offsetTop`. Each covered
   panel's target is the target of the panel above, less its own scaled
   strip `s(d)·h`.
3. **Shift.** `--modal-shift` = `min(0, target - offsetTop)`. A panel already
   higher than its target is never moved down, and the next panel's target
   is taken from where it actually lands. `offsetTop` is layout geometry: it
   ignores the step's own `transform` and the sheet's `translate`; the
   dialog is `position: fixed`, so it is the panel's offset parent.

Every shown panel gets all three values, zeros included, so a nested panel
never inherits an ancestor's. Values end in `px`: a unitless one would void
the whole `transform`.

Because the reserve above the top panel is the sum of the strips below,
every target lies at or below `1rem`, inside the viewport.

`ModalPanel`'s classes:

- `data-modal-depth:[transform:translateY(var(--modal-shift))_scale(calc(1-var(--modal-depth)*.05))]`
  with `--modal-depth` written beside the others, `origin-top`, and
  `data-modal-depth:opacity-[max(.35,calc(.95-var(--modal-depth)*.2))]`
  (`.75`, `.55`, then floored). The arbitrary `[transform:…]` form is
  required: `translate-y-[…]`/`scale-[…]` compile to the `translate` and
  `scale` properties and would clobber the sheet's slide.
- always: `motion-safe:transition-[transform,translate,opacity]
  motion-safe:duration-200 motion-safe:ease-out`, so the step back to rest
  animates too. The sheet panel drops its own `transition-transform`; this
  list keeps `translate`, so the slide and the sheet controller's
  `transitionend` filter (`propertyName === "translate"`) are unchanged.

The transform is on the panel, never on the dialog: the dialog stays the
viewport hit area and holds the toast region. While stepped, the panel is the
containing block of any `position: fixed` content inside it; floating panels
use the top layer and are unaffected.

### Trail

- `ModalPanelHeader` puts the `<h2>` in a `flex min-w-0 flex-col` column
  with a `<p data-modal-trail hidden>` above it in `text-type-micro
  text-body`.
- The layer fills the trail of the **top open modal** only: the names of the
  open modals below it, bottom first. Each separator is a `<span
  aria-hidden="true"> › </span>` beside a `<span class="sr-only">, </span>`,
  so Orca reads "Add session, Add game" rather than the glyph's name. Every
  other shown dialog's trail is hidden and emptied, so a covered dialog's
  strip shows its own title. A leaving dialog keeps its trail.
- A name is the text of the elements the dialog's `aria-labelledby` names,
  else its `aria-label`. That covers `<form-dialog>`'s header (filled from
  the page title), its `"bare"` chrome (`aria-label`), the sheet and the
  warning. A nameless modal adds nothing.
- While the trail shows, its id (minted if missing) is a token of the
  dialog's `aria-describedby`: first, or last on `role="alertdialog"`, which
  reads its description at once and must lead with its message. Other
  tokens are kept. The token goes when the trail hides, because a hidden
  element that `aria-describedby` names is still read.
- A `"bare"` dialog has no header: no trail, no strip, only scale and fade.
  Nothing touches `aria-labelledby`, so each dialog's name stays its title.

### Finish and reset

`finish()` clears the stamp, the properties, the trail and its token from the
dialog it closes and unobserves its parts. `resetModalLayerForTests()`
clears the same plus `covered`/`over`, and disconnects the observer.

## Tests

- vitest (`modal-layer.test.ts`): depth 2/1/none on panels, cleared on
  close; a leaving top un-steps the one below; shift and reserve from
  stubbed `offsetTop`/`offsetHeight`, in px, never positive; a panel nested
  in another dialog's DOM is ignored; trail on the top only, bottom first,
  with separators; `aria-describedby` order on dialog and alertdialog and
  removal when hidden; `aria-label` fallback; `refreshModalStack()` picks up
  a renamed title and is silent with nothing shown; a dialog with no panel,
  header or trail (the existing harnesses) raises nothing.
- pytest: the header's height classes and compact ×; the hidden trail;
  `ModalPanel`'s marker and classes, `[transform:` present and no
  `translate-y-`; the generated module states every role; the built
  `base.css` holds the arbitrary rules.
- e2e (`test_modal_layer_e2e.py`): three sibling titled modals with panels of
  differing height, one at max height, under `reduced_motion="reduce"`;
  each covered panel's top sits above the one over it, at y ≥ 0, and its
  title's text box lies inside its visible strip; the top trail reads
  `"Lower › Middle"` and is its description. Sheet e2e unchanged.
  `test_dialog_create_e2e.py`: the stacked dialog's trail reads
  `"Add New Game"` (Add session is still a page until #1385).

## Decisions

- Compact header, chosen by the person: one 44 px header for every modal.
- Step by the measured header, never lowering, with reserved room: each
  covered title shows for any pair of heights and stays in the viewport.
- The trail shows on the top modal only.
- The unsaved-changes warning is a stacked modal like any other.

## Follow-up issues to file

- None new. #1335 gains the Orca check the issue names (comment there).
