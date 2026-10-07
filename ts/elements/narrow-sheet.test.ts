// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DropdownElement } from "./drop-down.js";
import "./drop-down.js";
import { resetModalLayerForTests } from "./modal-layer.js";
import { resetSurfacesForTests } from "./surface-stack.js";

let wide = false;

function fixture(behavior = "menu"): string {
  return `
    <drop-down behavior="${behavior}" placement="bottom-start" submenu="false">
      <button data-toggle type="button" aria-expanded="false">Day</button>
      <div data-menu popover="manual" hidden id="panel"><button data-inside type="button">1</button></div>
      <dialog data-modal data-dropdown-sheet>
        <div data-sheet-panel>
          <div><h2 data-dropdown-sheet-title>Day</h2><button data-modal-dismiss type="button">×</button></div>
          <div data-sheet-body></div>
        </div>
      </dialog>
      <span data-dropdown-wide></span>
    </drop-down>`;
}

function mount(behavior = "menu"): {
  host: DropdownElement;
  toggle: HTMLButtonElement;
  panel: HTMLElement;
  dialog: HTMLDialogElement;
} {
  document.body.innerHTML = fixture(behavior);
  const host = document.querySelector("drop-down")!;
  const sentinel = host.querySelector<HTMLElement>("[data-dropdown-wide]")!;
  sentinel.getClientRects = () =>
    (wide ? [new DOMRect(0, 0, 1, 1)] : []) as unknown as DOMRectList;
  return {
    host,
    toggle: host.querySelector<HTMLButtonElement>("[data-toggle]")!,
    panel: host.querySelector<HTMLElement>("#panel")!,
    dialog: host.querySelector<HTMLDialogElement>("dialog")!,
  };
}

function mouseClick(element: HTMLElement): void {
  element.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
}

function resize(): void {
  window.dispatchEvent(new Event("resize"));
  vi.runAllTimers();
}

beforeEach(() => {
  wide = false;
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "setTimeout"] });
  // Reduced motion: a close finishes at once.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
  vi.stubGlobal("scrollTo", vi.fn());
});

afterEach(() => {
  document.body.replaceChildren();
  document.documentElement.removeAttribute("style");
  document.body.removeAttribute("style");
  resetSurfacesForTests();
  resetModalLayerForTests();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a dropdown with a narrow sheet", () => {
  it("opens anchored when wide", () => {
    wide = true;
    const { host, toggle, panel, dialog } = mount();
    mouseClick(toggle);
    expect(host.isOpen()).toBe(true);
    expect(panel.hidden).toBe(false);
    expect(panel.parentElement).toBe(host);
    expect(dialog.open).toBe(false);
  });

  it("lends the panel to the sheet when narrow, and takes it back", () => {
    const { host, toggle, panel, dialog } = mount();
    const body = dialog.querySelector("[data-sheet-body]")!;
    mouseClick(toggle);
    expect(dialog.open).toBe(true);
    expect(panel.parentElement).toBe(body);
    expect(panel.hasAttribute("popover")).toBe(false);
    expect(panel.hidden).toBe(false);
    expect(panel.getAttribute("data-dropdown-host")).toBe("sheet");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    const hostAtHide: (Element | null)[] = [];
    host.addEventListener("dropdown:hide", () => hostAtHide.push(panel.parentElement));
    host.close();
    expect(dialog.open).toBe(false);
    expect(hostAtHide).toEqual([host]);
    expect(panel.nextElementSibling).toBe(dialog);
    expect(panel.getAttribute("popover")).toBe("manual");
    expect(panel.hidden).toBe(true);
    expect(panel.hasAttribute("data-dropdown-host")).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
  });

  it("returns the panel when the modal layer refuses", () => {
    const { host, toggle, panel, dialog } = mount();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    dialog.showModal = () => {
      throw new DOMException("refused", "InvalidStateError");
    };
    mouseClick(toggle);
    expect(host.isOpen()).toBe(false);
    expect(panel.parentElement).toBe(host);
    expect(panel.getAttribute("popover")).toBe("manual");
    expect(panel.hidden).toBe(true);
  });

  it("returns the panel when the open throws", () => {
    const { host, panel, dialog } = mount();
    dialog.showModal = () => {
      throw new TypeError("broken");
    };
    expect(() => host.open()).toThrow(TypeError);
    expect(panel.parentElement).toBe(host);
    expect(panel.hidden).toBe(true);
  });

  it("moves an open panel across the breakpoint, both ways", () => {
    const { host, toggle, panel, dialog } = mount();
    mouseClick(toggle);
    expect(dialog.open).toBe(true);

    wide = true;
    resize();
    expect(dialog.open).toBe(false);
    expect(host.isOpen()).toBe(true);
    expect(panel.parentElement).toBe(host);
    expect(panel.hidden).toBe(false);

    wide = false;
    resize();
    expect(dialog.open).toBe(true);
    expect(panel.parentElement).toBe(dialog.querySelector("[data-sheet-body]"));
  });

  it("stays closed after a close", () => {
    const { host, toggle, dialog } = mount();
    mouseClick(toggle);
    host.close();
    wide = true;
    resize();
    expect(host.isOpen()).toBe(false);
    expect(dialog.open).toBe(false);
  });

  it("names each sheet by its own title", () => {
    document.body.innerHTML = fixture() + fixture();
    const dialogs = [...document.querySelectorAll("dialog")];
    const ids = dialogs.map((dialog) => dialog.getAttribute("aria-labelledby"));
    expect(new Set(ids).size).toBe(2);
    dialogs.forEach((dialog) => {
      const title = dialog.querySelector("[data-dropdown-sheet-title]")!;
      expect(dialog.getAttribute("aria-labelledby")).toBe(title.id);
    });
  });
});
