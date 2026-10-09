import { readTriStateCheckboxProps, type TriStateCheckboxProps } from "../generated/props.js";
import { reportClientError } from "../client-errors.js";

type TriState = TriStateCheckboxProps["held"];

/** The bound parts, all found and read. */
type BoundParts = {
  box: HTMLInputElement;
  postedInput: HTMLInputElement;
  hint: HTMLElement;
  props: TriStateCheckboxProps;
};

/** A press's next state, from the held one. */
function nextState(current: TriState, held: TriState): TriState {
  if (held !== "mixed") return current === "checked" ? "unchecked" : "checked";
  if (current === "mixed") return "checked";
  return current === "checked" ? "unchecked" : "mixed";
}

export class TriStateCheckboxElement extends HTMLElement {
  private parts: BoundParts | null = null;
  private state: TriState = "mixed";

  connectedCallback(): void {
    // A DOM move reconnects; bind once.
    if (this.parts) return;
    const parts = this.bind();
    if (!parts) return;
    this.parts = parts;
    parts.box.disabled = false;
    parts.box.addEventListener("change", () => {
      this.state = nextState(this.state, parts.props.held);
      this.reflect(parts);
    });
    this.state = this.readState(parts);
    this.reflect(parts);
  }

  /** Finds and reads every part; null reports why and leaves the box disabled. */
  private bind(): BoundParts | null {
    const name = this.getAttribute("name") ?? "";
    const box = this.querySelector<HTMLInputElement>("[data-tri-state-box]");
    const postedInput = this.querySelector<HTMLInputElement>("[data-tri-state-value]");
    const hint = this.querySelector<HTMLElement>("[data-tri-state-hint]");
    if (!box || !postedInput || !hint) {
      const missing = [
        box ? "" : "box",
        postedInput ? "" : "value",
        hint ? "" : "hint",
      ].filter((part) => part !== "");
      reportClientError("tri-state-checkbox", `${name}: missing ${missing.join(", ")}`);
      return null;
    }
    let props: TriStateCheckboxProps;
    try {
      props = readTriStateCheckboxProps(this);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      reportClientError("tri-state-checkbox", `${name}: ${reason}`);
      return null;
    }
    const { checkedWord, uncheckedWord } = props;
    if (!checkedWord || !uncheckedWord || checkedWord === uncheckedWord) {
      reportClientError(
        "tri-state-checkbox",
        `${name}: words must be non-empty and differ`,
      );
      return null;
    }
    return { box, postedInput, hint, props };
  }

  /** Hidden value; "" means held. */
  private readState({ postedInput, props }: BoundParts): TriState {
    const posted = postedInput.value;
    if (posted === "") return props.held;
    if (posted === props.checkedWord) return "checked";
    if (posted === props.uncheckedWord) return "unchecked";
    reportClientError(
      "tri-state-checkbox",
      `${props.name}: unknown posted value ${posted}`,
    );
    return props.held;
  }

  /** Box, hidden value and hint follow state. */
  private reflect({ box, postedInput, hint, props }: BoundParts): void {
    box.checked = this.state === "checked";
    box.indeterminate = this.state === "mixed";
    if (this.state === props.held) {
      postedInput.value = "";
      hint.textContent = this.state === "mixed" ? props.hintMixed : props.hintKept;
    } else {
      postedInput.value = this.state === "checked" ? props.checkedWord : props.uncheckedWord;
      hint.textContent = props.hintChanged;
    }
  }
}

customElements.define("tri-state-checkbox", TriStateCheckboxElement);
