/**
 * DatePicker — custom element wrapping the vanilla TS implementation.
 *
 * Drives the DatePicker component (common/components/date_picker.py): a
 * single presentation-aware segmented date (issue #485) plus a calendar
 * popup, replacing native `<input type="date">` on add/edit forms so the
 * account's DATETIME_FORMAT preference controls the visible segment order.
 *
 * Shares the segment-entry engine (date-field-core.ts) and the whole
 * single-select calendar wiring (bindSingleSelectCalendar in
 * date-calendar-core.ts) with date-time-field.ts:
 * - Segments: identical digit-typing/arrow/backspace/paste grammar, driving
 *   one side ("value") instead of two.
 * - Calendar: no presets, no anchor — clicking a day commits the value and
 *   closes the popup immediately (a native date input's one-click UX);
 *   Clear empties the value and keeps the popup open.
 *
 * Hosted in <drop-down behavior="date-calendar"> (issue #485 follow-up):
 * visibility, viewport-aware positioning, and outside-click/Escape dismiss
 * all come from the shared attachMenu engine (this element delegates to the
 * host's open()/close(), the same shape SearchSelect(host_dropdown) uses)
 * instead of a bespoke absolute-positioned Div + its own document listeners.
 *
 * The committed value lives in the hidden ISO input Django binds
 * (`[data-date-picker-hidden]`), named after the real form field.
 */
import { bindSegmentField, setSideValue } from "./date-field-core.js";
import { bindSingleSelectCalendar } from "./date-calendar-core.js";
import { freezeControls, type UnsetTarget } from "./unset-target.js";

export const DATE_PICKER_CHANGE_EVENT = "date-picker:change";

export interface DatePickerChangeDetail {
  value: string;
}

// The single side id this element's shared-engine hooks use — DateRangePicker
// keys its hooks by side ("min"/"max"); a single-date field has exactly one.
const SIDE = "value";

function resolveHidden(picker: HTMLElement): HTMLInputElement | null {
  return picker.querySelector<HTMLInputElement>("input[data-date-picker-hidden]");
}

function dispatchDatePickerChange(picker: HTMLElement): void {
  picker.dispatchEvent(
    new CustomEvent<DatePickerChangeDetail>(DATE_PICKER_CHANGE_EVENT, {
      bubbles: true,
      detail: { value: resolveHidden(picker)?.value ?? "" },
    }),
  );
}

function commitSelection(picker: HTMLElement, isoString: string): void {
  setSideValue(
    picker,
    SIDE,
    () => resolveHidden(picker),
    () => dispatchDatePickerChange(picker),
    isoString,
  );
}

// Listeners move with the subtree; wire once.
function initPicker(picker: HTMLElement): void {
  const calendar = bindSingleSelectCalendar({
    picker,
    idPrefix: "date-picker-calendar",
    selectedIso: () => resolveHidden(picker)?.value ?? "",
    onPickDay: (isoString) => commitSelection(picker, isoString),
    onClear: () => commitSelection(picker, ""),
  });

  const field = picker.querySelector<HTMLElement>("[data-date-picker-field]")!;
  bindSegmentField({
    picker,
    field,
    resolveHidden: () => resolveHidden(picker),
    onCommit: () => dispatchDatePickerChange(picker),
    onFocus: () => calendar.refreshFromField(),
  });
}

class DatePickerElement extends HTMLElement implements UnsetTarget {
  private initialized = false;
  private kept: { value: string; thaw: () => void } | null = null;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    initPicker(this);
  }

  unsetValue(): void {
    const value = resolveHidden(this)?.value ?? "";
    commitSelection(this, "");
    this.kept = { value, thaw: freezeControls(this) };
  }

  restoreValue(): void {
    const kept = this.kept;
    this.kept = null;
    if (!kept) return;
    kept.thaw();
    commitSelection(this, kept.value);
  }
}

customElements.define("date-picker", DatePickerElement);
