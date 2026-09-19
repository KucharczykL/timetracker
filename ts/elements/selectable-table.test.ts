// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { SelectionStatement } from "./selection-statement.js";
// Importing the module defines <selectable-table>.
import "./selectable-table.js";

beforeEach(() => {
  // A selection outlives its page; each case starts clean.
  sessionStorage.clear();
});

function mount(
  keys: string[],
  filter = '{"year":2025}',
  count = "50",
): HTMLElement {
  const rows = keys
    .map(
      (key) =>
        `<tr data-selection-key="${key}"><th scope="row">Game ${key}` +
        `<div data-row-summary>2 hours</div></th><td>2025</td></tr>`,
    )
    .join("");
  document.body.innerHTML = `
    <selectable-table filter='${filter}' count="${count}" scope="lib-1:Games">
      <div data-selection-bar>
        <button data-selection-toggle aria-pressed="false">Select</button>
      </div>
      <table><tbody>${rows}</tbody></table>
      <div data-selection-line hidden>
        <div data-selection-controls>
          <input type="checkbox" data-selection-check-all>
          <span data-selection-count>0 selected</span>
          <button data-selection-all-matching>Select all 50 matching</button>
          <button data-selection-clear>Clear</button>
          <div data-selection-actions></div>
        </div>
        <button data-selection-toggle aria-pressed="false">Select</button>
        <div data-selection-announcement role="status"></div>
        <template data-selection-checkbox-template>
          <input type="checkbox" data-selection-checkbox class="invisible">
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
  press(element.querySelector("[data-selection-bar] [data-selection-toggle]"));
}

/** The checkboxes a reader can see. */
function shownCheckboxes(element: HTMLElement): HTMLInputElement[] {
  return checkboxes(element).filter(
    (checkbox) => !checkbox.classList.contains("invisible"),
  );
}

function statements(element: HTMLElement): SelectionStatement[] {
  const seen: SelectionStatement[] = [];
  element.addEventListener("selectable-table:change", (event) =>
    seen.push((event as CustomEvent).detail),
  );
  return seen;
}

/** Escape decides in the task after the press, so every overlay is heard. */
function settled(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
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

  it("shows no checkbox until Select is pressed", () => {
    expect(checkboxes(element)).toHaveLength(3);
    expect(shownCheckboxes(element)).toHaveLength(0);
  });

  it("shows one checkbox per row, named by the row", () => {
    toggle(element);
    expect(shownCheckboxes(element)).toHaveLength(3);
    expect(checkboxes(element)[0].getAttribute("aria-label")).toBe("Game a");
  });

  it("hides every checkbox again without moving a row", () => {
    toggle(element);
    tick(element, 0);
    toggle(element);
    expect(checkboxes(element)).toHaveLength(3);
    expect(shownCheckboxes(element)).toHaveLength(0);
  });

  it("presses both toggles together", () => {
    toggle(element);
    const pressed = Array.from(
      element.querySelectorAll("[data-selection-toggle]"),
    ).map((button) => button.getAttribute("aria-pressed"));
    expect(pressed).toEqual(["true", "true"]);
  });

  it("keeps the mode on Escape, and only clears the selection", async () => {
    toggle(element);
    tick(element, 0);
    element.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      }),
    );
    await settled();
    expect(element.getAttribute("data-selection-mode")).toBe("on");
    expect(shownCheckboxes(element)).toHaveLength(3);
    expect(checkboxes(element)[0].checked).toBe(false);
  });

  it("shows the line with the mode", () => {
    const line = element.querySelector<HTMLElement>("[data-selection-line]")!;
    expect(line.hidden).toBe(true);
    toggle(element);
    expect(line.hidden).toBe(false);
  });

  it("clears the selection when it turns off", () => {
    toggle(element);
    tick(element, 0);
    toggle(element);
    const seen = statements(element);
    toggle(element);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: [] });
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
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a"] });
  });

  it("takes the range from the anchor on a shift-click", () => {
    const seen = statements(element);
    tick(element, 1);
    tick(element, 3, true);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["b", "c", "d"] });
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
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["b", "c", "d"] });
  });

  it("checks every row on the page", () => {
    const seen = statements(element);
    const checkAll = element.querySelector<HTMLInputElement>(
      "[data-selection-check-all]",
    );
    checkAll!.checked = true;
    checkAll!.dispatchEvent(new Event("change", { bubbles: true }));
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a", "b", "c", "d"] });
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
      mode: "all",
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

  it("clears a range from a row already marked", () => {
    const seen = statements(element);
    const checkAll = element.querySelector<HTMLInputElement>(
      "[data-selection-check-all]",
    );
    checkAll!.checked = true;
    checkAll!.dispatchEvent(new Event("change", { bubbles: true }));
    tick(element, 1);
    tick(element, 3, true);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a"] });
  });

  it("clears the same range from the keyboard", () => {
    const seen = statements(element);
    const checkAll = element.querySelector<HTMLInputElement>(
      "[data-selection-check-all]",
    );
    checkAll!.checked = true;
    checkAll!.dispatchEvent(new Event("change", { bubbles: true }));
    tick(element, 1);
    checkboxes(element)[3].dispatchEvent(
      new KeyboardEvent("keydown", {
        key: " ",
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    );
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a"] });
  });

  it("announces the page a check-all took", () => {
    const checkAll = element.querySelector<HTMLInputElement>(
      "[data-selection-check-all]",
    );
    checkAll!.checked = true;
    checkAll!.dispatchEvent(new Event("change", { bubbles: true }));
    expect(announcement(element)).toBe("4 selected");
  });

  it("forgets the selection when an action is submitted", () => {
    tick(element, 0);
    const actions = element.querySelector("[data-selection-actions]")!;
    const form = document.createElement("form");
    actions.appendChild(form);
    form.dispatchEvent(new Event("submit", { bubbles: true }));
    expect(element.getAttribute("data-selection-mode")).toBe(null);
    expect(sessionStorage.length).toBe(0);
  });

  it("empties on Clear", () => {
    const seen = statements(element);
    tick(element, 0);
    press(element.querySelector("[data-selection-clear]"));
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: [] });
  });
});

describe("Escape", () => {
  it("clears the selection", async () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    element.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
    await settled();
    expect(announcement(element)).toBe("Selection cleared.");
  });

  it("waits for the whole press, so a document-level closer is heard", async () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    // A tooltip and the date pickers close from a listener on the document,
    // which runs after this element's own.
    const closer = (event: Event) => event.preventDefault();
    document.addEventListener("keydown", closer);
    element.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
    await settled();
    document.removeEventListener("keydown", closer);
    expect(checkboxes(element)[0].checked).toBe(true);
  });

  it("changes nothing when a menu answered it first", async () => {
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
    await settled();
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
    expect(shownCheckboxes(element)).toHaveLength(2);
    expect(checkboxes(element)[0].checked).toBe(true);
  });

  it("takes a key the table no longer holds out of the selection", async () => {
    const element = mount(["a", "b"]);
    toggle(element);
    tick(element, 0);
    const seen = statements(element);
    element.querySelector("tbody")!.rows[0].remove();
    await Promise.resolve();
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: [] });
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

describe("a selection that outlives the page", () => {
  it("says nothing on arrival: the page came that way", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);
    const second = mount(["c", "d"]);
    expect(announcement(second)).toBe("");
  });

  it("states itself to a listener that was there before the page", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);

    const seen: unknown[] = [];
    const listener = (event: Event) => seen.push((event as CustomEvent).detail);
    document.addEventListener("selectable-table:change", listener);
    mount(["c", "d"]);
    document.removeEventListener("selectable-table:change", listener);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a"] });
  });

  it("brings a scope back, with every row of the next page marked", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    press(first.querySelector("[data-selection-all-matching]"));

    const second = mount(["c", "d"]);
    expect(second.getAttribute("data-selection-mode")).toBe("on");
    expect(checkboxes(second).every((box) => box.checked)).toBe(true);
    expect(
      second.querySelector("[data-selection-count]")?.textContent,
    ).toBe("50 selected");
  });

  it("refuses a scope on a page that states no count", () => {
    // Rows per page raised to the whole list: same path, same filter, but the
    // count that named the scope is gone, so the scope is not the same scope.
    const first = mount(["a", "b"]);
    toggle(first);
    press(first.querySelector("[data-selection-all-matching]"));

    const whole = mount(["a", "b", "c", "d"], '{"year":2025}', "0");
    expect(whole.getAttribute("data-selection-mode")).toBe(null);
    expect(whole.querySelector("[data-selection-count]")?.textContent).toBe(
      "0 selected",
    );
  });

  it("comes back with the mode, on the list's next page", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);

    const second = mount(["c", "d"]);
    expect(second.getAttribute("data-selection-mode")).toBe("on");
    const seen = statements(second);
    tick(second, 0);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a", "c"] });
  });

  it("counts the keys of every page", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);
    tick(first, 1);
    const second = mount(["c", "d"]);
    expect(
      second.querySelector("[data-selection-count]")?.textContent,
    ).toBe("2 selected");
  });

  it("keeps a key no page in front of the reader holds", async () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);
    const second = mount(["c", "d"]);
    const body = second.querySelector("tbody")!;
    const seen = statements(second);
    body.rows[0].remove();
    await Promise.resolve();
    // "c" left the table; "a" is the page before.
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a"] });
  });

  it("is forgotten on Clear", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);
    press(first.querySelector("[data-selection-clear]"));

    const second = mount(["c", "d"]);
    expect(second.getAttribute("data-selection-mode")).toBe(null);
  });

  it("is forgotten when the mode turns off", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);
    toggle(first);

    const second = mount(["c", "d"]);
    expect(second.getAttribute("data-selection-mode")).toBe(null);
  });

  it("is not restored under another filter: the set is another set", () => {
    const first = mount(["a", "b"]);
    toggle(first);
    tick(first, 0);

    const second = mount(["c", "d"], '{"year":2024}');
    expect(second.getAttribute("data-selection-mode")).toBe(null);
  });
});
