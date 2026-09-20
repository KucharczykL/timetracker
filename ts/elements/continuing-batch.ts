/** <continuing-batch> — the progress page's press, made unnecessary.
 *
 * A batch spans as many requests as its rows need. The server renders a
 * waypoint with a form that posts the rest; this element posts it, so a
 * person watches a count rise instead of pressing Continue. Stop is the
 * one press that still means something.
 *
 * It is an element rather than an `onSwap` handler because connecting is
 * the moment it must act, and a chunk arrives both ways: by navigation
 * on one and by swap on the next.
 */

const FORM = "[data-continuing-batch-form]";
const STOP = "[data-continuing-batch-stop]";

class ContinuingBatchElement extends HTMLElement {
  // Pressed once, and this host posts nothing again.
  private stopped = false;

  connectedCallback(): void {
    this.querySelector<HTMLButtonElement>(STOP)?.addEventListener("click", this.onStop);
    if (document.readyState === "loading") {
      // The form is a child, so a parse that has reached the start tag
      // has not read it yet. The same handler registers once.
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
    // The button posts its own name; this only keeps the host quiet.
    this.stopped = true;
  };

  private carryOn(): void {
    if (this.stopped) return;
    this.querySelector<HTMLFormElement>(FORM)?.requestSubmit();
  }
}

customElements.define("continuing-batch", ContinuingBatchElement);
