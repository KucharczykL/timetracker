// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
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
