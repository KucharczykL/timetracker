// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./quick-filter-bar.js";
import { applyUrl } from "./filter-url.js";

const LIST_URL = "/tracker/session/list";

// Static facet markup matching what the server's field_widget renders. For the
// set kind the <search-select> root carries the data-filter-widget attributes
// and pills live under [data-search-select-pills] (the readFilterSelect
// contract); no [data-search-select-search] input, so the search-select
// initializer bails harmlessly in jsdom. The scalar kinds mirror the
// NumberFilter / DateRangePicker markers their readers query.
function setFacet(field: string, pills = ""): string {
  return `
    <search-select name="${field}" filter-mode="true" data-filter-widget
        data-path='["${field}"]' data-kind="set">
      <div data-search-select-pills>${pills}</div>
    </search-select>`;
}

function includePill(value: string, label: string): string {
  return `<span data-pill data-value="${value}" data-label="${label}"
      data-search-select-type="include"></span>`;
}

function numberFacet(field: string, modifier: string, value: string): string {
  return `
    <div data-filter-widget data-path='["${field}"]' data-kind="number">
      <select data-number-modifier-select>
        <option value="EQUALS">is</option>
        <option value="GREATER_THAN"${modifier === "GREATER_THAN" ? " selected" : ""}>is greater than</option>
      </select>
      <input type="number" value="${value}">
      <input type="number" data-number-value2 class="hidden">
    </div>`;
}

function dateFacet(field: string, min: string, max: string): string {
  return `
    <div data-filter-widget data-path='["${field}"]' data-kind="date">
      <input type="hidden" data-range-min value="${min}">
      <input type="hidden" data-range-max value="${max}">
    </div>`;
}

function boolFacet(field: string, checked: "true" | "false" | "" = ""): string {
  const check = (value: string): string =>
    checked === value ? " checked" : "";
  return `
    <div data-filter-widget data-path='["${field}"]' data-kind="bool">
      <input type="radio" name="quick-${field}" value="true"${check("true")}>
      <input type="radio" name="quick-${field}" value="false"${check("false")}>
    </div>`;
}

function mount(facets: string): {
  bar: HTMLElement;
  form: HTMLFormElement;
  navigate: ReturnType<typeof vi.fn>;
} {
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}">
      <form>
        ${facets}
        <button type="submit">Apply</button>
      </form>
    </quick-filter-bar>`;
  const bar = document.querySelector("quick-filter-bar") as HTMLElement;
  const form = bar.querySelector("form") as HTMLFormElement;
  const navigate = vi.fn();
  (bar as unknown as { navigate: (url: string) => void }).navigate = navigate;
  return { bar, form, navigate };
}

function submit(form: HTMLFormElement): void {
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("<quick-filter-bar>", () => {
  it("Apply navigates with the set facet criteria only", () => {
    const { form, navigate } = mount(
      setFacet("game", includePill("1", "Outer Wilds")) + setFacet("device"),
    );
    submit(form);
    expect(navigate).toHaveBeenCalledWith(
      applyUrl(LIST_URL, {
        game: {
          value: [{ id: "1", label: "Outer Wilds" }],
          excludes: [],
          modifier: "INCLUDES",
        },
      }),
    );
  });

  it("serializes every facet kind into one flat filter", () => {
    const { form, navigate } = mount(
      setFacet("game", includePill("1", "Outer Wilds")) +
        numberFacet("duration_total_hours", "GREATER_THAN", "2") +
        dateFacet("timestamp_start", "2026-01-01", "") +
        boolFacet("mastered", "true"),
    );
    submit(form);
    expect(navigate).toHaveBeenCalledWith(
      applyUrl(LIST_URL, {
        game: {
          value: [{ id: "1", label: "Outer Wilds" }],
          excludes: [],
          modifier: "INCLUDES",
        },
        duration_total_hours: { value: 2, modifier: "GREATER_THAN" },
        timestamp_start: { value: "2026-01-01", modifier: "GREATER_THAN" },
        mastered: { value: true, modifier: "EQUALS" },
      }),
    );
  });

  it("navigates to the bare list URL when all facets are empty", () => {
    const { form, navigate } = mount(
      setFacet("game") +
        numberFacet("duration_total_hours", "EQUALS", "") +
        dateFacet("timestamp_start", "", "") +
        boolFacet("mastered"),
    );
    submit(form);
    expect(navigate).toHaveBeenCalledWith(LIST_URL);
  });

  it("does not navigate on a facet change without Apply", () => {
    const { bar, navigate } = mount(setFacet("game", includePill("1", "X")));
    const widget = bar.querySelector('search-select[name="game"]') as HTMLElement;
    widget.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: { name: "game", values: [], last: null },
      }),
    );
    expect(navigate).not.toHaveBeenCalled();
  });
});
