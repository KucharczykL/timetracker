import { readGameStatusSelectorProps } from "../generated/props.js";
import { initDropdown } from "./dropdown-select-helper.js";
import { MenuController } from "./menu-behavior.js";

class GameStatusSelectorElement extends HTMLElement {
  private controller?: MenuController;

  connectedCallback(): void {
    const props = readGameStatusSelectorProps(this);
    this.controller = initDropdown(this, {
      patchUrl: `/api/games/${props.gameId}/status`,
      bodyKey: "status",
      event: "status-changed",
      csrf: props.csrf,
    });
  }

  disconnectedCallback(): void {
    this.controller?.destroy();
    this.controller = undefined;
  }
}

customElements.define("game-status-selector", GameStatusSelectorElement);
