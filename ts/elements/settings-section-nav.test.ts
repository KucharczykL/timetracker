// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./settings-section-nav.js";

interface NavFixture {
  nav: HTMLElement & { layoutOverflow: () => void };
  row: HTMLElement;
  primary: HTMLElement;
  overflowHost: HTMLElement;
  overflowItems: HTMLElement;
  items: HTMLElement[];
  setWidth: (width: number) => void;
  setWide: (wide: boolean) => void;
}

function stubWidth(element: HTMLElement, width: number): void {
  Object.defineProperty(element, "offsetWidth", {
    get: () => width,
    configurable: true,
  });
}

function mountNav(): NavFixture {
  document.body.innerHTML = `
    <settings-section-nav>
      <nav>
        <div data-section-nav-row>
          <ul data-section-nav-primary>
            <li data-section-nav-item id="one"><a href="#one">General</a></li>
            <li data-section-nav-item id="two"><a href="#two">Appearance</a></li>
            <li data-section-nav-item id="three"><a href="#three">Privacy</a></li>
          </ul>
          <div class="hidden" data-section-nav-overflow>
            <drop-down>
              <button data-toggle></button>
              <div data-menu hidden role="menu"><ul role="presentation"></ul></div>
            </drop-down>
          </div>
        </div>
        <span data-section-nav-wide></span>
      </nav>
    </settings-section-nav>`;
  const nav = document.querySelector("settings-section-nav") as NavFixture["nav"];
  const row = nav.querySelector<HTMLElement>("[data-section-nav-row]")!;
  const primary = nav.querySelector<HTMLElement>("[data-section-nav-primary]")!;
  const overflowHost = nav.querySelector<HTMLElement>(
    "[data-section-nav-overflow]",
  )!;
  const overflowItems = nav.querySelector<HTMLElement>("[data-menu] > ul")!;
  const sentinel = nav.querySelector<HTMLElement>("[data-section-nav-wide]")!;
  const items = Array.from(nav.querySelectorAll<HTMLElement>("[data-section-nav-item]"));
  items.forEach((item) => stubWidth(item, 100));
  stubWidth(overflowHost, 40);
  let rowWidth = 1000;
  let wide = false;
  Object.defineProperty(row, "clientWidth", {
    get: () => rowWidth,
    configurable: true,
  });
  sentinel.getClientRects = () =>
    (wide ? ([{}] as unknown as DOMRectList) : ([] as unknown as DOMRectList));

  // Reconnect so connectedCallback measures the stubbed dimensions.
  nav.remove();
  document.body.appendChild(nav);
  return {
    nav,
    row,
    primary,
    overflowHost,
    overflowItems,
    items,
    setWidth: (width) => (rowWidth = width),
    setWide: (value) => (wide = value),
  };
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("<settings-section-nav> priority-plus layout", () => {
  it("keeps every anchor in the primary mobile row when it fits", () => {
    const fixture = mountNav();
    fixture.setWidth(1000);
    fixture.nav.layoutOverflow();
    expect(fixture.overflowItems.children).toHaveLength(0);
    expect(fixture.overflowHost.classList.contains("hidden")).toBe(true);
    expect(Array.from(fixture.primary.children).map((item) => item.id)).toEqual([
      "one",
      "two",
      "three",
    ]);
  });

  it("moves rightmost anchors, with menu semantics, when narrow", () => {
    const fixture = mountNav();
    fixture.setWidth(180); // 180 - 40 overflow = one 100px item
    fixture.nav.layoutOverflow();
    expect(Array.from(fixture.primary.children).map((item) => item.id)).toEqual([
      "one",
    ]);
    expect(Array.from(fixture.overflowItems.children).map((item) => item.id)).toEqual([
      "two",
      "three",
    ]);
    expect(fixture.overflowHost.classList.contains("hidden")).toBe(false);
    expect(fixture.items[1].getAttribute("role")).toBe("presentation");
    expect(fixture.items[1].querySelector("a")?.getAttribute("role")).toBe(
      "menuitem",
    );
  });

  it("restores the same nodes, order, and plain-nav semantics in wide mode", () => {
    const fixture = mountNav();
    fixture.setWidth(180);
    fixture.nav.layoutOverflow();
    fixture.setWide(true);
    fixture.nav.layoutOverflow();
    expect(Array.from(fixture.primary.children)).toEqual(fixture.items);
    expect(fixture.overflowItems.children).toHaveLength(0);
    expect(fixture.overflowHost.classList.contains("hidden")).toBe(true);
    for (const item of fixture.items) {
      expect(item.hasAttribute("role")).toBe(false);
      expect(item.querySelector("a")?.hasAttribute("role")).toBe(false);
      expect(item.querySelector("a")?.hasAttribute("tabindex")).toBe(false);
    }
  });
});
