import { readPlayEventRowProps } from "../generated/props.js";

// The "Played N times" split button. Open/close + positioning come from the
// inner <drop-down> (menu-behavior.ts); this element owns only the
// "Played +1" action: optimistic count bump + POST + refresh of the Play
// Events section. The menu auto-closes on the click (attachMenu), so there is
// no toggle/outside-click code here anymore.
class PlayEventRowElement extends HTMLElement {
  connectedCallback(): void {
    const props = readPlayEventRowProps(this);
    const count = this.querySelector<HTMLElement>("[data-count]");
    const addPlay = this.querySelector<HTMLElement>("[data-add-play]");
    if (!addPlay) return;

    addPlay.addEventListener("click", () => {
      if (count) count.textContent = String(Number(count.textContent) + 1);
      window
        .fetchWithHtmxTriggers(props.apiCreateUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": props.csrf },
          body: JSON.stringify({ game_id: props.gameId }),
        })
        .then(() => {
          // Refresh the Play Events section (table + count badge) without a
          // full reload; #playevents-container listens for this on body.
          document.body.dispatchEvent(new CustomEvent("play-added"));
        })
        .catch(() => {
          if (count) count.textContent = String(Number(count.textContent) - 1);
          console.error("Failed to record play");
        });
    });
  }
}

customElements.define("play-event-row", PlayEventRowElement);
