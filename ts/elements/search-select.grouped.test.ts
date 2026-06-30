// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import "./search-select.js"; // side-effect: customElements.define("search-select", …)

// jsdom does not implement scrollIntoView, which the widget calls when it
// auto-highlights an option on focus/keystroke. Stub it so the focus path runs.
Element.prototype.scrollIntoView = () => {};

// Minimal grouped single-select panel mirroring what SearchSelect(option_groups=)
// renders: a search box, a pills div, and an options panel of header rows +
// option rows. Only the data hooks the JS reads are present (issue #191 grouping).
function option(label: string): string {
  return `<div data-search-select-option data-value="${label}" data-label="${label}">${label}</div>`;
}

function header(label: string): string {
  return `<div data-search-select-group-header role="presentation">${label}</div>`;
}

function mount(): HTMLElement {
  document.body.replaceChildren();
  const host = document.createElement("search-select");
  host.setAttribute("name", "field-picker");
  host.setAttribute("multi", "false");
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options>
      ${header("Text")}${option("Name")}${option("Sort name")}
      ${header("Number")}${option("Year released")}
      <div data-search-select-no-results class="hidden">No results</div>
    </div>
  `;
  document.body.appendChild(host); // connectedCallback → initWidget
  return host;
}

function type(host: HTMLElement, query: string): void {
  const search = host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
  search.focus();
  search.value = query;
  search.dispatchEvent(new Event("input", { bubbles: true }));
}

function headers(host: HTMLElement): HTMLElement[] {
  return [...host.querySelectorAll<HTMLElement>("[data-search-select-group-header]")];
}

function visible(element: HTMLElement): boolean {
  return element.style.display !== "none";
}

describe("grouped <search-select> header hiding (#191)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("shows every header for an empty query", () => {
    const host = mount();
    type(host, "");
    expect(headers(host).map(visible)).toEqual([true, true]);
  });

  it("hides a header whose whole group is filtered out", () => {
    const host = mount();
    type(host, "year"); // matches only the Number group's option
    const [text, number] = headers(host);
    expect(visible(text)).toBe(false);
    expect(visible(number)).toBe(true);
  });

  it("keeps a header visible while any of its options match", () => {
    const host = mount();
    type(host, "name"); // "Name" + "Sort name" → Text group only
    const [text, number] = headers(host);
    expect(visible(text)).toBe(true);
    expect(visible(number)).toBe(false);
  });

  it("hides all headers when nothing matches", () => {
    const host = mount();
    type(host, "zzz");
    expect(headers(host).map(visible)).toEqual([false, false]);
  });
});
