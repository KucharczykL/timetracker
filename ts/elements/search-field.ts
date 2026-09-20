/**
 * SearchField — the quick bar's free-text field.
 *
 * The mode lives once, in the root's `data-modifier`: this element writes it
 * and the bar's string reader reads it. No hidden <select> carries it,
 * deliberately — `setupModifierToggles` reacts to a change on
 * `select[data-string-modifier-select]`, and `toggleStringFilterInput` then
 * walks `closest(".flex-col")` for an input to disable. The segmented field is
 * not that layout, so a select added here would disable an unrelated input.
 *
 * Choosing a mode applies nothing. Each apply loads a page, so one that fired
 * while a person typed would take the focus and scroll with every pause.
 */
import { onSwap } from "../utils.js";

const MODE_ITEM = "[data-match-mode]";

class SearchFieldElement extends HTMLElement {
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
      // Clone the row's server-rendered mark, not a second copy of the six.
      //
      // The clone takes the trigger mark's class, never the row's: the sizing
      // lives there, so a clone stripped of it renders at intrinsic size.
      const replacement = chosenMark.cloneNode(true) as SVGElement;
      replacement.setAttribute("class", mark.getAttribute("class") ?? "");
      replacement.setAttribute("data-match-mark", "");
      mark.replaceWith(replacement);
    }
    const words = chosen.querySelector("span")?.textContent?.trim() ?? mode;
    if (trigger) {
      // The name states the value, not just the control.
      trigger.setAttribute("aria-label", `Match mode: ${words}`);
      trigger.setAttribute("title", `Match mode: ${words}`);
    }
    // A picked mode closes the menu, which the generic behavior does not.
    //
    // attachMenu treats every menuitemcheckbox and menuitemradio as a toggle and
    // closes only for other roles. A radio is one choice of six, so the panel
    // would otherwise stay open over the box a person types in next.
    chosen
      .closest<HTMLElement & { close(): void }>("drop-down")
      ?.close();
  }
}

customElements.define("search-field", SearchFieldElement);

// Enter applies, as in a facet input. The bar owns the submit.
onSwap("search-field [data-match-value]", (input) => {
  input.addEventListener("keydown", (event) => {
    if ((event as KeyboardEvent).key !== "Enter") return;
    const form = input.closest("form");
    if (!form) return;
    event.preventDefault();
    form.requestSubmit();
  });
});
