# Motion

Part of #1485. Issue #1559. The sheet levels of
[Every dropdown opens as a bottom sheet](2026-10-09-issue-1559-sheet-by-default-design.md)
use it.

## Tokens

`common/input.css` `@theme` states every duration and easing. No site
writes its own number.

| Token | Value | Use |
| --- | --- | --- |
| `--duration-fast` / `-exit` | 150 / 100 ms | popover, menu, calendar |
| `--duration-medium` / `-exit` | 240 / 160 ms | centred modal, depth cue, toast |
| `--duration-slow` / `-exit` | 360 / 240 ms | sheet, level |
| `--duration-reduced` | 100 ms | reduced-motion crossfade |
| `--ease-enter` | `cubic-bezier(0.05, 0.7, 0.1, 1)` | entry |
| `--ease-exit` | `cubic-bezier(0.3, 0, 0.8, 0.15)` | exit |
| `--ease-sheet` | `cubic-bezier(0.32, 0.72, 0, 1)` | sheet and level |

An exit is two thirds of its entry. A class writes
`duration-(--duration-fast)`; Tailwind has no duration namespace.
TypeScript reads a duration with `motionDuration(token)` in
`ts/motion.ts`. A test refuses a literal duration or a bare
`ease-in`/`ease-out` class.

## Surfaces

- **Anchored popover:** fades in, scales from 95 % and moves 4 px from
  the side it opens towards. `positionAnchored` stamps `data-side` and
  `data-align`.
- **Centred modal:** fades and scales from 96 %. The backdrop fades.
- **Bottom sheet:** slides up. The backdrop fades.
- **Level:** the level slides in from the right. The sheet below moves
  30 % left and darkens under its scrim. The scrim keeps the panel
  opaque, so the page never shows through. The level casts a shadow on
  its leading edge. Back reverses the slide.
- **Depth cue:** a covered panel steps back and darkens under its scrim.
  The scrim is the panel's `::after`; no `filter` and no `opacity`.
- **Toast:** fades in from the right and fades out.

Only `transform`, `translate`, `scale` and `opacity` animate. No height
animates: a sheet that can open a level has a fixed height.

## Reduced motion

Under `prefers-reduced-motion: reduce`, every surface crossfades for
`--duration-reduced`. A level fades in over the darkened sheet below.

## Mechanism

- **Dialog entry** is CSS: `@starting-style` on the open state.
- **Anchored entry:** `showInTopLayer` stamps `data-motion="entering"`.
  The caller positions the panel, then `settleEntry` removes the stamp
  and the transition runs.
- **Exit** is held by script. `holdLeave` stamps `data-motion="leaving"`
  and hides the element when its animations finish, or at its exit
  duration plus 100 ms. Without `getAnimations`, or at duration 0, it
  hides at once.
- **Panels:** `hideFromTopLayer` holds the leave. The close is logical
  at once; geometry and listeners go when the leave ends. An open or
  `releaseFromTopLayer` cancels a held leave.
- **Modals:** the layer's `leave` hook holds a modal under a 1 s cap.
  A centred modal gets a default leave.
- **Levels** animate with the Web Animations API, `fill: "forwards"`. A
  slide keeps its last frame until the level settles, then the
  animations cancel. A slide that snaps back first shows the wrong panel
  for one frame in WebKit.

## Tests

`e2e/conftest.py` opens every context with `reduced_motion="reduce"`. A
test waits on a settled state. `e2e/test_motion_e2e.py` sets
`no-preference` and checks that each flow settles.
