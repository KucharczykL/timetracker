// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attachMenu, type MenuController } from "./menu-behavior.js";
import { openSurfaces, resetSurfacesForTests } from "./surface-stack.js";

function mount(): {
  host: HTMLElement;
  menu: HTMLElement;
  controller: MenuController;
} {
  document.body.innerHTML = `
    <div id="host">
      <button data-toggle type="button">Open</button>
      <div data-menu popover="manual" hidden>
        <button data-inside type="button">×</button>
      </div>
    </div>
    <button id="outside" type="button">elsewhere</button>`;
  const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
  const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
  const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
  const controller = attachMenu(host, toggle, menu);
  return { host, menu, controller };
}

function mountKeepOpenOnTab(): {
  menu: HTMLElement;
  controller: MenuController;
} {
  document.body.innerHTML = `
    <div id="host">
      <button data-toggle type="button">Open</button>
      <div data-menu popover="manual" hidden>
        <button data-first type="button">first</button>
        <button data-second type="button">second</button>
      </div>
    </div>
    <button id="outside" type="button">elsewhere</button>`;
  const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
  const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
  const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
  const controller = attachMenu(host, toggle, menu, {
    inlineTrigger: true,
    keepOpenOnTab: true,
  });
  return { menu, controller };
}

function click(element: HTMLElement): void {
  element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

// A press is pointerdown then pointerup, then click.
function press(element: HTMLElement): void {
  const init = { bubbles: true, composed: true, isPrimary: true, button: 0, pointerId: 1 };
  element.dispatchEvent(new PointerEvent("pointerdown", init));
  element.dispatchEvent(new PointerEvent("pointerup", init));
  click(element);
}

afterEach(() => {
  resetSurfacesForTests();
  document.body.innerHTML = "";
});

describe("attachMenu on the surface stack", () => {
  function escape(element: HTMLElement): KeyboardEvent {
    const event = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    element.dispatchEvent(event);
    return event;
  }

  it("closes on a press outside the host", () => {
    const { controller } = mount();
    controller.open();
    expect(openSurfaces()).toHaveLength(1);
    press(document.querySelector("#outside") as HTMLElement);
    expect(controller.isOpen()).toBe(false);
    expect(openSurfaces()).toEqual([]);
  });

  it("stays open when an inside press removes its own target", () => {
    const { menu, controller } = mount();
    const inside = menu.querySelector<HTMLElement>("[data-inside]") as HTMLElement;
    inside.addEventListener("pointerdown", () => inside.remove());
    controller.open();
    const init = { bubbles: true, composed: true, isPrimary: true, button: 0, pointerId: 1 };
    inside.dispatchEvent(new PointerEvent("pointerdown", init));
    document.body.dispatchEvent(new PointerEvent("pointerup", init));
    expect(controller.isOpen()).toBe(true);
  });

  it("closes, and stays closed, on a press of its own toggle", () => {
    const { host, controller } = mount();
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    controller.open();
    press(toggle);
    expect(controller.isOpen()).toBe(false);
    expect(openSurfaces()).toEqual([]);
  });

  it("closes an open submenu with its parent", () => {
    document.body.innerHTML = `
      <div id="parent">
        <button data-toggle type="button">Open</button>
        <div data-menu popover="manual" hidden>
          <div id="child">
            <button data-child-toggle type="button">More</button>
            <div data-child-menu popover="manual" hidden><button>Deep</button></div>
          </div>
        </div>
      </div>`;
    const parentHost = document.querySelector<HTMLElement>("#parent")!;
    const childHost = document.querySelector<HTMLElement>("#child")!;
    const parent = attachMenu(
      parentHost,
      parentHost.querySelector<HTMLElement>("[data-toggle]")!,
      parentHost.querySelector<HTMLElement>("[data-menu]")!,
    );
    const child = attachMenu(
      childHost,
      childHost.querySelector<HTMLElement>("[data-child-toggle]")!,
      childHost.querySelector<HTMLElement>("[data-child-menu]")!,
      { placement: "right-start", submenu: true },
    );
    parent.open();
    child.open();
    expect(openSurfaces()).toHaveLength(2);
    press(document.body);
    expect(child.isOpen()).toBe(false);
    expect(parent.isOpen()).toBe(false);
    expect(openSurfaces()).toEqual([]);
  });

  it("closes on Escape and returns focus to the toggle", () => {
    const { host, menu } = mount();
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    click(toggle);
    const inside = menu.querySelector<HTMLElement>("[data-inside]") as HTMLElement;
    inside.focus();
    const event = escape(inside);
    expect(menu.hidden).toBe(true);
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(toggle);
  });

  it("leaves an Escape that closed nothing to its host", () => {
    const { host } = mount();
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    expect(escape(toggle).defaultPrevented).toBe(false);
  });

  it("does not open a disconnected panel", () => {
    const { host, controller } = mount();
    host.remove();
    controller.open();
    expect(controller.isOpen()).toBe(false);
    expect(openSurfaces()).toEqual([]);
  });
});

describe("attachMenu toggle-resize reposition (issue #355)", () => {
  it("observes the toggle and menu while open and disconnects on close", () => {
    // A `fixed` panel does not auto-follow the toggle when it grows/shrinks
    // (a multi-select adding/removing a pill), and no scroll/resize fires — so
    // the toggle's box is observed. The menu itself is also observed so that
    // content-height changes (e.g. filtering a combobox) reposition a flipped
    // panel — without a second observe(menu) the stale top would float away from
    // the trigger (issue #443). Both are observed only while open to avoid churn.
    const observe = vi.fn();
    const disconnect = vi.fn();
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      observe = observe;
      disconnect = disconnect;
      unobserve = vi.fn();
    } as unknown as typeof ResizeObserver;
    try {
      const { controller } = mount();
      const toggle = document.querySelector("[data-toggle]") as HTMLElement;
      const menu = document.querySelector("[data-menu]") as HTMLElement;
      expect(observe).not.toHaveBeenCalled();
      controller.open();
      expect(observe).toHaveBeenCalledWith(toggle);
      expect(observe).toHaveBeenCalledWith(menu);
      expect(disconnect).not.toHaveBeenCalled();
      controller.close();
      expect(disconnect).toHaveBeenCalledTimes(1);
    } finally {
      globalThis.ResizeObserver = original;
    }
  });
});

describe("attachMenu inlineTrigger (issue #348)", () => {
  function mountInline(): {
    host: HTMLElement;
    toggle: HTMLElement;
    controller: MenuController;
  } {
    document.body.innerHTML = `
      <div id="host">
        <div data-toggle><input data-search-select-search /></div>
        <div data-menu popover="manual" hidden></div>
      </div>
      <button id="outside" type="button">elsewhere</button>`;
    const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
    const controller = attachMenu(host, toggle, menu, { inlineTrigger: true });
    return { host, toggle, controller };
  }

  it("does not open on a toggle click (the input's focus is the trigger)", () => {
    const { toggle, controller } = mountInline();
    click(toggle);
    expect(controller.isOpen()).toBe(false);
  });

  it("does not toggle-close when clicked while open", () => {
    // A click inside the field (a pill, the input) must never close the panel.
    const { toggle, controller } = mountInline();
    controller.open();
    click(toggle);
    expect(controller.isOpen()).toBe(true);
  });

  it("never writes aria-expanded on the toggle (the widget owns it on the input)", () => {
    const { toggle, controller } = mountInline();
    controller.open();
    expect(toggle.hasAttribute("aria-expanded")).toBe(false);
    controller.close();
    expect(toggle.hasAttribute("aria-expanded")).toBe(false);
  });

  it("still closes on an outside press", () => {
    const { controller } = mountInline();
    controller.open();
    press(document.querySelector("#outside") as HTMLElement);
    expect(controller.isOpen()).toBe(false);
  });
});

describe("attachMenu keepOpenOnTab", () => {
  it("keeps an itemless panel open while focus moves inside it", () => {
    const { menu, controller } = mountKeepOpenOnTab();
    const first = menu.querySelector("[data-first]") as HTMLElement;
    const second = menu.querySelector("[data-second]") as HTMLElement;
    controller.open();
    first.focus();
    first.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    first.dispatchEvent(
      new FocusEvent("focusout", { bubbles: true, relatedTarget: second }),
    );
    expect(controller.isOpen()).toBe(true);
  });

  it("closes when focus leaves the panel or has no destination", async () => {
    const { menu, controller } = mountKeepOpenOnTab();
    const first = menu.querySelector("[data-first]") as HTMLElement;
    const outside = document.querySelector("#outside") as HTMLElement;
    controller.open();
    first.dispatchEvent(
      new FocusEvent("focusout", { bubbles: true, relatedTarget: outside }),
    );
    expect(controller.isOpen()).toBe(false);

    controller.open();
    first.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    await Promise.resolve();
    expect(controller.isOpen()).toBe(false);
  });

  it("does not close when a browser omits relatedTarget for an in-panel move", async () => {
    const { menu, controller } = mountKeepOpenOnTab();
    const first = menu.querySelector("[data-first]") as HTMLElement;
    const second = menu.querySelector("[data-second]") as HTMLElement;
    controller.open();
    first.focus();
    second.focus();
    first.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    await Promise.resolve();
    expect(controller.isOpen()).toBe(true);
  });

  it("stays open when an activated control becomes disabled during its update", async () => {
    const { menu, controller } = mountKeepOpenOnTab();
    const first = menu.querySelector("[data-first]") as HTMLButtonElement;
    const outside = document.querySelector("#outside") as HTMLElement;
    controller.open();
    first.focus();
    first.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
    outside.focus();
    first.click();
    first.disabled = true;
    first.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    await Promise.resolve();
    expect(controller.isOpen()).toBe(true);
  });

  it("stays open when a focused control is detached during its own update", () => {
    const { menu, controller } = mountKeepOpenOnTab();
    const first = menu.querySelector("[data-first]") as HTMLElement;
    controller.open();
    first.addEventListener("focusout", () => first.remove());
    first.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    first.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    first.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(controller.isOpen()).toBe(true);
  });

  it("lets its own toggle close it when focus sits inside the panel", async () => {
    document.body.innerHTML = `
      <div id="host">
        <button data-toggle type="button">Open</button>
        <div data-menu popover="manual" hidden><button data-first type="button">first</button></div>
      </div>`;
    const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
    const controller = attachMenu(host, toggle, menu, { keepOpenOnTab: true });
    toggle.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
    const first = menu.querySelector("[data-first]") as HTMLElement;
    first.focus();

    // The mousedown on the toggle moves focus there before its click.
    toggle.focus();
    first.dispatchEvent(
      new FocusEvent("focusout", { bubbles: true, relatedTarget: toggle }),
    );
    await Promise.resolve();
    expect(controller.isOpen()).toBe(true);
    toggle.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
    expect(controller.isOpen()).toBe(false);
  });

  it("keeps the default Tab-close behavior when the option is absent", () => {
    const { menu, controller } = mount();
    controller.open();
    const inside = menu.querySelector("[data-inside]") as HTMLElement;
    inside.focus();
    inside.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    expect(controller.isOpen()).toBe(false);
  });
});

describe("attachMenu pointer follow", () => {
  function mountMenu(): { menu: HTMLElement; items: HTMLElement[]; controller: MenuController } {
    document.body.innerHTML = `
      <div id="host">
        <button data-toggle type="button">Open</button>
        <div data-menu role="menu" popover="manual" hidden>
          <button role="menuitem" type="button">one</button>
          <button role="menuitem" type="button">two</button>
        </div>
      </div>`;
    const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
    const controller = attachMenu(host, toggle, menu);
    const items = Array.from(menu.querySelectorAll<HTMLElement>("[role=menuitem]"));
    return { menu, items, controller };
  }

  function move(target: Element, x: number, y: number): void {
    const event = new MouseEvent("pointermove", { bubbles: true, clientX: x, clientY: y });
    Object.defineProperty(event, "pointerType", { value: "mouse" });
    target.dispatchEvent(event);
  }

  it("a hover focuses the item without scrolling it into view", () => {
    const { items, controller } = mountMenu();
    controller.open();
    const focus = vi.spyOn(items[1], "focus");
    move(items[1], 3, 30);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(document.activeElement).toBe(items[1]);
  });

  it("a still cursor over scrolled content moves nothing", () => {
    const { items, controller } = mountMenu();
    controller.open();
    move(items[0], 3, 10);
    move(items[1], 3, 10);
    expect(document.activeElement).toBe(items[0]);
  });
});

describe("attachMenu open state and opener", () => {
  it("stays closed while another host shows its panel", () => {
    const { menu, controller } = mount();
    menu.removeAttribute("popover");
    menu.hidden = false;
    expect(controller.isOpen()).toBe(false);
  });

  it("returns focus to the opener on Escape", () => {
    const { menu, controller } = mount();
    const opener = document.querySelector<HTMLElement>("#outside") as HTMLElement;
    controller.open(opener);
    const inside = menu.querySelector<HTMLElement>("[data-inside]") as HTMLElement;
    inside.focus();
    inside.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
    expect(controller.isOpen()).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("drives the presenter from its toggle", () => {
    document.body.innerHTML = `
      <div id="host">
        <button data-toggle type="button">Open</button>
        <div data-menu popover="manual" hidden></div>
      </div>`;
    const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
    let presenterOpen = false;
    const openedBy: (HTMLElement | undefined)[] = [];
    const presenter: MenuController = {
      open: (opener) => {
        presenterOpen = true;
        openedBy.push(opener);
      },
      close: () => {
        presenterOpen = false;
      },
      isOpen: () => presenterOpen,
      focusFirst: vi.fn(),
    };
    const controller = attachMenu(host, toggle, menu, { presenter: () => presenter });
    const mouseClick = (): boolean =>
      toggle.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
    mouseClick();
    expect(presenterOpen).toBe(true);
    expect(openedBy).toEqual([toggle]);
    expect(controller.isOpen()).toBe(false);
    mouseClick();
    expect(presenterOpen).toBe(false);
    toggle.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }),
    );
    expect(presenterOpen).toBe(true);
    expect(presenter.focusFirst).toHaveBeenCalledOnce();
  });
});

describe("attachMenu close motion", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.documentElement.style.setProperty("--duration-fast-exit", "100ms");
    document.documentElement.style.setProperty("--duration-reduced", "100ms");
  });

  afterEach(() => {
    vi.useRealTimers();
    document.documentElement.removeAttribute("style");
  });

  // An exit animation that never ends holds the leave until the cap.
  function holdExitAnimation(menu: HTMLElement): void {
    Object.defineProperty(menu, "getAnimations", {
      configurable: true,
      value: () => [{ finished: new Promise(() => {}) }],
    });
  }

  it("announces the hide at the start of the close", () => {
    const { host, menu, controller } = mount();
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    controller.open();
    holdExitAnimation(menu);
    const hide = vi.fn();
    host.addEventListener("dropdown:hide", hide);
    controller.close();
    expect(hide).toHaveBeenCalledTimes(1);
    expect(menu.getAttribute("data-motion")).toBe("leaving");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(controller.isOpen()).toBe(false);
  });

  it("keeps the geometry until the leave finishes", () => {
    const { menu, controller } = mount();
    controller.open();
    holdExitAnimation(menu);
    controller.close();
    expect(menu.matches(":popover-open")).toBe(true);
    expect(menu.style.position).toBe("fixed");
    expect(menu.getAttribute("data-side")).toBe("bottom");

    vi.advanceTimersByTime(200);
    expect(menu.hidden).toBe(true);
    expect(menu.style.position).toBe("");
    expect(menu.hasAttribute("data-side")).toBe(false);
  });

  it("reopens during a held leave and keeps the new geometry", () => {
    const { menu, controller } = mount();
    controller.open();
    holdExitAnimation(menu);
    controller.close();
    controller.open();
    vi.advanceTimersByTime(200);
    expect(controller.isOpen()).toBe(true);
    expect(menu.hidden).toBe(false);
    expect(menu.style.position).toBe("fixed");
    expect(menu.getAttribute("data-side")).toBe("bottom");
  });
});
