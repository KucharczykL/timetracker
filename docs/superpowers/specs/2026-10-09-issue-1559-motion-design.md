# Motion

Part of #1485. Issue #1559, first member of its stack. The sheet levels
of [Every dropdown opens as a bottom sheet](2026-10-09-issue-1559-sheet-by-default-design.md)
use it.

## Tokens

`common/input.css` `@theme` states every duration and easing. No site
writes its own number.

| Token | Value | Use |
| --- | --- | --- |
| `--duration-fast` | 150 ms | popover, menu, calendar in |
| `--duration-fast-exit` | 100 ms | their out |
| `--duration-medium` | 240 ms | centred modal in, depth cue, toast in |
| `--duration-medium-exit` | 160 ms | modal out, toast out |
| `--duration-slow` | 360 ms | sheet in, level push |
| `--duration-slow-exit` | 240 ms | sheet out, level back |
| `--duration-reduced` | 100 ms | reduced-motion crossfade |
| `--ease-enter` | `cubic-bezier(0.05, 0.7, 0.1, 1)` | Material 3 emphasized decelerate |
| `--ease-exit` | `cubic-bezier(0.3, 0, 0.8, 0.15)` | Material 3 emphasized accelerate |
| `--ease-sheet` | `cubic-bezier(0.32, 0.72, 0, 1)` | Apple's sheet curve (Ionic, Vaul) |

An exit is two thirds of its entry. Tailwind v4 makes `ease-enter`,
`ease-exit` and `ease-sheet` utilities from the `--ease-*` namespace. It
has no duration namespace, so a site writes
`duration-(--duration-fast)`. TypeScript reads a duration once from the
computed root style (`motionDuration(name)` in `ts/motion.ts`) and never
holds a number of its own.

## Surfaces

- **Anchored popover** (menus, listboxes, calendars, the overflow
  panels, tooltips): fade from 0, scale from 95 %, and move 4 px from the
  side it opens towards. `transform-origin` is the anchor corner.
  `positionAnchored` stamps `data-side` (`top`, `bottom`, `left`,
  `right`) and `data-align`; the panel's classes read them. Fast in, fast
  exit out.
- **Centred modal** (form dialog, unsaved-changes warning): the panel
  fades and scales from 96 %. The backdrop fades in and out. Medium in,
  medium exit out.
- **Bottom sheet**: slides up on `ease-sheet`, slow in, slow exit out.
  The backdrop fades with it.
- **Sheet level**: the iOS push. The level enters from 100 % right; the
  level below moves 30 % left and dims. Both use `ease-sheet`, slow; the
  height animates in the same time. Back reverses it at slow exit.
- **Depth cue** (#1514): the step back moves on medium and
  `ease-enter`. The darkening is a scrim over the covered panel whose
  opacity moves, not a `filter`. The panel class splits: the cue's
  transition on `transform` and the scrim, the sheet's on `translate`
  and `opacity`.
- **Toast**: enters (fade, 2 rem from the right) at medium on
  `ease-enter`, leaves at medium exit on `ease-exit`.

Only `transform`, `translate`, `scale` and `opacity` animate. A height
change between sheet levels is the one exception: it animates the
panel's `height` with the Web Animations API, because no transform keeps
the content unscaled.

## Reduced motion

Under `prefers-reduced-motion: reduce`, each surface keeps a crossfade of
`--duration-reduced` and drops every move and scale. A sheet and a level
fade in place.

## Mechanism

- **Dialog entry** is CSS: `@starting-style` (Tailwind's `starting:`) on
  the open state, with `transition-behavior: allow-discrete`.
- **Anchored entry** is a flushed state. `showInTopLayer` shows the panel
  with `data-motion="entering"`, whose classes hold the start values and
  no transition. The caller positions it, so `data-side` is known; then
  `settleEntry` reads one computed style and removes the stamp, and the
  transition runs. `@starting-style` would resolve before the side.
  `positionAnchored` writes `top` or `bottom`; `positionSubmenu` writes
  `left` or `right`.
- **Toast entry** is a class the toast takes once. A toast moves into the
  top modal on every modal change, and a moved node replays
  `@starting-style`.
- **Exit** is held by script, in every engine. The element stays open
  with `data-motion="leaving"` and its classes move to the closed
  values. It hides when every animation on it and its subtree
  (`getAnimations({ subtree: true })`) has finished, or at its exit
  duration plus 100 ms. Where `getAnimations` is absent (jsdom), or the
  duration reads 0, it hides at once, so unit tests stay synchronous.
- **Panels:** `hideFromTopLayer` holds the leave. The caller's close is
  logical at once: `dropdown:hide` fires at the start. Geometry
  (`clearAnchoredPosition`), scroll and resize listeners and the
  `ResizeObserver` go at the finish. An open, or `releaseFromTopLayer`
  (a host move into a sheet), cancels a held leave.
- **Modals:** the layer's `leave` hook already holds a modal; it now
  waits on the same animation rule under its 1 s cap. A centred modal
  that states no `leave` gets the default one. `CLOSE_FALLBACK_MS` and
  the `translate` `transitionend` go.
- **Why not `overlay`:** measured on 2026-10-09. Chromium 154 runs entry
  and a native exit (`overlay` and `display` with `allow-discrete`).
  Firefox 157 runs the entry, has no `overlay`, and hides a closed dialog
  or popover at once. Both run a held exit. WebKit was not measured
  here; Safari 17.5 and later have `@starting-style` and
  `allow-discrete`. A held exit needs neither. The person's iPhone check
  covers WebKit.
- `menu-behavior.ts`'s two "no animation" notes go. `motion-safe:` goes
  from every motion class: reduced motion now crossfades.

## Tests

`e2e/conftest.py` opens every context with `reduced_motion="reduce"`.
That bounds every leave at 200 ms; it does not remove it, so a test
waits on a settled state, as `picker_opened` does. A
few tests in `e2e/test_motion_e2e.py` set `no-preference` and check that
each open, close and level flow settles: the element reaches its end
state, and nothing stays `data-motion="leaving"`. A Python test refuses
a `duration-<number>` or a bare `ease-in`/`ease-out` class in
`common/` and `games/`, and a TypeScript literal duration beside a
transition.

## Follow-up issues to file

- None.
