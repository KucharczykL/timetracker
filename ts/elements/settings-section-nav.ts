/** Responsive settings section navigation (issue #384).
 *
 * Mobile uses a priority-plus chip row; desktop restores those exact anchor
 * nodes into a vertical sticky rail. A CSS sentinel exposes the container-query
 * mode so JavaScript never duplicates the @4xl threshold with matchMedia.
 */
import { readSettingsSectionNavProps } from "../generated/props.js";
import {
  priorityPlusFitCount,
  priorityPlusTotalWidth,
} from "./priority-plus.js";

interface NavItem {
  element: HTMLElement;
  width: number;
}

class SettingsSectionNavElement extends HTMLElement {
  private row: HTMLElement | null = null;
  private primary: HTMLElement | null = null;
  private overflowHost: HTMLElement | null = null;
  private overflowItems: HTMLElement | null = null;
  private wideSentinel: HTMLElement | null = null;
  private items: NavItem[] = [];
  private rowGap = 0;
  private itemGap = 0;
  private overflowWidth = 0;
  private observer: ResizeObserver | null = null;
  private layoutQueued = false;

  connectedCallback(): void {
    // Read the generated (currently empty) prop contract so adding a future
    // server prop stays on the normal register_element/codegen path.
    readSettingsSectionNavProps(this);
    this.row = this.querySelector<HTMLElement>("[data-section-nav-row]");
    this.primary = this.querySelector<HTMLElement>("[data-section-nav-primary]");
    this.overflowHost = this.querySelector<HTMLElement>(
      "[data-section-nav-overflow]",
    );
    this.overflowItems = this.querySelector<HTMLElement>("[data-menu] > ul");
    this.wideSentinel = this.querySelector<HTMLElement>("[data-section-nav-wide]");
    if (
      !this.row ||
      !this.primary ||
      !this.overflowHost ||
      !this.overflowItems ||
      !this.wideSentinel
    ) {
      return;
    }

    const elements = Array.from(
      this.querySelectorAll<HTMLElement>("[data-section-nav-item]"),
    );
    this.items = elements.map((element) => ({ element, width: 0 }));
    this.restoreAll();
    this.measure();

    if (typeof ResizeObserver !== "undefined") {
      this.observer = new ResizeObserver(() => this.queueLayout());
      this.observer.observe(this.row);
    }
    void document.fonts?.ready.then(() => {
      if (!this.isConnected) return;
      this.restoreAll();
      this.measure();
      this.layoutOverflow();
    });
    this.layoutOverflow();
  }

  disconnectedCallback(): void {
    this.observer?.disconnect();
    this.observer = null;
  }

  private measure(): void {
    if (!this.row || !this.primary || !this.overflowHost) return;
    this.rowGap = parseFloat(getComputedStyle(this.row).columnGap) || 0;
    this.itemGap = parseFloat(getComputedStyle(this.primary).columnGap) || 0;
    this.items.forEach((item) => (item.width = item.element.offsetWidth));
    if (this.isWide()) {
      this.overflowWidth = 0;
      return;
    }
    this.overflowHost.classList.remove("hidden");
    this.overflowWidth = this.overflowHost.offsetWidth;
    this.overflowHost.classList.add("hidden");
  }

  private isWide(): boolean {
    return (this.wideSentinel?.getClientRects().length ?? 0) > 0;
  }

  private queueLayout(): void {
    if (this.layoutQueued) return;
    this.layoutQueued = true;
    requestAnimationFrame(() => {
      this.layoutQueued = false;
      this.layoutOverflow();
    });
  }

  private setMenuSemantics(item: HTMLElement, inMenu: boolean): void {
    const link = item.querySelector<HTMLElement>("a[href^='#']");
    if (inMenu) {
      item.setAttribute("role", "presentation");
      link?.setAttribute("role", "menuitem");
      link?.setAttribute("tabindex", "-1");
    } else {
      item.removeAttribute("role");
      link?.removeAttribute("role");
      link?.removeAttribute("tabindex");
    }
  }

  private restoreAll(): void {
    if (!this.primary || !this.overflowHost) return;
    for (const item of this.items) {
      this.setMenuSemantics(item.element, false);
      this.primary.appendChild(item.element);
    }
    this.overflowHost.classList.add("hidden");
    const dropdown = this.overflowHost.querySelector<HTMLElement>("drop-down") as
      | (HTMLElement & { close?: () => void })
      | null;
    dropdown?.close?.();
  }

  /** Public for the stubbed-width Vitest contract. */
  layoutOverflow(): void {
    if (!this.row || !this.primary || !this.overflowHost || !this.overflowItems) {
      return;
    }
    if (this.isWide()) {
      this.restoreAll();
      return;
    }

    const widths = this.items.map((item) => item.width);
    const total = priorityPlusTotalWidth(widths, this.itemGap);
    const rowWidth = this.row.clientWidth;
    const fitCount =
      total <= rowWidth
        ? this.items.length
        : priorityPlusFitCount(
            widths,
            rowWidth - this.overflowWidth - this.rowGap,
            this.itemGap,
          );

    this.items.forEach((item, index) => {
      const inMenu = index >= fitCount;
      this.setMenuSemantics(item.element, inMenu);
      (inMenu ? this.overflowItems : this.primary)?.appendChild(item.element);
    });
    this.overflowHost.classList.toggle("hidden", fitCount === this.items.length);
  }
}

customElements.define("settings-section-nav", SettingsSectionNavElement);
