// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { getBehavior } from "../dropdown-behaviors.js";
import "./column-picker.js";

describe("column-picker sheetFocus", () => {
  it("focuses the first checkbox", () => {
    document.body.innerHTML = `
      <div data-menu id="menu">
        <input type="checkbox" id="first">
        <input type="checkbox" id="second">
        <button type="submit">Apply</button>
      </div>`;
    const menu = document.querySelector<HTMLElement>("#menu")!;
    expect(getBehavior("column-picker")?.sheetFocus?.(menu)?.id).toBe("first");
  });
});
