// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./drop-down.js";
import "./settings-section-nav.js";

interface NavFixture {
  nav: HTMLElement & { syncLayout: () => void };
  rail: HTMLElement;
  list: HTMLElement;
  sheetHost: HTMLElement;
  destination: HTMLElement;
  items: HTMLElement[];
  setWide: (wide: boolean) => void;
}

async function mountNav(): Promise<NavFixture> {
  document.body.innerHTML = `
    <settings-section-nav>
      <nav data-section-nav-rail aria-label="Settings sections">
        <ul data-section-nav-list>
          <li data-section-nav-item id="one"><a href="#one">General</a></li>
          <li data-section-nav-item id="two"><a href="#two">Appearance</a></li>
          <li data-section-nav-item id="three"><a href="#three">Privacy</a></li>
        </ul>
      </nav>
      <div data-section-nav-sheet hidden>
        <drop-down behavior="sheet" placement="bottom-start" submenu="false">
          <button data-toggle aria-expanded="false">Settings sections</button>
          <dialog data-menu data-bottom-sheet>
            <div data-sheet-panel>
              <button data-sheet-dismiss>Close</button>
              <nav data-section-nav-sheet-destination></nav>
            </div>
          </dialog>
        </drop-down>
      </div>
      <span data-section-nav-wide></span>
    </settings-section-nav>`;
  const nav = document.querySelector("settings-section-nav") as NavFixture["nav"];
  const rail = nav.querySelector<HTMLElement>("[data-section-nav-rail]")!;
  const list = nav.querySelector<HTMLElement>("[data-section-nav-list]")!;
  const sheetHost = nav.querySelector<HTMLElement>("[data-section-nav-sheet]")!;
  const destination = nav.querySelector<HTMLElement>(
    "[data-section-nav-sheet-destination]",
  )!;
  const sentinel = nav.querySelector<HTMLElement>("[data-section-nav-wide]")!;
  const items = Array.from(nav.querySelectorAll<HTMLElement>("[data-section-nav-item]"));
  let wide = false;
  sentinel.getClientRects = () =>
    (wide ? ([{}] as unknown as DOMRectList) : ([] as unknown as DOMRectList));

  // connectedCallback waits until the already-imported <drop-down> definition
  // is available before replacing the visible no-JS fallback.
  await customElements.whenDefined("drop-down");
  await Promise.resolve();
  nav.syncLayout();
  return {
    nav,
    rail,
    list,
    sheetHost,
    destination,
    items,
    setWide: (value) => (wide = value),
  };
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("<settings-section-nav> same-DOM sheet/rail layout", () => {
  it("moves the complete plain-navigation list into the mobile sheet", async () => {
    const fixture = await mountNav();

    expect(fixture.rail.hidden).toBe(true);
    expect(fixture.sheetHost.hidden).toBe(false);
    expect(fixture.list.parentElement).toBe(fixture.destination);
    expect(Array.from(fixture.list.children)).toEqual(fixture.items);
    for (const item of fixture.items) {
      expect(item.hasAttribute("role")).toBe(false);
      expect(item.querySelector("a")?.hasAttribute("role")).toBe(false);
      expect(item.querySelector("a")?.hasAttribute("tabindex")).toBe(false);
    }
  });

  it("restores the same list and anchors to the desktop rail", async () => {
    const fixture = await mountNav();
    const originalList = fixture.list;
    const originalItems = [...fixture.items];

    fixture.setWide(true);
    fixture.nav.syncLayout();

    expect(fixture.rail.hidden).toBe(false);
    expect(fixture.sheetHost.hidden).toBe(true);
    expect(fixture.list).toBe(originalList);
    expect(fixture.list.parentElement).toBe(fixture.rail);
    expect(Array.from(fixture.list.children)).toEqual(originalItems);
  });

  it("restores the accessible inline fallback when disconnected", async () => {
    const fixture = await mountNav();
    fixture.nav.remove();

    expect(fixture.rail.hidden).toBe(false);
    expect(fixture.sheetHost.hidden).toBe(true);
    expect(fixture.list.parentElement).toBe(fixture.rail);
  });
});
