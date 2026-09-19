// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { SelectionStatement } from "./selection-statement.js";
// Importing the module defines <selectable-table>.
import "./selectable-table.js";

function mount(keys: string[]): HTMLElement {
  const rows = keys
    .map(
      (key) =>
        `<tr data-selection-key="${key}"><th scope="row">Game ${key}` +
        `<div data-row-summary>2 hours</div></th><td>2025</td></tr>`,
    )
    .join("");
  document.body.innerHTML = `
    <selectable-table filter='{"year":2025}' count="50">
      <table><tbody>${rows}</tbody></table>
      <div data-selection-line>
        <button data-selection-toggle aria-pressed="false">Select</button>
        <div data-selection-controls hidden>
          <input type="checkbox" data-selection-check-all>
          <span data-selection-count>0 selected</span>
          <button data-selection-all-matching>Select all 50 matching</button>
          <button data-selection-clear>Clear</button>
        </div>
        <div data-selection-announcement role="status"></div>
        <template data-selection-checkbox-template>
          <input type="checkbox" data-selection-checkbox>
        </template>
      </div>
    </selectable-table>`;
  return document.querySelector("selectable-table") as HTMLElement;
}

function press(element: HTMLElement | null): void {
  element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

function checkboxes(element: HTMLElement): HTMLInputElement[] {
  return Array.from(
    element.querySelectorAll<HTMLInputElement>("tbody [data-selection-checkbox]"),
  );
}

function tick(element: HTMLElement, index: number, shiftKey = false): void {
  // The dispatched click toggles the box first, as a press does.
  checkboxes(element)[index].dispatchEvent(
    new MouseEvent("click", { bubbles: true, cancelable: true, shiftKey }),
  );
}

function toggle(element: HTMLElement): void {
  press(element.querySelector("[data-selection-toggle]"));
}

function statements(element: HTMLElement): SelectionStatement[] {
  const seen: SelectionStatement[] = [];
  element.addEventListener("selectable-table:change", (event) =>
    seen.push((event as CustomEvent).detail),
  );
  return seen;
}

function announcement(element: HTMLElement): string {
  return (
    element.querySelector("[data-selection-announcement]")?.textContent ?? ""
  );
}

describe("the mode", () => {
  let element: HTMLElement;

  beforeEach(() => {
    element = mount(["a", "b", "c"]);
  });

  it("renders no checkbox until Select is pressed", () => {
    expect(checkboxes(element)).toHaveLength(0);
  });

  it("builds one checkbox per row, named by the row", () => {
    toggle(element);
    expect(checkboxes(element)).toHaveLength(3);
    expect(checkboxes(element)[0].getAttribute("aria-label")).toBe("Game a");
  });

  it("takes every checkbox back when it turns off", () => {
    toggle(element);
    tick(element, 0);
    toggle(element);
    expect(checkboxes(element)).toHaveLength(0);
  });

  it("clears the selection when it turns off", () => {
    toggle(element);
    tick(element, 0);
    toggle(element);
    const seen = statements(element);
    toggle(element);
    expect(seen[seen.length - 1]).toEqual({ keys: [] });
  });

  it("presses the toggle", () => {
    toggle(element);
    expect(
      element.querySelector("[data-selection-toggle]")?.getAttribute("aria-pressed"),
    ).toBe("true");
    expect(element.getAttribute("data-selection-mode")).toBe("on");
  });
});

describe("the selection", () => {
  let element: HTMLElement;

  beforeEach(() => {
    element = mount(["a", "b", "c", "d"]);
    toggle(element);
  });

  it("states the keys a person marked", () => {
    const seen = statements(element);
    tick(element, 0);
    expect(seen[seen.length - 1]).toEqual({ keys: ["a"] });
  });

  it("takes the range from the anchor on a shift-click", () => {
    const seen = statements(element);
    tick(element, 1);
    tick(element, 3, true);
    expect(seen[seen.length - 1]).toEqual({ keys: ["b", "c", "d"] });
  });

  it("takes the same range from the keyboard, the anchor marked once", () => {
    const seen = statements(element);
    tick(element, 1);
    const target = checkboxes(element)[3];
    const event = new KeyboardEvent("keydown", {
      key: " ",
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    target.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(seen[seen.length - 1]).toEqual({ keys: ["b", "c", "d"] });
  });

  it("checks every row on the page", () => {
    const seen = statements(element);
    const checkAll = element.querySelector<HTMLInputElement>(
      "[data-selection-check-all]",
    );
    checkAll!.checked = true;
    checkAll!.dispatchEvent(new Event("change", { bubbles: true }));
    expect(seen[seen.length - 1]).toEqual({ keys: ["a", "b", "c", "d"] });
  });

  it("reads indeterminate with one row of the page unmarked", () => {
    tick(element, 0);
    const checkAll = element.querySelector<HTMLInputElement>(
      "[data-selection-check-all]",
    );
    expect(checkAll!.indeterminate).toBe(true);
  });

  it("states the scope and its exclusions", () => {
    const seen = statements(element);
    press(element.querySelector("[data-selection-all-matching]"));
    tick(element, 1);
    expect(seen[seen.length - 1]).toEqual({
      all: true,
      filter: '{"year":2025}',
      count: 50,
      except: ["b"],
    });
  });

  it("counts the matching set minus its exclusions", () => {
    press(element.querySelector("[data-selection-all-matching]"));
    tick(element, 1);
    expect(
      element.querySelector("[data-selection-count]")?.textContent,
    ).toBe("49 selected");
  });

  it("empties on Clear", () => {
    const seen = statements(element);
    tick(element, 0);
    press(element.querySelector("[data-selection-clear]"));
    expect(seen[seen.length - 1]).toEqual({ keys: [] });
  });
});

describe("Escape", () => {
  it("clears the selection", () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    element.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
    expect(announcement(element)).toBe("Selection cleared.");
  });

  it("changes nothing when a menu answered it first", () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    const event = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    event.preventDefault();
    element.dispatchEvent(event);
    expect(announcement(element)).not.toBe("Selection cleared.");
    expect(checkboxes(element)[0].checked).toBe(true);
  });
});

describe("a row that arrives", () => {
  it("is decorated and keeps the mark its key held", async () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    const body = element.querySelector("tbody")!;
    const row = body.rows[0];
    row.remove();
    body.insertBefore(row, body.firstChild);
    await Promise.resolve();
    expect(checkboxes(element)).toHaveLength(2);
    expect(checkboxes(element)[0].checked).toBe(true);
  });

  it("takes a key the table no longer holds out of the selection", async () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    const seen = statements(element);
    element.querySelector("tbody")!.rows[0].remove();
    await Promise.resolve();
    expect(seen[seen.length - 1]).toEqual({ keys: [] });
  });
});

describe("the announcement", () => {
  it("says nothing on a single tick", () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    expect(announcement(element)).toBe("Selecting rows.");
  });

  it("speaks at each change of scope", () => {
    const element = mount(["a", "b"]);
    toggle(element);
    press(element.querySelector("[data-selection-all-matching]"));
    expect(announcement(element)).toBe(
      "50 selected, every row matching the filter.",
    );
    press(element.querySelector("[data-selection-clear]"));
    expect(announcement(element)).toBe("Selection cleared.");
  });
});
