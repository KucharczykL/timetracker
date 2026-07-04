import { readPlayEventRowProps } from "../generated/props.js";

// The "Played N times" split button. Open/close + positioning come from the
// inner <drop-down> (menu-behavior.ts); this element owns only the
// "Played +1" action: optimistic count bump + POST + refresh of the Play
// Events section. The menu auto-closes on the click (attachMenu), so there is
// no toggle/outside-click code here anymore.
class PlayEventRowElement extends HTMLElement {
  // The play count lives here, seeded from the server-rendered prop; the
  // [data-count] span is a write-only display slot, never parsed back.
  private count = 0;

  connectedCallback(): void {
    const props = readPlayEventRowProps(this);
    this.count = props.count;
    const countDisplay = this.querySelector<HTMLElement>("[data-count]");
    const addPlay = this.querySelector<HTMLElement>("[data-add-play]");
    if (!addPlay) return;

    const showCount = (): void => {
      if (countDisplay) countDisplay.textContent = String(this.count);
    };

    addPlay.addEventListener("click", () => {
      this.count += 1;
      showCount();
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
          this.count -= 1;
          showCount();
          console.error("Failed to record play");
        });
    });
  }
}

customElements.define("play-event-row", PlayEventRowElement);
