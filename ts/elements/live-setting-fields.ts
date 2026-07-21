/** Optimistic live-save for native Django setting controls (issue #384). */
import { readLiveSettingFieldsProps } from "../generated/props.js";

type SettingControl = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

interface ControlSnapshot {
  value: string;
  checked?: boolean;
}

function isSettingControl(element: Element | null): element is SettingControl {
  return (
    element instanceof HTMLInputElement ||
    element instanceof HTMLSelectElement ||
    element instanceof HTMLTextAreaElement
  );
}

export function settingPayloadValue(
  control: SettingControl,
): string | number | boolean | null {
  if (control instanceof HTMLInputElement) {
    if (control.type === "checkbox") return control.checked;
    if (control.type === "number") {
      return control.value === "" ? null : control.valueAsNumber;
    }
  }
  // The settings API's clearing contract is value:null. Treat an empty native
  // control consistently across select/text/textarea so clearing a personal
  // override falls through to its site/default layer instead of storing "".
  if (control.value === "") return null;
  return control.value;
}

function snapshot(control: SettingControl): ControlSnapshot {
  return {
    value: control.value,
    ...(control instanceof HTMLInputElement && control.type === "checkbox"
      ? { checked: control.checked }
      : {}),
  };
}

function restore(control: SettingControl, state: ControlSnapshot): void {
  control.value = state.value;
  if (
    control instanceof HTMLInputElement &&
    control.type === "checkbox" &&
    state.checked !== undefined
  ) {
    control.checked = state.checked;
  }
}

class LiveSettingFieldsElement extends HTMLElement {
  private patchUrlTemplate = "";
  private csrf = "";
  private successEvent = "setting-saved";
  private committed = new Map<SettingControl, ControlSnapshot>();
  private pending = new Map<SettingControl, AbortController>();

  connectedCallback(): void {
    const props = readLiveSettingFieldsProps(this);
    this.patchUrlTemplate = props.patchUrlTemplate;
    this.csrf = props.csrf;
    this.successEvent = props.event || "setting-saved";
    this.querySelectorAll<HTMLElement>("[data-setting-key]").forEach((candidate) => {
      if (isSettingControl(candidate)) this.committed.set(candidate, snapshot(candidate));
    });
    this.addEventListener("change", this.onChange);
  }

  disconnectedCallback(): void {
    this.removeEventListener("change", this.onChange);
    this.pending.forEach((controller) => controller.abort());
    this.pending.clear();
  }

  private onChange = (event: Event): void => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const control = target.closest<HTMLElement>("[data-setting-key]");
    if (!isSettingControl(control) || !this.contains(control)) return;
    const readOnly =
      (control instanceof HTMLInputElement ||
        control instanceof HTMLTextAreaElement) &&
      control.readOnly;
    if (control.disabled || readOnly) return;
    void this.save(control);
  };

  private async save(control: SettingControl): Promise<void> {
    const key = control.dataset.settingKey ?? "";
    if (!key || !this.patchUrlTemplate.includes("__key__")) return;
    const value = settingPayloadValue(control);
    if (typeof value === "number" && !Number.isFinite(value)) {
      window.toast("Enter a valid number before saving.", "error");
      restore(control, this.committed.get(control) ?? snapshot(control));
      return;
    }

    this.pending.get(control)?.abort();
    const controller = new AbortController();
    this.pending.set(control, controller);
    control.setAttribute("aria-busy", "true");
    const url = this.patchUrlTemplate.replace("__key__", encodeURIComponent(key));

    try {
      const response = await window.fetchWithHtmxTriggers(url, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.csrf,
        },
        body: JSON.stringify({ value }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`PATCH ${url} → ${response.status}`);
      if (this.pending.get(control) !== controller) return;
      this.committed.set(control, snapshot(control));
      document.body.dispatchEvent(
        new CustomEvent(this.successEvent, {
          detail: { key, value },
          bubbles: true,
        }),
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      console.error("Failed to update setting", key, error);
      if (this.pending.get(control) !== controller) return;
      const previous = this.committed.get(control);
      if (previous) restore(control, previous);
      window.toast("Couldn't save your change — please try again.", "error");
    } finally {
      if (this.pending.get(control) === controller) {
        this.pending.delete(control);
        control.removeAttribute("aria-busy");
      }
    }
  }
}

customElements.define("live-setting-fields", LiveSettingFieldsElement);
