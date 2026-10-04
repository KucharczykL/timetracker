// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { isPopoverOpen } from "./popover.js";

afterEach(() => {
  document.body.innerHTML = "";
});

function mountPanel(): HTMLElement {
  const panel = document.createElement("div");
  panel.setAttribute("popover", "manual");
  document.body.append(panel);
  return panel;
}

describe("popover shim", () => {
  it("refuses an element without a popover attribute", () => {
    const element = document.createElement("div");
    document.body.append(element);
    expect(() => element.showPopover()).toThrow(
      expect.objectContaining({ name: "NotSupportedError" }),
    );
  });

  it("refuses to hide an element without a popover attribute", () => {
    const element = document.createElement("div");
    expect(() => element.hidePopover()).toThrow(
      expect.objectContaining({ name: "NotSupportedError" }),
    );
  });

  it("refuses a disconnected element", () => {
    const panel = document.createElement("div");
    panel.setAttribute("popover", "manual");
    expect(() => panel.showPopover()).toThrow(
      expect.objectContaining({ name: "InvalidStateError" }),
    );
  });

  it("shows and hides idempotently", () => {
    const panel = mountPanel();
    panel.showPopover();
    panel.showPopover();
    expect(isPopoverOpen(panel)).toBe(true);
    panel.hidePopover();
    panel.hidePopover();
    expect(isPopoverOpen(panel)).toBe(false);
  });
});
