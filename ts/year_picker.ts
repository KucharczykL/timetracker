/**
 * YearPicker — wires the Flowbite-datepicker year grid behind the YearPicker
 * component (common/components/primitives.py). The component renders a hidden
 * #year-picker-input carrying data-available-years / data-selected-year /
 * data-url-template; this turns it into a year-level Datepicker and navigates
 * to the chosen year's URL. Datepicker comes from the vendored UMD bundle
 * (datepicker.umd.js), loaded as a classic script before this module runs.
 */
import { onSwap } from "./utils.js";

declare const Datepicker: any;

// The Alpine toggle button reaches the Datepicker instance through this prop.
interface PickerElement extends HTMLInputElement {
  _pickerInstance?: any;
}

onSwap("#year-picker-input", (element) => {
  const pickerElement = element as PickerElement;
  const selectedYear = pickerElement.dataset.selectedYear;
  const urlTemplate = pickerElement.dataset.urlTemplate;
  const currentYear = new Date().getFullYear();
  const availableYears = new Set(
    (pickerElement.dataset.availableYears ?? "")
      .split(",")
      .map((part) => parseInt(part.trim(), 10))
      .filter((year) => !isNaN(year))
  );

  const picker = new Datepicker(pickerElement, {
    pickLevel: 2,
    format: "yyyy",
    minDate: new Date(1999, 0, 1),
    maxDate: new Date(currentYear, 11, 31),
    autohide: false,
    orientation: "bottom end",
    showOnClick: false,
    showOnFocus: false,
    beforeShowYear: (date: Date) => ({ enabled: availableYears.has(date.getFullYear()) }),
  });
  pickerElement._pickerInstance = picker;

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
});
