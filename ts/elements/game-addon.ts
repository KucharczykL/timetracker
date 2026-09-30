import { ADDON_KINDS } from "../generated/game-kinds.js";
import { readGameAddonProps } from "../generated/props.js";

/** Shows the parent row for add-ons only. */
class GameAddonElement extends HTMLElement {
  private kindSelect: HTMLSelectElement | null = null;
  private parentRow: HTMLElement | null = null;

  connectedCallback(): void {
    const { kindField, parentField } = readGameAddonProps(this);
    const form = this.closest("form");
    this.kindSelect =
      form?.querySelector<HTMLSelectElement>(`select[name="${kindField}"]`) ??
      null;
    this.parentRow =
      form?.querySelector<HTMLElement>(`[data-field-row="${parentField}"]`) ??
      null;
    //: Missing either, both rows stay visible.
    if (!this.kindSelect || !this.parentRow) {
      console.error(
        `game-addon: no select[name="${kindField}"] or ` +
          `[data-field-row="${parentField}"] in its form`
      );
      return;
    }
    this.kindSelect.addEventListener("change", this.onKindChange);
    //: A refused posted parent stays visible.
    if (!this.parentHeld()) this.show(this.isAddon());
  }

  disconnectedCallback(): void {
    this.kindSelect?.removeEventListener("change", this.onKindChange);
  }

  private readonly onKindChange = (): void => {
    const addon = this.isAddon();
    this.show(addon);
    if (!addon && this.parentHeld()) this.clearParent();
  };

  private isAddon(): boolean {
    return ADDON_KINDS.includes(this.kindSelect?.value ?? "");
  }

  private parentInputs(): HTMLInputElement[] {
    return Array.from(
      this.parentRow?.querySelectorAll<HTMLInputElement>(
        'input[type="hidden"]'
      ) ?? []
    );
  }

  private parentHeld(): boolean {
    return this.parentInputs().some(input => input.value !== "");
  }

  private clearParent(): void {
    const clear = this.parentRow?.querySelector<HTMLButtonElement>(
      "[data-search-select-clear]"
    );
    if (clear) {
      clear.click();
      return;
    }
    console.error("game-addon: the parent picker has no clear button");
    for (const input of this.parentInputs()) input.value = "";
  }

  private show(visible: boolean): void {
    if (this.parentRow) this.parentRow.hidden = !visible;
  }
}

customElements.define("game-addon", GameAddonElement);
