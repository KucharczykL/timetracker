// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "./drop-down.js";

interface DropdownHost extends HTMLElement {
  open(): void;
  close(): void;
}

let reducedMotion = true;
let previousShowModal: typeof HTMLDialogElement.prototype.showModal;
let previousClose: typeof HTMLDialogElement.prototype.close;

function mountSheet(): {
  host: DropdownHost;
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
      <dialog data-menu data-bottom-sheet>
        <div data-sheet-panel>
          <button data-sheet-dismiss>Close</button>
          <nav><a href="#privacy">Privacy</a></nav>
        </div>
      </dialog>
    </drop-down>
    <section id="privacy">
      <h2 data-settings-section-heading tabindex="-1">Privacy</h2>
    </section>`;
  const host = document.querySelector("drop-down") as DropdownHost;
  const toggle = host.querySelector<HTMLButtonElement>("[data-toggle]")!;
  const dialog = host.querySelector<HTMLDialogElement>("dialog")!;
  const panel = dialog.querySelector<HTMLElement>("[data-sheet-panel]")!;
  const closeButton = dialog.querySelector<HTMLButtonElement>("[data-sheet-dismiss]")!;
  const link = dialog.querySelector<HTMLAnchorElement>("a")!;
  const destination = document.querySelector<HTMLElement>("#privacy")!;
  const heading = destination.querySelector<HTMLElement>("h2")!;
  destination.scrollIntoView = vi.fn();
  return { host, toggle, dialog, panel, closeButton, link, destination, heading };
}

function mountTwoSheets(): {
  hosts: DropdownHost[];
  toggles: HTMLButtonElement[];
  dialogs: HTMLDialogElement[];
} {
  document.body.innerHTML = ["first", "second"]
    .map(
      (id) => `
        <drop-down behavior="sheet" placement="bottom-start" submenu="false">
          <button data-toggle aria-expanded="false">Open ${id}</button>
          <dialog data-menu data-bottom-sheet>
            <div data-sheet-panel>
              <button data-sheet-dismiss>Close</button>
            </div>
          </dialog>
        </drop-down>`,
    )
    .join("");
  return {
    hosts: Array.from(document.querySelectorAll("drop-down")) as DropdownHost[],
    toggles: Array.from(document.querySelectorAll("[data-toggle]")),
    dialogs: Array.from(document.querySelectorAll("dialog")),
  };
}

beforeEach(() => {
  reducedMotion = true;
  previousShowModal = HTMLDialogElement.prototype.showModal;
  previousClose = HTMLDialogElement.prototype.close;
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
    const trigger = this.closest("drop-down")?.querySelector<HTMLElement>("[data-toggle]");
    trigger?.focus();
  };
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
  HTMLDialogElement.prototype.showModal = previousShowModal;
  HTMLDialogElement.prototype.close = previousClose;
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
    HTMLDialogElement.prototype.showModal = function () {
      throw new DOMException("Already open", "InvalidStateError");
    };

    toggle.click();

    expect(dialog.open).toBe(false);
    expect(dialog.dataset.sheetState).toBe("closed");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");
    expect(error).toHaveBeenCalledOnce();
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
    expect(dialog.open).toBe(true);
  });

  it("closes on a true backdrop gesture but not one starting in the panel", () => {
    const { toggle, dialog, panel } = mountSheet();
    toggle.click();

    panel.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    dialog.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(dialog.open).toBe(true);

    dialog.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    dialog.dispatchEvent(new MouseEvent("click", { bubbles: true }));
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

  it("uses the timeout safety net when motion is enabled", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const { host, toggle, dialog } = mountSheet();
    toggle.click();

    host.close();
    expect(dialog.open).toBe(true);
    expect(dialog.dataset.sheetState).toBe("closing");

    vi.runAllTimers();
    expect(dialog.open).toBe(false);
    expect(dialog.dataset.sheetState).toBe("closed");
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

  it("performs immediate cleanup when disconnected while open", () => {
    const { host, toggle, dialog } = mountSheet();
    toggle.click();
    host.remove();

    expect(dialog.open).toBe(false);
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.position).toBe("");
  });

  it("fully closes a sibling sheet before taking over its scroll lock", () => {
    reducedMotion = false;
    vi.useFakeTimers();
    const { hosts, toggles, dialogs } = mountTwoSheets();
    document.documentElement.style.overflow = "clip";
    document.body.style.position = "relative";
    const originalHtmlStyle = document.documentElement.getAttribute("style");
    const originalBodyStyle = document.body.getAttribute("style");

    hosts[0].open();
    expect(dialogs[0].open).toBe(true);
    expect(document.body.style.position).toBe("fixed");

    hosts[1].open();
    expect(dialogs[0].open).toBe(false);
    expect(toggles[0].getAttribute("aria-expanded")).toBe("false");
    expect(dialogs[1].open).toBe(true);
    expect(toggles[1].getAttribute("aria-expanded")).toBe("true");
    expect(document.body.style.position).toBe("fixed");

    // The second close may animate, but its final restoration must return to
    // the page's original values—not the first sheet's locked snapshot.
    hosts[1].close();
    vi.runAllTimers();
    expect(dialogs[1].open).toBe(false);
    expect(document.documentElement.getAttribute("style")).toBe(originalHtmlStyle);
    expect(document.body.getAttribute("style")).toBe(originalBodyStyle);
  });
});
