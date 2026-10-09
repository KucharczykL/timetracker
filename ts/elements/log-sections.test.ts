// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import "./log-sections.js";

function mount(openSection = "", game = "1"): HTMLElement {
  document.body.innerHTML = `
    <form><log-sections open-section="${openSection}">
      <input type="hidden" name="game" value="${game}">
      <p data-log-sections-hint hidden>Pick a game first.</p>
      <label><input type="checkbox" name="sections" value="copy">Copy</label>
      <button type="button" data-log-section-edit="copy">Edit</button>
      <dialog data-modal data-log-section="copy">
        <button type="button" data-modal-dismiss>×</button>
        <input name="amount">
        <button type="button" data-log-section-done>Done</button>
      </dialog>
    </log-sections></form>`;
  return document.querySelector("log-sections")!;
}

function tick(host: HTMLElement): HTMLInputElement {
  return host.querySelector<HTMLInputElement>('input[name="sections"]')!;
}

function dialog(host: HTMLElement): HTMLDialogElement {
  return host.querySelector("dialog")!;
}

function press(host: HTMLElement, selector: string): void {
  host.querySelector<HTMLElement>(selector)!.click();
}

describe("log-sections", () => {
  it("opens a section when its tick is checked", () => {
    const host = mount();
    tick(host).click();
    expect(dialog(host).open).toBe(true);
  });

  it("keeps the tick when Done closes the section", () => {
    const host = mount();
    tick(host).click();
    press(host, "[data-log-section-done]");
    expect(dialog(host).open).toBe(false);
    expect(tick(host).checked).toBe(true);
  });

  it("unticks a dismissed section", () => {
    const host = mount();
    tick(host).click();
    press(host, "[data-modal-dismiss]");
    expect(dialog(host).open).toBe(false);
    expect(tick(host).checked).toBe(false);
  });

  it("reopens a section from Edit", () => {
    const host = mount();
    tick(host).click();
    press(host, "[data-log-section-done]");
    press(host, "[data-log-section-edit]");
    expect(dialog(host).open).toBe(true);
  });

  it("opens the section the server names", async () => {
    const host = mount("copy");
    await Promise.resolve();
    expect(dialog(host).open).toBe(true);
  });

  it("disables the ticks until a game is held", () => {
    const host = mount("", "");
    expect(tick(host).disabled).toBe(true);
    expect(host.querySelector<HTMLElement>("[data-log-sections-hint]")!.hidden).toBe(false);
    host.querySelector<HTMLInputElement>('input[name="game"]')!.value = "7";
    host.dispatchEvent(new CustomEvent("search-select:change", { bubbles: true }));
    expect(tick(host).disabled).toBe(false);
    expect(host.querySelector<HTMLElement>("[data-log-sections-hint]")!.hidden).toBe(true);
  });

  it("keeps the fields in the form", () => {
    const host = mount();
    const form = host.closest("form")!;
    expect(form.elements.namedItem("amount")).not.toBeNull();
  });
});
