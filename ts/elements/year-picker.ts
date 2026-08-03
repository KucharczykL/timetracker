/**
 * YearPicker — an in-house stats year grid hosted by the shared date-calendar
 * dropdown machinery.
 *
 * The server renders the toggle, popup structure, and a ControlButton template;
 * this element only supplies decade state, year-cell state, and navigation.
 * Enabled years navigate immediately to the URL template supplied by Django.
 */
import { YEAR_PICKER_CLASSES } from "../generated/calendar-classes.js";
import { readYearPickerProps } from "../generated/props.js";
import { bindCalendarPopupHost } from "./date-calendar-core.js";

export const YEAR_PICKER_MIN_YEAR = 1999;

export function decadeStartFor(year: number): number {
  return Math.floor(year / 10) * 10;
}

export function visibleYears(decadeStart: number): number[] {
  return Array.from({ length: 12 }, (_, index) => decadeStart - 1 + index);
}

export function buildYearUrl(urlTemplate: string, year: number): string | null {
  if (!urlTemplate) return null;
  return urlTemplate.replace("__year__", String(year));
}

type YearVariant = keyof typeof YEAR_PICKER_CLASSES;

function parseYear(value: string): number | null {
  const year = Number.parseInt(value, 10);
  return Number.isFinite(year) ? year : null;
}

function initYearPicker(picker: HTMLElement): boolean {
  const { selectedYear, availableYears, urlTemplate } = readYearPickerProps(picker);
  const toggle = picker.querySelector<HTMLElement>("[data-year-picker-toggle]");
  const popup = picker.querySelector<HTMLElement>("[data-year-picker-popup]");
  const period = picker.querySelector<HTMLElement>("[data-year-picker-period]");
  const grid = picker.querySelector<HTMLElement>("[data-year-picker-grid]");
  const template = picker.querySelector<HTMLTemplateElement>(
    '[data-year-picker-template="year"]',
  );
  const previous = picker.querySelector<HTMLButtonElement>("[data-year-picker-prev]");
  const next = picker.querySelector<HTMLButtonElement>("[data-year-picker-next]");
  if (!toggle || !popup || !period || !grid || !template || !previous || !next) {
    return false;
  }

  const currentYear = new Date().getFullYear();
  const enabledYears = new Set(
    availableYears
      .split(",")
      .map((part) => parseYear(part.trim()))
      .filter((year): year is number => year !== null),
  );
  let selected = parseYear(selectedYear);
  let decadeStart = decadeStartFor(selected ?? currentYear);

  const isSelectable = (year: number): boolean =>
    year >= YEAR_PICKER_MIN_YEAR && year <= currentYear && enabledYears.has(year);

  const render = (): void => {
    period.textContent = `${decadeStart}-${decadeStart + 9}`;
    previous.disabled = decadeStart <= YEAR_PICKER_MIN_YEAR;
    next.disabled = decadeStart + 9 >= currentYear;
    grid.replaceChildren();

    const prototype = template.content.firstElementChild;
    if (!prototype) return;
    for (const year of visibleYears(decadeStart)) {
      const button = prototype.cloneNode(true) as HTMLButtonElement;
      const adjacent = year < decadeStart || year > decadeStart + 9;
      const selectable = isSelectable(year);
      let variant: YearVariant;
      if (!selectable) {
        variant = adjacent ? "adjacent-disabled" : "disabled";
      } else if (year === selected) {
        variant = "selected";
      } else {
        variant = adjacent ? "adjacent" : "default";
      }
      button.className = YEAR_PICKER_CLASSES[variant];
      button.textContent = String(year);
      button.setAttribute("data-year", String(year));
      button.setAttribute("aria-label", String(year));
      if (year === selected) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
      button.disabled = !selectable;
      grid.appendChild(button);
    }
  };

  const beforeOpen = (): void => {
    selected = parseYear(readYearPickerProps(picker).selectedYear);
    decadeStart = decadeStartFor(selected ?? currentYear);
  };

  const host = bindCalendarPopupHost({
    picker,
    popup,
    toggleButton: toggle,
    idPrefix: "year-picker",
    beforeOpen,
    render,
  });

  previous.addEventListener("click", () => {
    if (previous.disabled) return;
    decadeStart -= 10;
    render();
  });
  next.addEventListener("click", () => {
    if (next.disabled) return;
    decadeStart += 10;
    render();
  });

  toggle.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      host.open();
    } else if (event.key === "Escape" && host.isOpen()) {
      event.preventDefault();
      host.close();
    }
  });

  grid.addEventListener("click", (event) => {
    const button = (event.target as Element).closest<HTMLButtonElement>(
      "button[data-year]",
    );
    if (!button || button.disabled) return;
    const year = parseYear(button.dataset.year ?? "");
    if (year === null) return;
    const url = buildYearUrl(urlTemplate, year);
    host.close();
    if (url !== null) window.location.href = url;
  });

  return true;
}

class YearPickerElement extends HTMLElement {
  private initialized = false;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = initYearPicker(this);
  }
}

customElements.define("year-picker", YearPickerElement);
