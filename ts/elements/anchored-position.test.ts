// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearAnchoredPosition,
  positionAnchored,
  stampSide,
} from "./anchored-position.js";

const VIEWPORT_HEIGHT = 400;

function setViewportHeight(value: number): void {
  Object.defineProperty(window, "innerHeight", { configurable: true, value });
}

function anchorBetween(top: number, bottom: number): HTMLElement {
  const anchor = document.createElement("button");
  document.body.append(anchor);
  anchor.getBoundingClientRect = () =>
    ({
      top,
      bottom,
      left: 10,
      right: 60,
      width: 50,
      height: bottom - top,
      x: 10,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
  return anchor;
}

// jsdom lays nothing out, so the panel's content height is stubbed.
function panelOf(contentHeight: number): HTMLElement {
  const panel = document.createElement("div");
  document.body.append(panel);
  Object.defineProperty(panel, "scrollHeight", { configurable: true, value: contentHeight });
  return panel;
}

beforeEach(() => {
  setViewportHeight(VIEWPORT_HEIGHT);
});

afterEach(() => {
  document.body.innerHTML = "";
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 768 });
});

describe("positionAnchored side stamp", () => {
  it("stamps bottom when the panel fits below", () => {
    const anchor = anchorBetween(10, 30);
    const panel = panelOf(300);
    const result = positionAnchored(anchor, panel, { align: "start", side: "bottom", scrollable: false });
    expect(result.side).toBe("bottom");
    expect(panel.getAttribute("data-side")).toBe("bottom");
    expect(panel.getAttribute("data-align")).toBe("start");
  });

  it("stamps top when a flipped panel lands above", () => {
    // Below has 22px of room, above 342px: the panel flips up.
    const anchor = anchorBetween(350, 370);
    const panel = panelOf(300);
    const result = positionAnchored(anchor, panel, { align: "end", side: "bottom", scrollable: false });
    expect(result.side).toBe("top");
    expect(panel.getAttribute("data-side")).toBe("top");
    expect(panel.getAttribute("data-align")).toBe("end");
  });
});

describe("stampSide", () => {
  it("writes the side and alignment it is given", () => {
    const panel = document.createElement("div");
    stampSide(panel, "left", "start");
    expect(panel.getAttribute("data-side")).toBe("left");
    expect(panel.getAttribute("data-align")).toBe("start");
  });
});

describe("clearAnchoredPosition", () => {
  it("removes the side and alignment stamps", () => {
    const anchor = anchorBetween(10, 30);
    const panel = panelOf(300);
    positionAnchored(anchor, panel, { align: "center", side: "bottom", scrollable: false });
    clearAnchoredPosition(panel);
    expect(panel.hasAttribute("data-side")).toBe(false);
    expect(panel.hasAttribute("data-align")).toBe(false);
    expect(panel.style.position).toBe("");
  });
});
