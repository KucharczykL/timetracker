import { readCopyControlProps } from "../generated/props.js";

class CopyControlElement extends HTMLElement {
  private button: HTMLButtonElement | null = null;
  private label: HTMLElement | null = null;
  private value = "";
  private initialLabel = "Copy";
  private resetTimer: number | null = null;

  connectedCallback(): void {
    this.value = readCopyControlProps(this).value;
    this.button = this.querySelector<HTMLButtonElement>("[data-copy-control]");
    this.label = this.querySelector<HTMLElement>("[data-copy-label]");
    this.initialLabel = this.label?.textContent?.trim() || "Copy";
    this.button?.addEventListener("click", this.onCopy);
  }

  disconnectedCallback(): void {
    this.button?.removeEventListener("click", this.onCopy);
    if (this.resetTimer !== null) window.clearTimeout(this.resetTimer);
    this.resetTimer = null;
    this.setLabel(this.initialLabel);
  }

  private setLabel(value: string, visible = false): void {
    if (!this.label) return;
    this.label.textContent = value;
    this.label.classList.toggle("sr-only", !visible);
  }

  private readonly onCopy = async (): Promise<void> => {
    if (this.resetTimer !== null) window.clearTimeout(this.resetTimer);
    this.resetTimer = null;
    this.setLabel(this.initialLabel);
    try {
      await navigator.clipboard.writeText(this.value);
      this.setLabel("Copied!", true);
      this.resetTimer = window.setTimeout(() => {
        this.resetTimer = null;
        this.setLabel(this.initialLabel);
      }, 2_000);
    } catch {
      this.setLabel("Couldn't copy");
    }
  };
}

customElements.define("copy-control", CopyControlElement);
