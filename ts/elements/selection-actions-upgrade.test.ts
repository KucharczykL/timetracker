// @vitest-environment jsdom
import { beforeEach, expect, it } from "vitest";

/** The slot's module runs before the table's.
 *
 * `Page()` emits the table's script first, because `collect_media` walks a
 * parent before its children -- so the happy path is the only order the
 * app produces today. This file states the other one, which a reordered
 * emission or a deferred module would produce: the slot upgrades against a
 * table that cannot answer yet, and must still reach the statement.
 *
 * Its own file, because a module is defined once per environment and
 * vitest gives each file its own.
 */

const FILTER = '{"year":2025}';
const SCOPE = "lib-1:Games";

beforeEach(() => {
  sessionStorage.clear();
});

function markup(): void {
  document.body.innerHTML = `
    <selectable-table filter='${FILTER}' count="50" scope="${SCOPE}">
      <div data-selection-bar>
        <button data-selection-toggle aria-pressed="false">Select</button>
      </div>
      <table><tbody>
        <tr data-selection-key="a"><th scope="row">Game a</th><td>2025</td></tr>
        <tr data-selection-key="b"><th scope="row">Game b</th><td>2025</td></tr>
      </tbody></table>
      <div data-selection-line hidden>
        <div data-selection-controls>
          <input type="checkbox" data-selection-check-all>
          <span data-selection-count>0 selected</span>
          <button data-selection-clear>Clear</button>
          <div data-selection-actions>
            <selection-actions>
              <form data-selection-actions-form method="post">
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
}

it("reaches the statement though the table upgraded second", async () => {
  sessionStorage.setItem(
    `selectable-table:${SCOPE}:${window.location.pathname}`,
    JSON.stringify({ version: 1, filter: FILTER, all: false, keys: ["b"] }),
  );
  markup();

  // The slot first: it can ask nothing, so it must listen.
  await import("./selection-actions.js");
  await import("./selectable-table.js");

  const field = document.querySelector(
    "[data-selection-statement]",
  ) as HTMLInputElement;
  const submit = document.querySelector(
    "[data-selection-actions-form] button[type=submit]",
  ) as HTMLButtonElement;
  expect(JSON.parse(field.value)).toEqual({ mode: "some", keys: ["b"] });
  expect(submit.disabled).toBe(false);
});
