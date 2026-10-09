// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import type { DropdownElement } from "../drop-down.js";
import "../drop-down.js";
import { SHEET_ATTRIBUTES, SHEET_HOST_VALUE } from "../../generated/sheet-attributes.js";
import { menuSheetFocus } from "./menu.js";

afterEach(() => {
  document.body.innerHTML = "";
});

const panel = (inner: string): HTMLElement => {
  document.body.innerHTML = `<div data-menu id="menu">${inner}</div>`;
  return document.querySelector<HTMLElement>("#menu")!;
};

describe("menuSheetFocus", () => {
  it("focuses the first enabled item of its own menu", () => {
    const menu = panel(`
      <button role="menuitem" id="off" disabled>Off</button>
      <button role="menuitem" id="ariaOff" aria-disabled="true">Also off</button>
      <button role="menuitem" id="first">First</button>
      <button role="menuitem" id="second">Second</button>`);
    expect(menuSheetFocus(menu)?.id).toBe("first");
  });

  it("skips an item of a nested submenu", () => {
    const menu = panel(`
      <drop-down behavior="menu" submenu="true">
        <button data-toggle role="menuitem" aria-haspopup="menu" id="more">More</button>
        <div data-menu hidden>
          <button role="menuitem" id="deep">Deep</button>
        </div>
      </drop-down>
      <button role="menuitem" id="own">Own</button>`);
    expect(menuSheetFocus(menu)?.id).toBe("more");
  });

  it("falls back to the first tabbable control when no item is enabled", () => {
    const menu = panel(`
      <button role="menuitem" disabled>Off</button>
      <button id="trigger" type="button">Trigger</button>
      <button id="other" type="button">Other</button>`);
    expect(menuSheetFocus(menu)?.id).toBe("trigger");
  });

  it("falls back past a disabled or hidden control", () => {
    const menu = panel(`
      <button disabled id="off">Off</button>
      <div hidden><button id="hidden">Hidden</button></div>
      <input id="field" type="text">`);
    expect(menuSheetFocus(menu)?.id).toBe("field");
  });

  it("returns null for a menu with nothing focusable", () => {
    const menu = panel(`<p>Nothing here</p>`);
    expect(menuSheetFocus(menu)).toBeNull();
  });
});

describe("menu behavior hover in a sheet", () => {
  // A parent menu whose panel is the sheet's lent node, holding a submenu.
  const mountSubmenu = (parentInSheet: boolean): DropdownElement => {
    document.body.innerHTML = `
      <drop-down behavior="menu" submenu="false" id="parent">
        <button data-toggle type="button">Parent</button>
        <div data-menu popover="manual" hidden ${
          parentInSheet ? `${SHEET_ATTRIBUTES.host}="${SHEET_HOST_VALUE}"` : ""
        }>
          <drop-down behavior="menu" submenu="true" id="child">
            <button data-toggle role="menuitem" aria-haspopup="menu" type="button">More</button>
            <div data-menu popover="manual" hidden role="menu">
              <button role="menuitem" type="button">Deep</button>
            </div>
          </drop-down>
        </div>
      </drop-down>`;
    return document.querySelector<DropdownElement>("#child")!;
  };

  const hover = (element: HTMLElement): void => {
    element.dispatchEvent(
      new PointerEvent("pointerenter", { bubbles: false, pointerType: "mouse" }),
    );
  };

  it("opens a submenu on hover outside a sheet", () => {
    const child = mountSubmenu(false);
    hover(child);
    expect(child.isOpen()).toBe(true);
  });

  it("opens nothing on hover while the parent menu is in a sheet", () => {
    const child = mountSubmenu(true);
    hover(child);
    expect(child.isOpen()).toBe(false);
  });
});
