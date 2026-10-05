// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import "./search-field.js";

function press(target: HTMLElement): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
}

describe("search-field", () => {
  it("submits its form on Enter, inserted after load", () => {
    document.body.innerHTML = "<form></form>";
    const form = document.querySelector("form")!;
    const submitted = vi.spyOn(form, "requestSubmit").mockImplementation(() => {});
    form.insertAdjacentHTML(
      "beforeend",
      "<search-field><input data-match-value></search-field>",
    );

    const event = press(form.querySelector<HTMLElement>("[data-match-value]")!);

    expect(event.defaultPrevented).toBe(true);
    expect(submitted).toHaveBeenCalledOnce();
  });

  it("leaves other keys and inputs alone", () => {
    document.body.innerHTML =
      "<form><search-field><input data-match-value><button>Mode</button></search-field></form>";
    const form = document.querySelector("form")!;
    const submitted = vi.spyOn(form, "requestSubmit").mockImplementation(() => {});

    press(form.querySelector("button")!);

    expect(submitted).not.toHaveBeenCalled();
  });
});
