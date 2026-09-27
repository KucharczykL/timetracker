import { readUnsetFieldProps, type UnsetFieldProps } from "../generated/props.js";
import { isUnsetTarget, type UnsetTarget } from "./unset-target.js";

/** Grace before a missing script is reported. */
const DEFINE_TIMEOUT_MS = 5_000;

/** Visible native controls. */
const NATIVE = "input:not([type=hidden]), textarea, select";

type Control = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

export interface UnsetFieldChangeDetail {
  name: UnsetFieldProps["name"];
  unset: boolean;
}

/** One native control, as a press found it. */
interface Kept {
  control: Control;
  value: string;
  placeholder: string | null;
  disabledByPress: boolean;
}

/** How a press reached the field. */
type Pressed = { target: UnsetTarget } | { kept: Kept[] };

export class UnsetFieldElement extends HTMLElement {
  private toggle: HTMLButtonElement | null = null;
  private state: HTMLInputElement | null = null;
  private member: HTMLElement | null = null;
  private pressed: Pressed | null = null;

  connectedCallback(): void {
    // A DOM move reconnects; bind once.
    if (this.toggle) return;
    this.toggle = this.querySelector<HTMLButtonElement>("[data-unset-field-toggle]");
    this.state = this.querySelector<HTMLInputElement>("[data-unset-field-state]");
    this.member = this.querySelector<HTMLElement>("[data-unset-field-member]");
    if (!this.toggle || !this.state || !this.member) {
      console.error("unset-field: missing toggle, checkbox or field", this);
      return;
    }
    this.toggle.addEventListener("click", this.onToggle);
    // Composites upgrade before they can empty.
    const toggle = this.toggle;
    const wasDisabled = toggle.disabled;
    toggle.disabled = true;
    void this.defined().then(() => {
      toggle.disabled = wasDisabled;
      if (this.state?.checked && !this.pressed) this.press();
      this.reflect();
    });
  }

  get unset(): boolean {
    return this.pressed !== null;
  }

  /** Every custom element in the field, upgraded. */
  private defined(): Promise<unknown> {
    const tags = new Set(
      Array.from(this.member?.querySelectorAll("*") ?? [])
        .map((element) => element.localName)
        .filter((tag) => tag.includes("-")),
    );
    const waits = Array.from(tags, (tag) =>
      // Reserved names reject; skip them.
      customElements.whenDefined(tag).catch(() => undefined),
    );
    const slow = window.setTimeout(() => {
      console.error("unset-field: field elements never defined", Array.from(tags), this);
    }, DEFINE_TIMEOUT_MS);
    return Promise.all(waits).finally(() => window.clearTimeout(slow));
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

  private target(): (HTMLElement & UnsetTarget) | null {
    const found = Array.from(this.member?.querySelectorAll("*") ?? []).find(isUnsetTarget);
    return found ?? null;
  }

  private press(): void {
    const target = this.target();
    if (target) {
      target.unsetValue();
      this.pressed = { target };
      return;
    }
    const controls = Array.from(this.member?.querySelectorAll<Control>(NATIVE) ?? []);
    if (controls.length === 0) {
      console.error("unset-field: no control to empty", this);
      return;
    }
    const kept = controls.map((control) => ({
      control,
      value: control.value,
      placeholder: control.getAttribute("placeholder"),
      disabledByPress: !control.disabled,
    }));
    const noneLabel = readUnsetFieldProps(this).noneLabel;
    kept.forEach(({ control }, index) => {
      control.value = "";
      if (index === 0) control.setAttribute("placeholder", noneLabel);
      control.disabled = true;
    });
    this.pressed = { kept };
  }

  private release(): void {
    const pressed = this.pressed;
    this.pressed = null;
    if (!pressed) return;
    if ("target" in pressed) {
      pressed.target.restoreValue();
      return;
    }
    pressed.kept.forEach(({ control, value, placeholder, disabledByPress }) => {
      if (disabledByPress) control.disabled = false;
      control.value = value;
      if (placeholder === null) control.removeAttribute("placeholder");
      else control.setAttribute("placeholder", placeholder);
    });
  }

  /** The checkbox posts; the toggle shows it. */
  private reflect(): void {
    if (this.state) this.state.checked = this.unset;
    this.toggle?.setAttribute("aria-pressed", String(this.unset));
  }
}

customElements.define("unset-field", UnsetFieldElement);
