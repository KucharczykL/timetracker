/**
 * Shared viewport-aware fixed positioner for anchored panels (issue #303).
 *
 * The geometry both the dropdown machinery (menu-behavior.ts, for its bottom-*
 * menu panels) and the hover tooltip (pop-over.ts) need: pin the panel
 * `position: fixed` so it escapes any clipping/overflow ancestor (issue #39),
 * align it under/over an anchor with a configurable default side + gap, flip to
 * the other side when the preferred one lacks room, clamp horizontally to the
 * viewport, and correct for a transformed/filtered ancestor that becomes the
 * containing block for `fixed`.
 *
 * It deliberately owns ONLY the geometry — not the menu concerns (keyboard
 * roving, single-open coordination, submenu flyouts), which stay in attachMenu.
 * The right-start submenu flyout has its own bespoke anchor/first-item alignment
 * and keeps its own positioner there.
 */

export const VIEWPORT_MARGIN = 8;

export type Align = "start" | "center" | "end";
export type Side = "top" | "bottom";

export interface AnchorOptions {
  // Horizontal alignment of the panel relative to the anchor.
  align: Align;
  // Preferred vertical side; flips to the other only when the content does not
  // fit the preferred side but fits better on the other. Defaults to "bottom".
  side?: Side;
  // Daylight between the anchor and the panel's near edge. Defaults to 0 (flush,
  // the dropdown look); tooltips pass a small gap.
  gap?: number;
  // Force the panel's min-width to the anchor's width (the value selectors).
  matchWidth?: boolean;
  // Cap the panel to the available height on its resolved side and let it scroll
  // (menus). Tooltips leave this off — they are small and never scroll.
  scrollable?: boolean;
}

export interface AnchorResult {
  // The resolved side after any flip.
  side: Side;
  // The panel's viewport-left (post-clamp) and measured width, plus the anchor's
  // horizontal center — enough for a caller to place an arrow without re-measuring.
  left: number;
  width: number;
  anchorCenterX: number;
}

/**
 * Position `panel` (already in the DOM; may have just been unhidden) against
 * `anchor`, writing its inline `position/left/top` (+ `max-height`/`overflow-y`
 * when scrollable, `min-width`/`width` when matchWidth). Returns the resolved
 * geometry.
 */
export function positionAnchored(
  anchor: HTMLElement,
  panel: HTMLElement,
  options: AnchorOptions,
): AnchorResult {
  const side = options.side ?? "bottom";
  const gap = options.gap ?? 0;

  // Pin `fixed` BEFORE measuring the anchor: a just-unhidden, still in-flow panel
  // that is a descendant of the anchor would otherwise inflate the anchor's box.
  panel.style.position = "fixed";
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  if (options.scrollable) panel.style.overflowY = "auto";

  // Pin to (0,0) and measure the origin so viewport coords convert to the
  // containing block's coords (a transformed/filtered ancestor becomes the
  // containing block for `fixed`, so fixed coords are relative to it).
  panel.style.left = "0px";
  panel.style.top = "0px";
  const origin = panel.getBoundingClientRect();
  const rect = anchor.getBoundingClientRect();

  const availableBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN - gap;
  const availableAbove = rect.top - VIEWPORT_MARGIN - gap;
  const spacePreferred = side === "bottom" ? availableBelow : availableAbove;
  const spaceOther = side === "bottom" ? availableAbove : availableBelow;
  // scrollHeight (not offsetHeight) so a tall scrollable panel's true content
  // height drives the flip, measured before any maxHeight cap and before
  // matchWidth (which the original menu positioner also applied post-flip).
  const flip = panel.scrollHeight > spacePreferred && spaceOther > spacePreferred;
  const resolved: Side = flip ? (side === "bottom" ? "top" : "bottom") : side;

  if (options.scrollable) {
    panel.style.maxHeight = `${Math.max(
      0,
      resolved === "bottom" ? availableBelow : availableAbove,
    )}px`;
  }
  if (options.matchWidth) {
    panel.style.minWidth = `${rect.width}px`;
    panel.style.width = "max-content";
  }

  const width = panel.offsetWidth;
  let left: number;
  if (options.align === "start") left = rect.left;
  else if (options.align === "end") left = rect.right - width;
  else left = rect.left + rect.width / 2 - width / 2;
  left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(left, window.innerWidth - width - VIEWPORT_MARGIN),
  );

  // offsetHeight is read AFTER maxHeight so a capped panel flips against its
  // capped height. Clamp the top so a tall panel near an edge can't run
  // off-screen (a no-op for scrollable menus, already capped to fit).
  const top = Math.max(
    VIEWPORT_MARGIN,
    resolved === "bottom" ? rect.bottom + gap : rect.top - panel.offsetHeight - gap,
  );

  panel.style.left = `${left - origin.x}px`;
  panel.style.top = `${top - origin.y}px`;

  return { side: resolved, left, width, anchorCenterX: rect.left + rect.width / 2 };
}
