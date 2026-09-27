// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";

import "./unset-field.js";
import type { UnsetFieldChangeDetail } from "./unset-field.js";

beforeEach(() => {
  document.body.innerHTML = "";
});

function mount(member: string, { checked = false } = {}): HTMLElement {
  document.body.innerHTML = `
    <unset-field name="note" none-label="No note">
      <div>
        <div data-unset-field-member>${member}</div>
        <button type="button" data-unset-field-toggle aria-pressed="${checked}"></button>
        <label><input type="checkbox" name="note-unset" value="1" data-unset-field-state ${
          checked ? "checked" : ""
        }></label>
      </div>
    </unset-field>`;
  return document.querySelector<HTMLElement>("unset-field")!;
}

/** Connect waits on custom elements. */
const settled = () => new Promise((resolve) => setTimeout(resolve));

const TEXTAREA = `<textarea name="note" placeholder="Keep: mixed">Hello</textarea>`;
const PICKER = `
  <input type="hidden" name="device" value="7">
  <input data-search-select-search placeholder="Keep: Steam Deck" value="Steam Deck">
  <button type="button" data-search-select-clear></button>`;

const toggle = () => document.querySelector<HTMLButtonElement>("[data-unset-field-toggle]")!;
const state = () => document.querySelector<HTMLInputElement>("[data-unset-field-state]")!;
const textarea = () => document.querySelector<HTMLTextAreaElement>("textarea")!;

it("a press empties and disables the control and states none", async () => {
  mount(TEXTAREA);
  await settled();
  toggle().click();

  expect(textarea().value).toBe("");
  expect(textarea().disabled).toBe(true);
  expect(textarea().getAttribute("placeholder")).toBe("No note");
  expect(toggle().getAttribute("aria-pressed")).toBe("true");
  expect(state().checked).toBe(true);
});

it("a second press restores the value and placeholder", async () => {
  mount(TEXTAREA);
  await settled();
  textarea().value = "Edited";
  toggle().click();
  toggle().click();

  expect(textarea().value).toBe("Edited");
  expect(textarea().disabled).toBe(false);
  expect(textarea().getAttribute("placeholder")).toBe("Keep: mixed");
  expect(toggle().getAttribute("aria-pressed")).toBe("false");
  expect(state().checked).toBe(false);
});

it("restores an absent placeholder as absent", async () => {
  mount(`<textarea name="note"></textarea>`);
  await settled();
  toggle().click();
  toggle().click();
  expect(textarea().hasAttribute("placeholder")).toBe(false);
});

it("on a picker, empties and disables only the search box", async () => {
  mount(PICKER);
  await settled();
  toggle().click();

  const hidden = document.querySelector<HTMLInputElement>("input[type=hidden]")!;
  const search = document.querySelector<HTMLInputElement>("[data-search-select-search]")!;
  expect(search.value).toBe("");
  expect(search.placeholder).toBe("No note");
  expect(search.disabled).toBe(true);
  // Still posts; the server lets ⊘ win.
  expect(hidden.disabled).toBe(false);

  toggle().click();
  expect(search.value).toBe("Steam Deck");
  expect(search.disabled).toBe(false);
});

it("leaves a control the page disabled disabled", async () => {
  mount(`<textarea name="note" disabled>Hello</textarea>`);
  await settled();
  toggle().click();
  toggle().click();
  expect(textarea().disabled).toBe(true);
  expect(textarea().value).toBe("Hello");
});

it("announces each press", async () => {
  mount(TEXTAREA);
  await settled();
  const events: UnsetFieldChangeDetail[] = [];
  document.addEventListener("unset-field:change", event =>
    events.push((event as CustomEvent<UnsetFieldChangeDetail>).detail),
  );
  toggle().click();
  toggle().click();
  expect(events).toEqual([
    { name: "note", unset: true },
    { name: "note", unset: false },
  ]);
});

it("a checked box at connect applies the press without an event", async () => {
  let fired = false;
  document.addEventListener("unset-field:change", () => (fired = true), { once: true });
  mount(TEXTAREA, { checked: true });
  await settled();

  expect(textarea().value).toBe("");
  expect(textarea().disabled).toBe(true);
  expect(toggle().getAttribute("aria-pressed")).toBe("true");
  expect(fired).toBe(false);

  toggle().click();
  expect(textarea().value).toBe("Hello");
});

it("binds once across a DOM move", async () => {
  const element = mount(TEXTAREA);
  await settled();
  const host = document.createElement("div");
  document.body.append(host);
  host.append(element);
  toggle().click();
  expect(toggle().getAttribute("aria-pressed")).toBe("true");
});

it("on a select, empties and restores the choice", async () => {
  mount(`<select name="letter"><option value="a">A</option><option value="b" selected>B</option></select>`);
  await settled();
  const select = document.querySelector<HTMLSelectElement>("select")!;
  toggle().click();
  expect(select.value).toBe("");
  expect(select.disabled).toBe(true);
  toggle().click();
  expect(select.value).toBe("b");
});

it("says so and stays unpressed when the field has no control", async () => {
  const error = vi.spyOn(console, "error").mockImplementation(() => {});
  mount(`<input type="hidden" name="note" value="x">`);
  await settled();
  toggle().click();
  expect(error).toHaveBeenCalledOnce();
  expect(toggle().getAttribute("aria-pressed")).toBe("false");
  expect(state().checked).toBe(false);
  error.mockRestore();
});

it("on several native controls, empties all and labels the first", async () => {
  mount(`<input type="number" name="h" value="2"><input type="number" name="m" value="30">`);
  await settled();
  const [hours, minutes] = Array.from(document.querySelectorAll<HTMLInputElement>("input[type=number]"));
  toggle().click();
  expect([hours.value, minutes.value]).toEqual(["", ""]);
  expect([hours.disabled, minutes.disabled]).toEqual([true, true]);
  expect(hours.placeholder).toBe("No note");
  expect(minutes.hasAttribute("placeholder")).toBe(false);
  toggle().click();
  expect([hours.value, minutes.value]).toEqual(["2", "30"]);
});

class FakeTarget extends HTMLElement {
  calls: string[] = [];
  unsetValue(): void {
    this.calls.push("unset");
  }
  restoreValue(): void {
    this.calls.push("restore");
  }
}
customElements.define("fake-target", FakeTarget);

it("hands a composite both calls and touches none of its inputs", async () => {
  mount(`<fake-target><input name="inner" value="x"></fake-target>`);
  await settled();
  const target = document.querySelector<FakeTarget>("fake-target")!;
  toggle().click();
  toggle().click();
  expect(target.calls).toEqual(["unset", "restore"]);
  expect(document.querySelector<HTMLInputElement>("input[name=inner]")!.value).toBe("x");
});

it("keeps the toggle disabled until the field's elements are defined", async () => {
  mount(`<later-target><input name="inner" value="x"></later-target>`);
  expect(toggle().disabled).toBe(true);
  customElements.define(
    "later-target",
    class extends HTMLElement {
      unsetValue(): void {}
      restoreValue(): void {}
    },
  );
  await settled();
  expect(toggle().disabled).toBe(false);
});
