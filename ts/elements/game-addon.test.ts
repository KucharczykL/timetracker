// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";

import "./game-addon.js";

function render(kind: string, parent = ""): {
  select: HTMLSelectElement;
  row: HTMLElement;
  clear: ReturnType<typeof vi.fn>;
} {
  document.body.innerHTML = `
    <form>
      <div data-field-row="kind">
        <select name="kind">
          <option value="main">Main game</option>
          <option value="dlc">DLC</option>
        </select>
      </div>
      <div data-field-row="parent">
        <input type="hidden" name="parent" value="${parent}">
        <button type="button" data-search-select-clear>×</button>
      </div>
      <game-addon kind-field="kind" parent-field="parent" hidden></game-addon>
    </form>`;
  const select = document.querySelector<HTMLSelectElement>("select")!;
  const row = document.querySelector<HTMLElement>('[data-field-row="parent"]')!;
  const clear = vi.fn();
  row.querySelector("button")!.addEventListener("click", clear);
  select.value = kind;
  document.querySelector("form")!.append(document.querySelector("game-addon")!);
  return { select, row, clear };
}

beforeEach(() => {
  document.body.innerHTML = "";
});

it("hides the parent row while the kind is main", () => {
  const { row } = render("main");
  expect(row.hidden).toBe(true);
});

it("shows the parent row for an add-on kind", () => {
  const { row } = render("dlc", "parent-key");
  expect(row.hidden).toBe(false);
});

it("shows and hides as the kind changes, clearing a held parent", () => {
  const { select, row, clear } = render("dlc", "parent-key");

  select.value = "main";
  select.dispatchEvent(new Event("change"));
  expect(row.hidden).toBe(true);
  expect(clear).toHaveBeenCalledTimes(1);

  select.value = "dlc";
  select.dispatchEvent(new Event("change"));
  expect(row.hidden).toBe(false);
});

it("keeps a parent posted beside main in view", () => {
  const { row } = render("main", "parent-key");
  expect(row.hidden).toBe(false);
});
