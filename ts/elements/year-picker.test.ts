// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildYearUrl,
  decadeStartFor,
  visibleYears,
} from "./year-picker.js";

class FakeDropDown extends HTMLElement {
  open(): void {
    this.querySelector("[data-menu]")?.removeAttribute("hidden");
  }

  close(): void {
    const menu = this.querySelector("[data-menu]");
    if (!menu || menu.hasAttribute("hidden")) return;
    menu.setAttribute("hidden", "");
    this.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
  }
}

if (!customElements.get("drop-down")) customElements.define("drop-down", FakeDropDown);

function mount(options: {
  selectedYear?: string;
  availableYears?: string;
  urlTemplate?: string;
} = {}): HTMLElement {
  document.body.replaceChildren();
  const dropdown = document.createElement("drop-down");
  const picker = document.createElement("year-picker");
  picker.setAttribute("selected-year", options.selectedYear ?? "2024");
  picker.setAttribute("available-years", options.availableYears ?? "2023,2024,2025");
  picker.setAttribute("url-template", options.urlTemplate ?? "/stats/__year__/");
  picker.innerHTML = `
    <button data-toggle data-year-picker-toggle aria-expanded="false" type="button">
      Choose a year
    </button>
    <div data-menu data-year-picker-popup hidden role="group" aria-labelledby="year-picker-period">
      <span id="year-picker-period" data-year-picker-period></span>
      <button data-year-picker-prev type="button"></button>
      <button data-year-picker-next type="button"></button>
      <div data-year-picker-grid></div>
      <template data-year-picker-template="year">
        <button data-year type="button"></button>
      </template>
    </div>`;
  dropdown.appendChild(picker);
  document.body.appendChild(dropdown);
  return picker;
}

function open(picker: HTMLElement): void {
  picker.querySelector<HTMLElement>("[data-year-picker-toggle]")!.click();
}

function gridButtons(picker: HTMLElement): NodeListOf<HTMLButtonElement> {
  return picker.querySelectorAll<HTMLButtonElement>(
    "[data-year-picker-grid] button[data-year]",
  );
}

beforeEach(() => {
  vi.useFakeTimers({ now: new Date(2026, 5, 1) });
});

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("year-picker helpers", () => {
  it("calculates decade pages and their twelve-cell sequence", () => {
    expect(decadeStartFor(2026)).toBe(2020);
    expect(decadeStartFor(1999)).toBe(1990);
    expect(visibleYears(2020)).toEqual([
      2019, 2020, 2021, 2022, 2023, 2024,
      2025, 2026, 2027, 2028, 2029, 2030,
    ]);
  });

  it("builds navigation URLs and preserves the empty-template guard", () => {
    expect(buildYearUrl("/stats/__year__/", 2024)).toBe("/stats/2024/");
    expect(buildYearUrl("", 2024)).toBeNull();
  });
});

describe("year-picker grid", () => {
  it("renders the selected year in a four-column twelve-cell page", () => {
    const picker = mount();
    open(picker);
    const buttons = gridButtons(picker);
    expect(buttons).toHaveLength(12);
    expect([...buttons].map((button) => Number(button.dataset.year))).toEqual(
      visibleYears(2020),
    );
    expect(buttons[5].getAttribute("aria-current")).toBe("page");
    expect(buttons[5].classList.contains("solid-brand")).toBe(true);
    expect(buttons[0].classList.contains("opacity-40")).toBe(true);
    expect(buttons[0].disabled).toBe(true);
    expect(buttons[2].disabled).toBe(true);
    expect(buttons[6].disabled).toBe(false);
    expect(buttons[6].hasAttribute("aria-current")).toBe(false);
    expect(buttons[0].hasAttribute("aria-selected")).toBe(false);
  });

  it("initializes an empty selection at the current year", () => {
    const picker = mount({ selectedYear: "" });
    open(picker);
    expect(picker.querySelector("[data-year-picker-period]")?.textContent).toBe(
      "2020-2029",
    );
  });

  it("disables previous at the minimum decade and next at the current boundary", () => {
    const minimum = mount({ selectedYear: "1999", availableYears: "1999" });
    open(minimum);
    expect(
      minimum.querySelector<HTMLButtonElement>("[data-year-picker-prev]")!.disabled,
    ).toBe(true);

    const current = mount({ selectedYear: "2024" });
    open(current);
    expect(
      current.querySelector<HTMLButtonElement>("[data-year-picker-next]")!.disabled,
    ).toBe(true);
  });

  it("moves between decade pages without navigating", () => {
    const picker = mount({ selectedYear: "2012", availableYears: "2012" });
    open(picker);
    expect(picker.querySelector("[data-year-picker-period]")?.textContent).toBe(
      "2010-2019",
    );
    picker.querySelector<HTMLButtonElement>("[data-year-picker-next]")!.click();
    expect(picker.querySelector("[data-year-picker-period]")?.textContent).toBe(
      "2020-2029",
    );
    picker.querySelector<HTMLButtonElement>("[data-year-picker-prev]")!.click();
    expect(picker.querySelector("[data-year-picker-period]")?.textContent).toBe(
      "2010-2019",
    );
  });
});

describe("year-picker popup behavior", () => {
  it("opens from ArrowDown without moving focus away from the trigger", () => {
    const picker = mount();
    const toggle = picker.querySelector<HTMLElement>("[data-year-picker-toggle]")!;
    toggle.focus();
    toggle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expect(picker.querySelector("[data-year-picker-popup]")?.hasAttribute("hidden")).toBe(
      false,
    );
    expect(document.activeElement).toBe(toggle);
  });

  it("closes from Escape", () => {
    const picker = mount();
    const toggle = picker.querySelector<HTMLElement>("[data-year-picker-toggle]")!;
    open(picker);
    toggle.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(picker.querySelector("[data-year-picker-popup]")?.hasAttribute("hidden")).toBe(
      true,
    );
  });

  it("closes after an enabled year is activated and ignores disabled years", () => {
    const picker = mount({ availableYears: "2024", urlTemplate: "" });
    open(picker);
    const disabled = [...gridButtons(picker)].find((button) => button.dataset.year === "2023")!;
    disabled.click();
    expect(picker.querySelector("[data-year-picker-popup]")?.hasAttribute("hidden")).toBe(
      false,
    );

    const enabled = [...gridButtons(picker)].find((button) => button.dataset.year === "2024")!;
    enabled.click();
    expect(picker.querySelector("[data-year-picker-popup]")?.hasAttribute("hidden")).toBe(
      true,
    );
  });

  it("does not register duplicate listeners when reconnected", () => {
    const picker = mount();
    const dropdown = picker.parentElement!;
    picker.remove();
    dropdown.appendChild(picker);
    open(picker);
    expect(picker.querySelector("[data-year-picker-popup]")?.hasAttribute("hidden")).toBe(
      false,
    );
  });
});
