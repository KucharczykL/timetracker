import { readSessionDeviceSelectorProps } from "../generated/props.js";
import { initDropdown } from "./dropdown.js";
import { MenuController } from "./menu-behavior.js";

class SessionDeviceSelectorElement extends HTMLElement {
  private controller?: MenuController;

  connectedCallback(): void {
    const props = readSessionDeviceSelectorProps(this);
    this.controller = initDropdown(this, {
      patchUrl: `/api/session/${props.sessionId}/device`,
      bodyKey: "device_id",
      event: "device-changed",
      csrf: props.csrf,
      numericValue: true,
    });
  }

  disconnectedCallback(): void {
    this.controller?.destroy();
    this.controller = undefined;
  }
}

customElements.define("session-device-selector", SessionDeviceSelectorElement);
