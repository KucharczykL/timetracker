// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./quick-filter-bar.js";
import { applyUrl } from "./filter-url.js";

const LIST_URL = "/tracker/game/list";

// Static facet markup matching what the server's field_widget renders: the
// <search-select> root carries the data-filter-widget attributes, pills live
// under [data-search-select-pills] (the readFilterSelect contract). No
// [data-search-select-search] input, so the search-select initializer bails
// harmlessly in jsdom.
function facetMarkup(field: string, pills = ""): string {
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

function mount(statusPills = "", platformPills = ""): {
  bar: HTMLElement;
  navigate: ReturnType<typeof vi.fn>;
  statusWidget: HTMLElement;
} {
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}">
      ${facetMarkup("status", statusPills)}
      ${facetMarkup("platform", platformPills)}
    </quick-filter-bar>`;
  const bar = document.querySelector("quick-filter-bar") as HTMLElement;
  const navigate = vi.fn();
  (bar as unknown as { navigate: (url: string) => void }).navigate = navigate;
  const statusWidget = bar.querySelector(
    'search-select[name="status"]',
  ) as HTMLElement;
  return { bar, navigate, statusWidget };
}

function dispatchChange(widget: HTMLElement): void {
  widget.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: { name: widget.getAttribute("name"), values: [], last: null },
    }),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("<quick-filter-bar>", () => {
  it("navigates with only the facet criteria on a facet change", () => {
    const { navigate, statusWidget } = mount(includePill("f", "Finished"));
    dispatchChange(statusWidget);
    expect(navigate).toHaveBeenCalledWith(
      applyUrl(LIST_URL, {
        status: {
          value: [{ id: "f", label: "Finished" }],
          excludes: [],
          modifier: "INCLUDES",
        },
      }),
    );
  });

  it("serializes every non-empty facet, not just the changed one", () => {
    const { navigate, statusWidget } = mount(
      includePill("f", "Finished"),
      includePill("1", "PC"),
    );
    dispatchChange(statusWidget);
    expect(navigate).toHaveBeenCalledWith(
      applyUrl(LIST_URL, {
        status: {
          value: [{ id: "f", label: "Finished" }],
          excludes: [],
          modifier: "INCLUDES",
        },
        platform: {
          value: [{ id: "1", label: "PC" }],
          excludes: [],
          modifier: "INCLUDES",
        },
      }),
    );
  });

  it("navigates to the bare list URL when all facets are empty", () => {
    const { navigate, statusWidget } = mount();
    dispatchChange(statusWidget);
    expect(navigate).toHaveBeenCalledWith(LIST_URL);
  });

  it("ignores search-select:change from a non-widget search-select", () => {
    const { bar, navigate } = mount();
    const stray = document.createElement("search-select");
    stray.setAttribute("name", "stray");
    bar.appendChild(stray);
    dispatchChange(stray);
    expect(navigate).not.toHaveBeenCalled();
  });
});
