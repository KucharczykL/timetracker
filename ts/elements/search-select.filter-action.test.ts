// @vitest-environment jsdom
// Filter-mode +/− action buttons (issue #302): include/exclude add a pill
// inline, and the action name is validated to a pill kind so a non-pill action
// (e.g. "delete") can never clone an exclude pill.
import { describe, it, expect, beforeEach } from "vitest";
import "./search-select.js"; // side effect: customElements.define
import type { SearchSelectChangeDetail, SearchSelectActionDetail } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

// A filter-mode value row with the +/− buttons FilterSelect renders. `action`
// overrides the exclude button's action name for the hazard test.
function valueRow(value: string, label: string, action = "exclude"): string {
  return `
    <div data-search-select-option data-value="${value}" data-label="${label}" role="option" aria-selected="false">
      <span data-search-select-label>${label}</span>
      <span>
        <button type="button" data-search-select-action="include">+</button>
        <button type="button" data-search-select-action="${action}">−</button>
      </span>
    </div>`;
}

function mountFilter(rows: string): HTMLElement {
  const host = document.createElement("search-select");
  host.setAttribute("name", "platform");
  host.setAttribute("multi", "true");
  host.setAttribute("filter-mode", "true");
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search role="combobox" aria-expanded="false" aria-autocomplete="list" />
    <div data-search-select-options class="hidden" role="listbox" aria-multiselectable="true" tabindex="-1">${rows}</div>
    <template data-search-select-template="pill-include"><span data-pill data-search-select-type="include"><span data-search-select-label></span><button data-pill-remove></button></span></template>
    <template data-search-select-template="pill-exclude"><span data-pill data-search-select-type="exclude"><span data-search-select-label></span><button data-pill-remove></button></span></template>
  `;
  document.body.appendChild(host);
  return host;
}

const searchOf = (host: HTMLElement): HTMLInputElement =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
const pillsOf = (host: HTMLElement): HTMLElement[] =>
  Array.from(host.querySelectorAll<HTMLElement>("[data-search-select-pills] [data-pill]"));
const buttonOf = (host: HTMLElement, value: string, action: string): HTMLElement =>
  host.querySelector<HTMLElement>(
    `[data-search-select-option][data-value="${value}"] [data-search-select-action="${action}"]`
  )!;

describe("<search-select> filter +/− action buttons (#302)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("include button adds an include pill, one change event, no action event", () => {
    const host = mountFilter(valueRow("1", "PC"));
    let changes = 0;
    let actions = 0;
    host.addEventListener("search-select:change", () => (changes += 1));
    host.addEventListener("search-select:action", () => (actions += 1));

    buttonOf(host, "1", "include").click();

    const pills = pillsOf(host);
    expect(pills).toHaveLength(1);
    expect(pills[0].getAttribute("data-search-select-type")).toBe("include");
    expect(changes).toBe(1);
    expect(actions).toBe(0);
  });

  it("exclude button adds an exclude pill", () => {
    const host = mountFilter(valueRow("1", "PC"));
    buttonOf(host, "1", "exclude").click();

    const pills = pillsOf(host);
    expect(pills).toHaveLength(1);
    expect(pills[0].getAttribute("data-search-select-type")).toBe("exclude");
  });

  it("a non-pill action (delete) on a value row adds no pill — the #302 hazard", () => {
    const host = mountFilter(valueRow("1", "PC", "delete"));
    buttonOf(host, "1", "delete").click();

    expect(pillsOf(host)).toHaveLength(0);
    expect(host.querySelector('[data-search-select-type="exclude"]')).toBeNull();
  });

  it("a bare row click adds an include pill", () => {
    const host = mountFilter(valueRow("1", "PC"));
    host.querySelector<HTMLElement>("[data-search-select-label]")!.click();

    const pills = pillsOf(host);
    expect(pills).toHaveLength(1);
    expect(pills[0].getAttribute("data-search-select-type")).toBe("include");
  });

  it("Enter on the highlighted row adds an include pill", () => {
    const host = mountFilter(valueRow("1", "PC"));
    const search = searchOf(host);
    search.dispatchEvent(new Event("focus")); // auto-highlights the first value row
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

    const pills = pillsOf(host);
    expect(pills).toHaveLength(1);
    expect(pills[0].getAttribute("data-search-select-type")).toBe("include");
  });
});
