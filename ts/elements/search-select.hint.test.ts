// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { SearchSelectChangeDetail } from "./search-select.js";
import "./search-select.js";
import { hosted } from "../test-setup/search-select-host.js";

Element.prototype.scrollIntoView = () => {};

const ROW_TEMPLATE =
  '<template data-search-select-template="row">' +
  '<div data-search-select-option="" role="option">' +
  '<span data-search-select-label=""></span>' +
  '<span data-search-select-hint="" hidden></span>' +
  "</div></template>";

function answering(rows: object[]) {
  return vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(rows) } as Response)
  );
}

function mountPicker(): HTMLElement {
  document.body.replaceChildren();
  const picker = document.createElement("search-select");
  picker.setAttribute("name", "device");
  picker.setAttribute("search-url", "/api/devices/search");
  picker.setAttribute("prefetch", "10");
  picker.innerHTML = `
    ${ROW_TEMPLATE}
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options>
      <div data-search-select-no-results class="hidden">No results</div>
    </div>
  `;
  document.body.appendChild(hosted(picker));
  return picker;
}

async function openRows(picker: HTMLElement): Promise<HTMLElement[]> {
  picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();
  await vi.waitFor(() =>
    expect(picker.querySelectorAll("[data-search-select-options] [data-value]").length).toBe(2)
  );
  return [...picker.querySelectorAll<HTMLElement>("[data-search-select-options] [data-value]")];
}

describe("<search-select> hints", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  it("shows a hint after the label and hides an empty one", async () => {
    vi.stubGlobal(
      "fetch",
      answering([
        { value: "a", label: "Deck", data: {}, hint: null },
        { value: "b", label: "Switch", data: {}, hint: "Sold" },
      ])
    );
    const [held, sold] = await openRows(mountPicker());

    const heldHint = held.querySelector<HTMLElement>("[data-search-select-hint]")!;
    const soldHint = sold.querySelector<HTMLElement>("[data-search-select-hint]")!;
    expect(heldHint.hidden).toBe(true);
    expect(held.hasAttribute("data-hint")).toBe(false);
    expect([soldHint.hidden, soldHint.textContent]).toEqual([false, "Sold"]);
    expect(sold.getAttribute("data-label")).toBe("Switch");
  });

  it("keeps the hint out of the option's data when read back from the row", async () => {
    vi.stubGlobal("fetch", answering([]));
    const picker = mountPicker();
    const options = picker.querySelector("[data-search-select-options]")!;
    options.insertAdjacentHTML(
      "beforeend",
      '<div data-search-select-option="" data-value="b" data-label="Switch" ' +
        'data-hint="Sold" data-kind="device" role="option">' +
        '<span data-search-select-label="">Switch</span>' +
        '<span data-search-select-hint="">Sold</span></div>'
    );
    let picked: SearchSelectChangeDetail | null = null;
    picker.addEventListener("search-select:change", event => {
      picked = (event as CustomEvent<SearchSelectChangeDetail>).detail;
    });

    options.querySelector<HTMLElement>('[data-value="b"]')!.click();

    const last = picked!.last!;
    expect([last.value, last.label, last.hint]).toEqual(["b", "Switch", "Sold"]);
    expect(last.data.kind).toBe("device");
    expect("hint" in last.data).toBe(false);
  });
});
