/** <continuing-batch> — the waypoint's press, made unnecessary.
 *
 * The server renders a form that posts the rest of the batch; this
 * posts it, so a person watches a count rise. Stop is the one press
 * left.
 */

const FORM = "[data-continuing-batch-form]";
const STOP = "[data-continuing-batch-stop]";

class ContinuingBatchElement extends HTMLElement {
  // Pressed once, and this host posts no more.
  private stopped = false;

  connectedCallback(): void {
    this.querySelector<HTMLButtonElement>(STOP)?.addEventListener("click", this.onStop);
    if (document.readyState === "loading") {
      // The form is a child: a parse at the start tag
      // has not read it yet.
      document.addEventListener("DOMContentLoaded", this.onParsed, { once: true });
      return;
    }
    this.carryOn();
  }

  disconnectedCallback(): void {
    this.querySelector<HTMLButtonElement>(STOP)?.removeEventListener("click", this.onStop);
  }

  private readonly onParsed = (): void => {
    if (this.isConnected) this.carryOn();
  };

  private readonly onStop = (): void => {
    // The button posts its own name.
    this.stopped = true;
  };

  private carryOn(): void {
    if (this.stopped) return;
    this.querySelector<HTMLFormElement>(FORM)?.requestSubmit();
  }
}

customElements.define("continuing-batch", ContinuingBatchElement);
