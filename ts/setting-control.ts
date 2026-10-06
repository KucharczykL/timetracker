/** One reader over every setting control kind. */
// Defines <search-select> before any read.
import { SearchSelectElement } from "./elements/search-select.js";
import type { ResolvedSetting, SettingValue } from "./settings-events.js";

export type { SettingValue };

export interface ControlSnapshot {
  value: string;
  checked?: boolean;
  none?: boolean;
}

export interface SaveAttempt {
  value: SettingValue;
  state: ControlSnapshot;
}

//: Marks a control the generic element saves.
const LIVE_MARKER = "data-live-setting-control";

export interface SettingControl {
  readonly element: HTMLElement;
  //: The event a person's commit fires.
  readonly changeEvent: string;
  //: `undefined`: nothing to save yet.
  read(): SettingValue | undefined;
  snapshot(): ControlSnapshot;
  //: Silent: fires no change event.
  restore(state: ControlSnapshot): void;
  write(value: SettingValue): void;
  resolvedSnapshot(attempt: SaveAttempt, resolved: ResolvedSetting): ControlSnapshot;
  equals(left: ControlSnapshot, right: ControlSnapshot): boolean;
  editable(): boolean;
  setDisabled(disabled: boolean): void;
  setBusy(busy: boolean): void;
}

type NativeElement = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

const snapshotsEqual = (left: ControlSnapshot, right: ControlSnapshot): boolean =>
  left.value === right.value && left.checked === right.checked && left.none === right.none;

const markBusy = (element: HTMLElement, busy: boolean): void => {
  if (busy) element.setAttribute("aria-busy", "true");
  else element.removeAttribute("aria-busy");
};

const isCheckbox = (element: NativeElement): element is HTMLInputElement =>
  element instanceof HTMLInputElement && element.type === "checkbox";

class NativeSettingControl implements SettingControl {
  readonly changeEvent = "change";

  constructor(readonly element: NativeElement) {}

  read(): SettingValue {
    const control = this.element;
    if (isCheckbox(control)) return control.checked;
    if (control instanceof HTMLInputElement && control.type === "number") {
      return control.value === "" ? null : control.valueAsNumber;
    }
    // Empty clears: the API takes null.
    if (control.value === "") return null;
    return control.value;
  }

  snapshot(): ControlSnapshot {
    const control = this.element;
    return { value: control.value, ...(isCheckbox(control) ? { checked: control.checked } : {}) };
  }

  restore(state: ControlSnapshot): void {
    const control = this.element;
    control.value = state.value;
    if (isCheckbox(control) && state.checked !== undefined) control.checked = state.checked;
  }

  write(value: SettingValue): void {
    const control = this.element;
    if (isCheckbox(control) && typeof value === "boolean") control.checked = value;
    else control.value = value === null ? "" : String(value);
  }

  resolvedSnapshot(attempt: SaveAttempt, resolved: ResolvedSetting): ControlSnapshot {
    const control = this.element;
    // Blank means "use default", whatever resolved.
    if (control instanceof HTMLSelectElement && attempt.value === null) return attempt.state;
    if (isCheckbox(control)) {
      return {
        ...attempt.state,
        checked: typeof resolved.value === "boolean" ? resolved.value : attempt.state.checked,
      };
    }
    return { value: resolved.value === null ? "" : String(resolved.value) };
  }

  equals(left: ControlSnapshot, right: ControlSnapshot): boolean {
    return snapshotsEqual(left, right);
  }

  editable(): boolean {
    const control = this.element;
    const readOnly = !(control instanceof HTMLSelectElement) && control.readOnly;
    return !control.disabled && !readOnly;
  }

  setDisabled(disabled: boolean): void {
    this.element.disabled = disabled;
  }

  setBusy(busy: boolean): void {
    markBusy(this.element, busy);
  }
}

class SearchSelectSettingControl implements SettingControl {
  readonly changeEvent = "search-select:change";

  constructor(readonly element: SearchSelectElement) {}

  private get search(): HTMLInputElement | null {
    return this.element.querySelector<HTMLInputElement>("[data-search-select-search]");
  }

  private heldInput(): HTMLInputElement | null {
    return this.element.querySelector<HTMLInputElement>(
      '[data-search-select-pills] input[type="hidden"]'
    );
  }

  read(): SettingValue | undefined {
    const held = this.heldInput();
    if (!held) return undefined;
    return held.hasAttribute("data-search-select-none") ? null : held.value;
  }

  snapshot(): ControlSnapshot {
    const held = this.heldInput();
    const none = held?.hasAttribute("data-search-select-none") ?? false;
    return { value: none ? "" : (held?.value ?? ""), none };
  }

  restore(state: ControlSnapshot): void {
    this.write(state.none ? null : state.value);
  }

  write(value: SettingValue): void {
    if (value === null || value === "") this.element.holdNone();
    else this.element.holdValue(String(value));
  }

  resolvedSnapshot(attempt: SaveAttempt, resolved: ResolvedSetting): ControlSnapshot {
    // None stays: its label names the default.
    if (attempt.value === null || resolved.value === null) return { value: "", none: true };
    return { value: String(resolved.value), none: false };
  }

  equals(left: ControlSnapshot, right: ControlSnapshot): boolean {
    return snapshotsEqual(left, right);
  }

  editable(): boolean {
    return !(this.search?.disabled ?? true);
  }

  setDisabled(disabled: boolean): void {
    if (this.search) this.search.disabled = disabled;
  }

  setBusy(busy: boolean): void {
    if (this.search) markBusy(this.search, busy);
  }
}

export function settingControlOf(element: Element): SettingControl | null {
  // Parents may connect before children upgrade.
  if (element.localName === "search-select") customElements.upgrade(element);
  if (element instanceof SearchSelectElement) return new SearchSelectSettingControl(element);
  if (
    element instanceof HTMLInputElement ||
    element instanceof HTMLSelectElement ||
    element instanceof HTMLTextAreaElement
  ) {
    return new NativeSettingControl(element);
  }
  return null;
}

/** The marked control an event commits. */
export function changedSettingControl(event: Event): SettingControl | null {
  // Ignores the search box's own blur change.
  const target = event.target;
  if (!(target instanceof Element) || !target.hasAttribute(LIVE_MARKER)) return null;
  const control = settingControlOf(target);
  return control && control.changeEvent === event.type ? control : null;
}
