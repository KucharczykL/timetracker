// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { isRendered } from "./rendered.js";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("isRendered", () => {
  it("trusts checkVisibility where the engine has it", () => {
    document.body.innerHTML = `<button id="shown">Edit</button>`;
    const button = document.getElementById("shown") as HTMLElement;
    button.checkVisibility = () => false;
    expect(isRendered(button)).toBe(false);
    button.checkVisibility = () => true;
    expect(isRendered(button)).toBe(true);
  });

  it("reads a hidden ancestor where there is no checkVisibility", () => {
    document.body.innerHTML = `<div hidden><button id="inner">Edit</button></div><button id="outer">Add</button>`;
    const inner = document.getElementById("inner")!;
    Object.defineProperty(inner, "checkVisibility", { value: undefined, configurable: true });
    expect(isRendered(inner)).toBe(false);
    expect(isRendered(document.getElementById("outer")!)).toBe(true);
  });

  it("refuses a disconnected element", () => {
    const button = document.createElement("button");
    expect(isRendered(button)).toBe(false);
  });
});
