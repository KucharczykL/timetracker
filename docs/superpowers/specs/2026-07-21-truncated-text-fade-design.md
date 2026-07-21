# Design: width-based fade truncation via `<truncated-text>`

> Design doc for review. No implementation yet — this PR is the plan.
> Rev 2: resolves review points 1–7 (width policy, controller API, overflow-close, table-column plumbing, ARIA, menu contract, verification).

## Context

Game/purchase names in list tables are truncated **by character count** (`truncate_info`, fixed `length=30`) with an ellipsis (now an `⋯` reveal button, from #445/#454). We want truncation driven by the **actual cell/container width** (responsive to column width, font, zoom), with a **right-edge fade** instead of an ellipsis, and the full text revealed on hover (desktop) or a tap button (mobile) — but only when the text actually overflows.

Character truncation can't know render width; only the browser can. So this moves overflow detection **client-side** and replaces the char-truncation display path with a CSS clip + `mask-image` fade in a new `<truncated-text>` custom element. Bonus: with `overflow:hidden` the full text stays in the DOM, so screen readers read the whole name (today's char-truncation drops characters).

Own GitHub issue + branch + PR. Rebase on `origin/main` first (main currently has #445+#454 merged).

## Decisions (settled)

- **Column width:** the element **self-caps** (`min-w-0` + a capped `max-w`, see Width policy) so the auto-layout table's name column stops growing at the cap and clips beyond — no `table-fixed`. *(Risk: table-auto + clipping; see Spike.)*
- **Mobile reveal:** keep the reveal button, but shown **only when actually overflowing** (client-detected), and mobile-only (`[@media(hover:hover)]:hidden`, from #454). Desktop reveals on hover/focus.
- **Scope:** all name/label truncation sites — `NameWithIcon` (linked + menu), `LinkedPurchase` single-game, sort-name column. Menu items (caller-wrapped in `<a>`) get fade + hover/focus tooltip, no tap button (see Menu contract).
- **Architecture:** dedicated `<truncated-text>` element. The menu/`attachMenu` engine is click/keyboard-menu-shaped and unsuitable for a passive tooltip (confirmed); the fitting engine is pop-over's tooltip state machine.
- **Code sharing:** extract pop-over's passive tooltip state machine into a shared controller reused by both `pop-over` and `<truncated-text>` (reusing the already-shared `positionAnchored` + `bindPopupDismiss`).

## Width policy (review #1)

`TruncatedText(..., max_width: str = _NAME_MAX_W)` where `_NAME_MAX_W = "max-w-[24rem]"` (384px). The host is always `min-w-0` so it can shrink **below** the cap. Rationale + behavior:

- **Desktop (wide):** the name gets up to 24rem, then fades. 24rem is generous for a game/purchase name without letting one long name dominate the row or force other columns off-screen. On very wide screens the column caps at 24rem and the remaining columns spread — no runaway.
- **Mobile 390px table (first + last columns only):** `min-w-0` lets the name cell shrink to the width left by the fixed-ish actions column; the name clips/fades to fit. **Acceptance: `document.documentElement.scrollWidth <= window.innerWidth` — no horizontal table scroll** (this is what the spike asserts, review #7).
- **Navbar recent-resumes menu:** caller passes `max_width="max-w-full"`; the menu's own `w-max max-w-xs` (20rem, `layout.py:488`) is the real bound, and `min-w-0` clips within it so a long name can't widen the panel.
- The cap is a single named constant (`_NAME_MAX_W`) so it's tunable in one place; a responsive variant (`max-w-[16rem] sm:max-w-[24rem]`) is a follow-up if 24rem-flat proves wrong on small tablets — not in v1.

## Step 0 — Empirical spike (do first, before the controller extraction)

Confirm the CSS clipping works in the **real** `table-auto` list table: a first-column `<th class="… whitespace-nowrap">` (`common/components/primitives.py:1369`) containing an `inline-flex min-w-0 max-w-[24rem]` host with an inner `overflow-hidden whitespace-nowrap min-w-0` clip span. Throwaway page + Playwright measure (like the earlier `test_tmp_*` probes). **Assert:**
1. desktop: a long name caps at 24rem and clips (`clip.scrollWidth > clip.clientWidth`), short name doesn't;
2. **390px mobile: no horizontal document overflow** (`documentElement.scrollWidth <= innerWidth`) and the name still clips to the available cell width.
- **If it works:** self-capping element, no table changes.
- **If it doesn't:** fall back to a `max-w` on the name `<th>` itself — which requires plumbing column metadata into row rendering (review #4): change `TableRow(data)` (`primitives.py:1347`) to `TableRow(data, columns)` (or pass the first-column class through), add an optional `class_`/`width` field to the `Column` NamedTuple (`primitives.py:1303`), and have `StyledTable` (`primitives.py:1750`) thread `columns` into every `TableRow` call. The hard-coded first-`<th>` class string moves to merge the column's class. Contained, but it is an interface change, not a one-field add.

## Components

### 1. Shared tooltip controller — `ts/elements/tooltip-behavior.ts` (new)
Extract from `ts/elements/pop-over.ts` (~lines 97–232). It is a passive engine; it must receive **all** the elements the positioning/arrow code touches, not just three (review #2):

```ts
interface TooltipConfig {
  host: HTMLElement;      // the custom element (positioning anchor + hover/focus surface)
  trigger: HTMLElement;   // the tappable/focusable element (reveal button, or the link/clip)
  panel: HTMLElement;     // the tooltip panel (data-*-panel)
  content: HTMLElement;   // inner scroll wrapper — max-height cap target (positionAnchored scrollTarget)
  arrow: HTMLElement;     // the arrow square — tintArrow + positionArrow operate on it
  side?: Side;            // "top" (tooltip default) | "bottom"
  tap: boolean;           // wire the pointerdown/click tap latch + bindPopupDismiss
  isActive?: () => boolean; // gate: suppress open when false (truncated-text: is-overflowing)
}
function attachTooltip(config: TooltipConfig): {
  open(): void; close(): void; destroy(): void;
};
```

The controller reads the **elements**, never hard-coded `data-pop-over-*` selectors — so `pop-over` passes its `data-pop-over-{content,arrow}` and `truncated-text` passes its `data-truncated-{content,arrow}`. It owns: pointer-gated hover (`pointerenter`/`pointerleave` gated to `pointerType==="mouse"`), focus in/out, tap latch, `positionAnchored`/`clearAnchoredPosition` + `tintArrow`/`positionArrow`, per-open scroll/resize reposition, Escape (hover mode) / `bindPopupDismiss` (tap mode).
- **`pop-over.ts` refactors to a thin wrapper** over `attachTooltip`. Its #445 vitest (`ts/elements/pop-over.test.ts`) + e2e are the regression net — must stay green unchanged (this is why the extraction follows the spike).

### 2. `<truncated-text>` element
- **Python** (`common/components/primitives.py`): `TruncatedText(text, *, link=None, tap=True, reveal_label="Show full name", max_width=_NAME_MAX_W)` builder + `_TruncatedText = custom_element_builder("truncated-text")`. Register `class TruncatedTextProps(TypedDict): tap: bool` in `custom_elements.py` (mirror `PopOverProps`, `custom_elements.py:512`); run `make gen-element-types`.
  - **Markup:** host `<truncated-text tap="…">` (`relative inline-flex min-w-0 {max_width}`); clip `<span data-truncated-clip>` (`block overflow-hidden whitespace-nowrap min-w-0`, mask via `data-[overflowing]:` variant on the host→clip); text/icon wrapped in `<a href>` when `link`; a sibling reveal `<button data-truncated-reveal>` (`Icon("ellipsis")`, mobile-only `[@media(hover:hover)]:hidden`, shown only under `data-overflowing`); a `data-truncated-panel` tooltip with inner `data-truncated-content` + `data-truncated-arrow`, mirroring `_popover_html` (`primitives.py:271-324`). Reveal button stays a **sibling of the `<a>`** (never nested — preserves the #445 invariant, guarded by `test_html_validity`).
  - **ARIA / tooltip identity (review #5):** the panel needs a unique `id` and the describing element needs `aria-describedby`. To avoid server-side id collisions for **duplicate names** (review #7), the **element assigns these client-side** in `connectedCallback` using a module-scoped counter: `panel.id = "tt-" + (++counter)`, and sets `aria-describedby=panel.id` on the visible name element (the `<a>` if linked, else the clip span) **and** on the reveal button when present. Server markup carries no panel `id` (so parsed HTML has no duplicate ids); the relationship is wired on connect (JS is mandatory in this app). `role="tooltip"` stays on the panel, server-side.
- **TS** (`ts/elements/truncated-text.ts`): `connectedCallback` reads `readTruncatedTextProps`, wires ARIA (above), and a `ResizeObserver` on the clip. On each measure: `overflowing = clip.scrollWidth > clip.clientWidth`; toggle `data-overflowing` on the host. **On the overflowing→not-overflowing transition, call `controller.close()`** so an open tooltip doesn't linger when a resize makes the text fit (review #3). Instantiate `attachTooltip({..., isActive: () => this.overflowing})`. `disconnectedCallback` disconnects the observer + `controller.destroy()`. Native `connectedCallback` (fires on parse + htmx swap) — no `onSwap`.
- **CSS:** fade only under overflow — `data-[overflowing]:[mask-image:linear-gradient(to_right,#000_calc(100%-1.5rem),transparent)]` on the clip (Tailwind v4.1.18 compiles arbitrary `[mask-image:…]` + `data-[…]` variants — confirmed in use). Reveal button + tooltip activation also gate on `data-overflowing`.

### 3. Menu contract (review #6)
`tap=False` (used only by the caller-wrapped navbar menu item, `layout.py:469`) means: **the fade + hover/focus tooltip remain available (as today's `PopoverTruncated` hover span), but no tap `<button>` is rendered.** On touch (no hover, no button) the menu row's own `<a>` navigates to the game — the #455 tap-through. This matches current desktop behavior exactly and keeps every element on the one controller (the tap latch is simply not wired when `tap=False`). e2e must confirm the desktop hover tooltip renders correctly *over* the open dropdown (positioning), and that no `<button>` appears inside the menu `<a>`.

### 4. Replace call sites (`common/components/domain.py`, `games/views/game.py`, `common/layout.py`)
- `NameWithIcon` linked → `TruncatedText(name, link=…)`; unlinked/menu → `TruncatedText(name, link=None, tap=tap)` (menu passes `tap=False`, `max_width="max-w-full"`).
- `LinkedPurchase` **single-game** → `TruncatedText`. **Multi-game games-list** stays an always-on info `Popover`/`_reveal_popover` (info reveal, not truncation — concerns kept separate).
- Sort-name column (`game.py:125`) → `TruncatedText(...)`.
- Remove `PopoverTruncated` once all callers migrate (+ its tests in `tests/test_components.py`); `_reveal_popover`/`_REVEAL_GLYPH_CLASS` retained only for the multi-game info case. Keep the `truncate_info`/`truncate` utility (general, tested) even if display no longer uses it.

### 5. Issue tracking
File a new GitHub issue for this work; update/close **#455** (menu-item residual is now fade + hover-tooltip + tap-through, resolved).

## Files to modify (representative)
- New: `ts/elements/tooltip-behavior.ts`, `ts/elements/truncated-text.ts`, `ts/elements/truncated-text.test.ts`, `e2e/test_truncated_text_e2e.py`.
- `ts/elements/pop-over.ts` (thin wrapper over the controller).
- `common/components/custom_elements.py` (register `TruncatedTextProps`), `common/components/primitives.py` (`TruncatedText`; `Column`/`TableRow(data, columns)`/`StyledTable` plumbing **if** the spike forces the `<th>` fallback; remove `PopoverTruncated`), `common/components/domain.py`, `games/views/game.py`, `common/layout.py`.
- `common/input.css` only if a mask utility needs safelisting.
- `CHANGELOG.md`.
- Regenerated (gitignored): `ts/generated/props.ts`, `dist/`, `games/static/base.css`.

## Verification (review #7)
- **Spike** (Step 0) green before building — including **no mobile horizontal document overflow** at 390px, not merely clip overflow.
- `direnv exec . make check` fully green (lint, format, mypy, ts-check, vitest, full pytest incl. e2e).
- **vitest** (`truncated-text.test.ts`), with faked `scrollWidth`/`clientWidth`:
  - `data-overflowing` toggles on measure; the controller's `isActive` gate blocks opens when not overflowing;
  - **resize into overflow** enables fade/button/tooltip; **resize out of overflow closes an already-open panel** and hides fade/button (review #3);
  - `pop-over.test.ts` still green after the extraction (regression).
- **Playwright** (`test_truncated_text_e2e.py`):
  - desktop: overflowing name fades, **hover opens** the tooltip, no button; **keyboard focus opens** the tooltip and **Escape closes** it;
  - mobile emulation (`is_mobile` → `hover:none`): overflowing name shows the 24px button + fade, tap reveals/dismisses;
  - **short name: no fade, no button, no tooltip** (hover/focus/tap all inert);
  - **dynamic layout:** shrinking the viewport into overflow shows fade+button; growing it back out removes them and closes an open panel;
  - **duplicate names** on one page get **unique panel ids** and correct `aria-describedby` targets;
  - `test_html_validity` invariant still passes (no `<button>` in `<a>`, no duplicate interactive nesting).
- Screenshot desktop vs mobile vs short-name for a visual spot-check.
