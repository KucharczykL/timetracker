// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./quick-filter-bar.js";
import { applyUrl } from "./filter-url.js";
import { openSurfaces } from "./surface-stack.js";
import {
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveAnswer,
  PresetSaveRequest,
  PresetState,
} from "./presets.js";

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

function mount(facets: string, perPage = ""): {
  bar: HTMLElement;
  form: HTMLFormElement;
  navigate: ReturnType<typeof vi.fn>;
} {
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}" per-page="${perPage}">
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
  window.history.replaceState({}, "", "/");
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
    // The dropdown facets host their <search-select> inside a
    // ComboboxDropdown's hidden [data-menu] dialog — serialization must be
    // depth- and visibility-agnostic.
    const { form, navigate } = mount(`
      <drop-down behavior="combobox">
        <button data-toggle type="button">Game</button>
        <div data-menu popover="manual" hidden>
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

  it("carries the live ?sort= from the URL through a facet Apply", () => {
    // Tweaking a facet must not reset the active sort (#77); the bar reads it
    // from window.location since it has no sort UI of its own.
    window.history.replaceState({}, "", "/tracker/session/list?sort=-duration");
    const { form, navigate } = mount(setFacet("game", includePill("1", "X")));
    submit(form);
    const filter = {
      game: {
        value: [{ id: "1", label: "X" }],
        excludes: [],
        modifier: "INCLUDES",
      },
    };
    expect(navigate).toHaveBeenCalledWith(applyUrl(LIST_URL, filter, "-duration"));
  });

  it("carries the sort even when all facets are empty", () => {
    window.history.replaceState({}, "", "/tracker/session/list?sort=-duration");
    const { form, navigate } = mount(setFacet("game"));
    submit(form);
    expect(navigate).toHaveBeenCalledWith(applyUrl(LIST_URL, {}, "-duration"));
  });

  it("carries the normalized explicit page size through a facet Apply (#386)", () => {
    window.history.replaceState(
      {},
      "",
      "/tracker/session/list?sort=-duration&per_page=lots",
    );
    const { form, navigate } = mount(
      setFacet("game", includePill("1", "X")),
      "100",
    );
    submit(form);
    const filter = {
      game: {
        value: [{ id: "1", label: "X" }],
        excludes: [],
        modifier: "INCLUDES",
      },
    };
    expect(navigate).toHaveBeenCalledWith(applyUrl(LIST_URL, filter, "-duration", "100"));
  });

  it("drops an invalid raw page size when the server marks it inherited (#386)", () => {
    window.history.replaceState(
      {},
      "",
      "/tracker/session/list?sort=-duration&per_page=-5",
    );
    const { form, navigate } = mount(setFacet("game"));

    submit(form);

    expect(navigate).toHaveBeenCalledWith(applyUrl(LIST_URL, {}, "-duration"));
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

// ── Priority-plus overflow: stubbed-width layout math ──────────────

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

function mountOverflow(
  options: { leadingWidth?: number; applied?: string[] } = {},
): OverflowFixture {
  // No data-quick-facet: furniture the reserve counts, the overflow never takes.
  const leading = options.leadingWidth ? '<search-field id="lead"></search-field>' : "";
  const applied = new Set(options.applied ?? []);
  const facet = (id: string): string =>
    `<drop-down data-quick-facet id="${id}"${
      applied.has(id) ? " data-quick-facet-applied" : ""
    }></drop-down>`;
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}" overflow-label="More filters"
        overflow-label-applied="More filters, some applied">
      <form>
        <div data-quick-row>
          ${leading}
          ${facet("f1")}
          ${facet("f2")}
          ${facet("f3")}
          <div class="hidden" data-quick-overflow>
            <drop-down>
              <button data-toggle data-quick-overflow-trigger aria-label="More filters"></button>
              <div data-menu popover="manual" hidden><div data-quick-overflow-items></div></div>
            </drop-down>
            <span class="invisible" data-quick-overflow-mark></span>
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
  const lead = bar.querySelector<HTMLElement>("#lead");
  if (lead && options.leadingWidth) stubWidth(lead, options.leadingWidth);
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

describe("quick-filter-bar priority-plus overflow", () => {
  it("reserves the width of a field that leads the row", () => {
    // Reading only the host's following siblings missed a leading member.
    const fixture = mountOverflow({ leadingWidth: 200 });
    // reserved = field(200) + group(80) + overflow(40) = 320.
    // available = 520 - 320 = 200 → two 100px facets fit.
    fixture.setRowWidth(520);
    fixture.bar.layoutOverflow();
    expect(fixture.facets[0].parentElement).toBe(fixture.row);
    expect(fixture.facets[1].parentElement).toBe(fixture.row);
    expect(fixture.facets[2].parentElement).toBe(fixture.items);
  });

  it("never moves the leading field into the overflow menu", () => {
    const fixture = mountOverflow({ leadingWidth: 200 });
    fixture.setRowWidth(240);
    fixture.bar.layoutOverflow();
    const field = fixture.bar.querySelector("#lead")!;
    expect(field.parentElement).toBe(fixture.row);
    expect(fixture.items.contains(field)).toBe(false);
  });

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

  it("spills rightmost idle facets into the overflow menu as the row narrows", () => {
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

describe("quick-filter-bar overflow menu", () => {
  it("closes before its host hides", () => {
    const fixture = mountOverflow();
    const menu = fixture.host.querySelector("drop-down")!;
    fixture.setRowWidth(300);
    fixture.bar.layoutOverflow();
    menu.open();
    expect(openSurfaces()).toHaveLength(1);

    fixture.setRowWidth(1000);
    fixture.bar.layoutOverflow();
    expect(fixture.host.classList.contains("hidden")).toBe(true);
    expect(openSurfaces()).toEqual([]);
  });
});

function ids(parent: Element): string[] {
  return Array.from(parent.querySelectorAll(":scope > [data-quick-facet]")).map(
    (facet) => facet.id,
  );
}

function overflowMark(fixture: OverflowFixture): { shown: boolean; label: string } {
  const mark = fixture.host.querySelector("[data-quick-overflow-mark]")!;
  const trigger = fixture.host.querySelector("[data-quick-overflow-trigger]")!;
  return {
    shown: !mark.classList.contains("invisible"),
    label: trigger.getAttribute("aria-label") ?? "",
  };
}

describe("quick-filter-bar applied facets", () => {
  it("spills idle facets before an applied one", () => {
    const fixture = mountOverflow({ applied: ["f3"] });
    // available = 300 - 120 = 180 → one facet fits.
    fixture.setRowWidth(300);
    fixture.bar.layoutOverflow();
    expect(ids(fixture.row)).toEqual(["f3"]);
    expect(ids(fixture.items)).toEqual(["f1", "f2"]);
  });

  it("keeps the declared order among the facets that stay", () => {
    const fixture = mountOverflow({ applied: ["f3"] });
    // 300 + 80 > 350, so not all fit; available = 350 - 120 = 230 → two:
    // f3 by priority, then f1.
    fixture.setRowWidth(350);
    fixture.bar.layoutOverflow();
    expect(ids(fixture.row)).toEqual(["f1", "f3"]);
    expect(ids(fixture.items)).toEqual(["f2"]);
  });

  it("keeps the declared order in the menu when the row narrows in steps", () => {
    const fixture = mountOverflow();
    for (const width of [1000, 350, 300]) {
      fixture.setRowWidth(width);
      fixture.bar.layoutOverflow();
    }
    expect(ids(fixture.row)).toEqual(["f1"]);
    expect(ids(fixture.items)).toEqual(["f2", "f3"]);
  });

  it("keeps both orders across a narrow-wide-narrow cycle", () => {
    const fixture = mountOverflow({ applied: ["f2"] });
    for (const width of [300, 1000, 350, 300]) {
      fixture.setRowWidth(width);
      fixture.bar.layoutOverflow();
    }
    expect(ids(fixture.row)).toEqual(["f2"]);
    expect(ids(fixture.items)).toEqual(["f1", "f3"]);
    fixture.setRowWidth(350);
    fixture.bar.layoutOverflow();
    expect(ids(fixture.row)).toEqual(["f1", "f2"]);
    expect(ids(fixture.items)).toEqual(["f3"]);
  });

  it("moves no node when the layout does not change", () => {
    for (const width of [300, 150]) {
      const fixture = mountOverflow({ applied: ["f3"] });
      fixture.setRowWidth(width);
      fixture.bar.layoutOverflow();
      const observer = new MutationObserver(() => undefined);
      observer.observe(fixture.row, { childList: true });
      observer.observe(fixture.items, { childList: true });
      fixture.bar.layoutOverflow();
      // A moved facet would close a panel open inside it.
      expect(observer.takeRecords()).toEqual([]);
      observer.disconnect();
    }
  });

  it("marks the menu only while it holds an applied facet", () => {
    const fixture = mountOverflow({ applied: ["f3"] });
    fixture.setRowWidth(1000);
    fixture.bar.layoutOverflow();
    expect(overflowMark(fixture)).toEqual({ shown: false, label: "More filters" });
    fixture.setRowWidth(300);
    fixture.bar.layoutOverflow();
    expect(overflowMark(fixture)).toEqual({ shown: false, label: "More filters" });
    // Nothing fits: the applied facet spills too, in declared order.
    fixture.setRowWidth(150);
    fixture.bar.layoutOverflow();
    expect(ids(fixture.items)).toEqual(["f1", "f2", "f3"]);
    expect(overflowMark(fixture)).toEqual({
      shown: true,
      label: "More filters, some applied",
    });
    fixture.setRowWidth(1000);
    fixture.bar.layoutOverflow();
    expect(overflowMark(fixture)).toEqual({ shown: false, label: "More filters" });
  });
});

// ── The Presets panel's host ───────────────────────────────────────────

function mountHost(facets = "", filter = ""): {
  bar: HTMLElement;
  panel: HTMLElement;
  navigate: ReturnType<typeof vi.fn>;
} {
  const filterAttribute = filter ? ` filter='${filter}'` : "";
  document.body.innerHTML = `
    <quick-filter-bar apply-url="${LIST_URL}" per-page="50"${filterAttribute}>
      <form>${facets}<div id="panel"></div></form>
    </quick-filter-bar>`;
  const bar = document.querySelector("quick-filter-bar") as HTMLElement;
  const navigate = vi.fn();
  (bar as unknown as { navigate: (url: string) => void }).navigate = navigate;
  return { bar, panel: bar.querySelector<HTMLElement>("#panel")!, navigate };
}

function load(panel: HTMLElement, preset: PresetState): void {
  panel.dispatchEvent(new CustomEvent(PRESET_LOAD_EVENT, { bubbles: true, detail: preset }));
}

function requestSave(panel: HTMLElement): PresetSaveAnswer | null {
  const request = new PresetSaveRequest();
  panel.dispatchEvent(new CustomEvent(PRESET_SAVE_EVENT, { bubbles: true, detail: request }));
  return request.answer;
}

describe("quick-filter-bar hosts the Presets panel", () => {
  it("a load navigates with the preset's filter, sort and per_page", () => {
    // The URL state differs, to prove the preset's own wins.
    window.history.replaceState({}, "", "/tracker/session/list?sort=name&per_page=25");
    const { panel, navigate } = mountHost();
    const filter = { game: { value: [{ id: "1", label: "X" }], modifier: "INCLUDES" } };
    load(panel, { filter, sort: "-playtime", perPage: "100" });
    expect(navigate).toHaveBeenCalledWith(applyUrl(LIST_URL, filter, "-playtime", "100"));
  });

  it("an empty preset navigates to the bare list URL", () => {
    window.history.replaceState({}, "", "/tracker/session/list?sort=name");
    const { panel, navigate } = mountHost();
    load(panel, { filter: {}, sort: "", perPage: "" });
    expect(navigate).toHaveBeenCalledWith(LIST_URL);
  });

  it("a save states the facets as they stand, applied or not", () => {
    window.history.replaceState({}, "", "/tracker/session/list?sort=-day");
    const { panel, navigate } = mountHost(setFacet("game", includePill("1", "X")));
    expect(requestSave(panel)).toEqual({
      kind: "state",
      state: {
        filter: {
          game: { value: [{ id: "1", label: "X" }], excludes: [], modifier: "INCLUDES" },
        },
        sort: "-day",
        perPage: "50",
      },
    });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("the degraded bar saves the page's filter", () => {
    const stated = { OR: [{ note: { value: "x", modifier: "INCLUDES" } }] };
    const { panel } = mountHost("", JSON.stringify(stated));
    expect(requestSave(panel)).toMatchObject({ kind: "state", state: { filter: stated } });
  });

  it("an unreadable page filter refuses the save rather than saving everything", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { panel } = mountHost("", "{not json");
    expect(requestSave(panel)?.kind).toBe("refused");
  });

  it("the degraded bar mounts with no row and reports nothing", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { panel } = mountHost("", JSON.stringify({ OR: [] }));
    expect(panel).toBeTruthy();
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("a load is marked handled", () => {
    const { panel } = mountHost();
    const event = new CustomEvent(PRESET_LOAD_EVENT, {
      bubbles: true,
      cancelable: true,
      detail: { filter: {}, sort: "", perPage: "" },
    });
    panel.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("the save request stops at the bar", () => {
    const { panel } = mountHost();
    const outer = vi.fn();
    document.body.addEventListener(PRESET_SAVE_EVENT, outer);
    requestSave(panel);
    document.body.removeEventListener(PRESET_SAVE_EVENT, outer);
    expect(outer).not.toHaveBeenCalled();
  });
});

// ── Overflow reserve counts furniture between host and group ────────

it("reserves width for furniture after the overflow host", () => {
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

  // Without #picker 300px would fit one 100px facet (reserve 120); with the
  // 120px #picker as furniture the reserve grows to 240 → nothing fits.
  rowWidth = 300;
  bar.layoutOverflow();
  const items = bar.querySelector<HTMLElement>("[data-quick-overflow-items]")!;
  expect(items.children.length).toBe(2);
  rowWidth = 1000;
  bar.layoutOverflow();
  expect(items.children.length).toBe(0);
});
