import { readPlaythroughSelectProps } from "../generated/props.js";
import type { SearchSelectChangeDetail } from "./search-select.js";

// Fills the run <select> with the runs of the game the form names, and hides
// itself while that game holds one run: a person picks a game, then a run,
// and a game with a single run needs no second pick. The server renders the
// options for the game it already knows, so the control works without JS
// wherever the game was known at render time.

interface RunRow {
  id: string;
  display_name: string;
}

class PlaythroughSelectElement extends HTMLElement {
  private select: HTMLSelectElement | null = null;
  private onGameChange = (event: Event): void => {
    const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
    if (!detail || detail.name !== readPlaythroughSelectProps(this).gameField) return;
    void this.refill(detail.values[0] ?? "");
  };

  connectedCallback(): void {
    this.select = this.querySelector("select");
    this.applyVisibility();
    this.closest("form")?.addEventListener("search-select:change", this.onGameChange);
  }

  disconnectedCallback(): void {
    this.closest("form")?.removeEventListener("search-select:change", this.onGameChange);
  }

  private async refill(gameId: string): Promise<void> {
    const select = this.select;
    if (!select) return;
    if (!gameId) {
      select.replaceChildren();
      this.applyVisibility();
      return;
    }
    const props = readPlaythroughSelectProps(this);
    const url = `${props.apiUrl}?game=${encodeURIComponent(gameId)}&limit=0`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const runs = (await response.json()) as RunRow[];
    let anySelected = false;
    const options = runs.map((run) => {
      const option = document.createElement("option");
      option.value = run.id;
      option.textContent = run.display_name;
      option.selected = run.id === props.selected;
      anySelected ||= option.selected;
      return option;
    });
    select.replaceChildren(...options);
    if (!anySelected && options[0]) {
      options[0].selected = true;
    }
    this.applyVisibility();
  }

  // One run needs no pick: the sole option stays selected and the row hides.
  private applyVisibility(): void {
    const count = this.select?.options.length ?? 0;
    const row = this.closest<HTMLElement>("[data-field-row]") ?? this;
    row.hidden = count <= 1;
  }
}

customElements.define("playthrough-select", PlaythroughSelectElement);
