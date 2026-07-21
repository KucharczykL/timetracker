/** Responsive settings section navigation (issue #384).
 *
 * The server renders one complete inline list as the no-JavaScript fallback.
 * After <drop-down> upgrades, narrow containers move that exact <ul> into a
 * modal bottom sheet; the @4xl sentinel restores it to the sticky desktop rail.
 * No links are cloned and no ARIA-menu semantics are introduced.
 */
import { readSettingsSectionNavProps } from "../generated/props.js";

interface SheetDropdown extends HTMLElement {
  close?: () => void;
}

class SettingsSectionNavElement extends HTMLElement {
  private rail: HTMLElement | null = null;
  private list: HTMLElement | null = null;
  private sheetHost: HTMLElement | null = null;
  private sheetDestination: HTMLElement | null = null;
  private sheetDropdown: SheetDropdown | null = null;
  private wideSentinel: HTMLElement | null = null;
  private observer: ResizeObserver | null = null;
  private layoutQueued = false;
  private enhanced = false;
  private desiredWide = false;
  private waitingForClose = false;

  connectedCallback(): void {
    readSettingsSectionNavProps(this);
    this.rail = this.querySelector<HTMLElement>("[data-section-nav-rail]");
    this.list = this.querySelector<HTMLElement>("[data-section-nav-list]");
    this.sheetHost = this.querySelector<HTMLElement>("[data-section-nav-sheet]");
    this.sheetDestination = this.querySelector<HTMLElement>(
      "[data-section-nav-sheet-destination]",
    );
    this.sheetDropdown = this.sheetHost?.querySelector<SheetDropdown>("drop-down") ?? null;
    this.wideSentinel = this.querySelector<HTMLElement>("[data-section-nav-wide]");
    if (
      !this.rail ||
      !this.list ||
      !this.sheetHost ||
      !this.sheetDestination ||
      !this.sheetDropdown ||
      !this.wideSentinel
    ) {
      return;
    }

    void customElements.whenDefined("drop-down").then(() => {
      if (!this.isConnected || this.enhanced) return;
      this.enhanced = true;
      this.setAttribute("data-section-nav-enhanced", "");
      if (typeof ResizeObserver !== "undefined") {
        this.observer = new ResizeObserver(() => this.queueLayout());
        this.observer.observe(this);
      }
      this.syncLayout();
    });
  }

  disconnectedCallback(): void {
    this.observer?.disconnect();
    this.observer = null;
    this.layoutQueued = false;
    this.waitingForClose = false;
    this.sheetDropdown?.close?.();
    this.restoreRail();
    this.sheetHost?.setAttribute("hidden", "");
    this.rail?.removeAttribute("hidden");
    this.enhanced = false;
    this.removeAttribute("data-section-nav-enhanced");
  }

  private isWide(): boolean {
    return (this.wideSentinel?.getClientRects().length ?? 0) > 0;
  }

  private queueLayout(): void {
    if (this.layoutQueued) return;
    this.layoutQueued = true;
    requestAnimationFrame(() => {
      this.layoutQueued = false;
      this.syncLayout();
    });
  }

  private restoreRail(): void {
    if (this.rail && this.list && this.list.parentElement !== this.rail) {
      this.rail.appendChild(this.list);
    }
  }

  private showWide(): void {
    this.restoreRail();
    this.sheetHost?.setAttribute("hidden", "");
    this.rail?.removeAttribute("hidden");
  }

  private showMobile(): void {
    if (this.list && this.sheetDestination) {
      this.sheetDestination.appendChild(this.list);
    }
    this.rail?.setAttribute("hidden", "");
    this.sheetHost?.removeAttribute("hidden");
  }

  private applyDesiredMode(): void {
    if (this.desiredWide) this.showWide();
    else this.showMobile();
  }

  /** Public for the sentinel-driven Vitest contract. */
  syncLayout(): void {
    if (!this.enhanced) return;
    this.desiredWide = this.isWide();
    if (!this.desiredWide) {
      this.showMobile();
      return;
    }
    const dialog = this.sheetHost?.querySelector<HTMLDialogElement>(
      "dialog[data-bottom-sheet]",
    );
    if (dialog?.open) {
      if (this.waitingForClose) return;
      this.waitingForClose = true;
      this.sheetDropdown?.addEventListener(
        "dropdown:hide",
        () => {
          this.waitingForClose = false;
          this.applyDesiredMode();
        },
        { once: true },
      );
      this.sheetDropdown?.close?.();
      return;
    }
    this.showWide();
  }
}

customElements.define("settings-section-nav", SettingsSectionNavElement);
