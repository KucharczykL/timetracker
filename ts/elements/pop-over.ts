/**
 * PopOver — hover/focus tooltip custom element. The server renders the trigger +
 * panel (common/components/primitives.py `_popover_html`); this owns show/hide
 * and viewport-aware `position: fixed` placement via positionAnchored.
 *
 * Shows on hover/focus, hides on leave/blur/Escape — deliberately not attachMenu
 * (a click/keyboard menu) or bindPopupDismiss (outside-click). The panel is
 * non-interactive text, so the pointer never needs to travel into it.
 */
import {
  clearAnchoredPosition,
  positionAnchored,
  type Side,
} from "./anchored-position.js";

// The arrow is an `w-2 h-2` (8px) square rotated 45°; half of it overhangs the
// panel edge to form the tip.
const ARROW_SIZE = 8;
// Daylight between the trigger and the panel, measured to the panel's edge. The
// arrow overhangs ARROW_SIZE / 2 into it, so the visible gap between the trigger
// and the arrow tip is TRIGGER_GAP - ARROW_SIZE / 2.
const TRIGGER_GAP = 8;

// Place the panel via the shared positioner (menu-behavior.ts uses the same for
// its dropdowns): centered on the trigger, defaulting ABOVE it with a small gap,
// flipping below only when there isn't room above. Then pin the arrow to the
// edge facing the trigger.
function positionPanel(host: HTMLElement, panel: HTMLElement): void {
  const { side, left, width, anchorCenterX } = positionAnchored(host, panel, {
    align: "center",
    side: "top",
    gap: TRIGGER_GAP,
  });
  // `anchorCenterX - left` is the trigger's center in the panel's own
  // left-origin coordinates.
  positionArrow(panel, side, anchorCenterX - left, width);
}

// Tint the arrow from the panel's own computed background/border so it tracks
// the theme. Done ONCE per open (the colors are position-invariant), not on
// every reposition — getComputedStyle forces a style flush, wasteful on the
// scroll/resize hot path. Stashes the border color for positionArrow to reuse.
function tintArrow(panel: HTMLElement): void {
  const arrow = panel.querySelector<HTMLElement>("[data-pop-over-arrow]");
  if (!arrow) return;
  const styles = getComputedStyle(panel);
  arrow.style.backgroundColor = styles.backgroundColor;
  arrow.dataset.borderColor = styles.borderTopColor;
}

// Pin the arrow to the edge facing the trigger (runs on every reposition, so it
// avoids getComputedStyle — colors come from tintArrow's stash). A 45°-rotated
// square shows two adjacent borders as the tip: bottom+right point down (panel
// above the trigger), top+left point up (panel below).
function positionArrow(
  panel: HTMLElement,
  side: Side,
  triggerCenterInPanel: number,
  panelWidth: number,
): void {
  const arrow = panel.querySelector<HTMLElement>("[data-pop-over-arrow]");
  if (!arrow) return;
  const panelAbove = side === "top";
  const border = `1px solid ${arrow.dataset.borderColor ?? ""}`;
  arrow.style.borderTop = panelAbove ? "" : border;
  arrow.style.borderLeft = panelAbove ? "" : border;
  arrow.style.borderBottom = panelAbove ? border : "";
  arrow.style.borderRight = panelAbove ? border : "";

  // Center the arrow on the trigger, clamped to keep a full ARROW_SIZE inset
  // from each rounded corner — symmetric, the same inset on the left and right.
  const half = ARROW_SIZE / 2;
  arrow.style.left = `${Math.max(
    ARROW_SIZE,
    Math.min(triggerCenterInPanel - half, panelWidth - 2 * ARROW_SIZE),
  )}px`;
  arrow.style.top = panelAbove ? "" : `${-half}px`;
  arrow.style.bottom = panelAbove ? `${-half}px` : "";
}

class PopOverElement extends HTMLElement {
  private panel: HTMLElement | null = null;
  private isOpen = false;

  connectedCallback(): void {
    this.panel = this.querySelector<HTMLElement>("[data-pop-over-panel]");
    if (!this.panel) return;
    // Hover reveals the tooltip; keyboard focus reveals it only when the
    // focusable element is INSIDE the pop-over (e.g. PopoverIf wrapping a
    // button) — focusin/out bubble up to this host. For a wrapping <a> ANCESTOR
    // (the NameWithIcon case) focusin fires on the <a> and bubbles up past this
    // element, not into it, so those keyboard users get only hover + the
    // aria-describedby link to the panel text.
    this.addEventListener("mouseenter", this.show);
    this.addEventListener("mouseleave", this.hide);
    this.addEventListener("focusin", this.show);
    this.addEventListener("focusout", this.onFocusOut);
  }

  disconnectedCallback(): void {
    // Drop the panel's inline positioning + document listeners; a lingering
    // open panel would sit at stale fixed coordinates after an htmx swap.
    this.close();
    this.removeEventListener("mouseenter", this.show);
    this.removeEventListener("mouseleave", this.hide);
    this.removeEventListener("focusin", this.show);
    this.removeEventListener("focusout", this.onFocusOut);
  }

  private onFocusOut = (event: FocusEvent): void => {
    // Only hide when focus actually left the element (not on a move between
    // the trigger and a focusable descendant).
    if (!this.contains(event.relatedTarget as Node)) this.hide();
  };

  private show = (): void => {
    if (this.isOpen || !this.panel) return;
    this.isOpen = true;
    this.panel.hidden = false;
    tintArrow(this.panel); // once per open; positionPanel only places it
    positionPanel(this, this.panel);
    document.addEventListener("keydown", this.onKeyDown);
    window.addEventListener("scroll", this.reposition, true);
    window.addEventListener("resize", this.reposition);
  };

  private hide = (): void => {
    this.close();
  };

  private close(): void {
    if (!this.isOpen || !this.panel) return;
    this.isOpen = false;
    this.panel.hidden = true;
    clearAnchoredPosition(this.panel);
    document.removeEventListener("keydown", this.onKeyDown);
    window.removeEventListener("scroll", this.reposition, true);
    window.removeEventListener("resize", this.reposition);
  }

  private reposition = (): void => {
    if (this.isOpen && this.panel) positionPanel(this, this.panel);
  };

  private onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === "Escape") this.hide();
  };
}

customElements.define("pop-over", PopOverElement);
