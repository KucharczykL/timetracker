/**
 * SearchField — the quick bar's free-text field.
 *
 * A match-mode trigger joined to a text box. The mode lives in one place, the
 * root's `data-modifier`: this element writes it, and the bar's generic string
 * reader reads it. There is no hidden <select> carrying the mode, deliberately —
 * `setupModifierToggles` reacts to a change on `select[data-string-modifier-select]`
 * and `toggleStringFilterInput` then walks `closest(".flex-col")` to find a value
 * input to disable. The segmented field is not that layout, so a select added
 * here to "reuse" the reader would disable an unrelated input in the row.
 *
 * Choosing a mode changes what the field means, not what it shows: no apply
 * happens until Enter or Apply, because each apply is a page the browser loads
 * and a filter that applied while a person typed would take the focus and the
 * scroll position with every pause.
 */
import { onSwap } from "../utils.js";

const MODE_ITEM = "[data-match-mode]";

class SearchFieldElement extends HTMLElement {
  private menu: HTMLElement | null = null;

  connectedCallback(): void {
    this.addEventListener("click", this.onPick);
  }

  disconnectedCallback(): void {
    this.removeEventListener("click", this.onPick);
  }

  private onPick = (event: Event): void => {
    const item = (event.target as HTMLElement | null)?.closest<HTMLElement>(MODE_ITEM);
    if (!item || !this.contains(item)) return;
    const mode = item.getAttribute("data-match-mode");
    if (!mode) return;
    this.applyMode(mode, item);
    // The mode is picked; the dropdown's own behavior closes on the click.
  };

  private applyMode(mode: string, chosen: HTMLElement): void {
    this.setAttribute("data-modifier", mode);
    for (const item of this.querySelectorAll<HTMLElement>(MODE_ITEM)) {
      item.setAttribute("aria-checked", item === chosen ? "true" : "false");
    }
    const trigger = this.querySelector<HTMLElement>("[data-match-trigger]");
    const mark = this.querySelector<SVGElement>("[data-match-mark]");
    const chosenMark = chosen.querySelector<SVGElement>("svg");
    if (trigger && mark && chosenMark) {
      // The menu row already holds the mode's mark, server-rendered — clone it
      // rather than keep a second copy of the six in the client. The clone takes
      // the class the trigger's own mark carries, never the row's: the sizing
      // lives in that class, so a clone stripped of it renders at the SVG's
      // intrinsic size instead of the trigger's.
      const replacement = chosenMark.cloneNode(true) as SVGElement;
      replacement.setAttribute("class", mark.getAttribute("class") ?? "");
      replacement.setAttribute("data-match-mark", "");
      mark.replaceWith(replacement);
    }
    const words = chosen.querySelector("span")?.textContent?.trim() ?? mode;
    if (trigger) {
      // The trigger's name states the value it holds, so the mode is spoken
      // rather than left to the mark.
      trigger.setAttribute("aria-label", `Match mode: ${words}`);
      trigger.setAttribute("title", `Match mode: ${words}`);
    }
  }
}

customElements.define("search-field", SearchFieldElement);

// Enter in the box applies, the way Enter in a facet input does. The bar owns
// the submit; this only keeps the keystroke from being swallowed where the
// field sits outside a <form> (the synthetic harness pages).
onSwap("search-field [data-match-value]", (input) => {
  input.addEventListener("keydown", (event) => {
    if ((event as KeyboardEvent).key !== "Enter") return;
    const form = input.closest("form");
    if (!form) return;
    event.preventDefault();
    form.requestSubmit();
  });
});
