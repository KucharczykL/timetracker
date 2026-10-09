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
  // A slow exit whose fade never ends: each leave waits for its cap (200 + 100 ms).
  document.documentElement.style.setProperty("--duration-slow-exit", "200ms");
  Object.defineProperty(Element.prototype, "getAnimations", {
    configurable: true,
    value: () => [{ finished: new Promise(() => {}) }],
  });
});

afterEach(() => {
  document.body.replaceChildren();
  document.documentElement.removeAttribute("style");
  document.body.removeAttribute("style");
  Reflect.deleteProperty(Element.prototype, "getAnimations");
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
    expect(host.hasAttribute("data-dropdown-sheetless")).toBe(true);
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

function lentFixture(): string {
  return `
    <drop-down behavior="test-lent" placement="bottom-start" submenu="false">
      <div data-face><button data-face-open type="button">Face</button></div>
      <div data-toggle id="lent">
        <input data-box>
        <div data-menu popover="manual" hidden id="panel"><button type="button">1</button></div>
      </div>
      <span id="after-lent"></span>
      <dialog data-modal data-dropdown-sheet>
        <div data-sheet-panel>
          <div><h2 data-dropdown-sheet-title>Pick</h2><button data-modal-dismiss type="button">×</button></div>
          <div data-sheet-body></div>
        </div>
      </dialog>
      <span data-dropdown-narrow></span>
    </drop-down>`;
}

registerBehavior("test-lent", {
  menuOptions: () => ({ itemSelector: "[data-none]", inlineTrigger: true }),
  sheetLent: (_host, toggle) => toggle,
  sheetOpener: (host) => host.querySelector<HTMLElement>("[data-face-open]"),
  sheetFocus: (menu) => menu.closest("drop-down")!.querySelector<HTMLElement>("[data-box]"),
});

function mountLent(markup = lentFixture()): {
  host: DropdownElement;
  lent: HTMLElement;
  panel: HTMLElement;
  dialog: HTMLDialogElement;
  face: HTMLButtonElement;
} {
  document.body.innerHTML = markup;
  const host = document.querySelector("drop-down")!;
  const sentinel = host.querySelector<HTMLElement>("[data-dropdown-narrow]")!;
  sentinel.getClientRects = () =>
    (narrow ? [new DOMRect(0, 0, 0, 0)] : []) as unknown as DOMRectList;
  return {
    host,
    lent: host.querySelector<HTMLElement>("#lent")!,
    panel: host.querySelector<HTMLElement>("#panel")!,
    dialog: host.querySelector<HTMLDialogElement>("dialog")!,
    face: host.querySelector<HTMLButtonElement>("[data-face-open]")!,
  };
}

describe("a sheet lent a node other than the panel", () => {
  it("moves the lent node in and back to its place", () => {
    const { host, lent, panel, dialog } = mountLent();
    const body = dialog.querySelector("[data-sheet-body]")!;
    host.open();
    expect(lent.parentElement).toBe(body);
    expect(panel.parentElement).toBe(lent);
    expect(panel.hasAttribute("popover")).toBe(false);
    expect(panel.hidden).toBe(false);
    expect(document.activeElement).toBe(lent.querySelector("[data-box]"));

    host.close();
    expect(lent.parentElement).toBe(host);
    expect(lent.nextElementSibling?.id).toBe("after-lent");
    expect(panel.parentElement).toBe(lent);
    expect(panel.getAttribute("popover")).toBe("manual");
    expect(panel.hidden).toBe(true);
  });

  it("stamps both nodes before the move in and clears them after the move back", () => {
    const { host, lent, panel } = mountLent();
    const stampedAtFocus: (string | null)[] = [];
    lent.querySelector("[data-box]")!.addEventListener("focus", () => {
      stampedAtFocus.push(lent.getAttribute("data-dropdown-host"));
    });
    host.open();
    expect(stampedAtFocus).toEqual(["sheet"]);
    expect(lent.getAttribute("data-dropdown-host")).toBe("sheet");
    expect(panel.getAttribute("data-dropdown-host")).toBe("sheet");

    const stampedAtBlur: (string | null)[] = [];
    lent.querySelector("[data-box]")!.addEventListener("blur", () => {
      stampedAtBlur.push(lent.getAttribute("data-dropdown-host"));
    });
    host.close();
    expect(stampedAtBlur.every((stamp) => stamp === "sheet")).toBe(true);
    expect(lent.hasAttribute("data-dropdown-host")).toBe(false);
    expect(panel.hasAttribute("data-dropdown-host")).toBe(false);
  });

  it("returns focus to the behavior's opener after a code open", () => {
    const { host, face } = mountLent();
    host.open();
    host.close();
    expect(document.activeElement).toBe(face);
  });

  it("keeps a stated opener", () => {
    const { host } = mountLent();
    const other = document.createElement("button");
    document.body.append(other);
    host.open(other);
    host.close();
    expect(document.activeElement).toBe(other);
  });

  it("opens anchored when wide, nothing moved", () => {
    narrow = false;
    const { host, lent, panel, dialog } = mountLent();
    host.open();
    expect(dialog.open).toBe(false);
    expect(lent.parentElement).toBe(host);
    expect(lent.hasAttribute("data-dropdown-host")).toBe(false);
    expect(panel.hidden).toBe(false);
  });
});

describe("an open while another sheet leaves", () => {
  beforeEach(() => {
    reducedMotion = false;
  });

  it("is retried once the layer settles", () => {
    document.body.innerHTML = fixture() + lentFixture();
    const [first, second] = [...document.querySelectorAll("drop-down")];
    for (const host of [first, second]) {
      host.querySelector<HTMLElement>("[data-dropdown-narrow]")!.getClientRects = () =>
        [new DOMRect(0, 0, 0, 0)] as unknown as DOMRectList;
    }
    const secondDialog = second.querySelector("dialog")!;
    first.open();
    first.close();
    second.open();
    expect(secondDialog.open).toBe(false);
    expect(second.querySelector("#lent")!.parentElement).toBe(second);

    vi.advanceTimersByTime(300);
    expect(secondDialog.open).toBe(true);
    expect(second.isOpen()).toBe(true);
  });

  it("is dropped when closed before the layer settles", () => {
    document.body.innerHTML = fixture() + lentFixture();
    const [first, second] = [...document.querySelectorAll("drop-down")];
    for (const host of [first, second]) {
      host.querySelector<HTMLElement>("[data-dropdown-narrow]")!.getClientRects = () =>
        [new DOMRect(0, 0, 0, 0)] as unknown as DOMRectList;
    }
    first.open();
    first.close();
    second.open();
    second.close();
    vi.advanceTimersByTime(300);
    expect(second.isOpen()).toBe(false);
  });
});

describe("a sheet and the on-screen keyboard", () => {
  class FakeViewport extends EventTarget {
    height = 768;
    offsetTop = 0;
  }

  it("writes the keyboard inset and visible height while open", () => {
    const viewport = new FakeViewport();
    vi.stubGlobal("visualViewport", viewport);
    const { host, dialog } = mountLent();
    host.open();
    expect(dialog.style.getPropertyValue("--sheet-keyboard-inset")).toBe("0px");
    expect(dialog.style.getPropertyValue("--sheet-visible-height")).toBe("768px");

    viewport.height = 400;
    viewport.offsetTop = 20;
    viewport.dispatchEvent(new Event("resize"));
    vi.advanceTimersToNextFrame();
    expect(dialog.style.getPropertyValue("--sheet-keyboard-inset")).toBe("348px");
    expect(dialog.style.getPropertyValue("--sheet-visible-height")).toBe("400px");

    host.close();
    expect(dialog.style.getPropertyValue("--sheet-keyboard-inset")).toBe("");
    expect(dialog.style.getPropertyValue("--sheet-visible-height")).toBe("");
    viewport.height = 300;
    viewport.dispatchEvent(new Event("scroll"));
    vi.advanceTimersToNextFrame();
    expect(dialog.style.getPropertyValue("--sheet-visible-height")).toBe("");
  });

  it("writes nothing without a visual viewport", () => {
    vi.stubGlobal("visualViewport", undefined);
    const { host, dialog } = mountLent();
    host.open();
    expect(dialog.style.getPropertyValue("--sheet-keyboard-inset")).toBe("");
  });
});

describe("a sheet's edges, lent", () => {
  beforeEach(() => {
    reducedMotion = false;
  });

  function twoHosts(): [DropdownElement, DropdownElement] {
    document.body.innerHTML = fixture() + lentFixture();
    const hosts = [...document.querySelectorAll("drop-down")] as DropdownElement[];
    for (const host of hosts) {
      host.querySelector<HTMLElement>("[data-dropdown-narrow]")!.getClientRects = () =>
        (narrow ? [new DOMRect(0, 0, 0, 0)] : []) as unknown as DOMRectList;
    }
    return [hosts[0], hosts[1]];
  }

  it("opens once for two taps during another leave", () => {
    const [first, second] = twoHosts();
    first.open();
    first.close();
    second.open();
    second.open();
    vi.advanceTimersByTime(300);
    expect(second.isOpen()).toBe(true);
    expect(document.querySelectorAll("dialog[open]")).toHaveLength(1);
  });

  it("opens anchored when the viewport widened during the leave", () => {
    const [first, second] = twoHosts();
    first.open();
    first.close();
    second.open();
    narrow = false;
    vi.advanceTimersByTime(300);
    expect(second.isOpen()).toBe(true);
    expect(second.querySelector("dialog")!.open).toBe(false);
    expect(second.querySelector("#lent")!.parentElement).toBe(second);
  });

  it("reports a retry refused again", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const [first, second] = twoHosts();
    first.open();
    first.close();
    second.open();
    second.querySelector("dialog")!.showModal = () => {
      throw new DOMException("refused", "InvalidStateError");
    };
    vi.advanceTimersByTime(300);
    expect(second.isOpen()).toBe(false);
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("refused again"));
  });
});

describe("a lent sheet that fails", () => {
  it("refuses a lent node that does not hold the menu", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    registerBehavior("test-bad-lent", {
      menuOptions: () => ({ itemSelector: "[data-none]", inlineTrigger: true }),
      sheetLent: (host) => host.querySelector<HTMLElement>("[data-face]")!,
    });
    const { host } = mountLent(
      lentFixture().replace('behavior="test-lent"', 'behavior="test-bad-lent"'),
    );
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("must hold the menu"));
    expect(host.hasAttribute("data-dropdown-sheetless")).toBe(true);
  });

  it("opens again after a return that threw", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { host, lent } = mountLent();
    host.open();
    const home = host;
    const insert = home.insertBefore.bind(home);
    let broken = true;
    home.insertBefore = (<T extends Node>(node: T, child: Node | null): T => {
      if (broken && (node as Node) === lent) throw new DOMException("no", "HierarchyRequestError");
      return insert(node, child);
    }) as typeof home.insertBefore;
    host.close();
    broken = false;
    expect(host.isOpen()).toBe(false);
    host.open();
    expect(host.isOpen()).toBe(true);
  });
});

describe("the keyboard inset, more", () => {
  class FakeViewport extends EventTarget {
    height = 768;
    offsetTop = 0;
  }

  it("follows a scroll while open, clamps, and coalesces", () => {
    const viewport = new FakeViewport();
    vi.stubGlobal("visualViewport", viewport);
    const frames = vi.spyOn(window, "requestAnimationFrame");
    const { host, dialog } = mountLent();
    host.open();
    frames.mockClear();
    viewport.offsetTop = 100;
    viewport.height = 500;
    viewport.dispatchEvent(new Event("scroll"));
    viewport.dispatchEvent(new Event("resize"));
    expect(frames).toHaveBeenCalledOnce();
    vi.advanceTimersToNextFrame();
    expect(dialog.style.getPropertyValue("--sheet-keyboard-inset")).toBe("168px");
    viewport.offsetTop = 400;
    viewport.dispatchEvent(new Event("scroll"));
    vi.advanceTimersToNextFrame();
    expect(dialog.style.getPropertyValue("--sheet-keyboard-inset")).toBe("0px");
  });
});

describe("a move back to the anchored host", () => {
  it("puts focus on the behavior's first focus", () => {
    registerBehavior("test-sheet-focus", {
      sheetFocus: (menu) => menu.querySelector<HTMLElement>("[data-inside]"),
    });
    const { host, toggle, panel } = mount("test-sheet-focus");
    mouseClick(toggle);
    narrow = false;
    resize();
    expect(host.isOpen()).toBe(true);
    expect(document.activeElement).toBe(panel.querySelector("[data-inside]"));
  });
});

function sheetMarkup(title: string, body: string): string {
  return `<dialog data-modal data-dropdown-sheet>
        <div data-sheet-panel>
          <div>
            <button data-sheet-back hidden type="button"><span data-sheet-back-label></span></button>
            <h2 data-dropdown-sheet-title>${title}</h2>
            <button data-modal-dismiss type="button">×</button>
          </div>
          <div data-sheet-body>${body}</div>
        </div>
      </dialog>
      <span data-dropdown-narrow></span>`;
}

/** A sheet whose body holds a nested dropdown with its own sheet. */
function nestedMount(): {
  outerHost: DropdownElement;
  outerToggle: HTMLButtonElement;
  outerDialog: HTMLDialogElement;
  innerHost: DropdownElement;
  innerToggle: HTMLButtonElement;
  innerDialog: HTMLDialogElement;
} {
  const inner = `<drop-down behavior="menu" placement="bottom-start" submenu="false">
      <button data-toggle type="button" aria-expanded="false">Pick</button>
      <div data-menu popover="manual" hidden><button role="menuitem" data-acting type="button">One</button></div>
      ${sheetMarkup("Pick", '<button data-inside-level type="button">Inside</button>')}
    </drop-down>`;
  document.body.innerHTML = `
    <drop-down behavior="menu" placement="bottom-start" submenu="false">
      <button data-toggle type="button" aria-expanded="false">Day</button>
      <div data-menu popover="manual" hidden>${inner}</div>
      ${sheetMarkup("Day", "")}
    </drop-down>`;
  for (const sentinel of document.querySelectorAll<HTMLElement>("[data-dropdown-narrow]")) {
    sentinel.getClientRects = () =>
      (narrow ? [new DOMRect(0, 0, 0, 0)] : []) as unknown as DOMRectList;
  }
  const outerHost = document.querySelector<DropdownElement>("drop-down")!;
  const innerHost = outerHost.querySelector<DropdownElement>("drop-down")!;
  return {
    outerHost,
    outerToggle: outerHost.querySelector<HTMLButtonElement>(":scope > [data-toggle]")!,
    outerDialog: outerHost.querySelector<HTMLDialogElement>(":scope > dialog")!,
    innerHost,
    innerToggle: innerHost.querySelector<HTMLButtonElement>(":scope > [data-toggle]")!,
    innerDialog: innerHost.querySelector<HTMLDialogElement>(":scope > dialog")!,
  };
}

function cancelNative(dialog: HTMLDialogElement): void {
  dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
}

describe("a dropdown sheet inside an open sheet", () => {
  it("opens its own sheet as a level, with a back control naming the sheet below", () => {
    const { outerToggle, outerDialog, innerToggle, innerDialog } = nestedMount();
    mouseClick(outerToggle);
    mouseClick(innerToggle);
    expect(innerDialog.open).toBe(true);
    expect(innerDialog.hasAttribute("data-sheet-level")).toBe(true);
    const back = innerDialog.querySelector<HTMLElement>("[data-sheet-back]")!;
    expect(back.hidden).toBe(false);
    expect(back.getAttribute("aria-label")).toBe("Back to Day");
    expect(back.querySelector("[data-sheet-back-label]")!.textContent).toBe("Day");
    expect(outerDialog.open).toBe(true);
    expect(outerDialog.querySelector<HTMLElement>("[data-sheet-panel]")!.style.visibility).toBe(
      "hidden",
    );
  });

  it("backs out of a level alone on Escape", () => {
    const { outerToggle, outerDialog, innerToggle, innerDialog } = nestedMount();
    mouseClick(outerToggle);
    mouseClick(innerToggle);
    cancelNative(innerDialog);
    expect(innerDialog.open).toBe(false);
    expect(outerDialog.open).toBe(true);
    expect(outerDialog.querySelector<HTMLElement>("[data-sheet-panel]")!.style.visibility).toBe("");
    expect(innerDialog.hasAttribute("data-sheet-level")).toBe(false);
  });

  it("backs out of a level alone through the back control", () => {
    const { outerToggle, outerDialog, innerToggle, innerDialog } = nestedMount();
    mouseClick(outerToggle);
    mouseClick(innerToggle);
    mouseClick(innerDialog.querySelector<HTMLElement>("[data-sheet-back]")!);
    expect(innerDialog.open).toBe(false);
    expect(outerDialog.open).toBe(true);
  });

  it("closes the whole chain on the × of a level", () => {
    const { outerToggle, outerDialog, innerToggle, innerDialog } = nestedMount();
    mouseClick(outerToggle);
    mouseClick(innerToggle);
    mouseClick(innerDialog.querySelector<HTMLElement>("[data-modal-dismiss]")!);
    expect(innerDialog.open).toBe(false);
    expect(outerDialog.open).toBe(false);
  });

  it("closes the whole chain when an acting menu item in a level is clicked", () => {
    const { outerToggle, outerDialog, innerToggle, innerDialog } = nestedMount();
    mouseClick(outerToggle);
    mouseClick(innerToggle);
    mouseClick(innerDialog.querySelector<HTMLElement>("[data-acting]")!);
    expect(innerDialog.open).toBe(false);
    expect(outerDialog.open).toBe(false);
  });

  it("moves only the first host on a widen, and the level closes with it", () => {
    const { outerHost, outerToggle, outerDialog, innerToggle, innerDialog } = nestedMount();
    mouseClick(outerToggle);
    mouseClick(innerToggle);
    narrow = false;
    resize();
    expect(innerDialog.open).toBe(false);
    expect(outerDialog.open).toBe(false);
    expect(outerHost.isOpen()).toBe(true);
    expect(outerHost.querySelector(":scope > [data-menu]")).not.toBeNull();
  });
});
