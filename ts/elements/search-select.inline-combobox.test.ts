// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import "./search-select.js"; // side effect: customElements.define("search-select")
import "./drop-down.js"; // side effect: define <drop-down> + register inline-combobox

Element.prototype.scrollIntoView = () => {};

// The standalone form combobox rehosted in <drop-down behavior="inline-combobox">
// (issue #348): the panel is the drop-down's [data-menu], toggled via the `hidden`
// attribute by attachMenu; the <search-select> element is the [data-toggle] anchor;
// its own search input is the trigger (focus opens). This mirrors the markup
// SearchSelect(host_dropdown=True) emits.
function mount(): HTMLElement {
  const host = document.createElement("drop-down");
  host.setAttribute("behavior", "inline-combobox");
  host.setAttribute("placement", "bottom-start");
  host.setAttribute("submenu", "false");
  host.innerHTML = `
    <search-select name="game" multi="false" data-toggle>
      <div data-search-select-pills></div>
      <input data-search-select-search role="combobox" aria-expanded="false" aria-autocomplete="list" />
      <div data-search-select-options data-menu hidden role="listbox" tabindex="-1">
        <div data-search-select-option data-value="1" data-label="One" role="option" aria-selected="false"><span data-search-select-label>One</span></div>
        <div data-search-select-option data-value="2" data-label="Two" role="option" aria-selected="false"><span data-search-select-label>Two</span></div>
        <div data-search-select-no-results role="presentation" class="hidden">No results</div>
      </div>
    </search-select>`;
  document.body.appendChild(host); // connectedCallback → attachMenu + initWidget
  return host;
}

const widgetOf = (host: HTMLElement) =>
  host.querySelector<HTMLElement>("search-select")!;
const searchOf = (host: HTMLElement) =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
const panelOf = (host: HTMLElement) =>
  host.querySelector<HTMLElement>("[data-search-select-options]")!;
const rowsOf = (host: HTMLElement) =>
  Array.from(host.querySelectorAll<HTMLElement>("[data-search-select-option]"));

const isOpen = (host: HTMLElement) => !panelOf(host).hasAttribute("hidden");

describe("<search-select> hosted in <drop-down behavior=inline-combobox> (#348)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("starts closed (panel carries the hidden attribute)", () => {
    const host = mount();
    expect(isOpen(host)).toBe(false);
    expect(searchOf(host).getAttribute("aria-expanded")).toBe("false");
  });

  it("opens on input focus and sets aria-expanded on the input", () => {
    const host = mount();
    searchOf(host).focus();
    expect(isOpen(host)).toBe(true);
    expect(searchOf(host).getAttribute("aria-expanded")).toBe("true");
  });

  it("never writes aria-expanded on the <search-select> toggle element", () => {
    const host = mount();
    searchOf(host).focus();
    expect(widgetOf(host).hasAttribute("aria-expanded")).toBe(false);
  });

  it("commits an option click and closes", () => {
    const host = mount();
    searchOf(host).focus();
    const rowOne = rowsOf(host)[0];
    rowOne.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    rowOne.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(isOpen(host)).toBe(false);
    const hidden = widgetOf(host).querySelector<HTMLInputElement>(
      'input[type="hidden"][name="game"]',
    );
    expect(hidden?.value).toBe("1");
  });

  it("closes on Escape", () => {
    const host = mount();
    const search = searchOf(host);
    search.focus();
    expect(isOpen(host)).toBe(true);
    search.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    expect(isOpen(host)).toBe(false);
  });

  it("closes on an outside click", () => {
    const host = mount();
    searchOf(host).focus();
    expect(isOpen(host)).toBe(true);
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(isOpen(host)).toBe(false);
  });
});
