# Mobile settings section bottom-sheet plan (#384)

**Status:** planned; adversarial review incorporated

**Prepared:** 2026-07-21

**Scope:** replace the settings scaffold's mobile priority-plus section chips and
`More` menu with a clear, accessible bottom sheet while preserving the existing
desktop sticky rail and the identity of every section anchor.

## Outcome

At narrow settings-scaffold widths, one full-width sticky control identifies
itself as settings navigation and opens a modal bottom sheet containing every
section link. At `@4xl`, that same link list lives in the existing 14rem sticky
desktop rail. JavaScript moves the list; it never clones links or creates a
second navigation model.

The mobile trigger has two lines:

```text
┌────────────────────────────────────────┐
│ Settings sections                   ⌃ │
│ Jump to a section                      │
└────────────────────────────────────────┘
```

The open sheet has one visible surface docked to the viewport bottom:

```text
           dimmed page backdrop

╭────────────────────────────────────────╮
│ Settings sections                   × │
├────────────────────────────────────────┤
│ Application                            │
│ Authentication                         │
│ Integrations                           │
│ Preferences                            │
│ Advanced                               │
│                                        │
│              safe-area padding         │
╰────────────────────────────────────────╯
```

The trigger stays available while the settings content scrolls. Selecting a
section closes the sheet, updates the URL fragment, scrolls the destination
below the sticky trigger, and puts programmatic focus on the destination so the
keyboard and assistive-technology context follows the visual navigation.

## Why the current mobile navigation is being replaced

The priority-plus layout exposes whichever first chip happens to fit beside a
`More` control. On a narrow screen that single chip looks detached from any
navigation context, while `More` does not explain that it contains the rest of
the page's settings sections. The mechanism is useful for compact filtering
controls, but it is a poor information architecture for page navigation.

The bottom sheet fixes the problem by making both the subject and action
explicit before it opens:

- `Settings sections` names the content;
- `Jump to a section` explains the action;
- the full-width control reads as an intentional page-navigation surface;
- the sheet exposes every peer destination at once; and
- the desktop rail remains unchanged at wide scaffold widths.

## Non-goals

This work does not:

- add scrollspy or active-section highlighting;
- turn section links into an ARIA menu;
- add swipe-to-dismiss, a drag handle, or spring physics;
- migrate the existing HTMX confirmation `<modal-dialog>` component;
- change quick-filter priority-plus behavior or its shared width arithmetic;
- change the desktop rail width, typography, label-fit policy, or sticky boundary;
- clone section links for different responsive modes; or
- run the full project check before the settings epic's final verification gate.

Do not display a drag handle until a real, tested pointer gesture exists. A
handle without the gesture advertises behavior that is not implemented.

## Existing architecture and reuse boundary

The Python `Dropdown` component is already a generic trigger-to-panel assembly:
it assigns stable IDs, `data-toggle` / `data-menu`, `aria-controls`, initial
expanded state, a behavior name, and a public custom-element shell. Its current
TypeScript controller, `attachMenu`, is not generic: it positions a panel beside
its trigger and implements the ARIA-menu interaction model.

The sheet must reuse the shell without inheriting that presentation.

| Existing part | Decision | Reason |
| --- | --- | --- |
| `Dropdown` trigger/panel ID stamping | Reuse | The ownership and expanded-state contract is already tested. |
| `<drop-down>.open()` / `.close()` | Reuse | Consumers and responsive teardown get one public API. |
| Registered behavior lookup | Extend | `behavior="sheet"` may supply a controller instead of configuring `attachMenu`. |
| Existing `MenuController` shape | Reuse unchanged | `open`, `close`, `isOpen`, `focusFirst`, and `bindDocument` are sufficient; preserving the shape avoids churn in menu/select/combobox behavior. |
| `attachMenu` | Preserve as the default | Existing dropdowns must not enter new modal branches. |
| `positionAnchored` | Do not use | A sheet is docked to the UA viewport, not positioned relative to its trigger. |
| Menu roles, roving tabindex, typeahead, arrow navigation | Do not use | These are one ARIA-menu interaction model, not generic popup behavior. |
| Dropdown single-open notification | Reuse | Opening the sheet should close an already-open dropdown rather than leave it hidden underneath. |
| `bindPopupDismiss` | Do not use for the sheet | Native dialog cancel handling and a local backdrop hit area are more precise and avoid a second Escape listener. |
| Dropdown surface tokens | Reuse | The sheet belongs to the same light/dark overlay family. Geometry remains sheet-specific. |
| Priority-plus math | Keep for quick filters only | `quick-filter-bar.ts` remains a consumer after settings stops using it. |
| Existing `<modal-dialog>` behavior | Do not reuse unchanged | It removes throwaway HTMX overlays and does not implement persistent open/close, focus containment, or focus restoration. |

The visual-conventions documentation currently says that the overlay stack can
be reused unchanged for a future sheet. Replace that statement with a narrower
rule: overlay tokens and trigger/panel contracts are shared, while anchored,
tooltip, menu, and modal presentations each own their geometry and interaction
controller.

## Semantic contract

The bottom sheet is modal document navigation, not an application menu.

The closed control must have:

- native `<button type="button">` semantics;
- `aria-haspopup="dialog"`;
- `aria-controls` pointing at the dialog;
- `aria-expanded="false"`, updated while open; and
- visible text that communicates both subject and action.

The sheet must use:

- a native `<dialog>` opened with `showModal()`;
- an accessible name from its visible `Settings sections` heading;
- a visible close button with an explicit accessible label;
- `<nav aria-labelledby="...">`;
- a semantic `<ul>`; and
- ordinary `<a href="#section-id">` links.

It must not add `role="menu"`, `role="menuitem"`, `role="presentation"`, or
roving `tabindex` to the section navigation. Every link remains in the dialog's
normal Tab order. Enter follows the normal link activation path. Native modal
dialog behavior makes the background inert and restores focus for ordinary
dismissals. Because browser sequential-focus behavior differs at the dialog
boundary, the sheet controller also wraps Tab/Shift+Tab locally between its
first and last tabbable controls; it does not add a competing Escape handler.

The first section link receives focus after the dialog opens. Do not focus the
dialog element itself; the HTML dialog element must not receive `tabindex`.

## DOM ownership and responsive transformation

There is exactly one section-link `<ul>` and one set of anchors.

```text
Narrow, enhanced:

settings-section-nav
├── mobile drop-down trigger
├── dialog
│   └── sheet panel
│       └── nav
│           └── shared <ul>
├── desktop nav destination (empty and hidden)
└── @4xl sentinel

Wide:

settings-section-nav (sticky grid item)
├── mobile drop-down trigger + closed dialog (hidden)
├── desktop nav
│   └── shared <ul>
└── @4xl sentinel
```

The settings custom element continues to read a CSS sentinel instead of
duplicating the `@4xl` threshold in `matchMedia`. A `ResizeObserver` observes
the settings navigation host and queues one mode synchronization per animation
frame.

Mode synchronization must be atomic:

1. Determine the sentinel mode.
2. If leaving mobile, request sheet close and wait for its single
   `dropdown:hide` completion before moving the list.
3. Hide the outgoing visible navigation surface.
4. Move the existing `<ul>` to the new destination.
5. Reveal the incoming surface.
6. Leave the trigger's expanded state false in desktop mode.

Moving the `<ul>` preserves every anchor node and any listeners or state it may
gain later. Tests compare node identity before and after both transitions.

### JavaScript-disabled fallback

The server renders the shared list in the ordinary inline/rail `<nav>`, outside
the closed dialog. Until the settings custom element successfully enhances the
navigation, that list remains visible and usable. Enhancement may replace the
fallback with the mobile trigger only after
`customElements.whenDefined("drop-down")` resolves and the dialog controller is
available.

The fallback prioritizes access over pixel-identical enhanced presentation. Do
not server-render links inside a closed dialog, hide the only list in anticipation
of JavaScript, or duplicate the list in `<noscript>`.

Keep the host in normal layout flow. Responsive reflow at the container boundary
is intentional; absolutely positioning the trigger would remove its reserved
space and create overlap and sticky-boundary problems. Enhancement visibility
changes happen in one queued layout pass so there is never a frame with two
usable copies or no usable copy.

## Sheet geometry and visual contract

The native `<dialog>` is an explicit full-viewport, transparent hit area. A
child `[data-sheet-panel]` owns the visible bottom surface. This separation makes
outside-panel presses detectable without treating padding inside the visible
surface as backdrop.

Reset UA dialog geometry only through an explicit selector such as
`dialog[data-bottom-sheet]`:

- fixed/full inset hit area;
- zero margin, padding, and border;
- full viewport width and height;
- no UA max-width or max-height constraint;
- transparent background;
- hidden outer overflow; and
- bottom alignment for the visible panel.

Do not use `dialog[behavior="sheet"]`: `behavior="sheet"` belongs to the
`<drop-down>` host. Do not remove outlines globally. The dialog is not a focus
target, while its controls retain the shared focus-ring contract.

The visible panel uses:

- the canonical overlay surface and text tokens;
- rounded top corners only;
- full viewport width;
- content-driven height up to `min(80dvh, 32rem)`;
- a sticky internal header;
- an independently scrolling navigation body;
- `overscroll-behavior: contain` on the scrolling region;
- bottom padding that is at least the normal spacing token and respects
  `env(safe-area-inset-bottom)`; and
- the existing modal backdrop color in `::backdrop` unless visual review proves
  a weaker shared token is needed.

The header contains the sheet title and a standard control-sized close button.
Use the established button/focus treatment; do not add an unregistered raw SVG.
The navigation rows are full-width, left-aligned links with at least the shared
minimum control height. They do not need chevrons or a selected appearance.

## Sticky trigger and anchor offset

The mobile trigger is a normal-flow grid item that becomes sticky with the
settings scaffold. It uses an opaque surface and a stacking position above
static section content but below real floating overlays. Document the exact
stacking choice beside the existing overlay scale rather than assuming every
`z-10` consumer has the same role.

The desktop rail retains the current ownership:

- `<settings-section-nav>` is the sticky grid item;
- the inner desktop `<nav>` owns viewport-height capping and vertical scrolling;
- the rail stops at the settings scaffold boundary; and
- label-fit checks remain browser-only CI checks.

Mobile anchor destinations need a larger scroll margin than desktop because the
sticky trigger occupies vertical space. Use one settings-owned class contract,
for example a mobile `scroll-mt-*` large enough for the measured trigger plus
its top gap and `@4xl:scroll-mt-4` for the desktop rail. Do not duplicate an
unexplained magic offset across callers.

## Dialog lifecycle

### Open

1. Ignore an open request if the dialog is already open or the navigation is in
   desktop mode.
2. Notify the existing single-open coordination so anchored dropdowns close.
3. Snapshot and lock document scrolling.
4. Set `aria-expanded="true"` on the trigger.
5. Call `dialog.showModal()`.
6. Set the opening animation state and advance it on the next animation frame.
7. Focus the first section link after the dialog is open.
8. Emit the existing `dropdown:show` event exactly once. A behavior-owned
   controller still lives behind the documented `<drop-down>` lifecycle and
   must not create a second visibility-event dialect.

`showModal()` may throw if called on a disconnected element or an already-open
dialog. Connection and state guards must make those cases impossible during
normal operation; the controller must still fail closed and release any scroll
lock if the call unexpectedly fails.

### Ordinary close

Backdrop, close-button, and Escape dismissals use the same idempotent close path:

1. Mark the sheet as closing and reject duplicate close requests.
2. Start the panel slide-down and backdrop fade.
3. Under reduced motion, skip directly to native close.
4. Otherwise finish on the relevant animation/transition completion event.
5. Keep a timeout matching the motion duration so an interrupted transition
   cannot strand an open modal.
6. Call `dialog.close()`; never remove the `open` attribute manually.
7. Restore document scrolling and all prior inline styles.
8. Set `aria-expanded="false"`.
9. Let native dialog behavior restore focus to the trigger.
10. Clear closing state and emit `dropdown:hide` exactly once.

The native `cancel` event is the only Escape path. Call `preventDefault()` in
that handler, then enter the animated close path. Do not also install the
shared document Escape listener.

### Backdrop close

Listen locally on the full-viewport dialog hit area. A backdrop gesture closes
only when both its pointer-down and pointer-up/click land outside
`[data-sheet-panel]`. This prevents a gesture that begins inside the sheet and
ends outside it from dismissing accidentally.

Do not describe `event.target === dialog` as inherently safe. It is safe only
because this design gives the dialog an explicit transparent viewport box and
the visible sheet a distinct child box.

### Section-link activation

Native modal close restores the previously focused trigger. Merely adding a
`restoreFocus: false` option cannot suppress that UA behavior. Section navigation
therefore needs a dedicated close-then-navigate sequence:

1. Validate that the clicked link is a same-document `#section-id` anchor owned
   by this settings navigation.
2. Prevent its immediate default navigation.
3. Resolve and retain the destination element.
4. Close the dialog through the normal animation and cleanup path.
5. Update `location.hash` so browser history and copied URLs retain the anchor.
6. Ensure repeated activation of the existing hash still scrolls the target.
7. Scroll the destination using the section's responsive scroll margin.
8. Programmatically focus the destination heading or section, which carries
   `tabindex="-1"`, without introducing it into normal Tab order.

The browser test asserts the final hash, viewport position, and active element.
This is stronger than checking only that the viewport did not jump back to the
trigger.

### Resize or disconnect while open

Switching to desktop mode or disconnecting the host must bypass cosmetic delay
when necessary and leave the document usable:

- close the native dialog exactly once;
- cancel pending animation frames and timeout fallbacks;
- restore scroll state;
- reset `aria-expanded`;
- unbind document-level listeners;
- restore the shared list to the inline/desktop nav before permanent removal;
  and
- rebind exactly one set of document listeners if the same custom element is
  moved and reconnects.

A responsive mode switch uses the public asynchronous close lifecycle: request
`drop-down.close()`, wait for `dropdown:hide`, then move the list. A disconnect
cannot wait for animation; `close()` detects the disconnected host and performs
native close and cleanup immediately. No extra public force-close method is
added to the existing controller interface.

The existing `<drop-down>` reconnection rule persists: element-local listeners
travel with the subtree, while `bindDocument()` listeners are detached on
disconnect and rebound on reconnect. The sheet controller must implement that
same contract and its tests must count listeners/effects across repeated moves.

## Document scroll-lock contract

`showModal()` makes background content inert, but document scrolling requires
an explicit, shared lock. The controller owns one reversible operation rather
than scattering body-class mutations across sheet consumers.

On lock:

1. Snapshot the current `window.scrollY`.
2. Snapshot every inline style property the lock will change on both `html` and
   `body`.
3. Account for the scrollbar gutter where relevant so the page width does not
   jump.
4. Prevent root overscroll and background scrolling.
5. Use the fixed-body/top-offset treatment required by mobile Safari if a
   simple root overflow lock does not pass the browser spike.

On unlock:

1. Restore the exact prior inline values rather than assigning assumed defaults.
2. Restore the captured scroll position without smooth scrolling.
3. Make the operation idempotent.
4. Run it for ordinary close, failed open, responsive teardown, and disconnect.

If the lock is extracted as a reusable utility, it needs ownership or reference
counting so one overlay cannot unlock a document still owned by another. Do not
generalize it speculatively beyond what the sheet and an isolated unit test can
prove.

`overscroll-behavior: contain` on the sheet's own scroll region complements the
document lock; it is not a replacement for it.

## Motion contract

Opening transitions the panel from below the viewport to its resting position
while the backdrop fades in. Closing reverses those states. Use a short shared
duration in the approximate 180–220ms range and one easing curve; do not make
motion duration configurable per settings page.

The state machine has explicit `closed`, `opening`, `open`, and `closing` states.
Each public operation is idempotent, and stale completion events are ignored.
Reduced-motion users get the same state changes with no transition delay.

Animation is presentation only. Focus, expanded state, scroll lock, dialog
modality, and cleanup must remain correct if CSS fails to load or no completion
event fires.

## Implementation sequence

### 1. Codify the convention

Modify:

- `docs/visual-conventions.md`
- `docs/settings-ui-kit.md`
- `docs/settings-panel-epic.md` only where its mobile navigation decision still
  prescribes priority-plus

Record the reuse boundary, semantic contract, mobile trigger, top-layer
geometry, scroll-lock ownership, same-DOM rule, and no-JS fallback. Keep the
quick-filter priority-plus convention intact.

### 2. Add the controller factory seam

Modify:

- `ts/elements/dropdown-behaviors.ts`
- `ts/elements/drop-down.ts`
- their focused Vitest coverage

Add an optional behavior factory with the exact existing controller shape:

```ts
createController?: (
  host: HTMLElement,
  toggle: HTMLElement,
  menu: HTMLElement,
) => MenuController;
```

`DropdownElement.connectedCallback()` selects the custom factory when supplied
and otherwise calls `attachMenu()` exactly as today. Unknown behaviors retain
their current diagnostic. Public open/close and reconnect handling remain in
the host.

Do not add sheet conditionals to `attachMenu`. Add a regression test proving
ordinary menu, select, combobox, and inline-combobox registrations still use the
default controller path.

### 3. Implement and register the sheet controller

Add focused files such as:

- `ts/elements/sheet-controller.ts`
- `ts/elements/behaviors/sheet.ts`
- `ts/elements/sheet-controller.test.ts`

The behavior factory validates that its target is an `HTMLDialogElement` and
that `[data-sheet-panel]` exists. It implements the complete lifecycle above,
including local dismissal listeners, animation state, initial focus, scroll
locking, single-open notification, link navigation, and reconnect-safe document
binding.

Export only the smallest existing single-open notification seam needed by the
sheet; do not move anchored positioning or menu keyboard code into a new shared
module. The sheet emits the already-documented `dropdown:show` and
`dropdown:hide` events on the host.

Import the behavior for registration beside the existing built-in behaviors in
`drop-down.ts`.

JSDOM dialog methods may require small local stubs in the unit fixture. Do not
replace the real-browser coverage with those stubs; Playwright must exercise
actual `showModal()`, cancel, inertness, and focus restoration.

### 4. Add a reusable bottom-sheet target

Modify:

- `common/components/custom_elements.py`
- `common/components/__init__.py` if the new public builder is exported
- component contract tests

Extend `DropdownBehaviorName` with `sheet`. Make target stamping aware that a
native dialog is closed by the absence of `open`: omit the ordinary dropdown's
`hidden` attribute for the sheet behavior instead of stripping it during client
initialization.

Add a reusable target builder that owns:

- the native dialog and `data-bottom-sheet` hook;
- transparent viewport hit area;
- `[data-sheet-panel]`;
- title and label IDs;
- visible close control;
- header/body/safe-area anatomy; and
- the empty navigation destination that accepts caller-owned content.

The settings kit supplies the trigger label and the section list; callers do
not recreate the sheet surface classes.

### 5. Replace settings priority-plus markup and behavior

Modify:

- `common/components/settings_kit.py`
- `ts/elements/settings-section-nav.ts`
- `ts/elements/settings-section-nav.test.ts`
- settings component tests

Server changes:

- render one shared section list in the inline/desktop nav;
- render the full-width two-line mobile trigger;
- compose the reusable bottom-sheet target;
- keep the CSS mode sentinel;
- remove the settings `More` dropdown and its empty menu list;
- change mobile link styling from chips to full-width sheet rows when moved;
  and
- add programmatic focusability to the chosen anchor destination.

Client changes:

- delete item-width measurement and overflow fitting;
- delete menu-role and tabindex mutation;
- move the whole list between destinations;
- synchronize enhanced/fallback visibility atomically;
- close before a mobile-to-desktop move; and
- preserve the existing desktop restoration path and sentinel source of truth.

Do not delete `priority-plus.ts`: the quick-filter bar still imports it.

### 6. Add sticky mobile geometry and styles

Modify:

- `common/components/settings_kit.py`
- `common/input.css` for explicit dialog/backdrop/state selectors that component
  classes cannot express cleanly
- generated `games/static/base.css` through the normal CSS build

Add the normal-flow sticky mobile trigger, opaque surface, documented stacking
level, responsive section scroll margin, sheet maximum height, internal
scrolling, safe-area padding, and reduced-motion rules. Preserve all desktop
sticky and label-fit classes.

CSS is generated through the repository's normal command; do not edit the
compiled stylesheet by hand.

### 7. Replace and extend tests

Update obsolete settings priority-plus expectations rather than keeping tests
for a layout that is no longer supported.

Server/component assertions:

- one settings navigation host;
- one section list and one copy of every anchor;
- full-width explanatory trigger;
- correct dialog ownership and labels;
- no `hidden` collision on the native dialog;
- no menu/menuitem roles or forced negative tabindex;
- responsive scroll-margin classes;
- the sheet's JS media dependency; and
- unchanged desktop rail classes and label contract.

Vitest assertions:

- behavior factory selection and unchanged default selection;
- idempotent open and close;
- failed-open cleanup;
- first-link focus;
- `aria-expanded` transitions;
- cancel interception with one Escape path;
- panel-safe backdrop gestures;
- close-button dismissal;
- link close-then-hash-scroll-focus ordering;
- timeout and reduced-motion completion;
- exact scroll-style restoration;
- resize/disconnect cleanup; and
- repeated disconnect/reconnect without duplicated effects.

Playwright assertions at a representative narrow viewport:

- only the full-width settings trigger is shown after enhancement;
- the trigger's label and helper text are visible;
- the trigger remains sticky after a reachable scroll;
- the sheet is a real open native dialog;
- the visible panel is bottom-docked and does not exceed its height cap;
- the background is inert and cannot scroll;
- Tab and Shift+Tab remain within the dialog;
- Escape, close button, and a safe backdrop press dismiss;
- a press starting in the panel and ending outside does not dismiss;
- short-viewport navigation scrolls inside the sheet;
- link activation leaves the expected hash, destination position, and active
  element;
- the destination is not hidden under the sticky trigger;
- mobile-to-desktop resize while open restores document scrolling and the same
  node identities; and
- disabling JavaScript leaves all section links visible and usable inline.

Retain and run the desktop tests proving:

- rail stickiness at a bounded top coordinate;
- scaffold-boundary stopping;
- inner navigation scrolling in a short viewport;
- no horizontal label overflow;
- inset focus rings; and
- the supported field-layout widths.

## Focused verification strategy

During implementation, run only the narrow checks for the file or behavior just
changed:

- settings component/server-render tests;
- dropdown and sheet Vitest files;
- settings-kit Playwright tests affected by the current step;
- targeted Ruff lint/format checks for changed Python files;
- TypeScript formatting/type checking scoped through the normal project command
  when the controller seam changes;
- CSS generation/check after the style step; and
- `git diff --check` before each commit.

Do not repeatedly run the full project suite. Run `make check` once at the final
settings-panel epic gate, after the remaining issue stages are implemented and
before the epic is declared complete.

## Suggested commit boundaries

1. `docs(settings): specify mobile section bottom sheet`
   - convention and inventory updates only.
2. `refactor(dropdown): allow behavior-owned controllers`
   - controller factory seam and default-path regression tests.
3. `feat(ui): add reusable modal bottom sheet`
   - sheet controller, target builder, styling, and focused primitive tests.
4. `feat(settings): replace mobile priority-plus nav with sheet`
   - same-DOM movement, sticky trigger, anchor focus, and settings tests.
5. `test(settings): harden bottom-sheet browser contract`
   - real-browser interaction, resize, no-JS, and desktop regression coverage
     if those tests are too large to review cleanly in the feature commit.

Each commit stages only its named files. The user's existing `Makefile` change
is unrelated and must remain unstaged.

## Adversarial gates

The implementation is not complete unless every gate passes:

1. **No node cloning.** The same `<ul>` and anchors survive mobile → desktop →
   mobile transitions by identity.
2. **No ARIA-menu leakage.** The sheet remains nav/list/link semantics with
   normal Tab order.
3. **No Escape duplication.** Native `cancel` is intercepted once; no document
   Escape listener races it.
4. **No stranded modality.** Every animation, failure, resize, and disconnect
   path eventually calls native close and releases the document.
5. **No leaked scroll styles.** `html`/`body` inline values and scroll position
   are restored exactly.
6. **No backdrop false positives.** A gesture beginning inside the panel cannot
   dismiss merely because it ends outside.
7. **No focus/navigation conflict.** Section selection ends with the destination
   in view and programmatically focused, not the trigger.
8. **No UA-style collision.** The explicit sheet selector resets native dialog
   geometry, and no unconditional `hidden` competes with native closed state.
9. **No sticky obstruction.** Anchor destinations land below the mobile trigger.
10. **No overlay inversion.** Static content remains below the sticky trigger;
    dropdowns, popovers, the modal sheet, and toasts retain their documented
    ordering.
11. **No reconnect leaks.** Moving/reconnecting the host never duplicates
    document listeners or close effects.
12. **No JavaScript-only navigation.** Failed or disabled enhancement leaves the
    complete inline section list usable.
13. **No fake gesture affordance.** No drag handle ships without tested swipe
    behavior.
14. **No quick-filter regression.** Shared priority-plus arithmetic and the
    quick-filter overflow UI remain intact.
15. **No desktop regression.** Sticky travel, boundary stopping, rail scrolling,
    focus rings, and label fit remain proven in a browser.

## Definition of done

The mobile section navigator is complete when:

- its closed state is self-explanatory on first encounter;
- all section destinations are available in one bottom sheet;
- semantic, keyboard, touch, focus, scroll, motion, and no-JS contracts pass;
- the single section-link DOM survives every responsive transition;
- the existing dropdown menu controller remains behaviorally unchanged;
- the desktop rail retains all existing guarantees;
- documentation no longer claims a sheet can reuse anchored overlay machinery
  unchanged; and
- focused verification is recorded, with the full suite still reserved for the
  final epic gate.
