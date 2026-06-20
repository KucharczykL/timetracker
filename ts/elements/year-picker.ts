/**
 * YearPicker — custom element wrapping the Flowbite-datepicker year grid behind
 * the YearPicker component (common/components/primitives.py).
 *
 * The component renders a toggle <button> plus a hidden #year-picker-input and
 * carries selected-year / available-years / url-template as typed props. This
 * turns the input into a year-level Datepicker, toggles it from the button, and
 * navigates to the chosen year's URL. Datepicker comes from the vendored UMD
 * bundle (datepicker.umd.js), a classic script loaded before this module runs.
 *
 * The Datepicker popup is appended to document.body, so its built-in
 * outside-click handler is bypassed (it only fires when the input is focused,
 * and our input is unfocusable). bindPopupDismiss handles Escape + outside
 * click instead, treating the body-mounted popup as "inside".
 */
import { readYearPickerProps } from "../generated/props.js";
import { bindPopupDismiss } from "../utils.js";

declare const Datepicker: any;

class YearPickerElement extends HTMLElement {
  private cleanup: (() => void) | null = null;

  connectedCallback(): void {
    const { selectedYear, availableYears, urlTemplate } = readYearPickerProps(this);
    const input = this.querySelector<HTMLInputElement>("#year-picker-input");
    const toggle = this.querySelector<HTMLElement>("[data-year-picker-toggle]");
    if (!input || !toggle) return;

    const currentYear = new Date().getFullYear();
    const enabledYears = new Set(
      availableYears
        .split(",")
        .map((part) => parseInt(part.trim(), 10))
        .filter((year) => !isNaN(year))
    );

    const picker = new Datepicker(input, {
      pickLevel: 2,
      format: "yyyy",
      minDate: new Date(1999, 0, 1),
      maxDate: new Date(currentYear, 11, 31),
      autohide: false,
      orientation: "bottom end",
      showOnClick: false,
      showOnFocus: false,
      beforeShowYear: (date: Date) => ({ enabled: enabledYears.has(date.getFullYear()) }),
    });

    picker.element.addEventListener("changeDate", (event: Event) => {
      const year = (event as CustomEvent).detail.date?.getFullYear();
      if (year && urlTemplate) {
        window.location.href = urlTemplate.replace("__year__", String(year));
      }
    });

    if (selectedYear) {
      picker.dates = [new Date(parseInt(selectedYear, 10), 0, 1)];
      picker.update();
    }

    toggle.addEventListener("click", () => {
      if (picker.active) picker.hide();
      else picker.show();
    });

    this.cleanup = bindPopupDismiss({
      host: this,
      isOpen: () => picker.active,
      close: () => picker.hide(),
      extraInside: () => [picker.picker?.element],
    });
  }

  disconnectedCallback(): void {
    this.cleanup?.();
    this.cleanup = null;
  }
}

customElements.define("year-picker", YearPickerElement);
