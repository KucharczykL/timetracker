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
 * stay in attachMenu (the submenu keeps its own bespoke positioner).
 */

export const VIEWPORT_MARGIN = 8;

export type Align = "start" | "center" | "end";
export type Side = "top" | "bottom";

export interface AnchorOptions {
  align: Align;
  // Preferred vertical side; flips to the other only when the panel doesn't fit
  // the preferred side but fits better on the other. Default "bottom".
  side?: Side;
  // Daylight between the anchor and the panel's near edge. Default 0 (flush).
  gap?: number;
  // Force the panel's min-width to the anchor's width.
  matchWidth?: boolean;
  // Cap the panel to the available height on its resolved side and let it
  // scroll. Off for tooltips (small, never scroll).
  scrollable?: boolean;
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
 * its inline position/left/top (+ max-height/overflow-y when scrollable,
 * min-width/width when matchWidth) and returns the resolved geometry.
 */
export function positionAnchored(
  anchor: HTMLElement,
  panel: HTMLElement,
  options: AnchorOptions,
): AnchorResult {
  const side = options.side ?? "bottom";
  const gap = options.gap ?? 0;

  // Pin fixed BEFORE measuring the anchor: a just-unhidden, still-in-flow panel
  // that is a descendant of the anchor would otherwise inflate the anchor's box.
  panel.style.position = "fixed";
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  if (options.scrollable) panel.style.overflowY = "auto";

  // Pin to (0,0) and measure the origin to convert viewport coords to the
  // containing block's — a transformed/filtered ancestor becomes the containing
  // block for `fixed`, so its coords are relative to that, not the viewport.
  panel.style.left = "0px";
  panel.style.top = "0px";
  const origin = panel.getBoundingClientRect();
  const rect = anchor.getBoundingClientRect();

  const availableBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN - gap;
  const availableAbove = rect.top - VIEWPORT_MARGIN - gap;
  const spacePreferred = side === "bottom" ? availableBelow : availableAbove;
  const spaceOther = side === "bottom" ? availableAbove : availableBelow;
  // scrollHeight, not offsetHeight, so a tall scrollable panel's full content
  // height drives the flip — measured before the maxHeight cap and matchWidth.
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

  // offsetHeight read AFTER maxHeight so a capped panel flips against its capped
  // height. No vertical clamp — the panel tracks its anchor and scrolls off with
  // it; the horizontal clamp above only keeps it within the viewport sideways.
  const top =
    resolved === "bottom" ? rect.bottom + gap : rect.top - panel.offsetHeight - gap;

  panel.style.left = `${left - origin.x}px`;
  panel.style.top = `${top - origin.y}px`;

  return { side: resolved, left, width, anchorCenterX: rect.left + rect.width / 2 };
}
