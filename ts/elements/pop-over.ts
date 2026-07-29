/** PopOver — server-rendered tooltip wrapper over the shared passive engine. */
import { readPopOverProps } from "../generated/props.js";
import {
  attachTooltip,
  type TooltipController,
} from "./tooltip-behavior.js";

class PopOverElement extends HTMLElement {
  private controller: TooltipController | null = null;

  connectedCallback(): void {
    const panel = this.querySelector<HTMLElement>("[data-pop-over-panel]");
    const trigger = this.querySelector<HTMLElement>("[data-pop-over-trigger]");
    if (!panel || !trigger) return;

    this.controller = attachTooltip({
      host: this,
      trigger,
      // The trigger, not the host: the host spans the value and the reveal
      // glyph together, so centring on it aims the arrow at the gap between
      // them — or at empty space when the value wraps.
      anchor: trigger,
      panel,
      content:
        panel.querySelector<HTMLElement>("[data-pop-over-content]") ?? undefined,
      arrow:
        panel.querySelector<HTMLElement>("[data-pop-over-arrow]") ?? undefined,
      tap: readPopOverProps(this).tap,
    });
  }

  disconnectedCallback(): void {
    this.controller?.destroy();
    this.controller = null;
  }
}

customElements.define("pop-over", PopOverElement);
