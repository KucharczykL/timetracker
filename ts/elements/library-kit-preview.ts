const TOAST_ID = "library-kit-preview:conversion";
const RUNNING =
  "Prices are being converted. Totals will update when conversion is complete.";
const FAILED =
  "Prices couldn't be converted. Existing totals are still available. We'll retry automatically.";
const COMPLETE = "Prices converted. Totals are now up to date.";

class LibraryKitPreviewElement extends HTMLElement {
  connectedCallback(): void {
    this.addEventListener("click", this.onClick);
  }

  disconnectedCallback(): void {
    this.removeEventListener("click", this.onClick);
  }

  private readonly onClick = (event: Event): void => {
    const button = (event.target as HTMLElement).closest<HTMLElement>(
      "[data-preview-conversion-toast]",
    );
    if (!button || !this.contains(button)) return;
    const state = button.dataset.previewConversionToast;
    if (state === "running") {
      window.toast(RUNNING, "info", { id: TOAST_ID, duration: null });
    } else if (state === "failed") {
      window.toast(FAILED, "error", { id: TOAST_ID, duration: null });
    } else if (state === "complete") {
      window.removeToast(TOAST_ID);
      window.toast(COMPLETE, "success");
    }
  };
}

customElements.define("library-kit-preview", LibraryKitPreviewElement);
