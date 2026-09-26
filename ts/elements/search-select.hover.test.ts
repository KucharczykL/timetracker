// @vitest-environment jsdom
// The mouse moves the one highlight, and a hover never scrolls.
import { describe, it, expect, vi, beforeEach } from "vitest";
import "./search-select.js"; // side effect: customElements.define

const scrollIntoView = vi.fn();
Element.prototype.scrollIntoView = scrollIntoView;

function mount(): { host: HTMLElement; rows: HTMLElement[] } {
  document.body.replaceChildren();
  const host = document.createElement("search-select");
  host.setAttribute("name", "device");
  host.setAttribute("multi", "false");
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options hidden>
      <div data-search-select-option role="option" aria-selected="false" data-value="1" data-label="Deck"><span data-search-select-label>Deck</span></div>
      <div data-search-select-option role="option" aria-selected="false" data-value="2" data-label="Switch"><span data-search-select-label>Switch</span></div>
      <div data-search-select-option role="option" aria-selected="false" data-value="3" data-label="PC"><span data-search-select-label>PC</span></div>
    </div>
  `;
  document.body.appendChild(host);
  return {
    host,
    rows: Array.from(host.querySelectorAll<HTMLElement>("[data-search-select-option]")),
  };
}

function move(target: Element, x: number, y: number): void {
  const event = new MouseEvent("pointermove", { bubbles: true, clientX: x, clientY: y });
  Object.defineProperty(event, "pointerType", { value: "mouse" });
  target.dispatchEvent(event);
}

const highlighted = (host: HTMLElement): HTMLElement[] =>
  Array.from(host.querySelectorAll<HTMLElement>("[data-search-select-highlighted]"));

describe("picker pointer follow", () => {
  beforeEach(() => scrollIntoView.mockClear());

  it("a mouse move highlights the row under it and clears the last", () => {
    const { host, rows } = mount();
    move(rows[0].querySelector("span")!, 5, 5);
    expect(highlighted(host)).toEqual([rows[0]]);
    move(rows[1], 5, 40);
    expect(highlighted(host)).toEqual([rows[1]]);
    const search = host.querySelector("[data-search-select-search]")!;
    expect(search.getAttribute("aria-activedescendant")).toBe(rows[1].id);
  });

  it("a hover never scrolls", () => {
    const { rows } = mount();
    move(rows[2], 5, 80);
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("a still cursor keeps the keyboard's row", () => {
    const { host, rows } = mount();
    const search = host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
    move(rows[0], 5, 5);
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expect(highlighted(host)).toEqual([rows[1]]);
    expect(scrollIntoView).toHaveBeenCalled();
    // The list scrolled under the cursor: same position, new row.
    move(rows[2], 5, 5);
    expect(highlighted(host)).toEqual([rows[1]]);
  });
});
