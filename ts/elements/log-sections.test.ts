// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { FORM_DIALOG_RELOAD, type FormDialogReloadDetail } from "./form-dialog/events.js";
import { browser } from "./form-dialog/navigation.js";
import { resetModalLayerForTests } from "./modal-layer.js";
import "./log-sections.js";

const ROUTE = "/tracker/log/";

function mount(
  { openSection = "", game = "1", origin = "", inDialog = false } = {},
): HTMLElement {
  const host = `
    <log-sections open-section="${openSection}" route="${ROUTE}" origin="${origin}">
      <search-select name="game"><input type="hidden" name="game" value="${game}"></search-select>
      <button type="button" data-log-section-edit="playtime">
        <span data-log-section-idle>Add playtime…</span>
        <span data-log-section-held hidden>Playtime added</span>
      </button>
      <dialog data-modal data-log-section="playtime" data-log-section-holds="duration_hours duration_minutes">
        <button type="button" data-modal-dismiss>×</button>
        <input name="duration_hours">
        <input name="duration_minutes">
        <button type="button" data-log-section-done>Done</button>
      </dialog>
    </log-sections>`;
  document.body.innerHTML = inDialog
    ? `<dialog data-modal id="outer">${host}</dialog>`
    : `<form>${host}</form>`;
  return document.querySelector("log-sections")!;
}

function dialog(host: HTMLElement): HTMLDialogElement {
  return host.querySelector("dialog[data-log-section]")!;
}

function press(host: HTMLElement, selector: string): void {
  host.querySelector<HTMLElement>(selector)!.click();
}

function pick(host: HTMLElement, values: string[], name = "game"): void {
  host.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: { name, values, last: null, none: values.length === 0 },
    }),
  );
}

function opener(host: HTMLElement): HTMLElement {
  return host.querySelector<HTMLElement>("[data-log-section-edit]")!;
}

afterEach(() => {
  resetModalLayerForTests();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("log-sections", () => {
  it("opens a section from its opener", () => {
    const host = mount();
    press(host, "[data-log-section-edit]");
    expect(dialog(host).open).toBe(true);
  });

  it("keeps the fields when Done closes the section", () => {
    const host = mount();
    press(host, "[data-log-section-edit]");
    host.querySelector<HTMLInputElement>('input[name="duration_hours"]')!.value = "2";
    press(host, "[data-log-section-done]");
    expect(dialog(host).open).toBe(false);
    expect(host.querySelector<HTMLInputElement>('input[name="duration_hours"]')!.value).toBe("2");
  });

  it("keeps the fields when × closes the section", () => {
    const host = mount();
    press(host, "[data-log-section-edit]");
    host.querySelector<HTMLInputElement>('input[name="duration_hours"]')!.value = "2";
    press(host, "[data-modal-dismiss]");
    expect(dialog(host).open).toBe(false);
    expect(host.querySelector<HTMLInputElement>('input[name="duration_hours"]')!.value).toBe("2");
  });

  it("opens the section the server names", async () => {
    const host = mount({ openSection: "playtime" });
    await Promise.resolve();
    expect(dialog(host).open).toBe(true);
  });

  it("reads held once a named field holds a value", () => {
    const host = mount();
    const idle = opener(host).querySelector<HTMLElement>("[data-log-section-idle]")!;
    const held = opener(host).querySelector<HTMLElement>("[data-log-section-held]")!;
    expect(idle.hidden).toBe(false);
    expect(held.hidden).toBe(true);

    const hours = host.querySelector<HTMLInputElement>('input[name="duration_hours"]')!;
    hours.value = "1";
    hours.dispatchEvent(new Event("input", { bubbles: true }));

    expect(idle.hidden).toBe(true);
    expect(held.hidden).toBe(false);
  });

  it("reloads the form inside a dialog for a picked game, carrying the origin", () => {
    const host = mount({ origin: "/tracker/game/list", inDialog: true });
    const reloads: FormDialogReloadDetail[] = [];
    document.addEventListener(FORM_DIALOG_RELOAD, (event) => {
      reloads.push((event as CustomEvent<FormDialogReloadDetail>).detail);
    });

    pick(host, ["7"]);

    expect(reloads).toHaveLength(1);
    const url = new URL(reloads[0].url, "http://localhost");
    expect(url.pathname).toBe(ROUTE);
    expect(url.searchParams.get("prefill_game")).toBe("7");
    expect(url.searchParams.get("origin")).toBe("/tracker/game/list");
  });

  it("navigates to the same URL outside a dialog", () => {
    const host = mount();
    const assigned: string[] = [];
    vi.spyOn(browser, "assign").mockImplementation((url) => {
      assigned.push(url);
    });

    pick(host, ["7"]);

    expect(assigned).toHaveLength(1);
    expect(new URL(assigned[0], "http://localhost").searchParams.get("prefill_game")).toBe("7");
  });

  it("does nothing when the game is cleared", () => {
    const host = mount({ inDialog: true });
    const reloads: Event[] = [];
    document.addEventListener(FORM_DIALOG_RELOAD, (event) => reloads.push(event));

    pick(host, []);

    expect(reloads).toHaveLength(0);
  });

  it("ignores a pick of another field", () => {
    const host = mount({ inDialog: true });
    const reloads: Event[] = [];
    document.addEventListener(FORM_DIALOG_RELOAD, (event) => reloads.push(event));

    pick(host, ["7"], "platform");

    expect(reloads).toHaveLength(0);
  });
});
