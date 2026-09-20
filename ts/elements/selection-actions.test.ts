// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
// Importing both modules defines both elements.
import "./selectable-table.js";
import "./selection-actions.js";

beforeEach(() => {
  sessionStorage.clear();
});

const FILTER = '{"year":2025}';
const SCOPE = "lib-1:Games";

function mount(keys: string[], count = "50"): HTMLElement {
  const rows = keys
    .map(
      (key) =>
        `<tr data-selection-key="${key}"><th scope="row">Game ${key}</th>` +
        "<td>2025</td></tr>",
    )
    .join("");
  document.body.innerHTML = `
    <selectable-table filter='${FILTER}' count="${count}" scope="${SCOPE}">
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
          <div data-selection-actions>
            <selection-actions>
              <form data-selection-actions-form method="post">
                <input type="hidden" name="csrfmiddlewaretoken" value="a-token">
                <input type="hidden" data-selection-statement name="selection">
                <button type="submit" formaction="/bulk/session.remove/" disabled>
                  Remove
                </button>
              </form>
            </selection-actions>
          </div>
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

function field(): HTMLInputElement {
  return document.querySelector(
    "[data-selection-statement]",
  ) as HTMLInputElement;
}

function submits(): HTMLButtonElement[] {
  return Array.from(
    document.querySelectorAll<HTMLButtonElement>(
      "[data-selection-actions-form] button[type=submit]",
    ),
  );
}

function posted(): unknown {
  return JSON.parse(field().value);
}

function press(element: HTMLElement | null): void {
  element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

function toggle(element: HTMLElement): void {
  press(element.querySelector("[data-selection-bar] [data-selection-toggle]"));
}

function tick(element: HTMLElement, index: number): void {
  const boxes = element.querySelectorAll<HTMLInputElement>(
    "tbody [data-selection-checkbox]",
  );
  boxes[index].dispatchEvent(
    new MouseEvent("click", { bubbles: true, cancelable: true }),
  );
}

function submit(): void {
  document
    .querySelector("[data-selection-actions-form]")
    ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

/** A back-navigation the browser serves from its cache. */
function restored(): void {
  window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
}

describe("<selection-actions>", () => {
  it("writes an empty statement and disables every submit at connect", () => {
    mount(["a", "b"]);

    expect(posted()).toEqual({ mode: "some", keys: [] });
    expect(submits().every((button) => button.disabled)).toBe(true);
  });

  it("writes the keys a person marks", () => {
    const table = mount(["a", "b"]);
    toggle(table);

    tick(table, 0);

    expect(posted()).toEqual({ mode: "some", keys: ["a"] });
    expect(submits().every((button) => button.disabled)).toBe(false);
  });

  it("writes the wider statement, and counts it", () => {
    const table = mount(["a", "b"]);
    toggle(table);

    press(table.querySelector("[data-selection-all-matching]"));

    expect(posted()).toEqual({
      mode: "all",
      filter: FILTER,
      count: 50,
      except: [],
    });
    expect(submits().every((button) => button.disabled)).toBe(false);
  });

  it("disables the submits again when the selection empties", () => {
    const table = mount(["a", "b"]);
    toggle(table);
    tick(table, 0);

    press(table.querySelector("[data-selection-clear]"));

    expect(posted()).toEqual({ mode: "some", keys: [] });
    expect(submits().every((button) => button.disabled)).toBe(true);
  });

  it("disables the submits under a wider statement that excludes every row", () => {
    const table = mount(["a", "b"], "2");
    toggle(table);
    press(table.querySelector("[data-selection-all-matching]"));

    tick(table, 0);
    tick(table, 1);

    expect(submits().every((button) => button.disabled)).toBe(true);
  });

  it("fills the field from a selection restored before it upgraded", () => {
    // The table announces a restored selection from its own connect, which
    // runs before this element exists.
    sessionStorage.setItem(
      `selectable-table:${SCOPE}:${window.location.pathname}`,
      JSON.stringify({ version: 1, filter: FILTER, all: false, keys: ["b"] }),
    );

    mount(["a", "b"]);

    expect(posted()).toEqual({ mode: "some", keys: ["b"] });
    expect(submits().every((button) => button.disabled)).toBe(false);
  });

  it("keeps what was pressed, though the table forgets it", () => {
    // <selectable-table> answers the press by forgetting the selection,
    // which announces an empty statement while the form is being read.
    const table = mount(["a", "b"]);
    toggle(table);
    tick(table, 0);

    submit();

    expect(posted()).toEqual({ mode: "some", keys: ["a"] });
  });

  it("writes nothing more after the press", () => {
    const table = mount(["a", "b"]);
    toggle(table);
    tick(table, 0);
    submit();

    tick(table, 1);

    expect(posted()).toEqual({ mode: "some", keys: ["a"] });
  });

  it("chooses again on a page the browser brought back", () => {
    // A restored document runs no connectedCallback, so the latch the
    // press set would stand for the life of the tab and the next press
    // would post the statement of the press before it.
    const table = mount(["a", "b"]);
    toggle(table);
    tick(table, 0);
    submit();

    restored();

    expect(posted()).toEqual({ mode: "some", keys: [] });
    expect(submits().every((button) => button.disabled)).toBe(true);

    tick(table, 1);

    expect(posted()).toEqual({ mode: "some", keys: ["b"] });
  });

  it("keeps the press when the page was never restored", () => {
    const table = mount(["a", "b"]);
    toggle(table);
    tick(table, 0);
    submit();

    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: false }),
    );
    tick(table, 1);

    expect(posted()).toEqual({ mode: "some", keys: ["a"] });
  });
});
