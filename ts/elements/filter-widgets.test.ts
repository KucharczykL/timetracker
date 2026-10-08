// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import {
  parseNumberInputValue,
  readDateWidget,
  readNumberWidget,
  readStringWidget,
  setupModifierToggles,
  writeDateWidget,
  writeNumberWidget,
  writeStringWidget,
} from "./filter-widgets.js";
import { choicePickerHtml } from "../test-setup/choice-picker.js";
import { choiceControl } from "./choice-control.js";

Element.prototype.scrollIntoView = () => {};

function dateWidget(): HTMLElement {
  const element = document.createElement("div");
  element.innerHTML =
    '<input type="hidden" data-date-range-hidden="min" data-range-min value="">' +
    '<input type="hidden" data-date-range-hidden="max" data-range-max value="">' +
    '<input type="hidden" data-range-modifier value="">';
  return element;
}

describe("the date widget round-trips every modifier it hydrates", () => {
  it("keeps WITHIN through write then read", () => {
    const element = dateWidget();
    writeDateWidget(element, { value: "2024-01-01", value2: "2024-12-31", modifier: "WITHIN" });
    expect(readDateWidget(element)).toEqual({
      value: "2024-01-01",
      value2: "2024-12-31",
      modifier: "WITHIN",
    });
  });
  it("reads BETWEEN where nothing was carried", () => {
    const element = dateWidget();
    writeDateWidget(element, { value: "2024-01-01", value2: "2024-12-31", modifier: "BETWEEN" });
    expect(readDateWidget(element)?.["modifier"]).toBe("BETWEEN");
  });
  it("forgets a carried WITHIN once BETWEEN is written over it", () => {
    const element = dateWidget();
    writeDateWidget(element, { value: "2024-01-01", value2: "2024-12-31", modifier: "WITHIN" });
    writeDateWidget(element, { value: "2024-02-01", value2: "2024-03-01", modifier: "BETWEEN" });
    expect(readDateWidget(element)?.["modifier"]).toBe("BETWEEN");
  });
  it("leaves NOT_BETWEEN blank, so the leaf prunes", () => {
    const element = dateWidget();
    writeDateWidget(element, { value: "2024-01-01", value2: "2024-12-31", modifier: "NOT_BETWEEN" });
    expect(readDateWidget(element)).toBeNull();
  });
  it("keeps a one-sided range one-sided", () => {
    const element = dateWidget();
    writeDateWidget(element, { value: "2024-01-01", modifier: "GREATER_THAN" });
    const read = readDateWidget(element);
    expect([read?.["value"], read?.["modifier"]]).toEqual(["2024-01-01", "GREATER_THAN"]);
  });
});

const STRING_MODES = [
  { value: "EQUALS", label: "is" },
  { value: "IS_NULL", label: "is null" },
];

function stringWidget(held = "EQUALS"): HTMLElement {
  const root = document.createElement("div");
  root.setAttribute("data-filter-widget", "");
  root.innerHTML =
    choicePickerHtml({
      name: "name-modifier",
      marker: "data-string-modifier-select",
      rows: STRING_MODES,
      held,
    }) + '<input type="text" data-string-value value="">';
  document.body.append(root);
  return root;
}

function numberWidget(): HTMLElement {
  const root = document.createElement("div");
  root.setAttribute("data-filter-widget", "");
  root.innerHTML =
    choicePickerHtml({
      name: "year-modifier",
      marker: "data-number-modifier-select",
      rows: [
        { value: "EQUALS", label: "is" },
        { value: "BETWEEN", label: "between" },
        { value: "IS_NULL", label: "is null" },
      ],
      held: "EQUALS",
    }) +
    '<input type="number" value="1990"><input type="number" data-number-value2 class="hidden">';
  document.body.append(root);
  return root;
}

function pickerBox(root: HTMLElement): HTMLInputElement {
  return root.querySelector<HTMLInputElement>("[data-search-select-search]")!;
}

function pick(root: HTMLElement, value: string): void {
  pickerBox(root).focus();
  root.querySelector<HTMLElement>(`[data-search-select-option][data-value="${value}"]`)!.click();
}

describe("the string and number widgets read their picker", () => {
  afterEach(() => document.body.replaceChildren());

  it("reads the value input, not the picker's box", () => {
    const root = stringWidget();
    root.querySelector<HTMLInputElement>("[data-string-value]")!.value = " Hades ";
    expect(readStringWidget(root)).toEqual({ value: "Hades", modifier: "EQUALS" });
  });

  it("reads a root-stated mode beside its value input", () => {
    const root = document.createElement("search-field");
    root.setAttribute("data-modifier", "INCLUDES");
    root.innerHTML = '<input type="text" data-match-value data-string-value value="zelda">';
    expect(readStringWidget(root)).toEqual({ value: "zelda", modifier: "INCLUDES" });
  });

  it("answers null while the picker holds nothing", () => {
    const root = stringWidget();
    root.querySelector<HTMLInputElement>("[data-string-value]")!.value = "Hades";
    const box = pickerBox(root);
    box.focus();
    box.value = "i";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    expect(readStringWidget(root)).toBeNull();
  });

  it("writes the modifier and disables the value for a presence one", () => {
    const root = stringWidget();
    writeStringWidget(root, { modifier: "IS_NULL" });
    expect(choiceControl(root, "data-string-modifier-select")!.read()).toBe("IS_NULL");
    expect(root.querySelector<HTMLInputElement>("[data-string-value]")!.disabled).toBe(true);
    expect(readStringWidget(root)).toEqual({ modifier: "IS_NULL" });
  });

  it("toggles the value input on a pick", () => {
    const root = stringWidget();
    setupModifierToggles(document.body);
    pick(root, "IS_NULL");
    expect(root.querySelector<HTMLInputElement>("[data-string-value]")!.disabled).toBe(true);
    pick(root, "EQUALS");
    expect(root.querySelector<HTMLInputElement>("[data-string-value]")!.disabled).toBe(false);
  });

  it("reveals the second number on a range pick", () => {
    const root = numberWidget();
    setupModifierToggles(document.body);
    pick(root, "BETWEEN");
    expect(root.querySelector("[data-number-value2]")!.classList.contains("hidden")).toBe(false);
    root.querySelector<HTMLInputElement>("[data-number-value2]")!.value = "2000";
    expect(readNumberWidget(root)).toEqual({ value: 1990, value2: 2000, modifier: "BETWEEN" });
  });
});

describe("a number input reads only a finite value", () => {
  it("reads a decimal", () => {
    const input = document.createElement("input");
    input.type = "text";
    input.value = "1.5";
    expect(parseNumberInputValue(input)).toBe(1.5);
  });

  it("refuses an overflow to Infinity as blank", () => {
    const input = document.createElement("input");
    input.type = "text";
    input.value = "1e400";
    expect(parseNumberInputValue(input)).toBe("");
  });
});
