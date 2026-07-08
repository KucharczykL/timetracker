/**
 * PopOver — custom-element hover/focus tooltip (issue #303).
 *
 * Replaces the old Flowbite popover (data-popover-target/data-popover), which
 * carried its own Popper positioning + dismiss engine outside the app's
 * `<drop-down>`/attachMenu algebra. This is a first-class light-DOM custom
 * element instead: the server renders the trigger + panel (common/components/
 * primitives.py `_popover_html`), this module owns show/hide + viewport-aware
 * `position: fixed` placement.
 *
 * It is deliberately NOT built on attachMenu (a click/keyboard MENU) nor on
 * bindPopupDismiss (outside-click dismiss): a tooltip shows on hover/focus and
 * hides on leave/blur/Escape. The panel is non-interactive (plain text — a
 * truncated name, a converted price, a release year), so there is no need to
 * let the pointer travel into it.
 */

// Matches menu-behavior.ts: keep the panel this far from every viewport edge.
const VIEWPORT_MARGIN = 8;
// The arrow is an `w-2 h-2` (8px) square rotated 45°; half of it overhangs the
// panel edge to form the tip.
const ARROW_SIZE = 8;

// Center the panel under the trigger, fixed-positioned so it escapes any
// clipping/overflow ancestor (issue #39's rationale) and flips above when there
// is not enough room below. Mirrors the bottom-center branch of menu-behavior's
// positioner, minus the menu-only concerns (submenus, width matching).
function positionPanel(host: HTMLElement, panel: HTMLElement): void {
  // Pin `fixed` BEFORE measuring the host. The panel was just unhidden and its
  // class is `inline-block`; while still in normal flow it is a child that
  // inflates the host's box (taller AND wider), which would anchor the tooltip
  // far below the trigger and off-center. Taking it out of flow first makes the
  // host rect the trigger alone. (menu-behavior.ts pins fixed before unhiding
  // for the same reason.)
  panel.style.position = "fixed";
  panel.style.right = "auto";
  panel.style.bottom = "auto";

  const rect = host.getBoundingClientRect();

  // A transformed/filtered ancestor becomes the containing block for
  // `position: fixed`, so fixed coords would be relative to it. Pin to (0,0),
  // measure that origin, then convert viewport coords by subtracting it.
  panel.style.left = "0px";
  panel.style.top = "0px";
  const origin = panel.getBoundingClientRect();

  const width = panel.offsetWidth;
  const height = panel.offsetHeight;

  const centerX = rect.left + rect.width / 2;
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(centerX - width / 2, window.innerWidth - width - VIEWPORT_MARGIN),
  );

  const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN;
  const spaceAbove = rect.top - VIEWPORT_MARGIN;
  const openUp = height > spaceBelow && spaceAbove > spaceBelow;
  // Clamp the flipped-up case to the viewport top so a tall tooltip near the
  // top edge doesn't take a negative `top` and clip off-screen.
  const top = Math.max(VIEWPORT_MARGIN, openUp ? rect.top - height : rect.bottom);

  panel.style.left = `${left - origin.x}px`;
  panel.style.top = `${top - origin.y}px`;

  // The arrow sits on the panel edge facing the trigger, centered on the
  // trigger (clamped inside the panel's rounded corners). `centerX - left` is
  // the trigger's center in the panel's own left-origin coordinates.
  positionArrow(panel, openUp, centerX - left, width);
}

// Tint the arrow from the panel's own computed background/border so it tracks
// the theme, and pin it to the edge that faces the trigger. A 45°-rotated
// square shows two adjacent borders as the tip: top+left point up (panel below
// the trigger), bottom+right point down (panel above).
function positionArrow(
  panel: HTMLElement,
  openUp: boolean,
  triggerCenterInPanel: number,
  panelWidth: number,
): void {
  const arrow = panel.querySelector<HTMLElement>("[data-pop-over-arrow]");
  if (!arrow) return;
  const styles = getComputedStyle(panel);
  const border = `1px solid ${styles.borderTopColor}`;
  arrow.style.backgroundColor = styles.backgroundColor;
  arrow.style.borderTop = openUp ? "" : border;
  arrow.style.borderLeft = openUp ? "" : border;
  arrow.style.borderBottom = openUp ? border : "";
  arrow.style.borderRight = openUp ? border : "";

  const half = ARROW_SIZE / 2;
  arrow.style.left = `${Math.max(
    ARROW_SIZE,
    Math.min(triggerCenterInPanel - half, panelWidth - ARROW_SIZE - half),
  )}px`;
  arrow.style.top = openUp ? "" : `${-half}px`;
  arrow.style.bottom = openUp ? `${-half}px` : "";
}

class PopOverElement extends HTMLElement {
  private panel: HTMLElement | null = null;
  private isOpen = false;

  connectedCallback(): void {
    this.panel = this.querySelector<HTMLElement>("[data-pop-over-panel]");
    if (!this.panel) return;
    // Hover reveals the tooltip; keyboard focus also reveals it when the
    // focusable element is INSIDE the pop-over (e.g. PopoverIf wrapping a
    // button) — focusin/out bubble up to this host. For the common NameWithIcon
    // case the focusable <a> is an ANCESTOR of <pop-over>, so its focusin
    // bubbles up past this element, not into it; those keyboard users rely on
    // hover plus the aria-describedby link to the panel text (parity with the
    // old Flowbite popover, whose non-focusable trigger span behaved the same).
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
    for (const property of ["position", "top", "left", "right", "bottom"]) {
      this.panel.style.removeProperty(property);
    }
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
