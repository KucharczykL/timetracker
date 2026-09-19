// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { readDateWidget, writeDateWidget } from "./filter-widgets.js";

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
