// @vitest-environment jsdom
import { beforeEach, expect, it } from "vitest";

import "./unset-field.js";
import type { UnsetFieldChange } from "./unset-field.js";

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

const TEXTAREA = `<textarea name="note" placeholder="Keep: mixed">Hello</textarea>`;
const PICKER = `
  <input type="hidden" name="device" value="7">
  <input data-search-select-search placeholder="Keep: Steam Deck" value="Steam Deck">
  <button type="button" data-search-select-clear></button>`;

const toggle = () => document.querySelector<HTMLButtonElement>("[data-unset-field-toggle]")!;
const state = () => document.querySelector<HTMLInputElement>("[data-unset-field-state]")!;
const textarea = () => document.querySelector<HTMLTextAreaElement>("textarea")!;

it("a press empties and disables the control and states none", () => {
  mount(TEXTAREA);
  toggle().click();

  expect(textarea().value).toBe("");
  expect(textarea().disabled).toBe(true);
  expect(textarea().getAttribute("placeholder")).toBe("No note");
  expect(toggle().getAttribute("aria-pressed")).toBe("true");
  expect(state().checked).toBe(true);
});

it("a second press restores the value and placeholder", () => {
  mount(TEXTAREA);
  textarea().value = "Edited";
  toggle().click();
  toggle().click();

  expect(textarea().value).toBe("Edited");
  expect(textarea().disabled).toBe(false);
  expect(textarea().getAttribute("placeholder")).toBe("Keep: mixed");
  expect(toggle().getAttribute("aria-pressed")).toBe("false");
  expect(state().checked).toBe(false);
});

it("restores an absent placeholder as absent", () => {
  mount(`<textarea name="note"></textarea>`);
  toggle().click();
  toggle().click();
  expect(textarea().hasAttribute("placeholder")).toBe(false);
});

it("on a picker, empties and disables only the search box", () => {
  mount(PICKER);
  toggle().click();

  const hidden = document.querySelector<HTMLInputElement>("input[type=hidden]")!;
  const search = document.querySelector<HTMLInputElement>("[data-search-select-search]")!;
  expect(search.value).toBe("");
  expect(search.placeholder).toBe("No note");
  expect(search.disabled).toBe(true);
  // The server lets ⊘ win over the value it still posts.
  expect(hidden.disabled).toBe(false);

  toggle().click();
  expect(search.value).toBe("Steam Deck");
  expect(search.disabled).toBe(false);
});

it("leaves a control the page disabled disabled", () => {
  mount(`<textarea name="note" disabled>Hello</textarea>`);
  toggle().click();
  toggle().click();
  expect(textarea().disabled).toBe(true);
  expect(textarea().value).toBe("Hello");
});

it("announces each press", () => {
  mount(TEXTAREA);
  const events: UnsetFieldChange[] = [];
  document.addEventListener("unset-field:change", event =>
    events.push((event as CustomEvent<UnsetFieldChange>).detail),
  );
  toggle().click();
  toggle().click();
  expect(events).toEqual([
    { name: "note", unset: true },
    { name: "note", unset: false },
  ]);
});

it("a checked box at connect applies the press without an event", () => {
  let fired = false;
  document.addEventListener("unset-field:change", () => (fired = true), { once: true });
  mount(TEXTAREA, { checked: true });

  expect(textarea().value).toBe("");
  expect(textarea().disabled).toBe(true);
  expect(toggle().getAttribute("aria-pressed")).toBe("true");
  expect(fired).toBe(false);

  toggle().click();
  expect(textarea().value).toBe("Hello");
});

it("binds once across a DOM move", () => {
  const element = mount(TEXTAREA);
  const host = document.createElement("div");
  document.body.append(host);
  host.append(element);
  toggle().click();
  expect(toggle().getAttribute("aria-pressed")).toBe("true");
});
