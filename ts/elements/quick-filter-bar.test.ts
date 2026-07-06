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

  it("finds a set facet nested inside a hidden dropdown panel", () => {
    // The #315 dropdown facets host their <search-select> inside a
    // ComboboxDropdown's hidden [data-menu] dialog — serialization must be
    // depth- and visibility-agnostic.
    const { form, navigate } = mount(`
      <drop-down behavior="combobox">
        <button data-toggle type="button">Game</button>
        <div data-menu hidden>
          ${setFacet("game", includePill("1", "Outer Wilds"))}
        </div>
      </drop-down>`);
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

// ── Priority-plus overflow (#315): stubbed-width layout math ──────────────

interface OverflowFixture {
  bar: HTMLElement & { layoutOverflow: () => void };
  row: HTMLElement;
  host: HTMLElement;
  items: HTMLElement;
  facets: HTMLElement[];
  setRowWidth: (width: number) => void;
}

function stubWidth(element: HTMLElement, width: number): void {
  Object.defineProperty(element, "offsetWidth", {
    get: () => width,
    configurable: true,
  });
}

function mountOverflow(): OverflowFixture {
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}">
      <form>
        <div data-quick-row>
          <drop-down data-quick-facet id="f1"></drop-down>
          <drop-down data-quick-facet id="f2"></drop-down>
          <drop-down data-quick-facet id="f3"></drop-down>
          <div class="hidden" data-quick-overflow>
            <div data-quick-overflow-items></div>
          </div>
          <div id="group"></div>
        </div>
      </form>
    </quick-filter-bar>`;
  const bar = document.querySelector("quick-filter-bar") as OverflowFixture["bar"];
  const row = bar.querySelector<HTMLElement>("[data-quick-row]")!;
  const host = bar.querySelector<HTMLElement>("[data-quick-overflow]")!;
  const items = bar.querySelector<HTMLElement>("[data-quick-overflow-items]")!;
  const facets = Array.from(bar.querySelectorAll<HTMLElement>("[data-quick-facet]"));
  // jsdom has no layout: stub the widths the element measures at connect.
  // Measurement already happened in connectedCallback (all zeros), so stub
  // and re-run setup by reconnecting the node.
  facets.forEach((facet) => stubWidth(facet, 100));
  stubWidth(host, 40);
  stubWidth(bar.querySelector<HTMLElement>("#group")!, 80);
  let rowWidth = 1000;
  Object.defineProperty(row, "clientWidth", {
    get: () => rowWidth,
    configurable: true,
  });
  // Reconnect so setupOverflow measures the stubbed widths.
  const parent = bar.parentElement!;
  parent.removeChild(bar);
  parent.appendChild(bar);
  return {
    bar,
    row: bar.querySelector<HTMLElement>("[data-quick-row]")!,
    host: bar.querySelector<HTMLElement>("[data-quick-overflow]")!,
    items: bar.querySelector<HTMLElement>("[data-quick-overflow-items]")!,
    facets,
    setRowWidth: (width: number) => {
      rowWidth = width;
    },
  };
}

describe("quick-filter-bar priority-plus overflow (#315)", () => {
  it("keeps all facets in the row when they fit", () => {
    const fixture = mountOverflow();
    fixture.setRowWidth(1000);
    fixture.bar.layoutOverflow();
    expect(fixture.items.children.length).toBe(0);
    expect(fixture.host.classList.contains("hidden")).toBe(true);
    fixture.facets.forEach((facet) =>
      expect(facet.parentElement).toBe(fixture.row),
    );
  });

  it("spills rightmost facets into the overflow menu as the row narrows", () => {
    const fixture = mountOverflow();
    // reserved = group(80) + overflow(40); available = 300 - 120 = 180 → one
    // 100px facet fits.
    fixture.setRowWidth(300);
    fixture.bar.layoutOverflow();
    expect(fixture.facets[0].parentElement).toBe(fixture.row);
    expect(fixture.facets[1].parentElement).toBe(fixture.items);
    expect(fixture.facets[2].parentElement).toBe(fixture.items);
    expect(fixture.host.classList.contains("hidden")).toBe(false);
    // Spilled facets keep their original order inside the menu.
    expect(Array.from(fixture.items.children).map((child) => child.id)).toEqual([
      "f2",
      "f3",
    ]);
  });

  it("moves facets back, in order, when the row widens again", () => {
    const fixture = mountOverflow();
    fixture.setRowWidth(300);
    fixture.bar.layoutOverflow();
    fixture.setRowWidth(1000);
    fixture.bar.layoutOverflow();
    expect(fixture.items.children.length).toBe(0);
    expect(fixture.host.classList.contains("hidden")).toBe(true);
    const rowIds = Array.from(
      fixture.row.querySelectorAll("[data-quick-facet]"),
    ).map((facet) => facet.id);
    expect(rowIds).toEqual(["f1", "f2", "f3"]);
  });
});

// ── Preset pick navigation (#297 picker as quick-bar row furniture) ────────

function mountWithPicker(): {
  bar: HTMLElement;
  navigate: ReturnType<typeof vi.fn>;
  pick: (filter: string | null) => void;
} {
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}">
      <form>
        <div data-quick-row>
          <div data-preset-picker>
            <search-select name="preset"></search-select>
          </div>
        </div>
      </form>
    </quick-filter-bar>`;
  const bar = document.querySelector("quick-filter-bar") as HTMLElement;
  const navigate = vi.fn();
  (bar as unknown as { navigate: (url: string) => void }).navigate = navigate;
  const widget = bar.querySelector("search-select") as HTMLElement;
  const pick = (filter: string | null): void => {
    widget.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: {
          name: "preset",
          values: ["1"],
          last: {
            value: "1",
            label: "My preset",
            data: filter === null ? {} : { filter },
          },
        },
      }),
    );
  };
  return { bar, navigate, pick };
}

describe("quick-filter-bar preset pick", () => {
  it("navigates to the list with the preset's filter JSON", () => {
    const { navigate, pick } = mountWithPicker();
    const filter = { game: { value: [{ id: "1", label: "X" }], modifier: "INCLUDES" } };
    pick(JSON.stringify(filter));
    expect(navigate).toHaveBeenCalledWith(applyUrl(LIST_URL, filter));
  });

  it("an empty preset navigates to the bare list URL", () => {
    const { navigate, pick } = mountWithPicker();
    pick(null);
    expect(navigate).toHaveBeenCalledWith(LIST_URL);
  });

  it("invalid preset JSON toasts and stays put", () => {
    const { navigate, pick } = mountWithPicker();
    const toast = vi.fn();
    (window as unknown as { toast: typeof toast }).toast = toast;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    pick("{not json");
    expect(navigate).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalled();
    expect(consoleError.mock.calls[0][0]).toContain("preset load failed");
  });

  it("facet search-select changes are not treated as preset picks", () => {
    document.body.innerHTML = `
      <quick-filter-bar apply-url="${LIST_URL}">
        <form><div data-quick-row>
          <search-select name="game"></search-select>
        </div></form>
      </quick-filter-bar>`;
    const bar = document.querySelector("quick-filter-bar") as HTMLElement;
    const navigate = vi.fn();
    (bar as unknown as { navigate: (url: string) => void }).navigate = navigate;
    bar.querySelector("search-select")!.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: { name: "game", values: [], last: { value: "1", label: "X", data: {} } },
      }),
    );
    expect(navigate).not.toHaveBeenCalled();
  });
});

// ── Overflow reserve counts furniture between host and group (#315) ────────

it("reserves width for furniture after the overflow host (preset picker)", () => {
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}">
      <form>
        <div data-quick-row>
          <drop-down data-quick-facet id="f1"></drop-down>
          <drop-down data-quick-facet id="f2"></drop-down>
          <div class="hidden" data-quick-overflow>
            <div data-quick-overflow-items></div>
          </div>
          <div id="picker"></div>
          <div id="group"></div>
        </div>
      </form>
    </quick-filter-bar>`;
  const bar = document.querySelector("quick-filter-bar") as HTMLElement & {
    layoutOverflow: () => void;
  };
  const row = bar.querySelector<HTMLElement>("[data-quick-row]")!;
  const facets = Array.from(bar.querySelectorAll<HTMLElement>("[data-quick-facet]"));
  facets.forEach((facet) => stubWidth(facet, 100));
  stubWidth(bar.querySelector<HTMLElement>("[data-quick-overflow]")!, 40);
  stubWidth(bar.querySelector<HTMLElement>("#picker")!, 120);
  stubWidth(bar.querySelector<HTMLElement>("#group")!, 80);
  let rowWidth = 1000;
  Object.defineProperty(row, "clientWidth", { get: () => rowWidth, configurable: true });
  const parent = bar.parentElement!;
  parent.removeChild(bar);
  parent.appendChild(bar);

  // Without the picker 300px would fit one 100px facet (reserve 120); with the
  // 120px picker as furniture the reserve grows to 240 → nothing fits.
  rowWidth = 300;
  bar.layoutOverflow();
  const items = bar.querySelector<HTMLElement>("[data-quick-overflow-items]")!;
  expect(items.children.length).toBe(2);
  rowWidth = 1000;
  bar.layoutOverflow();
  expect(items.children.length).toBe(0);
});
