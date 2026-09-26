// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { followPointer } from "./pointer-follow.js";

// jsdom drops pointerType; pin it.
function move(target: Element, pointerType: string, x: number, y: number): void {
  const event = new MouseEvent("pointermove", { bubbles: true, clientX: x, clientY: y });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  target.dispatchEvent(event);
}

function mount(): { list: HTMLElement; items: HTMLElement[] } {
  document.body.innerHTML = `
    <ul id="list">
      <li data-item><span>One</span></li>
      <li data-item>Two</li>
      <li>Heading</li>
    </ul>`;
  const list = document.getElementById("list")!;
  return { list, items: Array.from(list.querySelectorAll<HTMLElement>("li")) };
}

describe("followPointer", () => {
  let activated: HTMLElement[];
  beforeEach(() => (activated = []));

  it("a mouse move activates the item under it", () => {
    const { list, items } = mount();
    followPointer(list, "[data-item]", (item) => activated.push(item));
    move(items[0].querySelector("span")!, "mouse", 1, 1);
    move(items[1], "mouse", 1, 20);
    expect(activated).toEqual([items[0], items[1]]);
  });

  it("a move off every item activates nothing", () => {
    const { list, items } = mount();
    followPointer(list, "[data-item]", (item) => activated.push(item));
    move(items[2], "mouse", 1, 40);
    expect(activated).toEqual([]);
  });

  it("a touch or pen move activates nothing", () => {
    const { list, items } = mount();
    followPointer(list, "[data-item]", (item) => activated.push(item));
    move(items[0], "touch", 1, 1);
    move(items[0], "pen", 2, 2);
    expect(activated).toEqual([]);
  });

  it("a move at the last position activates nothing", () => {
    const { list, items } = mount();
    followPointer(list, "[data-item]", (item) => activated.push(item));
    move(items[0], "mouse", 5, 5);
    // Content scrolled under a still cursor.
    move(items[1], "mouse", 5, 5);
    expect(activated).toEqual([items[0]]);
  });

  it("the disposer detaches", () => {
    const { list, items } = mount();
    const dispose = followPointer(list, "[data-item]", (item) => activated.push(item));
    dispose();
    move(items[0], "mouse", 1, 1);
    expect(activated).toEqual([]);
  });
});
