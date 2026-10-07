// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DropdownElement } from "./drop-down.js";
import "./drop-down.js";
import { registerBehavior } from "./dropdown-behaviors.js";
import { resetModalLayerForTests } from "./modal-layer.js";
import { resetSurfacesForTests } from "./surface-stack.js";

let narrow = true;
let reducedMotion = true;

function fixture(behavior = "menu", panelContent = '<button data-inside type="button">1</button>'): string {
  return `
    <drop-down behavior="${behavior}" placement="bottom-start" submenu="false">
      <button data-toggle type="button" aria-expanded="false">Day</button>
      <div data-menu popover="manual" hidden id="panel">${panelContent}</div>
      <dialog data-modal data-dropdown-sheet>
        <div data-sheet-panel>
          <div><h2 data-dropdown-sheet-title>Day</h2><button data-modal-dismiss type="button">×</button></div>
          <div data-sheet-body></div>
        </div>
      </dialog>
      <span data-dropdown-narrow></span>
    </drop-down>`;
}

function mount(behavior = "menu", panelContent?: string): {
  host: DropdownElement;
  toggle: HTMLButtonElement;
  panel: HTMLElement;
  dialog: HTMLDialogElement;
} {
  document.body.innerHTML = fixture(behavior, panelContent);
  const host = document.querySelector("drop-down")!;
  const sentinel = host.querySelector<HTMLElement>("[data-dropdown-narrow]")!;
  sentinel.getClientRects = () =>
    (narrow ? [new DOMRect(0, 0, 0, 0)] : []) as unknown as DOMRectList;
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
  narrow = true;
  reducedMotion = true;
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "setTimeout"] });
  // Reduced motion: a close finishes at once.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: reducedMotion,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
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
    narrow = false;
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

    narrow = false;
    resize();
    expect(dialog.open).toBe(false);
    expect(host.isOpen()).toBe(true);
    expect(panel.parentElement).toBe(host);
    expect(panel.hidden).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    narrow = true;
    resize();
    expect(dialog.open).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(panel.parentElement).toBe(dialog.querySelector("[data-sheet-body]"));
  });

  it("stays closed after a close", () => {
    const { host, toggle, dialog } = mount();
    mouseClick(toggle);
    host.close();
    narrow = false;
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

describe("a sheet that slides out", () => {
  function leave(): void {
    vi.advanceTimersByTime(300);
  }

  beforeEach(() => {
    reducedMotion = false;
  });

  it("refuses an open while it leaves", () => {
    const { host, toggle, panel, dialog } = mount();
    mouseClick(toggle);
    host.close();
    host.open();
    expect(dialog.querySelectorAll("#panel")).toHaveLength(1);
    leave();
    expect(dialog.open).toBe(false);
    expect(panel.parentElement).toBe(host);
    expect(host.isOpen()).toBe(false);
  });

  it("drops a pending move on a close", () => {
    const { host, toggle, panel, dialog } = mount();
    mouseClick(toggle);
    narrow = false;
    window.dispatchEvent(new Event("resize"));
    vi.advanceTimersToNextFrame();
    host.close();
    leave();
    expect(dialog.open).toBe(false);
    expect(host.isOpen()).toBe(false);
    expect(panel.parentElement).toBe(host);
    expect(panel.hidden).toBe(true);
  });

  it("moves once for two resizes during the leave", () => {
    const { host, toggle, panel } = mount();
    mouseClick(toggle);
    narrow = false;
    window.dispatchEvent(new Event("resize"));
    vi.advanceTimersToNextFrame();
    window.dispatchEvent(new Event("resize"));
    vi.advanceTimersToNextFrame();
    leave();
    expect(host.isOpen()).toBe(true);
    expect(panel.parentElement).toBe(host);
    expect(panel.matches(":popover-open")).toBe(true);
  });
});

describe("a sheet's first focus", () => {
  it("is the behavior's choice", () => {
    const { host } = mount(
      "date-calendar",
      '<button data-date="2026-10-01">1</button><button data-date="2026-10-02" aria-selected="true">2</button>',
    );
    host.open();
    expect(document.activeElement?.getAttribute("data-date")).toBe("2026-10-02");
  });

  it("falls back to the dismiss button", () => {
    const { host, dialog } = mount();
    host.open();
    expect(document.activeElement).toBe(dialog.querySelector("[data-modal-dismiss]"));
  });

  it("opens from the toggle's ArrowDown into the sheet", () => {
    const { toggle, dialog } = mount();
    toggle.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }),
    );
    expect(dialog.open).toBe(true);
    expect(document.activeElement).toBe(dialog.querySelector("[data-modal-dismiss]"));
  });
});

describe("a dropdown sheet's edges", () => {
  it("ignores a nested dropdown's hide", () => {
    const { host, toggle, panel } = mount();
    mouseClick(toggle);
    panel
      .querySelector("[data-inside]")!
      .dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
    narrow = false;
    resize();
    expect(host.isOpen()).toBe(true);
    expect(panel.parentElement).toBe(host);
  });

  it("reports a half-built sheet and stays anchored", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    document.body.innerHTML = fixture().replace("<span data-dropdown-narrow></span>", "");
    const host = document.querySelector("drop-down")!;
    host.open();
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("narrow sentinel"));
    expect(host.querySelector("#panel")!.parentElement).toBe(host);
    expect(host.isOpen()).toBe(true);
  });

  it("reports a sheet beside its own controller", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    registerBehavior("test-own-controller", {
      createController: () => ({
        open: vi.fn(),
        close: vi.fn(),
        isOpen: () => false,
        focusFirst: vi.fn(),
      }),
    });
    mount("test-own-controller");
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("its sheet stays unused"));
  });
});
