import { readUnsetFieldProps, type UnsetFieldProps } from "../generated/props.js";
import { reportClientError } from "../client-errors.js";
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
interface KeptControl {
  control: Control;
  value: string;
  placeholder: string | null;
  disabledByPress: boolean;
}

/** How a press reached the field. */
type Pressed = { target: UnsetTarget } | { kept: KeptControl[] };

export class UnsetFieldElement extends HTMLElement {
  private toggle: HTMLButtonElement | null = null;
  private state: HTMLInputElement | null = null;
  private member: HTMLElement | null = null;
  private pressed: Pressed | null = null;
  /** Set when a composite never defined. */
  private nativeOnly = false;

  connectedCallback(): void {
    // A DOM move reconnects; bind once.
    if (this.toggle) return;
    this.toggle = this.querySelector<HTMLButtonElement>("[data-unset-field-toggle]");
    this.state = this.querySelector<HTMLInputElement>("[data-unset-field-state]");
    this.member = this.querySelector<HTMLElement>("[data-unset-field-member]");
    if (!this.toggle || !this.state || !this.member) {
      reportClientError("unset-field", "missing toggle, checkbox or field");
      return;
    }
    this.toggle.addEventListener("click", this.onToggle);
    // Composites upgrade before they can empty.
    const toggle = this.toggle;
    const member = this.member;
    const wasDisabled = toggle.disabled;
    const wasInert = member.hasAttribute("inert");
    toggle.disabled = true;
    // No typing into a field stated none.
    if (this.state.checked) member.toggleAttribute("inert", true);
    let settled = false;
    const settle = (): void => {
      if (settled) return;
      settled = true;
      toggle.disabled = wasDisabled;
      member.toggleAttribute("inert", wasInert);
      if (!this.state?.checked || this.pressed) return;
      // A failed press keeps the server's none.
      if (this.press()) this.reflect();
    };
    const tags = this.customTags();
    const slow = window.setTimeout(() => {
      reportClientError("unset-field", `never defined: ${tags.join(", ")}`);
      this.nativeOnly = true;
      settle();
    }, DEFINE_TIMEOUT_MS);
    void Promise.all(
      tags.map((tag) =>
        // Reserved names reject; skip them.
        customElements.whenDefined(tag).catch(() => undefined),
      ),
    ).then(() => {
      window.clearTimeout(slow);
      settle();
    });
  }

  get unset(): boolean {
    return this.pressed !== null;
  }

  private customTags(): string[] {
    const tags = new Set(
      Array.from(this.member?.querySelectorAll("*") ?? [])
        .map((element) => element.localName)
        .filter((tag) => tag.includes("-")),
    );
    return Array.from(tags);
  }

  private readonly onToggle = (): void => {
    if (this.pressed) this.release();
    else if (!this.press()) return;
    this.reflect();
    this.dispatchEvent(
      new CustomEvent<UnsetFieldChangeDetail>("unset-field:change", {
        bubbles: true,
        detail: { name: readUnsetFieldProps(this).name, unset: this.unset },
      }),
    );
  };

  private target(): (HTMLElement & UnsetTarget) | null {
    if (this.nativeOnly) return null;
    const found = Array.from(this.member?.querySelectorAll("*") ?? []).find(isUnsetTarget);
    return found ?? null;
  }

  /** Whether the field now states none. */
  private press(): boolean {
    const target = this.target();
    if (target) {
      target.unsetValue();
      this.pressed = { target };
      return true;
    }
    const controls = Array.from(this.member?.querySelectorAll<Control>(NATIVE) ?? []);
    if (controls.length === 0) {
      reportClientError("unset-field", "no control to empty");
      return false;
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
    return true;
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
