import { readSessionDeviceSelectorProps } from "../generated/props.js";
import { initDropdown } from "./dropdown.js";

class SessionDeviceSelectorElement extends HTMLElement {
  connectedCallback(): void {
    const props = readSessionDeviceSelectorProps(this);
    initDropdown(this, {
      patchUrl: `/api/session/${props.sessionId}/device`,
      bodyKey: "device_id",
      event: "device-changed",
      csrf: props.csrf,
      numericValue: true,
    });
  }
}

customElements.define("session-device-selector", SessionDeviceSelectorElement);
