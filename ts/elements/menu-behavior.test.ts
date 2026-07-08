// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { attachMenu, type MenuController } from "./menu-behavior.js";

function mount(): {
  host: HTMLElement;
  menu: HTMLElement;
  controller: MenuController;
} {
  document.body.innerHTML = `
    <div id="host">
      <button data-toggle type="button">Open</button>
      <div data-menu hidden>
        <button data-inside type="button">×</button>
      </div>
    </div>
    <button id="outside" type="button">elsewhere</button>`;
  const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
  const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
  const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
  const controller = attachMenu(host, toggle, menu);
  controller.bindDocument();
  return { host, menu, controller };
}

function click(element: HTMLElement): void {
  element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("attachMenu outside-click containment", () => {
  it("closes on a click outside the host", () => {
    const { controller } = mount();
    controller.open();
    expect(controller.isOpen()).toBe(true);
    click(document.querySelector("#outside") as HTMLElement);
    expect(controller.isOpen()).toBe(false);
  });

  it("stays open when an inside click synchronously removes its own target", () => {
    // The filter pill × removes the pill during bubble; by the time the
    // document-level guard runs, `host.contains(event.target)` is already
    // false for the detached node. composedPath() is captured at dispatch,
    // so containment must consult it first.
    const { menu, controller } = mount();
    const inside = menu.querySelector<HTMLElement>(
      "[data-inside]",
    ) as HTMLElement;
    inside.addEventListener("click", () => inside.remove());
    controller.open();
    click(inside);
    expect(document.contains(inside)).toBe(false);
    expect(controller.isOpen()).toBe(true);
  });

  it("still closes on outside clicks after an inside self-removing click", () => {
    const { menu, controller } = mount();
    const inside = menu.querySelector<HTMLElement>(
      "[data-inside]",
    ) as HTMLElement;
    inside.addEventListener("click", () => inside.remove());
    controller.open();
    click(inside);
    click(document.querySelector("#outside") as HTMLElement);
    expect(controller.isOpen()).toBe(false);
  });
});

describe("attachMenu toggle-resize reposition (issue #355)", () => {
  it("observes the toggle while open and disconnects on close", () => {
    // A `fixed` panel does not auto-follow the toggle when it grows/shrinks
    // (a multi-select adding/removing a pill), and no scroll/resize fires — so
    // the toggle's box is observed, but only while open to avoid churn.
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
      expect(observe).not.toHaveBeenCalled();
      controller.open();
      expect(observe).toHaveBeenCalledWith(toggle);
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
        <div data-menu hidden></div>
      </div>
      <button id="outside" type="button">elsewhere</button>`;
    const host = document.querySelector<HTMLElement>("#host") as HTMLElement;
    const toggle = host.querySelector<HTMLElement>("[data-toggle]") as HTMLElement;
    const menu = host.querySelector<HTMLElement>("[data-menu]") as HTMLElement;
    const controller = attachMenu(host, toggle, menu, { inlineTrigger: true });
    controller.bindDocument();
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

  it("still closes on an outside click", () => {
    const { controller } = mountInline();
    controller.open();
    click(document.querySelector("#outside") as HTMLElement);
    expect(controller.isOpen()).toBe(false);
  });
});
