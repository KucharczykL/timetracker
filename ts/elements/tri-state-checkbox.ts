import { readTriStateCheckboxProps, type TriStateCheckboxProps } from "../generated/props.js";
import { reportClientError } from "../client-errors.js";

type TriState = TriStateCheckboxProps["held"];

/** A press's next state, from the held one. */
function nextState(current: TriState, held: TriState): TriState {
  if (held !== "mixed") return current === "checked" ? "unchecked" : "checked";
  if (current === "mixed") return "checked";
  return current === "checked" ? "unchecked" : "mixed";
}

export class TriStateCheckboxElement extends HTMLElement {
  private box: HTMLInputElement | null = null;
  private postedInput: HTMLInputElement | null = null;
  private hint: HTMLElement | null = null;
  private state: TriState = "mixed";

  connectedCallback(): void {
    // A DOM move reconnects; bind once.
    if (this.box) return;
    this.box = this.querySelector<HTMLInputElement>("[data-tri-state-box]");
    this.postedInput = this.querySelector<HTMLInputElement>("[data-tri-state-value]");
    this.hint = this.querySelector<HTMLElement>("[data-tri-state-hint]");
    if (!this.box || !this.postedInput || !this.hint) {
      reportClientError("tri-state-checkbox", "missing box, value or hint");
      return;
    }
    this.box.addEventListener("change", this.onChange);
    this.state = this.readState();
    this.reflect();
  }

  /** The hidden value states the shown state; "" is the held one. */
  private readState(): TriState {
    const props = readTriStateCheckboxProps(this);
    const posted = this.postedInput?.value ?? "";
    if (posted === "") return props.held;
    if (posted === props.checkedWord) return "checked";
    if (posted === props.uncheckedWord) return "unchecked";
    return props.held;
  }

  private readonly onChange = (): void => {
    this.state = nextState(this.state, readTriStateCheckboxProps(this).held);
    this.reflect();
  };

  /** The box, the hidden value and the hint all follow the state. */
  private reflect(): void {
    const props = readTriStateCheckboxProps(this);
    if (!this.box || !this.postedInput || !this.hint) return;
    this.box.checked = this.state === "checked";
    this.box.indeterminate = this.state === "mixed";
    if (this.state === props.held) {
      this.postedInput.value = "";
      this.hint.textContent = this.state === "mixed" ? props.hintMixed : props.hintKept;
    } else {
      this.postedInput.value = this.state === "checked" ? props.checkedWord : props.uncheckedWord;
      this.hint.textContent = props.hintChanged;
    }
  }
}

customElements.define("tri-state-checkbox", TriStateCheckboxElement);
