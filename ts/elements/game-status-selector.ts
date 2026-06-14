import { readGameStatusSelectorProps } from "../generated/props.js";
import { initDropdown } from "./dropdown.js";

class GameStatusSelectorElement extends HTMLElement {
  connectedCallback(): void {
    const props = readGameStatusSelectorProps(this);
    initDropdown(this, {
      patchUrl: `/api/games/${props.gameId}/status`,
      bodyKey: "status",
      event: "status-changed",
      csrf: props.csrf,
    });
  }
}

customElements.define("game-status-selector", GameStatusSelectorElement);
