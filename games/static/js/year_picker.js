import { onSwap } from "./utils.js";

onSwap("#year-picker-input", function(pickerEl) {
    const selectedYear = pickerEl.dataset.selectedYear;
    const urlTemplate = pickerEl.dataset.urlTemplate;
    const currentYear = new Date().getFullYear();
    const availableYears = new Set(
        pickerEl.dataset.availableYears
            .split(",")
            .map(s => parseInt(s.trim()))
            .filter(n => !isNaN(n))
    );

    const picker = new Datepicker(pickerEl, {
        pickLevel: 2,
        format: "yyyy",
        minDate: new Date(1999, 0, 1),
        maxDate: new Date(currentYear, 11, 31),
        autohide: false,
        orientation: "bottom end",
        showOnClick: false,
        showOnFocus: false,
        beforeShowYear: (date) => ({ enabled: availableYears.has(date.getFullYear()) }),
    });
    pickerEl._pickerInstance = picker;

    picker.element.addEventListener("changeDate", (event) => {
        const year = event.detail.date?.getFullYear();
        if (year && urlTemplate) {
            window.location.href = urlTemplate.replace("__year__", year);
        }
    });

    if (selectedYear) {
        picker.dates = [new Date(parseInt(selectedYear), 0, 1)];
        picker.update();
    }
});
