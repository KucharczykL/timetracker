import { reportClientError } from "../client-errors.js";
import { readFieldMirrorProps } from "../generated/props.js";

function report(detail: string): void {
  reportClientError("field-mirror", detail, { toast: false });
}

/** Copies a field into another until edited. */
class FieldMirrorElement extends HTMLElement {
  private form: HTMLFormElement | null = null;
  private sourceField = "";
  private targetField = "";
  /** The person took the target over. */
  private targetEdited = false;

  connectedCallback(): void {
    const props = readFieldMirrorProps(this);
    this.sourceField = props.sourceField;
    this.targetField = props.targetField;
    this.form = this.closest("form");
    if (!this.form) {
      report("no enclosing form");
      return;
    }
    if (!this.targetInput()) report(`no [name="${this.targetField}"] in its form`);
    this.form.addEventListener("input", this.onInput);
  }

  disconnectedCallback(): void {
    this.form?.removeEventListener("input", this.onInput);
    this.form = null;
  }

  private targetInput(): HTMLInputElement | null {
    return this.form?.querySelector<HTMLInputElement>(`[name="${this.targetField}"]`) ?? null;
  }

  private readonly onInput = (event: Event): void => {
    const changed = event.target;
    if (!(changed instanceof HTMLInputElement)) return;
    if (changed.name === this.targetField) {
      this.targetEdited = true;
      return;
    }
    if (changed.name !== this.sourceField || this.targetEdited) return;
    const target = this.targetInput();
    // A programmatic write fires no input.
    if (target) target.value = changed.value;
  };
}

customElements.define("field-mirror", FieldMirrorElement);
