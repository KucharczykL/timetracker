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
});
