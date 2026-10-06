// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./game-addon.js";

interface Rendered {
  picker: HTMLElement;
  row: HTMLElement;
  input: HTMLInputElement;
  clear: ReturnType<typeof vi.fn>;
}

function render(
  kind: string,
  parent = "",
  { withPicker = true, withClear = true } = {}
): Rendered {
  document.body.innerHTML = `
    <form>
      <div data-field-row="kind">
        ${
          withPicker
            ? `<search-select name="kind">
                 <div data-search-select-pills>
                   <input type="hidden" name="kind" value="${kind}">
                 </div>
               </search-select>`
            : ""
        }
      </div>
      <div data-field-row="parent">
        <search-select name="parent">
          <input type="hidden" name="parent" value="${parent}">
          ${withClear ? "<button type='button' data-search-select-clear>×</button>" : ""}
        </search-select>
      </div>
    </form>`;
  const picker = document.querySelector<HTMLElement>('search-select[name="kind"]')!;
  const row = document.querySelector<HTMLElement>('[data-field-row="parent"]')!;
  const input = row.querySelector<HTMLInputElement>("input")!;
  const clear = vi.fn();
  row.querySelector("button")?.addEventListener("click", clear);
  //: Appended last: connects after the picker.
  const element = document.createElement("game-addon");
  element.setAttribute("kind-field", "kind");
  element.setAttribute("parent-field", "parent");
  document.querySelector("form")!.append(element);
  return { picker, row, input, clear };
}

function change(picker: Element, values: string[]): void {
  picker.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: { name: "", values, last: null, none: false },
    })
  );
}

function choose(picker: HTMLElement, kind: string): void {
  change(picker, [kind]);
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
  const { picker, row, clear } = render("dlc", "parent-key");

  choose(picker, "main");
  expect(row.hidden).toBe(true);
  expect(clear).toHaveBeenCalledTimes(1);

  choose(picker, "dlc");
  expect(row.hidden).toBe(false);
});

it("presses no clear when no parent is held", () => {
  const { picker, clear } = render("dlc");

  choose(picker, "main");

  expect(clear).not.toHaveBeenCalled();
});

it("keeps a parent posted beside main in view, then clears it", () => {
  const { picker, row, clear } = render("main", "parent-key");
  expect(row.hidden).toBe(false);

  choose(picker, "dlc");
  choose(picker, "main");

  expect(row.hidden).toBe(true);
  expect(clear).toHaveBeenCalledTimes(1);
});

it("empties the value itself when the picker has no clear", () => {
  const { picker, input } = render("dlc", "parent-key", { withClear: false });

  choose(picker, "main");

  expect(input.value).toBe("");
  expect(console.error).toHaveBeenCalled();
});

it("keeps the parent while a keystroke drops the kind", () => {
  const { picker, row, clear } = render("dlc", "parent-key");

  change(picker, []);

  expect(row.hidden).toBe(false);
  expect(clear).not.toHaveBeenCalled();
});

it("ignores the parent picker's own changes", () => {
  const { row, clear } = render("dlc", "parent-key");

  change(row.querySelector("search-select")!, ["main"]);

  expect(row.hidden).toBe(false);
  expect(clear).not.toHaveBeenCalled();
});

it("leaves the parent row visible and says so without a kind picker", () => {
  const { row } = render("main", "", { withPicker: false });

  expect(row.hidden).toBe(false);
  expect(console.error).toHaveBeenCalled();
});
