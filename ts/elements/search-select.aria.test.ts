// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import "./search-select.js"; // side effect: customElements.define

Element.prototype.scrollIntoView = () => {};

// The ARIA combobox wiring (issue #154): initWidget assigns the listbox and
// option ids, points aria-controls at the panel, and mirrors the keyboard
// highlight into aria-activedescendant + aria-selected. The static roles come
// from the server markup, reproduced here.
function mountSingle(name: string): HTMLElement {
  const host = document.createElement("search-select");
  host.setAttribute("name", name);
  host.setAttribute("multi", "false");
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search role="combobox" aria-expanded="false" aria-autocomplete="list" />
    <div data-search-select-options class="hidden" role="listbox" tabindex="-1">
      <div data-search-select-option data-value="1" data-label="One" role="option" aria-selected="false"></div>
      <div data-search-select-option data-value="2" data-label="Two" role="option" aria-selected="false"></div>
    </div>
  `;
  document.body.appendChild(host); // connectedCallback → initWidget
  return host;
}

// A filter-mode widget: aria-multiselectable listbox with a pinned modifier
// row, two value rows, and the pill templates the JS clones on commit.
function mountFilter(pillsHtml = ""): HTMLElement {
  const host = document.createElement("search-select");
  host.setAttribute("name", "platform");
  host.setAttribute("multi", "true");
  host.setAttribute("filter-mode", "true");
  host.innerHTML = `
    <div data-search-select-pills>${pillsHtml}</div>
    <input data-search-select-search role="combobox" aria-expanded="false" aria-autocomplete="list" />
    <div data-search-select-options class="hidden" role="listbox" aria-multiselectable="true" tabindex="-1">
      <div data-search-select-modifier-option="IS_NULL" data-label="(None)" role="option" aria-selected="false"></div>
      <div data-search-select-option data-value="1" data-label="One" role="option" aria-selected="false"></div>
      <div data-search-select-option data-value="2" data-label="Two" role="option" aria-selected="false"></div>
    </div>
    <template data-search-select-template="pill-include"><span data-pill data-search-select-type="include"><span data-search-select-label></span><button data-pill-remove></button></span></template>
    <template data-search-select-template="pill-exclude"><span data-pill data-search-select-type="exclude"><span data-search-select-label></span><button data-pill-remove></button></span></template>
    <template data-search-select-template="pill-modifier"><span data-pill><span data-search-select-label></span><button data-pill-remove></button></span></template>
  `;
  document.body.appendChild(host);
  return host;
}

const searchOf = (host: HTMLElement): HTMLInputElement =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
const panelOf = (host: HTMLElement): HTMLElement =>
  host.querySelector<HTMLElement>("[data-search-select-options]")!;
const rowsOf = (host: HTMLElement): HTMLElement[] =>
  Array.from(host.querySelectorAll<HTMLElement>("[data-search-select-option]"));

describe("<search-select> ARIA combobox wiring (#154)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("assigns a listbox id and points aria-controls at it on init", () => {
    const host = mountSingle("games");
    const panel = panelOf(host);
    expect(panel.id).toMatch(/^search-select-listbox-\d+$/);
    expect(searchOf(host).getAttribute("aria-controls")).toBe(panel.id);
  });

  it("gives each widget a distinct listbox id", () => {
    const first = mountSingle("games");
    const second = mountSingle("platforms");
    expect(panelOf(first).id).not.toBe(panelOf(second).id);
  });

  it("syncs aria-expanded and aria-activedescendant with focus + highlight", () => {
    const host = mountSingle("games");
    const search = searchOf(host);
    const [rowOne, rowTwo] = rowsOf(host);

    search.dispatchEvent(new Event("focus"));

    // Panel open, first option auto-highlighted.
    expect(search.getAttribute("aria-expanded")).toBe("true");
    expect(rowOne.id).toBeTruthy();
    expect(search.getAttribute("aria-activedescendant")).toBe(rowOne.id);
    expect(rowOne.getAttribute("aria-selected")).toBe("true");
    expect(rowTwo.getAttribute("aria-selected")).toBe("false");

    // ArrowDown moves the highlight — activedescendant + selection follow.
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expect(search.getAttribute("aria-activedescendant")).toBe(rowTwo.id);
    expect(rowOne.getAttribute("aria-selected")).toBe("false");
    expect(rowTwo.getAttribute("aria-selected")).toBe("true");
  });

  it("collapses and drops the active option on Escape", () => {
    const host = mountSingle("games");
    const search = searchOf(host);

    search.dispatchEvent(new Event("focus"));
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

    expect(search.getAttribute("aria-expanded")).toBe("false");
    expect(search.hasAttribute("aria-activedescendant")).toBe(false);
    for (const row of rowsOf(host)) {
      expect(row.getAttribute("aria-selected")).toBe("false");
    }
  });

  it("collapses on an outside mousedown via the shared dismiss (#303)", () => {
    // The bespoke document-click listener was replaced by bindPopupDismiss,
    // which dismisses on an outside mousedown (and Escape). Focus-to-open is
    // unchanged; this guards that the panel still closes on an outside press.
    const host = mountSingle("games");
    const search = searchOf(host);

    search.dispatchEvent(new Event("focus"));
    expect(panelOf(host).classList.contains("hidden")).toBe(false);

    document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(panelOf(host).classList.contains("hidden")).toBe(true);
    expect(search.getAttribute("aria-expanded")).toBe("false");
  });

  it("clears the highlight when a single-select option is click-committed", () => {
    const host = mountSingle("games");
    const search = searchOf(host);
    const [rowOne, rowTwo] = rowsOf(host);

    search.dispatchEvent(new Event("focus")); // auto-highlights rowOne
    expect(rowOne.getAttribute("aria-selected")).toBe("true");
    rowTwo.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(search.getAttribute("aria-expanded")).toBe("false");
    expect(search.hasAttribute("aria-activedescendant")).toBe(false);
    expect(host.querySelector("[data-search-select-highlighted]")).toBeNull();
    for (const row of rowsOf(host)) {
      expect(row.getAttribute("aria-selected")).toBe("false");
    }
  });
});

describe("<search-select> filter-mode ARIA membership (#154 review)", () => {
  beforeEach(() => document.body.replaceChildren());

  const valueRowsOf = (host: HTMLElement): HTMLElement[] =>
    Array.from(host.querySelectorAll<HTMLElement>("[data-search-select-option]"));
  const modifierRowOf = (host: HTMLElement): HTMLElement =>
    host.querySelector<HTMLElement>("[data-search-select-modifier-option]")!;

  it("marks rows with existing pills as members at init", () => {
    const host = mountFilter(
      '<span data-pill data-value="1" data-label="One"><button data-pill-remove></button></span>'
    );
    const [rowOne, rowTwo] = valueRowsOf(host);
    expect(rowOne.getAttribute("aria-selected")).toBe("true");
    expect(rowTwo.getAttribute("aria-selected")).toBe("false");
  });

  it("keeps aria-selected as membership while the highlight moves", () => {
    const host = mountFilter();
    const search = searchOf(host);
    const [rowOne] = valueRowsOf(host);

    search.dispatchEvent(new Event("focus"));

    // The auto-highlight prefers the first VALUE row over the pinned modifier
    // row, drives aria-activedescendant, and does NOT claim aria-selected.
    expect(search.getAttribute("aria-activedescendant")).toBe(rowOne.id);
    expect(rowOne.getAttribute("aria-selected")).toBe("false");
  });

  it("marks a row as member once its include pill is added", () => {
    const host = mountFilter();
    const search = searchOf(host);
    const [rowOne, rowTwo] = valueRowsOf(host);

    search.dispatchEvent(new Event("focus"));
    rowOne.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(host.querySelector("[data-pill]")).not.toBeNull();
    expect(rowOne.getAttribute("aria-selected")).toBe("true");
    expect(rowTwo.getAttribute("aria-selected")).toBe("false");
  });

  it("reaches the pinned modifier row by keyboard and commits it with Enter", () => {
    const host = mountFilter();
    const search = searchOf(host);
    const modifierRow = modifierRowOf(host);

    search.dispatchEvent(new Event("focus")); // highlights the first value row
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }));
    expect(search.getAttribute("aria-activedescendant")).toBe(modifierRow.id);

    search.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

    expect(host.getAttribute("data-modifier")).toBe("IS_NULL");
    expect(modifierRow.getAttribute("aria-selected")).toBe("true");
    expect(search.getAttribute("aria-expanded")).toBe("false");
    expect(search.hasAttribute("aria-activedescendant")).toBe(false);
  });
});
