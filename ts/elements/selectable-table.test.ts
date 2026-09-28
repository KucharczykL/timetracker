// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SelectionStatement } from "./selection-statement.js";
import { storageKeyFor } from "./selection-storage.js";
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
        `<tr data-selection-key="${key}"><th scope="row">` +
        `<div data-row-identity>Game ${key}</div>` +
        `<div data-row-summary>2 hours</div></th><td>2025</td></tr>`,
    )
    .join("");
  document.body.innerHTML = `
    <selectable-table filter='${filter}' count="${count}" scope="lib-1:Games">
      <table>
        <thead><tr><th scope="col">
          <input type="checkbox" data-selection-check-all>Name
        </th><th scope="col">Year</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div data-selection-line hidden>
        <div data-selection-controls>
          <input type="checkbox" data-selection-check-all>
          <span data-selection-count>0 selected</span>
          <button data-selection-all-matching>Select all 50 matching</button>
          <button data-selection-clear>Clear</button>
          <div data-selection-actions></div>
        </div>
        <template data-selection-checkbox-template>
          <input type="checkbox" data-selection-checkbox>
        </template>
      </div>
      <div data-selection-announcement role="status"></div>
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

function line(element: HTMLElement): HTMLElement {
  return element.querySelector<HTMLElement>("[data-selection-line]")!;
}

function headerCheckAll(element: HTMLElement): HTMLInputElement {
  return element.querySelector<HTMLInputElement>(
    "thead [data-selection-check-all]",
  )!;
}

function lineCheckAll(element: HTMLElement): HTMLInputElement {
  return element.querySelector<HTMLInputElement>(
    "[data-selection-line] [data-selection-check-all]",
  )!;
}

function checkAllPage(checkAll: HTMLInputElement, checked = true): void {
  checkAll.checked = checked;
  checkAll.dispatchEvent(new Event("change", { bubbles: true }));
}

function escape(element: HTMLElement): void {
  element.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
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

describe("the tray", () => {
  let element: HTMLElement;

  beforeEach(() => {
    element = mount(["a", "b", "c"]);
  });

  it("gives every row a checkbox, named by the row, with no press", () => {
    expect(checkboxes(element)).toHaveLength(3);
    expect(checkboxes(element)[0].getAttribute("aria-label")).toBe("Game a");
  });

  it("names a clipped row once, not by its tooltip's copy", async () => {
    const row = document.createElement("tr");
    row.setAttribute("data-selection-key", "z");
    row.innerHTML =
      '<th scope="row"><div data-row-identity><truncated-text>' +
      "<span data-truncated-clip>Steam Deck</span>" +
      '<div data-pop-over-panel aria-hidden="true" hidden>Steam Deck</div>' +
      "</truncated-text></div></th>";
    element.querySelector("tbody")!.appendChild(row);
    await Promise.resolve();

    expect(
      row.querySelector("[data-selection-checkbox]")?.getAttribute("aria-label"),
    ).toBe("Steam Deck");
  });

  it("hides the line while nothing is selected", () => {
    expect(line(element).hidden).toBe(true);
    tick(element, 0);
    expect(line(element).hidden).toBe(false);
    tick(element, 0);
    expect(line(element).hidden).toBe(true);
  });

  it("keeps both check-alls in step", () => {
    tick(element, 0);
    expect(headerCheckAll(element).indeterminate).toBe(true);
    expect(lineCheckAll(element).indeterminate).toBe(true);
    checkAllPage(lineCheckAll(element));
    expect(headerCheckAll(element).checked).toBe(true);
    expect(headerCheckAll(element).indeterminate).toBe(false);
    checkAllPage(headerCheckAll(element), false);
    expect(lineCheckAll(element).checked).toBe(false);
    expect(line(element).hidden).toBe(true);
  });

  it("takes a scope whose every row is unmarked back to none", () => {
    const table = mount(["a", "b"], '{"year":2025}', "2");
    press(table.querySelector("[data-selection-all-matching]"));
    const seen = statements(table);
    tick(table, 0);
    tick(table, 1);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: [] });
    expect(line(table).hidden).toBe(true);
    expect(sessionStorage.length).toBe(0);
  });

  it("does nothing on Escape with nothing selected", async () => {
    escape(element);
    await settled();
    expect(announcement(element)).toBe("");
  });

  it("clears on Escape and hides the line", async () => {
    tick(element, 0);
    escape(element);
    await settled();
    expect(checkboxes(element)[0].checked).toBe(false);
    expect(line(element).hidden).toBe(true);
  });

  it("moves focus from Clear to the header's check-all", () => {
    tick(element, 0);
    const clear = element.querySelector<HTMLElement>("[data-selection-clear]")!;
    clear.focus();
    press(clear);
    expect(document.activeElement).toBe(headerCheckAll(element));
  });

  it("moves focus off a line its own check-all empties", () => {
    tick(element, 0);
    const checkAll = lineCheckAll(element);
    checkAll.focus();
    checkAllPage(checkAll);
    checkAllPage(checkAll, false);
    expect(line(element).hidden).toBe(true);
    expect(document.activeElement).toBe(headerCheckAll(element));
  });

  it("moves focus off the line on Escape pressed inside it", async () => {
    tick(element, 0);
    const clear = element.querySelector<HTMLElement>("[data-selection-clear]")!;
    clear.focus();
    clear.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
    await settled();
    expect(document.activeElement).toBe(headerCheckAll(element));
  });

  it("disables itself aloud when the server rendered no line", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    document.body.innerHTML = `
      <selectable-table filter="" count="0" scope="lib-1:Games">
        <table><thead><tr><th><input type="checkbox" data-selection-check-all></th></tr></thead></table>
      </selectable-table>`;
    const table = document.querySelector("selectable-table") as HTMLElement;
    expect(error).toHaveBeenCalled();
    expect(headerCheckAll(table).hidden).toBe(true);
    error.mockRestore();
  });

  it("moves focus to the first row's box where no header is shown", () => {
    element.querySelector("thead")!.remove();
    tick(element, 1);
    const clear = element.querySelector<HTMLElement>("[data-selection-clear]")!;
    clear.focus();
    press(clear);
    expect(document.activeElement).toBe(checkboxes(element)[0]);
  });

  it("leaves focus alone when Clear came from outside the line", async () => {
    tick(element, 0);
    checkboxes(element)[2].focus();
    escape(element);
    await settled();
    expect(document.activeElement).toBe(checkboxes(element)[2]);
  });

  it("keeps its announcement outside the line that hides", () => {
    const region = element.querySelector("[data-selection-announcement]")!;
    expect(line(element).contains(region)).toBe(false);
  });
});

describe("the selection", () => {
  let element: HTMLElement;

  beforeEach(() => {
    element = mount(["a", "b", "c", "d"]);
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

  it("announces the line when a check-all brings it", () => {
    checkAllPage(headerCheckAll(element));
    expect(announcement(element)).toBe(
      "4 selected. Selection actions follow the table.",
    );
  });

  it("announces the page a later check-all took", () => {
    tick(element, 0);
    checkAllPage(headerCheckAll(element));
    expect(announcement(element)).toBe("4 selected");
  });

  it("forgets the selection when an action is submitted", () => {
    tick(element, 0);
    const actions = element.querySelector("[data-selection-actions]")!;
    const form = document.createElement("form");
    actions.appendChild(form);
    form.dispatchEvent(new Event("submit", { bubbles: true }));
    expect(line(element).hidden).toBe(true);
    expect(checkboxes(element)[0].checked).toBe(false);
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
    tick(element, 0);
    element.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
    await settled();
    expect(announcement(element)).toBe("Selection cleared.");
  });

  it("waits for the whole press, so a document-level closer is heard", async () => {
    const element = mount(["a", "b"]);
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
    tick(element, 0);
    const body = element.querySelector("tbody")!;
    const row = body.rows[0];
    row.remove();
    body.insertBefore(row, body.firstChild);
    await Promise.resolve();
    expect(checkboxes(element)).toHaveLength(2);
    expect(checkboxes(element)[0].checked).toBe(true);
  });

  it("comes in checked under a scope", async () => {
    const element = mount(["a", "b"]);
    press(element.querySelector("[data-selection-all-matching]"));
    const body = element.querySelector("tbody")!;
    const row = document.createElement("tr");
    row.setAttribute("data-selection-key", "z");
    row.innerHTML = '<th scope="row"><div data-row-identity>Game z</div></th>';
    body.appendChild(row);
    await Promise.resolve();
    expect(checkboxes(element)[2].checked).toBe(true);
  });

  it("takes a key the table no longer holds out of the selection", async () => {
    const element = mount(["a", "b"]);
    tick(element, 0);
    const seen = statements(element);
    element.querySelector("tbody")!.rows[0].remove();
    await Promise.resolve();
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: [] });
  });
});

describe("the announcement", () => {
  it("announces the line once, on the first tick", () => {
    const element = mount(["a", "b"]);
    tick(element, 0);
    expect(announcement(element)).toBe(
      "1 selected. Selection actions follow the table.",
    );
    tick(element, 1);
    expect(announcement(element)).toBe(
      "1 selected. Selection actions follow the table.",
    );
  });

  it("announces the line once for a keyboard range from none", () => {
    const element = mount(["a", "b", "c"]);
    tick(element, 0);
    tick(element, 0);
    const target = checkboxes(element)[2];
    target.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: " ",
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    );
    expect(announcement(element)).toBe(
      "3 selected. Selection actions follow the table.",
    );
  });

  it("speaks at each change of scope", () => {
    const element = mount(["a", "b"]);
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
    tick(first, 0);
    const second = mount(["c", "d"]);
    expect(announcement(second)).toBe("");
  });

  it("states itself to a listener that was there before the page", () => {
    const first = mount(["a", "b"]);
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
    press(first.querySelector("[data-selection-all-matching]"));

    const second = mount(["c", "d"]);
    expect(line(second).hidden).toBe(false);
    expect(checkboxes(second).every((box) => box.checked)).toBe(true);
    expect(
      second.querySelector("[data-selection-count]")?.textContent,
    ).toBe("50 selected");
  });

  it("refuses a scope on a page that states no count", () => {
    // Rows per page raised to the whole list: same path, same filter, but the
    // count that named the scope is gone, so the scope is not the same scope.
    const first = mount(["a", "b"]);
    press(first.querySelector("[data-selection-all-matching]"));

    const whole = mount(["a", "b", "c", "d"], '{"year":2025}', "0");
    expect(line(whole).hidden).toBe(true);
    expect(whole.querySelector("[data-selection-count]")?.textContent).toBe(
      "0 selected",
    );
  });

  it("comes back with its line, on the list's next page", () => {
    const first = mount(["a", "b"]);
    tick(first, 0);

    const second = mount(["c", "d"]);
    expect(line(second).hidden).toBe(false);
    const seen = statements(second);
    tick(second, 0);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a", "c"] });
  });

  it("counts the keys of every page", () => {
    const first = mount(["a", "b"]);
    tick(first, 0);
    tick(first, 1);
    const second = mount(["c", "d"]);
    expect(
      second.querySelector("[data-selection-count]")?.textContent,
    ).toBe("2 selected");
  });

  it("keeps a key no page in front of the reader holds", async () => {
    const first = mount(["a", "b"]);
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
    tick(first, 0);
    press(first.querySelector("[data-selection-clear]"));

    const second = mount(["c", "d"]);
    expect(line(second).hidden).toBe(true);
  });

  it("is forgotten when its last row is unmarked", () => {
    const first = mount(["a", "b"]);
    tick(first, 0);
    tick(first, 0);

    const second = mount(["c", "d"]);
    expect(line(second).hidden).toBe(true);
  });

  it("forgets a stored scope that excepts every row it named", () => {
    sessionStorage.setItem(
      storageKeyFor("lib-1:Games", window.location.pathname),
      JSON.stringify({ version: 1, filter: '{"year":2025}', all: true, except: ["a", "b"] }),
    );
    const table = mount(["a", "b"], '{"year":2025}', "2");
    expect(line(table).hidden).toBe(true);
    expect(sessionStorage.length).toBe(0);
    const seen = statements(table);
    tick(table, 0);
    expect(seen[seen.length - 1]).toEqual({ mode: "some", keys: ["a"] });
  });

  it("is not restored under another filter: the set is another set", () => {
    const first = mount(["a", "b"]);
    tick(first, 0);

    const second = mount(["c", "d"], '{"year":2024}');
    expect(line(second).hidden).toBe(true);
  });

  it("keeps another filter's selection through a mount and a row that leaves", async () => {
    const first = mount(["a", "b"]);
    tick(first, 0);
    expect(sessionStorage.length).toBe(1);
    const stored = JSON.stringify({ ...sessionStorage });

    const second = mount(["c", "d"], '{"year":2024}');
    second.querySelector("tbody")!.rows[0].remove();
    await Promise.resolve();
    expect(JSON.stringify({ ...sessionStorage })).toBe(stored);
  });
});

describe("the checkbox's place in the cell", () => {
  it("joins the name's own row, leaving the summary below it", () => {
    const table = mount(["a"]);

    const identity = table.querySelector("[data-row-identity]") as HTMLElement;
    const box = table.querySelector("[data-selection-checkbox]") as HTMLElement;

    expect(identity.contains(box)).toBe(true);
    expect(identity.firstElementChild).toBe(box);
    expect(
      table.querySelector("[data-row-summary]")?.contains(box),
    ).toBe(false);
  });

  it("takes the cell itself where no row is stated", () => {
    document.body.innerHTML = `
      <selectable-table filter="" count="0" scope="lib-1:Games">
        <table><tbody>
          <tr data-selection-key="a"><th scope="row">Game a</th><td>2025</td></tr>
        </tbody></table>
        <div data-selection-line hidden>
          <div data-selection-controls>
            <input type="checkbox" data-selection-check-all>
            <span data-selection-count>0 selected</span>
            <button data-selection-clear>Clear</button>
            <div data-selection-actions></div>
          </div>
          <template data-selection-checkbox-template>
            <input type="checkbox" data-selection-checkbox>
          </template>
        </div>
        <div data-selection-announcement role="status"></div>
      </selectable-table>`;
    const table = document.querySelector("selectable-table") as HTMLElement;
    const cell = table.querySelector("th") as HTMLElement;

    expect(cell.firstElementChild?.matches("[data-selection-checkbox]")).toBe(
      true,
    );
  });
});
