// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./game-addon.js";

interface Rendered {
  select: HTMLSelectElement;
  row: HTMLElement;
  input: HTMLInputElement;
  clear: ReturnType<typeof vi.fn>;
}

function render(
  kind: string,
  parent = "",
  { withSelect = true, withClear = true } = {}
): Rendered {
  document.body.innerHTML = `
    <form>
      <div data-field-row="kind">
        ${
          withSelect
            ? `<select name="kind">
                 <option value="main">Main game</option>
                 <option value="dlc">DLC</option>
               </select>`
            : ""
        }
      </div>
      <div data-field-row="parent">
        <input type="hidden" name="parent" value="${parent}">
        ${withClear ? "<button type='button' data-search-select-clear>×</button>" : ""}
      </div>
    </form>`;
  const select = document.querySelector<HTMLSelectElement>("select")!;
  const row = document.querySelector<HTMLElement>('[data-field-row="parent"]')!;
  const input = row.querySelector<HTMLInputElement>("input")!;
  const clear = vi.fn();
  row.querySelector("button")?.addEventListener("click", clear);
  if (select) select.value = kind;
  //: Appended last: connects after the select.
  const element = document.createElement("game-addon");
  element.setAttribute("kind-field", "kind");
  element.setAttribute("parent-field", "parent");
  document.querySelector("form")!.append(element);
  return { select, row, input, clear };
}

function choose(select: HTMLSelectElement, kind: string): void {
  select.value = kind;
  select.dispatchEvent(new Event("change"));
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("hides the parent row while the kind is main", () => {
  expect(render("main").row.hidden).toBe(true);
});

it("shows the parent row for an add-on kind", () => {
  expect(render("dlc", "parent-key").row.hidden).toBe(false);
});

it("shows and hides as the kind changes, clearing a held parent", () => {
  const { select, row, clear } = render("dlc", "parent-key");

  choose(select, "main");
  expect(row.hidden).toBe(true);
  expect(clear).toHaveBeenCalledTimes(1);

  choose(select, "dlc");
  expect(row.hidden).toBe(false);
});

it("presses no clear when no parent is held", () => {
  const { select, clear } = render("dlc");

  choose(select, "main");

  expect(clear).not.toHaveBeenCalled();
});

it("keeps a parent posted beside main in view, then clears it", () => {
  const { select, row, clear } = render("main", "parent-key");
  expect(row.hidden).toBe(false);

  choose(select, "dlc");
  choose(select, "main");

  expect(row.hidden).toBe(true);
  expect(clear).toHaveBeenCalledTimes(1);
});

it("empties the value itself when the picker has no clear", () => {
  const { select, input } = render("dlc", "parent-key", { withClear: false });

  choose(select, "main");

  expect(input.value).toBe("");
  expect(console.error).toHaveBeenCalled();
});

it("leaves the parent row visible and says so without a kind select", () => {
  const { row } = render("main", "", { withSelect: false });

  expect(row.hidden).toBe(false);
  expect(console.error).toHaveBeenCalled();
});
