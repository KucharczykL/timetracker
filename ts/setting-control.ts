/** One reader over every setting control kind. */
// Defines <search-select> before any read.
import { SearchSelectElement } from "./elements/search-select.js";
import type { ResolvedSetting, SettingValue } from "./settings-events.js";

export type { SettingValue };

interface NativeSnapshot {
  readonly kind: "native";
  readonly value: string;
  readonly checked?: boolean;
}

type HeldSnapshot =
  | { readonly kind: "held"; readonly value: string; readonly none: false }
  | { readonly kind: "held"; readonly value: ""; readonly none: true };

export type ControlSnapshot = NativeSnapshot | HeldSnapshot;

export interface SaveAttempt {
  readonly value: SettingValue;
  readonly state: ControlSnapshot;
}

//: Every event a control commits with.
export const SETTING_CHANGE_EVENTS = ["change", "search-select:change"] as const;
export type SettingChangeEvent = (typeof SETTING_CHANGE_EVENTS)[number];

//: Marks a control the generic element saves.
const LIVE_MARKER = "data-live-setting-control";

const HELD_NONE: HeldSnapshot = { kind: "held", value: "", none: true };

export interface SettingControl {
  readonly element: HTMLElement;
  //: The event a person's commit fires.
  readonly changeEvent: SettingChangeEvent;
  //: `undefined`: nothing to save yet.
  read(): SettingValue | undefined;
  //: `restore(snapshot())` changes nothing.
  snapshot(): ControlSnapshot;
  //: Silent: fires no change event.
  restore(state: ControlSnapshot): void;
  write(value: SettingValue): void;
  resolvedSnapshot(attempt: SaveAttempt, resolved: ResolvedSetting): ControlSnapshot;
  editable(): boolean;
  setDisabled(disabled: boolean): void;
  setBusy(busy: boolean): void;
}

export function snapshotsEqual(left: ControlSnapshot, right: ControlSnapshot): boolean {
  if (left.kind === "native" && right.kind === "native") {
    return left.value === right.value && left.checked === right.checked;
  }
  if (left.kind === "held" && right.kind === "held") {
    return left.value === right.value && left.none === right.none;
  }
  return false;
}

function markBusy(element: HTMLElement, busy: boolean): void {
  if (busy) element.setAttribute("aria-busy", "true");
  else element.removeAttribute("aria-busy");
}

type NativeElement = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

function isCheckbox(element: NativeElement): element is HTMLInputElement {
  return element instanceof HTMLInputElement && element.type === "checkbox";
}

function refuseKind(expected: ControlSnapshot["kind"], state: ControlSnapshot): never {
  throw new Error(`setting control: a ${state.kind} snapshot is no ${expected} one`);
}

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

  snapshot(): NativeSnapshot {
    const control = this.element;
    return isCheckbox(control)
      ? { kind: "native", value: control.value, checked: control.checked }
      : { kind: "native", value: control.value };
  }

  restore(state: ControlSnapshot): void {
    if (state.kind !== "native") refuseKind("native", state);
    const control = this.element;
    control.value = state.value;
    if (isCheckbox(control) && state.checked !== undefined) control.checked = state.checked;
  }

  write(value: SettingValue): void {
    const control = this.element;
    if (isCheckbox(control)) {
      if (typeof value !== "boolean") {
        throw new Error(`setting control: a checkbox takes a boolean, not ${value}`);
      }
      control.checked = value;
      return;
    }
    control.value = value === null ? "" : String(value);
  }

  resolvedSnapshot(attempt: SaveAttempt, resolved: ResolvedSetting): ControlSnapshot {
    const control = this.element;
    // Blank means "use default", whatever resolved.
    if (control instanceof HTMLSelectElement && attempt.value === null) return attempt.state;
    if (isCheckbox(control)) {
      const checked = attempt.state.kind === "native" ? attempt.state.checked : undefined;
      return {
        kind: "native",
        value: control.value,
        checked: typeof resolved.value === "boolean" ? resolved.value : checked,
      };
    }
    return { kind: "native", value: resolved.value === null ? "" : String(resolved.value) };
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
  private readonly search: HTMLInputElement;

  constructor(readonly element: SearchSelectElement) {
    const search = element.querySelector<HTMLInputElement>("[data-search-select-search]");
    if (!search) throw new Error(`search-select[${element.getAttribute("name")}]: no search box`);
    this.search = search;
  }

  private reportUnoffered(value: SettingValue): void {
    console.error(`search-select[${this.element.getAttribute("name")}]: no row offers`, value);
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

  snapshot(): HeldSnapshot {
    const held = this.heldInput();
    if (held?.hasAttribute("data-search-select-none")) return HELD_NONE;
    return { kind: "held", value: held?.value ?? "", none: false };
  }

  restore(state: ControlSnapshot): void {
    if (state.kind !== "held") refuseKind("held", state);
    this.write(state.none ? null : state.value);
  }

  write(value: SettingValue): void {
    if (value === null || value === "") {
      this.element.holdNone();
    } else if (!this.element.holdValue(String(value))) {
      this.reportUnoffered(value);
    }
  }

  resolvedSnapshot(attempt: SaveAttempt, resolved: ResolvedSetting): ControlSnapshot {
    // Null holds none; its label names the default.
    if (attempt.value === null || resolved.value === null) return HELD_NONE;
    const value = String(resolved.value);
    if (!this.element.offers(value)) {
      this.reportUnoffered(value);
      return HELD_NONE;
    }
    return { kind: "held", value, none: false };
  }

  editable(): boolean {
    return !this.search.disabled;
  }

  setDisabled(disabled: boolean): void {
    this.search.disabled = disabled;
  }

  setBusy(busy: boolean): void {
    markBusy(this.search, busy);
  }
}

export function settingControlOf(element: Element): SettingControl | null {
  // Parents may connect before children upgrade.
  if (element.localName === "search-select") customElements.upgrade(element);
  if (element instanceof SearchSelectElement) {
    if (element.getAttribute("multi") === "true") {
      throw new Error(`search-select[${element.getAttribute("name")}]: a setting holds one value`);
    }
    return new SearchSelectSettingControl(element);
  }
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
