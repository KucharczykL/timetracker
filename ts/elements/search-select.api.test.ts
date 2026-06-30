// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { readFilterSelect } from "./search-select.js"; // also: customElements.define

Element.prototype.scrollIntoView = () => {};

interface SearchSelectLike extends HTMLElement {
  setSelected(value: string, label?: string): void;
}

function mountSingle(): SearchSelectLike {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as SearchSelectLike;
  host.setAttribute("name", "field-picker");
  host.setAttribute("multi", "false");
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options></div>
  `;
  document.body.appendChild(host); // connectedCallback → initWidget
  return host;
}

// A filter-mode pill, as FilterSelect renders one. Modifier pills carry
// data-search-select-modifier; exclude pills carry data-search-select-type.
function pill(attrs: string): string {
  return `<span data-pill ${attrs}><button data-pill-remove></button></span>`;
}

function mountFilter(pills: string): HTMLElement {
  document.body.replaceChildren();
  const host = document.createElement("search-select");
  host.setAttribute("name", "platform");
  host.setAttribute("filter-mode", "true");
  host.innerHTML = `
    <div data-search-select-pills>${pills}</div>
    <input data-search-select-search />
    <div data-search-select-options></div>
  `;
  document.body.appendChild(host);
  return host;
}

describe("<search-select> setSelected (#192)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("seeds a single-select value + label without firing change", () => {
    const host = mountSingle();
    let changes = 0;
    host.addEventListener("search-select:change", () => (changes += 1));

    host.setSelected("name", "Name");

    expect(host.querySelector<HTMLInputElement>("[data-search-select-search]")!.value).toBe("Name");
    const hidden = host.querySelector<HTMLInputElement>('[data-search-select-pills] input[type="hidden"]');
    expect(hidden?.value).toBe("name");
    expect(changes).toBe(0); // silent restore — no loop back into the consumer
  });

  it("falls back to the value as label when none is given", () => {
    const host = mountSingle();
    host.setSelected("year_released");
    expect(host.querySelector<HTMLInputElement>("[data-search-select-search]")!.value).toBe("year_released");
  });
});

describe("readFilterSelect (#192)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("reads include / exclude pills and the modifier", () => {
    const host = mountFilter(
      pill('data-value="1" data-label="PC"') +
        pill('data-value="2" data-label="Switch" data-search-select-type="exclude"') +
        pill('data-search-select-modifier="INCLUDES_ALL"'),
    );
    expect(readFilterSelect(host)).toEqual({
      included: [{ id: "1", label: "PC" }],
      excluded: [{ id: "2", label: "Switch" }],
      modifier: "INCLUDES_ALL",
    });
  });

  it("returns empty arrays + blank modifier for no pills", () => {
    expect(readFilterSelect(mountFilter(""))).toEqual({ included: [], excluded: [], modifier: "" });
  });
});
