/**
 * Shared viewport-aware fixed positioner for anchored panels: the geometry both
 * the dropdown menus (menu-behavior.ts) and the hover tooltip (pop-over.ts) use.
 * Pins the panel `position: fixed` (so it escapes clipping/overflow ancestors),
 * aligns it under/over an anchor with a configurable default side + gap, flips
 * to the other side when the preferred one lacks room, clamps horizontally to
 * the viewport, and corrects for a transformed/filtered ancestor becoming the
 * containing block for `fixed`.
 *
 * Geometry only — keyboard roving, single-open coordination, and submenu flyouts
 * stay in attachMenu (the submenu keeps its own flip/first-item geometry, but
 * shares the pin/clamp/clear scaffold exported here).
 */

export const VIEWPORT_MARGIN = 8;

export type Align = "start" | "center" | "end";
export type Side = "top" | "bottom";

// Every inline property the anchored positioners may write (positionAnchored plus
// the submenu path through pinFixedAndMeasureOrigin), in one place so the teardown
// stays the exact inverse of the writers (see clearAnchoredPosition). overflow-y is
// NOT here: it is a static class on scrollable panels, not written by the geometry.
const ANCHORED_PROPERTIES = [
  "position",
  "top",
  "bottom",
  "left",
  "right",
  "width",
  "min-width",
  "max-height",
] as const;

/**
 * The fixed-position scaffold shared by positionAnchored and the submenu flyout:
 * pin the panel `position: fixed`, reset the edges it might have carried, then
 * pin it to (0,0) and measure the origin. A transformed/filtered ancestor becomes
 * the containing block for `fixed`, so its coords are relative to that ancestor,
 * not the viewport; the returned origin is subtracted from viewport coords to
 * convert. Callers must measure the anchor AFTER this returns: a just-unhidden,
 * still-in-flow panel that descends from the anchor would otherwise inflate the
 * anchor's box before it is pinned out of flow here.
 */
export function pinFixedAndMeasureOrigin(panel: HTMLElement): DOMRect {
  panel.style.position = "fixed";
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  panel.style.left = "0px";
  panel.style.top = "0px";
  return panel.getBoundingClientRect();
}

// Clamp a viewport-left so the panel stays fully on-screen sideways (a full
// VIEWPORT_MARGIN of daylight on each edge). Reads the panel's laid-out width.
export function clampLeftToViewport(panel: HTMLElement, left: number): number {
  return Math.max(
    VIEWPORT_MARGIN,
    Math.min(left, window.innerWidth - panel.offsetWidth - VIEWPORT_MARGIN),
  );
}

// Remove every inline property the anchored positioners write — the exact inverse,
// so a closed panel leaks no stale fixed coordinates. Removing an unset property is
// a no-op, so callers that never opt into scrollable/matchWidth delegate here too.
export function clearAnchoredPosition(panel: HTMLElement): void {
  for (const property of ANCHORED_PROPERTIES) {
    panel.style.removeProperty(property);
  }
}

export interface AnchorOptions {
  align: Align;
  // Preferred vertical side; flips to the other only when the panel doesn't fit
  // the preferred side but fits better on the other. Default "bottom".
  side?: Side;
  // Daylight between the anchor and the panel's near edge. Default 0 (flush).
  gap?: number;
  // Force the panel's min-width to the anchor's width.
  matchWidth?: boolean;
  // Cap the scroll target to the available height on its resolved side so a panel
  // taller than the viewport scrolls instead of overflowing off-screen.
  scrollable?: boolean;
  // Element the max-height cap is written to (its class owns `overflow-y: auto`).
  // Defaults to `panel`; the tooltip passes an inner wrapper so the cap doesn't
  // clip its arrow, which overhangs the panel edge.
  scrollTarget?: HTMLElement;
}

export interface AnchorResult {
  side: Side; // resolved side after any flip
  // Panel viewport-left, measured width, and anchor horizontal center — enough
  // to place an arrow without re-measuring.
  left: number;
  width: number;
  anchorCenterX: number;
}

/**
 * Position `panel` (in the DOM, possibly just unhidden) against `anchor`; writes
 * its inline position/left/top (+ max-height on the scroll target when scrollable,
 * min-width/width when matchWidth) and returns the resolved geometry.
 */
export function positionAnchored(
  anchor: HTMLElement,
  panel: HTMLElement,
  options: AnchorOptions,
): AnchorResult {
  const side = options.side ?? "bottom";
  const gap = options.gap ?? 0;

  const origin = pinFixedAndMeasureOrigin(panel);
  const rect = anchor.getBoundingClientRect();

  const availableBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN - gap;
  const availableAbove = rect.top - VIEWPORT_MARGIN - gap;
  const spacePreferred = side === "bottom" ? availableBelow : availableAbove;
  const spaceOther = side === "bottom" ? availableAbove : availableBelow;
  // scrollHeight, not offsetHeight, so a tall scrollable panel's full content
  // height drives the flip — measured before the maxHeight cap and matchWidth.
  const flip = panel.scrollHeight > spacePreferred && spaceOther > spacePreferred;
  const resolved: Side = flip ? (side === "bottom" ? "top" : "bottom") : side;
  // Room on the side we resolved to — the flip swaps preferred/other.
  const resolvedSpace = flip ? spaceOther : spacePreferred;

  if (options.scrollable) {
    // Cap the scroll target (its class carries overflow-y:auto). Capping an inner
    // wrapper still bounds the panel, so the offsetHeight read below — and thus the
    // top geometry — reflects the cap.
    (options.scrollTarget ?? panel).style.maxHeight = `${Math.max(0, resolvedSpace)}px`;
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
  left = clampLeftToViewport(panel, left);

  // offsetHeight read AFTER maxHeight so a capped panel flips against its capped
  // height. No vertical clamp — the panel tracks its anchor and scrolls off with
  // it; the horizontal clamp above only keeps it within the viewport sideways.
  const top =
    resolved === "bottom" ? rect.bottom + gap : rect.top - panel.offsetHeight - gap;

  panel.style.left = `${left - origin.x}px`;
  panel.style.top = `${top - origin.y}px`;

  return { side: resolved, left, width, anchorCenterX: rect.left + rect.width / 2 };
}
