// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DropdownElement } from "./drop-down.js";
import "./drop-down.js";
import { MODAL_CHANGE } from "./modal-layer.js";
import { openSurfaces } from "./surface-stack.js";
import { attachSheetCore } from "./sheet-controller.js";

let reducedMotion = true;
const SLOW_EXIT_MS = 240;
// The slow exit plus holdLeave's slack.
const EXIT_CAP_MS = SLOW_EXIT_MS + 100;

function expectNoLeaveLimit(logged: ReturnType<typeof vi.spyOn>): void {
  expect(logged).not.toHaveBeenCalledWith(expect.stringContaining("never called finish"));
}

// An exit animation that never ends: the leave waits for its cap.
function holdExit(dialog: HTMLDialogElement): void {
  Object.defineProperty(dialog, "getAnimations", {
    configurable: true,
    value: () => [{ finished: new Promise(() => {}) }],
  });
}

function mountSheet(): {
  host: DropdownElement;
  toggle: HTMLButtonElement;
  dialog: HTMLDialogElement;
  panel: HTMLElement;
  closeButton: HTMLButtonElement;
  link: HTMLAnchorElement;
  destination: HTMLElement;
  heading: HTMLElement;
} {
  document.body.innerHTML = `
    <drop-down behavior="sheet" placement="bottom-start" submenu="false">
      <button data-toggle aria-expanded="false">Settings sections</button>
      <dialog data-menu data-modal data-bottom-sheet>
        <div data-sheet-panel>
          <button data-modal-dismiss>Close</button>
          <nav><a href="#privacy">Privacy</a></nav>
        </div>
      </dialog>
    </drop-down>
    <section id="privacy">
      <h2 data-sectioned-page-section-heading tabindex="-1">Privacy</h2>
    </section>`;
  const host = document.querySelector("drop-down")!;
  const toggle = host.querySelector<HTMLButtonElement>("[data-toggle]")!;
  const dialog = host.querySelector<HTMLDialogElement>("dialog")!;
  const panel = dialog.querySelector<HTMLElement>("[data-sheet-panel]")!;
  const closeButton = dialog.querySelector<HTMLButtonElement>("[data-modal-dismiss]")!;
  const link = dialog.querySelector<HTMLAnchorElement>("a")!;
  const destination = document.querySelector<HTMLElement>("#privacy")!;
  const heading = destination.querySelector<HTMLElement>("h2")!;
  destination.scrollIntoView = vi.fn();
  return { host, toggle, dialog, panel, closeButton, link, destination, heading };
}

function mountTwoSheets(): {
  hosts: DropdownElement[];
  toggles: HTMLButtonElement[];
  dialogs: HTMLDialogElement[];
} {
  document.body.innerHTML = ["first", "second"]
    .map(
      (id) => `
        <drop-down behavior="sheet" placement="bottom-start" submenu="false">
          <button data-toggle aria-expanded="false">Open ${id}</button>
          <dialog data-menu data-modal data-bottom-sheet>
            <div data-sheet-panel>
              <button data-modal-dismiss>Close</button>
            </div>
          </dialog>
        </drop-down>`,
    )
    .join("");
  return {
    hosts: Array.from(document.querySelectorAll("drop-down")),
    toggles: Array.from(document.querySelectorAll("[data-toggle]")),
    dialogs: Array.from(document.querySelectorAll("dialog")),
  };
}

function pointerEvent(type: "pointerdown" | "pointerup", pointerId: number): Event {
  const event = new MouseEvent(type, { bubbles: true });
  Object.defineProperty(event, "pointerId", { value: pointerId });
  return event;
}

beforeEach(() => {
  reducedMotion = true;
  document.documentElement.style.setProperty("--duration-slow-exit", `${SLOW_EXIT_MS}ms`);
  document.documentElement.style.setProperty("--duration-reduced", "100ms");
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: reducedMotion,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
  vi.stubGlobal("scrollTo", vi.fn());
});

afterEach(() => {
  document.body.replaceChildren();
  document.documentElement.removeAttribute("style");
  document.body.removeAttribute("style");
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe('drop-down behavior="sheet"', () => {
  it("opens natively, focuses the first link, and emits one lifecycle", () => {
    const { host, toggle, dialog, link } = mountSheet();
    const shown = vi.fn();
    host.addEventListener("dropdown:show", shown);
    toggle.focus();

    toggle.click();

    expect(dialog.open).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(link);
    expect(shown).toHaveBeenCalledTimes(1);
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.position).toBe("fixed");
  });

  it("cleans up completely when native opening fails", () => {
    const { toggle, dialog } = mountSheet();
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(() => {
      throw new DOMException("Already open", "InvalidStateError");
    });

    toggle.click();

    expect(dialog.open).toBe(false);
    expect(dialog.dataset.sheetState).toBe("closed");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");
    expect(error).toHaveBeenCalledWith(expect.stringContaining("modal-layer"));
    expect(openSurfaces()).toEqual([]);
  });

  it("ignores programmatic opening while its trigger surface is hidden", () => {
    const { host, toggle, dialog } = mountSheet();
    const showModal = vi.spyOn(HTMLDialogElement.prototype, "showModal");
    host.setAttribute("hidden", "");

    host.open();

    expect(showModal).not.toHaveBeenCalled();
    expect(dialog.open).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");
  });

  it("intercepts native cancel and restores focus and scroll styles", () => {
    const { host, toggle, dialog } = mountSheet();
    const hidden = vi.fn();
    host.addEventListener("dropdown:hide", hidden);
    toggle.focus();
    toggle.click();
    const cancel = new Event("cancel", { cancelable: true });

    dialog.dispatchEvent(cancel);

    expect(cancel.defaultPrevented).toBe(true);
    expect(dialog.open).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");
    expect(hidden).toHaveBeenCalledTimes(1);
  });

  it("keeps Tab within the sheet without adding an Escape key listener", () => {
    const { toggle, dialog, closeButton, link } = mountSheet();
    toggle.click();
    expect(document.activeElement).toBe(link);

    const forward = new KeyboardEvent("keydown", {
      key: "Tab",
      bubbles: true,
      cancelable: true,
    });
    link.dispatchEvent(forward);
    expect(forward.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(closeButton);

    const backward = new KeyboardEvent("keydown", {
      key: "Tab",
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    closeButton.dispatchEvent(backward);
    expect(backward.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(link);

    const escape = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    link.dispatchEvent(escape);
    expect(escape.defaultPrevented).toBe(false);
  });

  it("closes only when the same pointer starts and ends on the backdrop", () => {
    const { toggle, dialog, panel } = mountSheet();
    toggle.click();

    panel.dispatchEvent(pointerEvent("pointerdown", 1));
    dialog.dispatchEvent(pointerEvent("pointerup", 1));
    expect(dialog.open).toBe(true);

    dialog.dispatchEvent(pointerEvent("pointerdown", 2));
    panel.dispatchEvent(pointerEvent("pointerup", 2));
    expect(dialog.open).toBe(true);

    dialog.dispatchEvent(pointerEvent("pointerdown", 3));
    dialog.dispatchEvent(pointerEvent("pointerup", 4));
    expect(dialog.open).toBe(true);

    dialog.dispatchEvent(pointerEvent("pointerdown", 5));
    dialog.dispatchEvent(pointerEvent("pointerup", 5));
    expect(dialog.open).toBe(false);
  });

  it("closes from the visible dismiss control", () => {
    const { toggle, dialog, closeButton } = mountSheet();
    toggle.click();
    closeButton.click();
    expect(dialog.open).toBe(false);
  });

  it("closes before updating the hash, scrolling, and focusing the destination", () => {
    const { toggle, dialog, link, destination, heading } = mountSheet();
    toggle.click();

    link.click();

    expect(dialog.open).toBe(false);
    expect(window.location.hash).toBe("#privacy");
    expect(destination.scrollIntoView).toHaveBeenCalledWith({ block: "start" });
    expect(document.activeElement).toBe(heading);
  });

  it("holds the slide out until its exit animation ends", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const logged = vi.spyOn(console, "error");
    const { host, toggle, dialog } = mountSheet();
    toggle.click();
    holdExit(dialog);

    host.close();
    expect(dialog.open).toBe(true);
    expect(dialog.dataset.sheetState).toBe("closing");
    expect(dialog.getAttribute("data-motion")).toBe("leaving");

    vi.advanceTimersByTime(EXIT_CAP_MS);
    expectNoLeaveLimit(logged);
    expect(dialog.open).toBe(false);
    expect(dialog.dataset.sheetState).toBe("closed");
    expect(dialog.hasAttribute("data-motion")).toBe(false);
  });

  it("restores every owned inline scroll style exactly", () => {
    const { host, toggle } = mountSheet();
    const html = document.documentElement;
    const body = document.body;
    html.style.overflow = "clip";
    html.style.overscrollBehavior = "contain";
    html.style.scrollBehavior = "smooth";
    body.style.position = "relative";
    body.style.top = "1px";
    body.style.right = "2px";
    body.style.bottom = "3px";
    body.style.left = "4px";
    body.style.width = "90%";
    body.style.overflow = "auto";
    body.style.paddingRight = "5px";
    const before = {
      html: html.getAttribute("style"),
      body: body.getAttribute("style"),
    };

    toggle.click();
    host.close();

    expect(html.getAttribute("style")).toBe(before.html);
    expect(body.getAttribute("style")).toBe(before.body);
  });

  it("is a modal surface from open to every close", () => {
    const { host, toggle, dialog, closeButton } = mountSheet();
    toggle.click();
    expect(openSurfaces()).toEqual([expect.objectContaining({ host, kind: "modal" })]);
    closeButton.click();
    expect(openSurfaces()).toEqual([]);

    toggle.click();
    dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(openSurfaces()).toEqual([]);

    vi.useFakeTimers();
    toggle.click();
    dialog.close();
    vi.runAllTimers();
    expect(openSurfaces()).toEqual([]);
  });

  it("closes a dropdown outside the sheet as it opens", () => {
    const { toggle } = mountSheet();
    const outside = document.createElement("drop-down");
    outside.innerHTML = '<button data-toggle>Menu</button><div data-menu popover="manual" hidden></div>';
    document.body.append(outside);
    outside.open();
    toggle.click();
    expect(outside.querySelector<HTMLElement>("[data-menu]")!.hidden).toBe(true);
    expect(openSurfaces().map((surface) => surface.kind)).toEqual(["modal"]);
  });

  it("keeps a dropdown inside the sheet open", () => {
    const { toggle, panel } = mountSheet();
    const inside = document.createElement("drop-down");
    inside.innerHTML = '<button data-toggle>Pick</button><div data-menu popover="manual" hidden></div>';
    panel.append(inside);
    toggle.click();
    inside.open();
    expect(openSurfaces().map((surface) => surface.kind)).toEqual(["modal", "panel"]);
  });

  it("performs immediate cleanup when disconnected while open", () => {
    const { host, toggle, dialog } = mountSheet();
    toggle.click();
    host.remove();

    expect(openSurfaces()).toEqual([]);
    expect(dialog.open).toBe(false);
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");
  });

  it("performs immediate cleanup when disconnected while closing", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const { host, toggle, dialog, closeButton } = mountSheet();
    toggle.click();
    holdExit(dialog);
    closeButton.click();
    expect(dialog.dataset.sheetState).toBe("closing");
    host.remove();

    expect(dialog.open).toBe(false);
    expect(openSurfaces()).toEqual([]);
    expect(document.documentElement.style.overflow).toBe("");
  });

  it("closes a panel inside as its slide starts", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const { toggle, panel, closeButton } = mountSheet();
    const inside = document.createElement("drop-down");
    inside.innerHTML = '<button data-toggle>Pick</button><div data-menu popover="manual" hidden></div>';
    panel.append(inside);
    toggle.click();
    inside.open();
    closeButton.click();
    expect(inside.querySelector<HTMLElement>("[data-menu]")!.hidden).toBe(true);
  });

  it("nests two sheets and the last close restores the page style", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const { hosts, toggles, dialogs } = mountTwoSheets();
    dialogs.forEach(holdExit);
    document.documentElement.style.overflow = "clip";
    document.body.style.position = "relative";
    const originalHtmlStyle = document.documentElement.getAttribute("style");
    const originalBodyStyle = document.body.getAttribute("style");

    hosts[0].open();
    hosts[1].open();
    expect(dialogs[0].open).toBe(true);
    expect(dialogs[1].open).toBe(true);
    expect(toggles[1].getAttribute("aria-expanded")).toBe("true");

    hosts[1].close();
    vi.advanceTimersByTime(EXIT_CAP_MS);
    expect(dialogs[1].open).toBe(false);
    expect(dialogs[0].open).toBe(true);
    expect(document.body.style.position).toBe("fixed");

    hosts[0].close();
    vi.advanceTimersByTime(EXIT_CAP_MS);
    expect(document.documentElement.getAttribute("style")).toBe(originalHtmlStyle);
    expect(document.body.getAttribute("style")).toBe(originalBodyStyle);
  });

  it("emits dropdown:show after the layer's change event", () => {
    const { host, toggle } = mountSheet();
    const order: string[] = [];
    const onChange = (): number => order.push("change");
    window.addEventListener(MODAL_CHANGE, onChange);
    host.addEventListener("dropdown:show", () => order.push("show"));
    toggle.click();
    window.removeEventListener(MODAL_CHANGE, onChange);
    expect(order).toEqual(["change", "show"]);
  });

  it("cleans up a sheet closed from below", () => {
    const { hosts, toggles, dialogs } = mountTwoSheets();
    const hidden = vi.fn();
    hosts[1].addEventListener("dropdown:hide", hidden);
    hosts[0].open();
    hosts[1].open();

    hosts[0].close();

    expect(dialogs[1].open).toBe(false);
    expect(dialogs[1].dataset.sheetState).toBe("closed");
    expect(toggles[1].getAttribute("aria-expanded")).toBe("false");
    expect(hidden).toHaveBeenCalledOnce();
  });

  it("ignores the toggle while the sheet slides out", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const { host, toggle, dialog } = mountSheet();
    toggle.click();
    holdExit(dialog);
    host.close();
    toggle.click();
    expect(dialog.dataset.sheetState).toBe("closing");
    vi.advanceTimersByTime(EXIT_CAP_MS);
    expect(dialog.open).toBe(false);
    expect(dialog.dataset.sheetState).toBe("closed");
  });

  it("closes a sliding upper sheet once when the lower one closes", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const { hosts, dialogs } = mountTwoSheets();
    dialogs.forEach(holdExit);
    const hidden = [vi.fn(), vi.fn()];
    hosts.forEach((host, index) => host.addEventListener("dropdown:hide", hidden[index]));
    hosts[0].open();
    hosts[1].open();
    hosts[1].close();
    hosts[0].close();
    vi.runAllTimers();
    expect(hidden.map((listener) => listener.mock.calls.length)).toEqual([1, 1]);
    expect(dialogs.map((dialog) => dialog.dataset.sheetState)).toEqual([
      "closed",
      "closed",
    ]);
  });
});

describe("attachSheetCore", () => {
  function mountCore(): { host: HTMLElement; trigger: HTMLButtonElement; dialog: HTMLDialogElement } {
    document.body.innerHTML = `
      <div id="host">
        <div data-toggle>field <button id="trigger" type="button">Open</button></div>
        <dialog data-modal>
          <div data-sheet-panel><button data-modal-dismiss>Close</button></div>
        </dialog>
      </div>`;
    return {
      host: document.querySelector<HTMLElement>("#host")!,
      trigger: document.querySelector<HTMLButtonElement>("#trigger")!,
      dialog: document.querySelector<HTMLDialogElement>("dialog")!,
    };
  }

  it("binds no toggle and runs its hooks around each event", () => {
    const { host, trigger, dialog } = mountCore();
    const steps: string[] = [];
    host.addEventListener("dropdown:show", () => steps.push("show"));
    host.addEventListener("dropdown:hide", () => steps.push("hide"));
    const sheet = attachSheetCore(host, dialog, {
      beforeShow: () => steps.push("beforeShow"),
      beforeHide: () => steps.push("beforeHide"),
      afterHide: () => steps.push("afterHide"),
    });
    host.querySelector<HTMLElement>("[data-toggle]")!.click();
    expect(sheet.isOpen()).toBe(false);

    expect(sheet.open(trigger)).toBe(true);
    expect(dialog.open).toBe(true);
    sheet.close();
    expect(dialog.open).toBe(false);
    expect(steps).toEqual(["beforeShow", "show", "beforeHide", "hide", "afterHide"]);
    expect(document.activeElement).toBe(trigger);
  });

  it("answers false when the dialog is detached", () => {
    const { host, dialog } = mountCore();
    const sheet = attachSheetCore(host, dialog);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    dialog.remove();
    expect(sheet.open()).toBe(false);
  });
});
