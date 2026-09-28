// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import "../drop-down.js";

const mount = (): HTMLElement => {
  const host = document.createElement("drop-down");
  host.setAttribute("behavior", "choice-grid");
  host.innerHTML = `
    <button data-toggle aria-expanded="false" type="button">
      <span data-choice-grid-glyph><svg data-glyph="gog"></svg></span>
      <span data-choice-grid-label>GOG.com</span>
    </button>
    <div data-menu hidden role="dialog" aria-label="Icon">
      <fieldset>
        <label><input type="radio" name="icon" value="gog" data-choice-label="GOG.com" checked>
          <span data-choice-grid-glyph><svg data-glyph="gog"></svg></span></label>
        <label><input type="radio" name="icon" value="steam" data-choice-label="Steam">
          <span data-choice-grid-glyph><svg data-glyph="steam"></svg></span></label>
      </fieldset>
    </div>`;
  document.body.replaceChildren(host);
  return host;
};

const parts = (host: HTMLElement) => ({
  toggle: host.querySelector<HTMLElement>("[data-toggle]")!,
  menu: host.querySelector<HTMLElement>("[data-menu]")!,
  steam: host.querySelector<HTMLInputElement>('input[value="steam"]')!,
  label: () => host.querySelector("[data-choice-grid-label]")!.textContent,
  glyph: () =>
    host
      .querySelector("[data-toggle] [data-choice-grid-glyph] svg")!
      .getAttribute("data-glyph"),
});

const open = (host: HTMLElement) => {
  parts(host).toggle.click();
  expect(parts(host).menu.hidden).toBe(false);
};

describe("choice-grid behavior", () => {
  it("focuses the checked tile on open", () => {
    const host = mount();
    open(host);
    expect(document.activeElement).toBe(
      host.querySelector('input[value="gog"]'),
    );
  });

  it("reflects a changed choice on the trigger and stays open", () => {
    const host = mount();
    open(host);
    const { steam, menu } = parts(host);
    steam.checked = true;
    steam.dispatchEvent(new Event("change", { bubbles: true }));
    expect(parts(host).label()).toBe("Steam");
    expect(parts(host).glyph()).toBe("steam");
    const label = host.querySelector("[data-choice-grid-label]")!;
    expect(label.hasAttribute("data-keep")).toBe(false);
    expect(menu.hidden).toBe(false);
  });

  it("closes on a pointer pick and returns focus to the trigger", () => {
    const host = mount();
    open(host);
    const { steam, menu, toggle } = parts(host);
    steam.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
    expect(steam.checked).toBe(true);
    expect(menu.hidden).toBe(true);
    expect(document.activeElement).toBe(toggle);
  });

  it("an arrow key's click keeps the panel open", () => {
    const host = mount();
    open(host);
    const { steam, menu } = parts(host);
    steam.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 0 }));
    expect(menu.hidden).toBe(false);
  });

  it("picks with Enter without submitting the form", () => {
    const host = mount();
    open(host);
    const { steam, menu } = parts(host);
    const enter = new KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    });
    steam.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);
    expect(steam.checked).toBe(true);
    expect(parts(host).label()).toBe("Steam");
    expect(menu.hidden).toBe(true);
  });
});
