// @vitest-environment jsdom
/** The tray's priority-plus overflow: stubbed-width layout math.
 *
 * jsdom has no layout engine, so every width the element reads is stubbed and
 * the layout is called rather than waited on.
 */
import { beforeEach, describe, expect, it } from "vitest";
import "./selection-actions.js";

interface TrayFixture {
  tray: HTMLElement & { layoutActs: () => void };
  line: HTMLElement;
  row: HTMLElement;
  host: HTMLElement;
  items: HTMLElement;
  acts: HTMLButtonElement[];
  setRowWidth: (width: number) => void;
}

function stubWidth(element: HTMLElement, width: number): void {
  Object.defineProperty(element, "offsetWidth", {
    get: () => width,
    configurable: true,
  });
}

const ACTS = ["Move to playthrough…", "Finish", "Record", "Remove"];

function mountTray(): TrayFixture {
  const submits = ACTS.map(
    (label, index) =>
      `<button type="submit" data-selection-act formaction="/bulk/act-${index}/"` +
      ` disabled>${label}</button>`,
  ).join("");
  document.body.innerHTML = `
    <div data-selection-line hidden>
      <div data-selection-controls>
        <span data-selection-count>0 selected</span>
        <button data-selection-clear>Clear</button>
        <div data-selection-actions>
          <selection-actions>
            <form data-selection-actions-form data-selection-acts-row method="post">
              <input type="hidden" data-selection-statement name="selection">
              ${submits}
              <div class="hidden" data-selection-overflow>
                <div data-selection-overflow-items></div>
              </div>
            </form>
          </selection-actions>
        </div>
      </div>
    </div>`;
  const tray = document.querySelector("selection-actions") as TrayFixture["tray"];
  const line = document.querySelector<HTMLElement>("[data-selection-line]")!;
  const controls = document.querySelector<HTMLElement>("[data-selection-controls]")!;
  const host = tray.querySelector<HTMLElement>("[data-selection-overflow]")!;
  const items = tray.querySelector<HTMLElement>("[data-selection-overflow-items]")!;
  const acts = Array.from(
    tray.querySelectorAll<HTMLButtonElement>("[data-selection-act]"),
  );
  acts.forEach((act) => stubWidth(act, 150));
  stubWidth(host, 40);
  stubWidth(controls.querySelector<HTMLElement>("[data-selection-count]")!, 80);
  stubWidth(controls.querySelector<HTMLElement>("[data-selection-clear]")!, 60);
  let lineWidth = 0;
  Object.defineProperty(line, "clientWidth", {
    get: () => lineWidth,
    configurable: true,
  });
  return {
    tray,
    line,
    row: controls,
    host,
    items,
    acts,
    setRowWidth: (width: number) => {
      lineWidth = width;
    },
  };
}

//: The line's width is the room the acts lay out in. The controls row is a
//: flex item, so its own width follows its content: measuring there shrinks
//: as acts leave and every act ends up behind the trigger.
/** What the table does when the mode turns on. */
function reveal(fixture: TrayFixture, width: number): void {
  fixture.line.removeAttribute("hidden");
  fixture.setRowWidth(width);
  fixture.tray.layoutActs();
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("selection-actions priority-plus overflow", () => {
  it("keeps every act in the row where they fit", () => {
    const fixture = mountTray();

    reveal(fixture, 1000);

    fixture.acts.forEach((act) => expect(act.parentElement).toBe(fixture.tray.querySelector("form")));
    expect(fixture.items.children.length).toBe(0);
    expect(fixture.host.classList.contains("hidden")).toBe(true);
  });

  it("moves the acts that do not fit, rightmost first", () => {
    const fixture = mountTray();

    // furniture 80 + 60 = 140, overflow 40; two 150px acts fit in 480.
    reveal(fixture, 480);

    expect(fixture.acts[0].parentElement).not.toBe(fixture.items);
    expect(fixture.acts[1].parentElement).not.toBe(fixture.items);
    expect(fixture.acts[2].parentElement).toBe(fixture.items);
    expect(fixture.acts[3].parentElement).toBe(fixture.items);
    expect(fixture.host.classList.contains("hidden")).toBe(false);
  });

  it("states the overflowed acts in declaration order", () => {
    const fixture = mountTray();

    reveal(fixture, 480);

    expect(
      Array.from(fixture.items.children).map((node) => node.textContent?.trim()),
    ).toEqual(["Record", "Remove"]);
  });

  it("moves them back when the row widens", () => {
    const fixture = mountTray();
    reveal(fixture, 480);

    fixture.setRowWidth(1000);
    fixture.tray.layoutActs();

    fixture.acts.forEach((act) => expect(fixture.items.contains(act)).toBe(false));
    expect(fixture.host.classList.contains("hidden")).toBe(true);
  });

  it("keeps the overflowed acts inside the one form", () => {
    const fixture = mountTray();

    reveal(fixture, 480);

    const form = fixture.tray.querySelector("form")!;
    fixture.acts.forEach((act) => expect(form.contains(act)).toBe(true));
  });

  it("measures nothing while the line is hidden", () => {
    const fixture = mountTray();

    //: Every width reads 0 under `display:none`, so a layout that measured
    //: here would cache zeros and spill every act for the page's life.
    fixture.setRowWidth(0);
    fixture.tray.layoutActs();

    expect(fixture.items.children.length).toBe(0);

    reveal(fixture, 1000);

    expect(fixture.items.children.length).toBe(0);
    fixture.acts.forEach((act) => expect(fixture.items.contains(act)).toBe(false));
  });

  it("re-reads the furniture when the count's text grows", () => {
    // "1 selected" becomes "1,284 selected" on Select all matching. The line
    // never changes size, so a latched furniture width would leave the last
    // act in a row that has no room for it — and the shell clips.
    const fixture = mountTray();
    //: 600 of acts and 140 of furniture fit in 800.
    reveal(fixture, 800);
    expect(fixture.acts[3].parentElement).not.toBe(fixture.items);

    stubWidth(
      fixture.row.querySelector<HTMLElement>("[data-selection-count]")!,
      230,
    );
    fixture.tray.layoutActs();

    expect(fixture.acts[3].parentElement).toBe(fixture.items);
  });

  it("measures the natural widths once the line is shown", () => {
    const fixture = mountTray();
    fixture.setRowWidth(0);
    fixture.tray.layoutActs();

    reveal(fixture, 480);

    expect(fixture.acts[2].parentElement).toBe(fixture.items);
  });
});
