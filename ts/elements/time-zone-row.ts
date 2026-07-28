import { readTimeZoneRowProps } from "../generated/props.js";
import type { SearchSelectChangeDetail } from "./search-select.js";

// The per-timestamp "Time zone" row: one hidden input (the only submitted
// channel) and one always-visible picker trigger. Nothing here hides or
// reveals anything — the hosting <drop-down> owns the panel's open state. On a
// browser-vs-effective zone mismatch the trigger gains an emphasis class; the
// panel is never opened programmatically, which would steal focus on load.
const EMPHASIS_CLASS = "font-semibold";

function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

class TimeZoneRowElement extends HTMLElement {
  private labelPrefix = "";

  connectedCallback(): void {
    const props = readTimeZoneRowProps(this);
    const valueInput = this.querySelector<HTMLInputElement>("[data-time-zone-value]");
    const trigger = this.querySelector<HTMLElement>('button[aria-haspopup="dialog"]');
    if (!valueInput || !trigger) return;

    const triggerText = trigger.childNodes[0]?.textContent ?? "";
    this.labelPrefix = triggerText.split(":")[0] ?? "";
    // What a NULL value reads as, reused by the clear branch below.
    const fallbackLabel = `${props.displayZone} (display zone)`;

    const detectedZone = browserTimeZone();
    if (props.captureDefault && valueInput.value === "") {
      // The capture default: the browser was in this zone when the timestamp
      // was committed. Stamped only on unsaved records — an existing NULL
      // stays NULL (that IS today's behaviour) unless the user picks a zone.
      valueInput.value = detectedZone;
      this.updateTriggerLabel(trigger, detectedZone);
    }
    const effectiveZone = valueInput.value || props.displayZone;
    if (effectiveZone !== detectedZone) {
      // The zone this row will submit is not the zone this browser is in —
      // worth a look. Emphasis only: the trigger already names the value.
      trigger.classList.add(EMPHASIS_CLASS);
    }

    this.addEventListener("search-select:change", (event) => {
      const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
      if (!detail || detail.last === null) return;
      // The API's pinned "" option is an explicit clear back to NULL.
      valueInput.value = detail.last.value;
      this.updateTriggerLabel(trigger, detail.last.value || fallbackLabel);
    });
  }

  private updateTriggerLabel(trigger: HTMLElement, zoneName: string): void {
    const textNode = trigger.childNodes[0];
    if (textNode) textNode.textContent = `${this.labelPrefix}: ${zoneName}`;
  }
}

customElements.define("time-zone-row", TimeZoneRowElement);
