/** Width-aware text clipping with passive hover/focus/tap reveal. */
import { readTruncatedTextProps } from "../generated/props.js";
import {
  attachTooltip,
  type TooltipController,
} from "./tooltip-behavior.js";

const mountedInstances = new Set<TruncatedTextElement>();
let observedFonts: FontFaceSet | null = null;
let onFontsLoaded: (() => void) | null = null;

function remeasureMounted(): void {
  for (const instance of mountedInstances) instance.measure();
}

function ensureFontMeasurement(): void {
  if (!("fonts" in document) || document.fonts === observedFonts) return;
  if (observedFonts && onFontsLoaded) {
    observedFonts.removeEventListener("loadingdone", onFontsLoaded);
  }
  observedFonts = document.fonts;
  onFontsLoaded = remeasureMounted;
  observedFonts.addEventListener("loadingdone", onFontsLoaded);
  void observedFonts.ready.then(remeasureMounted);
}

class TruncatedTextElement extends HTMLElement {
  private clip: HTMLElement | null = null;
  private controller: TooltipController | null = null;
  private observer: ResizeObserver | null = null;
  private overflowing = false;
  private linked = false;
  private tap = false;
  private reveal: "auto" | "always" = "auto";

  connectedCallback(): void {
    this.clip = this.querySelector<HTMLElement>("[data-truncated-clip]");
    const panel = this.querySelector<HTMLElement>("[data-pop-over-panel]");
    const clip = this.clip;
    if (!clip || !panel) return;

    const props = readTruncatedTextProps(this);
    this.tap = props.tap;
    this.reveal = props.reveal === "always" ? "always" : "auto";
    this.linked = clip.closest("a") !== null;
    const revealButton = this.querySelector<HTMLElement>("[data-truncated-reveal]");
    const trigger = revealButton ?? clip.closest<HTMLElement>("a") ?? clip;

    this.controller = attachTooltip({
      host: this,
      trigger,
      anchor: () =>
        revealButton && revealButton.getClientRects().length > 0
          ? revealButton
          : clip,
      panel,
      content:
        panel.querySelector<HTMLElement>("[data-pop-over-content]") ?? undefined,
      arrow:
        panel.querySelector<HTMLElement>("[data-pop-over-arrow]") ?? undefined,
      tap: this.tap && revealButton !== null,
      isActive: () => this.reveal === "always" || this.overflowing,
    });

    mountedInstances.add(this);
    ensureFontMeasurement();
    this.measure();
    if (typeof ResizeObserver !== "undefined") {
      this.observer = new ResizeObserver(() => this.measure());
      this.observer.observe(clip);
    }
  }

  disconnectedCallback(): void {
    mountedInstances.delete(this);
    this.observer?.disconnect();
    this.observer = null;
    this.controller?.destroy();
    this.controller = null;
  }

  measure(): void {
    if (!this.clip) return;
    const wasOverflowing = this.overflowing;
    this.overflowing = this.clip.scrollWidth - this.clip.clientWidth > 1;
    this.toggleAttribute("data-overflowing", this.overflowing);

    const keyboardReveal =
      !this.linked && this.tap && (this.overflowing || this.reveal === "always");
    if (keyboardReveal) this.clip.setAttribute("tabindex", "0");
    else this.clip.removeAttribute("tabindex");

    if (wasOverflowing && !this.overflowing) this.controller?.close();
  }
}

customElements.define("truncated-text", TruncatedTextElement);
