import { readPlayEventRowProps } from "../generated/props.js";

class PlayEventRowElement extends HTMLElement {
  connectedCallback(): void {
    const props = readPlayEventRowProps(this);
    const toggle = this.querySelector<HTMLElement>("[data-toggle]");
    const menu = this.querySelector<HTMLElement>("[data-menu]");
    const count = this.querySelector<HTMLElement>("[data-count]");
    const addPlay = this.querySelector<HTMLElement>("[data-add-play]");
    if (!toggle || !menu) return;

    const close = () => {
      menu.hidden = true;
    };
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener("click", (event) => {
      if (!this.contains(event.target as Node)) close();
    });

    addPlay?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (count) count.textContent = String(Number(count.textContent) + 1);
      close();
      window
        .fetchWithHtmxTriggers(props.apiCreateUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": props.csrf },
          body: JSON.stringify({ game_id: props.gameId }),
        })
        .catch(() => {
          if (count) count.textContent = String(Number(count.textContent) - 1);
          console.error("Failed to record play");
        });
    });
  }
}

customElements.define("play-event-row", PlayEventRowElement);
