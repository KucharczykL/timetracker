# Design: width-based fade truncation via `<truncated-text>`

> Design doc for review. No implementation yet — this PR is the plan.

## Context

Game/purchase names in list tables are truncated **by character count** (`truncate_info`, fixed `length=30`) with an `⋯` reveal button. We want truncation driven by the **actual cell/container width** (responsive to column width, font, zoom), with a **right-edge fade** instead of an ellipsis, and the full text revealed on hover (desktop) or a tap button (mobile) — but only when the text actually overflows.

Character truncation can't know render width; only the browser can. So this moves overflow detection **client-side** and replaces the char-truncation display path with a CSS clip + `mask-image` fade in a new `<truncated-text>` custom element. With `overflow:hidden` the **full text stays in the clip's DOM** and thus in the accessibility tree — a screen reader reads the whole name straight from the visible cell (the existing char-truncation likewise exposes the full name via its popover's `aria-describedby`, so neither path loses SR data). Because the clip already exposes the full text to AT, the new element needs **almost no ARIA** — see §ARIA.

Own GitHub issue + branch + PR. Rebase on `origin/main` first.

## Decisions (settled)

- **Column width:** the element **self-caps** (`min-w-0` + a capped `max-w`, see Width policy) so the auto-layout table's name column stops growing at the cap and clips beyond — no `table-fixed`. *(Risk: table-auto + clipping; see Spike.)*
- **Mobile reveal:** keep the reveal button, but shown **only when actually overflowing** (client-detected), and mobile-only (`[@media(hover:hover)]:hidden`). Desktop reveals on hover/focus.
- **Scope:** all name/label truncation sites — `NameWithIcon` (linked + menu), `LinkedPurchase` (single- **and** multi-game), sort-name column. Menu items (caller-wrapped in `<a>`) get fade + **hover-only** tooltip, no tap button (see Menu contract).
- **Architecture:** dedicated `<truncated-text>` element. The menu/`attachMenu` engine is click/keyboard-menu-shaped and unsuitable for a passive tooltip; the fitting engine is pop-over's tooltip state machine.
- **Code sharing:** extract pop-over's passive tooltip state machine into a shared controller reused by both `pop-over` and `<truncated-text>` (reusing the already-shared `positionAnchored` + `bindPopupDismiss`).

## Width policy

`TruncatedText(..., max_width: str = _NAME_MAX_W)` where `_NAME_MAX_W = "max-w-[24rem]"` (384px). The host is always `min-w-0` so it can shrink **below** the cap. Rationale + behavior:

- **Desktop (wide):** the name gets up to 24rem, then fades. 24rem is generous for a game/purchase name without letting one long name dominate the row or force other columns off-screen. On very wide screens the column caps at 24rem and the remaining columns spread — no runaway.
- **Mobile 390px table (first + last columns only):** `min-w-0` lets the name cell shrink to the width left by the fixed-ish actions column; the name clips/fades to fit. **Acceptance: the table's own `overflow-x-auto` scroll wrapper (`primitives.py:1757`, `Div(class_="relative overflow-x-auto")`) has `scrollWidth <= clientWidth`.** The wrapper absorbs table overflow into an inner scrollbar, so `documentElement` cannot be the measurement target — a probe showed doc `scrollWidth==390` while the wrapper was `580`. The self-cap alone did **not** achieve this in the probe (the host stayed 384px instead of shrinking into the first-column space), so this is expected to require the fallback (below).
- **Navbar recent-resumes menu:** caller passes `max_width="max-w-full"`; the menu's own `w-max max-w-xs` (20rem, `layout.py:488`) is the real bound, and `min-w-0` clips within it so a long name can't widen the panel.
- The cap is a single named constant (`_NAME_MAX_W`) so it's tunable in one place; a responsive variant (`max-w-[16rem] sm:max-w-[24rem]`) is a follow-up if 24rem-flat proves wrong on small tablets — not in v1.

## Step 0 — Empirical spike (do first, before the controller extraction)

Confirm the CSS clipping works in the **real** `table-auto` list table (first-column `<th class="… whitespace-nowrap">`, `common/components/primitives.py:1369`) inside its `overflow-x-auto` scroll wrapper. Throwaway page + Playwright measure (`test_tmp_*`-style probe). A probe has already shown the self-cap **insufficient** (host 384px, wrapper 580px; even `max-width:384px` on the `<th>` alone left the wrapper at 532px), so the spike's job is to find the **complete cell + child constraint set**, empirically, and encode it. **Assert, at 390 / 640 / 768px:**
1. **the scroll wrapper** (`div.overflow-x-auto`) has `scrollWidth <= clientWidth` (no inner horizontal scrollbar) at 390px;
2. the mobile clip is **narrower than the 24rem cap** (it actually shrank into the available first-column space, not stuck at 384px);
3. the actions (last) column stays **visible and non-overlapping** at 390px;
4. at an intermediate width (640 or 768px) the responsive-hidden middle columns **reappear** and still no wrapper scroll;
5. desktop: a long name caps at 24rem and clips; a short name does not.
- **Expected fallback (per the probe):** constrain **both** the table cell sizing **and** the child's used width — likely `table-fixed` with an explicit first-column width, **or** a `<th>` `max-w` combined with the host being forced to the cell width (`w-full min-w-0`) rather than self-sizing. The exact combination is the spike's deliverable.
- **Table plumbing this needs:** giving the first `<th>` a class/width means `TableRow` must see the column metadata. Change `TableRow(data)` (`primitives.py:1347`) to **`TableRow(data, columns=None)` — the new arg is OPTIONAL**, because there is a production call outside `StyledTable` (`games/views/purchase.py:466`, the refund HTMX row fragment) plus direct test calls that must keep working; when `columns` is absent, behavior is unchanged. `StyledTable` (`primitives.py:1750`) passes `columns`; add an optional `class_`/`width` to `Column` (`primitives.py:1303`) merged into the first-`<th>` class. (Alternatively route both `StyledTable` and the purchase fragment through one shared purchase-column definition.)

## Components

### 1. Shared tooltip controller — `ts/elements/tooltip-behavior.ts` (new)
Extract from `ts/elements/pop-over.ts` (~lines 97–232). It is a passive engine; it must receive **all** the elements the positioning/arrow code touches:

```ts
interface TooltipConfig {
  host: HTMLElement;      // the custom element (positioning anchor + hover/focus surface)
  trigger: HTMLElement;   // the tappable/focusable element (reveal button, or the link/clip)
  panel: HTMLElement;     // the tooltip panel (data-*-panel)
  content?: HTMLElement;  // OPTIONAL inner scroll wrapper — max-height cap target; falls back to panel when absent (the pop-over test fixture has no content wrapper)
  arrow?: HTMLElement;    // OPTIONAL arrow square — tint/position skipped when absent (same fixture has one, but keep it optional/robust)
  side?: Side;            // "top" (tooltip default) | "bottom"
  tap: boolean;           // wire the pointerdown/click tap latch + bindPopupDismiss
  isActive?: () => boolean; // gate: suppress open when false (truncated-text: is-overflowing)
}
function attachTooltip(config: TooltipConfig): {
  open(): void; close(): void; destroy(): void;
};
```

The controller reads the passed **elements**, never hard-coded selectors, so callers own their own markup — though both `pop-over` and `truncated-text` use the same `data-pop-over-{panel,content,arrow}` attributes for the panel anatomy (truncated-text adds only `data-truncated-{clip,reveal}`). It owns: pointer-gated hover (`pointerenter`/`pointerleave` gated to `pointerType==="mouse"`), focus in/out, tap latch, `positionAnchored`/`clearAnchoredPosition` + `tintArrow`/`positionArrow`, per-open scroll/resize reposition, Escape (hover mode) / `bindPopupDismiss` (tap mode).
- **`pop-over.ts` refactors to a thin wrapper** over `attachTooltip`, preserving its `data-pop-over-*` markup so existing selectors keep working. Its vitest (`ts/elements/pop-over.test.ts`) + e2e are the regression net — must stay green (this is why the extraction follows the spike). **Note:** the vitest mount fixture (`pop-over.test.ts:8-24`) renders `data-pop-over-{trigger,panel,arrow}` but **no `data-pop-over-content`** wrapper — so `content` is optional in the controller (above); the fixture stays as-is. The **name-reveal** e2e selectors move from `pop-over [data-pop-over-trigger]` to `truncated-text [data-truncated-reveal]` in `test_touch_targets_e2e.py` + `test_purchase_e2e.py` once names migrate (the "!" cue and price popovers stay on `pop-over`).

### 2. `<truncated-text>` element
- **Python** (`common/components/primitives.py`): `TruncatedText(text, *, leading=None, link=None, tap=True, reveal="auto", tooltip_content=None, instance_key=None, reveal_label="Show full text", max_width=_NAME_MAX_W)` builder + `_TruncatedText = custom_element_builder("truncated-text")`. Register `class TruncatedTextProps(TypedDict): tap: bool; reveal: str` in `custom_elements.py` (mirror `PopOverProps`, `custom_elements.py:512`); run `make gen-element-types`.
  - **`leading`**: a visible-content slot (platform/emulation icons) rendered **before the clip, always outside it** — the same on linked and unlinked, so clip/mask math and the focus target are identical. Inside the `<a>` when `link` (icons stay in the hit area), but never inside the `overflow-hidden` clip span. **`reveal`**: `"auto"` (overflow-gated) or `"always"` (multi-game). **`tooltip_content`**: panel body; **`None` = the tooltip shows the same `text`** (the common case). **`instance_key`**: only needed when `tooltip_content` is set (see ARIA — the default case has no panel id at all). **`reveal_label`**: generic default `"Show full text"` (no name-specific default in a primitive).
  - **Markup + DOM nesting:** host `<truncated-text tap="…">` is a Tailwind **`group`** (`group relative inline-flex min-w-0 {max_width}`) carrying `data-overflowing`; overflow-reactive children use `group-data-[overflowing]:` (never a bare `data-[overflowing]:`, which matches the child's own attr, not the host's). **Icons are always outside the clip** (one structure for both linked and unlinked):
    - **inner run** (the flex content): `[ leading-icons, <span data-truncated-clip>text</span> ]`; wrapped in `<a href>` when `link` (icons + clip inside the link → full hit area), bare otherwise.
    - then the `absolute` reveal `<button>` (below) and the panel — both **siblings of the `<a>`** (never nested — the `test_html_validity` invariant).
    - `overflow-hidden` is on the **clip span only** (text), so the `<a>`'s focus ring (link box, outside the clip) isn't clipped, and the mask covers only the text — icons never fade.
    - `data-truncated-clip`: `block overflow-hidden whitespace-nowrap min-w-0` + `group-data-[overflowing]:[mask-image:…]`. Reveal `<button data-truncated-reveal>` (`Icon("ellipsis")`, mobile-only `[@media(hover:hover)]:hidden`, shown via `group-data-[overflowing]:` — or always for `reveal="always"`).
    - **Panel reuses the pop-over anatomy attributes**: `data-pop-over-{panel,content,arrow}` (the controller/positioner already understand them; only `data-truncated-{clip,reveal}` are new concepts), so existing panel selectors + the positioner need no new dialect — halves the e2e selector migration.
  - **Unlinked desktop keyboard reveal:** an unlinked host has no focusable element for desktop keyboard users (the only `<button>` is `hover:hover`-hidden). So the element manages an **overflow-only `tabindex="0"` on the clip span** — added when `data-overflowing` (and no wrapping link) so the clip is focusable and focus opens the tooltip via the controller (`trigger` = the clip span), **removed when it fits** so short names gain **no useless tab stop**. Linked hosts already have the `<a>` (a descendant → focus bubbles to the host); menu (`tap=False`) stays hover-only.
  - **No overflow hysteresis:** the reveal button is **`absolute` positioned** over the clip's right-edge fade area (`absolute inset-y-0 right-0` on the host, which is `relative`), **out of normal flow**, so showing/hiding it does **not** change the clip's width — the measurement basis (`clip.scrollWidth` vs `clip.clientWidth`) is independent of the button. An in-flow `inline-flex` sibling button would consume ~24px when shown, keeping the clip narrow enough to stay `data-overflowing` even after the viewport grew past the point where the text fits in a no-button layout (a stuck-open feedback loop). The button overlays the already-faded last ~1.5rem, so it hides no readable text, and is 24px (WCAG 2.5.8). It remains a **sibling of the `<a>`**, just positioned — the invariant holds.
  - **ARIA — almost none:** because the clip keeps the **full text in the DOM/accessibility tree**, a screen reader already reads the whole name from the visible cell. When `tooltip_content is None` (the default — the panel just re-shows `text`), the tooltip is a **purely visual** recovery of visually-clipped text and adds nothing for AT. So in the default case: the panel gets **`aria-hidden="true"`, no `id`, no `aria-describedby`, no `instance_key`.**
    - **Only when `tooltip_content` differs** from the text (the multi-game games-list) is the panel real information: there render the WAI relationship — `role="tooltip"`, a unique `panel_id = randomid(content=f"truncated-text:{instance_key}:{text}")` (**`content=` not `seed=`** — the `content=` form hashes to a valid id; `seed=`, `core.py:470`, returns a ≥10-char seed verbatim, yielding invalid ids with spaces), and `aria-describedby={panel_id}` on the link + reveal button. `instance_key` (context+slot, e.g. `purchase-list:{purchase.pk}`) is required **only here**, so the collision surface shrinks to the few multi-game rows.
    - **Uniqueness enforcement:** add a **DEBUG-only render-time assertion** — the `Page()`/document walk that already collects media also asserts no duplicate element `id` (cheap, catches any future differing-content call site). The full-page id-uniqueness / `aria-describedby`-resolves test targets a fixture with **multi-game purchases** (the only id-bearing case).
- **TS** (`ts/elements/truncated-text.ts`): `connectedCallback` reads `readTruncatedTextProps` and wires a `ResizeObserver` on the clip. Measurement uses a **1px epsilon**: `overflowing = clip.scrollWidth - clip.clientWidth > 1` — `scrollWidth` ceils content width, so a text fitting to the subpixel would otherwise read as 1px-overflowing (false fade/button, flapping at zoom levels); toggle `data-overflowing` accordingly. On overflowing→not, **`controller.close()`** (so an open tooltip doesn't linger) **and remove the managed `tabindex`** (unlinked); on the reverse, add it. `reveal="always"` is always-active (fade still gates on overflow): `attachTooltip({..., isActive: () => this.reveal === "always" || this.overflowing})`. `disconnectedCallback` disconnects the observer + `controller.destroy()`. Native `connectedCallback` (fires on parse + htmx swap) — no `onSwap`.
  - **Font-load re-measure:** names use the `font-condensed` webfont (`domain.py:239`). If `connectedCallback` measures before the font loads, the fallback-font width is wrong; when the real font swaps in, the clip's **border-box is unchanged** (column-constrained), so the `ResizeObserver` **never fires** and `data-overflowing` stays stale until an unrelated resize. So: a **single shared module listener** re-measures every mounted instance on `document.fonts.ready` (and on `document.fonts`' `loadingdone` for late/again-cached loads); each instance registers/deregisters in connect/disconnect. Covered by vitest (mock `document.fonts.ready`) + e2e (assert an overflowing name is `data-overflowing` after fonts settle, with no intervening resize).
- **CSS:** fade only under overflow — `group-data-[overflowing]:[mask-image:linear-gradient(to_right,#000_calc(100%-1.5rem),transparent)]` on the clip (host is the `group`; Tailwind v4 — lockfile resolves **4.3.0** — compiles arbitrary `[mask-image:…]` + `group-data-[…]` variants). The reveal button's visibility gates the same way (`group-data-[overflowing]:` shown, or always for `reveal="always"`); tooltip activation is JS via the controller's `isActive`.

### 3. Menu contract
`tap=False` (used only by the caller-wrapped navbar menu item, `layout.py:469`) means: **fade + hover-only tooltip (desktop), no tap `<button>`, tap-through on touch.** The menu case is **hover-only, not hover/focus**: the menu row's `<a role=menuitem>` is an **ancestor** of `<truncated-text>`, and focus on it does not propagate *down* into the host (focus events bubble up, not down), so the host never sees the focus — the same limitation `pop-over` documents for a wrapping-`<a>` ancestor, and the same as today's `PopoverTruncated` hover span. On touch (no hover, no button) the `<a>` navigates to the game (tap-through). Keeps every element on the one controller (the tap latch is simply not wired when `tap=False`). e2e: confirm the desktop **hover** tooltip renders correctly *over* the open dropdown, and that **no `<button>` appears inside the menu `<a>`** — don't assert a focus-triggered tooltip there.

(Focus-triggered tooltips DO work for the non-menu **linked table names**, where the `<a>` is a **descendant** of the host — focus bubbles up to it; that's the keyboard case in Verification.)

### 4. Replace call sites (`common/components/domain.py`, `games/views/game.py`, `common/layout.py`)
- `NameWithIcon` linked → `TruncatedText(name, link=…, leading=icons)`; unlinked/menu → `TruncatedText(name, link=None, leading=icons, tap=tap)` (menu passes `tap=False`, `max_width="max-w-full"`). **No `instance_key`** — the tooltip re-shows the name, so no panel id. `leading` carries the platform/emulation icons (`domain.py:222-251`).
- `LinkedPurchase` **single-game** → `TruncatedText(name, link=…, leading=Icon(...))` (no `instance_key`). **Multi-game:** `TruncatedText(..., reveal="always", tooltip_content=games_list, instance_key=f"purchase-list:{purchase.pk}")` — the bundle name width-clips + fades, and the games-list reveal is always available. **This is the only call site that passes `instance_key`** (its tooltip content differs from the text), so it's the only one bearing a panel id. Replaces the separate `_reveal_popover` for the bundle case — no second competing tooltip/button, no leftover char-truncation.
- Sort-name column (`game.py:125`, unlinked) → `TruncatedText(sort_name, link=None, tap=True)` (no `instance_key`).
- Remove `PopoverTruncated` and `_reveal_popover`/`_REVEAL_GLYPH_CLASS` once all callers migrate (+ their tests in `tests/test_components.py`). Keep the `truncate_info`/`truncate` utility (general, tested) even if display no longer uses it.

### 5. Issue tracking
File a new GitHub issue for this work. **#455 is already closed** — no action (the menu residual it tracked is subsumed here).

## Files to modify (representative)
- New: `ts/elements/tooltip-behavior.ts`, `ts/elements/truncated-text.ts`, `ts/elements/truncated-text.test.ts`, `e2e/test_truncated_text_e2e.py`.
- `ts/elements/pop-over.ts` (thin wrapper over the controller).
- `common/components/custom_elements.py` (register `TruncatedTextProps`), `common/components/primitives.py` (`TruncatedText`; `Column` + `TableRow(data, columns=None)` optional + `StyledTable` plumbing **if** the spike forces the `<th>` fallback; remove `PopoverTruncated`), `common/components/domain.py`, `games/views/game.py`, `common/layout.py`.
- `tests/test_touch_targets_e2e.py` + `e2e/test_purchase_e2e.py` (migrate name-reveal selectors from `pop-over` to `truncated-text`); the full-page id-uniqueness invariant (extend `tests/test_html_validity.py` or a sibling).
- `common/input.css` only if a mask utility needs safelisting.
- `CHANGELOG.md`.
- Regenerated (gitignored): `ts/generated/props.ts`, `dist/`, `games/static/base.css`.

## Verification
- **Spike** (Step 0) green before building — the **`overflow-x-auto` scroll wrapper** (not `documentElement`) has `scrollWidth <= clientWidth` at 390px, the clip shrank below the 24rem cap, the actions column stays visible, and middle columns reappear at 640/768px. Also pin the **exactly-fits** case: a name whose text fits to the subpixel is **not** flagged overflowing (no false fade at the 1px boundary).
- `direnv exec . make check` fully green (lint, format, mypy, ts-check, vitest, full pytest incl. e2e).
- **vitest** (`truncated-text.test.ts`), with faked `scrollWidth`/`clientWidth`:
  - `data-overflowing` toggles on measure; the controller's `isActive` gate blocks opens when not overflowing;
  - **1px epsilon:** `scrollWidth == clientWidth + 1` reads as **not** overflowing; `+2` does;
  - **font-load:** an instance that measured "fits" with the fallback font flips to `data-overflowing` after `document.fonts.ready` resolves, **with no resize event** in between (mock `document.fonts.ready`);
  - **resize into overflow** enables fade/button/tooltip; **resize out of overflow closes an already-open panel** and hides fade/button;
  - `pop-over.test.ts` still green after the extraction (regression).
- **Playwright** (`test_truncated_text_e2e.py`):
  - desktop: overflowing name fades, **hover opens** the tooltip, no button; **keyboard focus opens** the tooltip and **Escape closes** it;
  - mobile emulation (`is_mobile` → `hover:none`): overflowing name shows the 24px button + fade, tap reveals/dismisses;
  - **short name: no fade, no button, no tooltip, and no tab stop** (hover/focus/tap all inert; the unlinked clip has no `tabindex`);
  - **unlinked keyboard:** an overflowing **sort-name** (unlinked) is Tab-focusable, focus opens its tooltip, Escape closes it; a short sort-name is not in the tab order;
  - **multi-game bundle:** a long-named multi-game purchase clips + fades the bundle name **and** exposes the games-list reveal (`reveal="always"`) with a single tooltip/button (no competing popover);
  - **dynamic layout:** shrinking the viewport into overflow shows fade+button; growing it back out removes them and closes an open panel;
  - **no button-width hysteresis:** overflow → button appears → grow the viewport to just past where the text fits the **no-button** layout → `data-overflowing` clears at that threshold (not a button-width later), and fade+button disappear — proving the absolute button doesn't hold the state open;
  - **default-case a11y:** a plain overflowing name has **no panel `id`, no `aria-describedby`**, and the panel is `aria-hidden="true"` — the clip's own text is the accessible text; only **multi-game** rows bear a panel id;
  - **id uniqueness:** a fixture with several **multi-game purchases** (the only id-bearing case) — every id unique, every `aria-describedby` token resolves to exactly one element; plus the DEBUG render-time `Page()`-walk duplicate-id assertion;
  - `test_html_validity` invariant still passes (no `<button>` in `<a>`, no duplicate interactive nesting).
- Screenshot desktop vs mobile vs short-name for a visual spot-check.
