import { readFieldMirrorProps } from "../generated/props.js";

/** Copies a field into another until edited. */
class FieldMirrorElement extends HTMLElement {
  private form: HTMLFormElement | null = null;
  /** The person took the target over. */
  private targetEdited = false;

  connectedCallback(): void {
    this.form = this.closest("form");
    if (!this.form) {
      console.error("field-mirror: no enclosing form");
      return;
    }
    this.form.addEventListener("input", this.onInput);
  }

  disconnectedCallback(): void {
    this.form?.removeEventListener("input", this.onInput);
    this.form = null;
  }

  private readonly onInput = (event: Event): void => {
    const { sourceField, targetField } = readFieldMirrorProps(this);
    const changed = event.target;
    if (!(changed instanceof HTMLInputElement)) return;
    if (changed.name === targetField) {
      this.targetEdited = true;
      return;
    }
    if (changed.name !== sourceField || this.targetEdited) return;
    const target = this.form?.querySelector<HTMLInputElement>(`[name="${targetField}"]`);
    // A programmatic write fires no input.
    if (target) target.value = changed.value;
  };
}

customElements.define("field-mirror", FieldMirrorElement);
