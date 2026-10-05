import { reportClientError } from "../client-errors.js";
import { readFieldMirrorProps } from "../generated/props.js";

function report(detail: string): void {
  reportClientError("field-mirror", detail, { toast: false });
}

/** Copies a field into another until edited. */
class FieldMirrorElement extends HTMLElement {
  private form: HTMLFormElement | null = null;
  private source = "";
  private target = "";
  /** The person took the target over. */
  private targetEdited = false;

  connectedCallback(): void {
    const { sourceField, targetField } = readFieldMirrorProps(this);
    this.source = sourceField;
    this.target = targetField;
    this.form = this.closest("form");
    if (!this.form) {
      report("no enclosing form");
      return;
    }
    if (!this.targetInput()) report(`no [name="${targetField}"] in its form`);
    this.form.addEventListener("input", this.onInput);
  }

  disconnectedCallback(): void {
    this.form?.removeEventListener("input", this.onInput);
    this.form = null;
  }

  private targetInput(): HTMLInputElement | null {
    return this.form?.querySelector<HTMLInputElement>(`[name="${this.target}"]`) ?? null;
  }

  private readonly onInput = (event: Event): void => {
    const changed = event.target;
    if (!(changed instanceof HTMLInputElement)) return;
    if (changed.name === this.target) {
      this.targetEdited = true;
      return;
    }
    if (changed.name !== this.source || this.targetEdited) return;
    const target = this.targetInput();
    // A programmatic write fires no input.
    if (target) target.value = changed.value;
  };
}

customElements.define("field-mirror", FieldMirrorElement);
