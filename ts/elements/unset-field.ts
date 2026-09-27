import { readUnsetFieldProps, type UnsetFieldProps } from "../generated/props.js";

/** The field's one visible control. */
const CONTROL = "input:not([type=hidden]), textarea, select";

type Control = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

export interface UnsetFieldChangeDetail {
  name: UnsetFieldProps["name"];
  unset: boolean;
}

/** What a second press puts back. */
interface Pressed {
  value: string;
  placeholder: string | null;
  disabledByPress: boolean;
}

export class UnsetFieldElement extends HTMLElement {
  private toggle: HTMLButtonElement | null = null;
  private state: HTMLInputElement | null = null;
  private control: Control | null = null;
  private pressed: Pressed | null = null;

  connectedCallback(): void {
    // A DOM move reconnects; bind once.
    if (this.toggle) return;
    this.toggle = this.querySelector<HTMLButtonElement>("[data-unset-field-toggle]");
    this.state = this.querySelector<HTMLInputElement>("[data-unset-field-state]");
    this.control =
      this.querySelector<HTMLElement>("[data-unset-field-member]")?.querySelector<Control>(CONTROL) ?? null;
    if (!this.toggle || !this.state || !this.control) {
      console.error("unset-field: missing toggle, checkbox or control", this);
      return;
    }
    this.toggle.addEventListener("click", this.onToggle);
    if (this.state.checked) this.press();
    this.reflect();
  }

  get unset(): boolean {
    return this.pressed !== null;
  }

  private readonly onToggle = (): void => {
    if (this.pressed) this.release();
    else this.press();
    this.reflect();
    this.dispatchEvent(
      new CustomEvent<UnsetFieldChangeDetail>("unset-field:change", {
        bubbles: true,
        detail: { name: readUnsetFieldProps(this).name, unset: this.unset },
      }),
    );
  };

  private press(): void {
    const control = this.control;
    if (!control) return;
    this.pressed = {
      value: control.value,
      placeholder: control.getAttribute("placeholder"),
      disabledByPress: !control.disabled,
    };
    control.value = "";
    control.setAttribute("placeholder", readUnsetFieldProps(this).noneLabel);
    control.disabled = true;
  }

  private release(): void {
    const pressed = this.pressed;
    this.pressed = null;
    const control = this.control;
    if (!pressed || !control) return;
    if (pressed.disabledByPress) control.disabled = false;
    control.value = pressed.value;
    if (pressed.placeholder === null) control.removeAttribute("placeholder");
    else control.setAttribute("placeholder", pressed.placeholder);
  }

  /** The checkbox posts; the toggle shows it. */
  private reflect(): void {
    if (this.state) this.state.checked = this.unset;
    this.toggle?.setAttribute("aria-pressed", String(this.unset));
  }
}

customElements.define("unset-field", UnsetFieldElement);
