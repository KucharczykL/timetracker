import { readGameAddonProps } from "../generated/props.js";

const MAIN_KIND = "main";

/** Shows the parent row only while the kind names an add-on. */
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
    this.kindSelect?.addEventListener("change", this.onKindChange);
    //: A parent posted beside main keeps its row, so its refusal shows.
    if (!this.parentHeld()) this.show(!this.isMain());
  }

  disconnectedCallback(): void {
    this.kindSelect?.removeEventListener("change", this.onKindChange);
  }

  private readonly onKindChange = (): void => {
    const main = this.isMain();
    this.show(!main);
    if (main && this.parentHeld()) {
      this.parentRow
        ?.querySelector<HTMLButtonElement>("[data-search-select-clear]")
        ?.click();
    }
  };

  private isMain(): boolean {
    const kind = this.kindSelect?.value ?? MAIN_KIND;
    return kind === "" || kind === MAIN_KIND;
  }

  private parentHeld(): boolean {
    const inputs = this.parentRow?.querySelectorAll<HTMLInputElement>(
      'input[type="hidden"]'
    );
    return Array.from(inputs ?? []).some(input => input.value !== "");
  }

  private show(visible: boolean): void {
    if (this.parentRow) this.parentRow.hidden = !visible;
  }
}

customElements.define("game-addon", GameAddonElement);
