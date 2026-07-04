// @vitest-environment jsdom
// The combobox dropdown behavior (issue #297): a <drop-down> whose panel hosts
// a search-select. On open it refetches + focuses the search input (the #94
// dropdown:show seam); attachMenu's item navigation is inert (match-nothing
// itemSelector + the empty-items keydown guard), so caret keys work inside the
// input while Escape still closes; Enter never implicitly submits a form.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "../drop-down.js"; // registers <drop-down> + the built-in behaviors
import "../search-select.js";

Element.prototype.scrollIntoView = () => {};

interface DropdownHost extends HTMLElement {
  close(): void;
}

function mountComboboxDropdown(): DropdownHost {
  vi.stubGlobal("fetch", () =>
    Promise.resolve({ json: () => Promise.resolve([]) }),
  );
  const host = document.createElement("drop-down") as DropdownHost;
  host.setAttribute("behavior", "combobox");
  host.setAttribute("placement", "bottom-start");
  host.setAttribute("submenu", "false");
  host.innerHTML = `
    <button data-toggle aria-expanded="false" type="button">Load preset</button>
    <div data-menu hidden role="dialog" aria-label="Load preset">
      <search-select name="preset" multi="false" always-visible="true"
                     search-url="/api/presets/?mode=games" prefetch="100">
        <div data-search-select-pills></div>
        <input data-search-select-search />
        <div data-search-select-options role="listbox"></div>
      </search-select>
    </div>
  `;
  document.body.appendChild(host);
  return host;
}

const toggleOf = (host: HTMLElement): HTMLButtonElement =>
  host.querySelector<HTMLButtonElement>("[data-toggle]")!;
const menuOf = (host: HTMLElement): HTMLElement =>
  host.querySelector<HTMLElement>("[data-menu]")!;
const inputOf = (host: HTMLElement): HTMLInputElement =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;

const keydown = (key: string): KeyboardEvent =>
  new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });

describe("combobox dropdown behavior (#297)", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  it("open refetches the widget and focuses the search input", () => {
    const host = mountComboboxDropdown();
    const widget = host.querySelector("search-select") as HTMLElement & {
      refetchOptions(): void;
    };
    const refetch = vi.spyOn(widget, "refetchOptions");

    toggleOf(host).click();

    expect(menuOf(host).hidden).toBe(false);
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(inputOf(host));
    expect(toggleOf(host).getAttribute("aria-expanded")).toBe("true");
  });

  it("caret keys inside the input are not swallowed by the itemless menu", () => {
    const host = mountComboboxDropdown();
    toggleOf(host).click();

    for (const key of ["Home", "End", "ArrowDown", "ArrowUp"]) {
      const event = keydown(key);
      inputOf(host).dispatchEvent(event);
      // ArrowDown/Up may be consumed by the widget itself when options exist;
      // with an empty panel nothing may preventDefault Home/End.
      if (key === "Home" || key === "End") {
        expect(event.defaultPrevented).toBe(false);
      }
    }
  });

  it("Enter in the search input is always defaultPrevented (no form submit)", () => {
    const host = mountComboboxDropdown();
    toggleOf(host).click();

    const event = keydown("Enter");
    inputOf(host).dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("Escape inside the input closes the dropdown and refocuses the toggle", () => {
    const host = mountComboboxDropdown();
    toggleOf(host).click();
    expect(menuOf(host).hidden).toBe(false);

    inputOf(host).dispatchEvent(keydown("Escape"));

    expect(menuOf(host).hidden).toBe(true);
    expect(document.activeElement).toBe(toggleOf(host));
  });

  it("close() closes programmatically and is a pre-connect no-op", () => {
    const host = mountComboboxDropdown();
    toggleOf(host).click();
    host.close();
    expect(menuOf(host).hidden).toBe(true);

    const detached = document.createElement("drop-down") as DropdownHost;
    expect(() => detached.close()).not.toThrow();
  });
});
