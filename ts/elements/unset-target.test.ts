// @vitest-environment jsdom
import { expect, it } from "vitest";

import { freezeControls, isUnsetTarget } from "./unset-target.js";

it("freezes what was enabled and thaws only that", () => {
  const root = document.createElement("div");
  root.innerHTML = `<input name="a"><button disabled>b</button><select></select>`;
  const [input, button, select] = Array.from(root.children) as HTMLInputElement[];
  const thaw = freezeControls(root);
  expect([input.disabled, button.disabled, select.disabled, root.hasAttribute("inert")]).toEqual([true, true, true, true]);
  thaw();
  expect([input.disabled, button.disabled, select.disabled, root.hasAttribute("inert")]).toEqual([false, true, false, false]);
});

it("knows a target by its two methods", () => {
  const plain = document.createElement("div");
  const target = Object.assign(document.createElement("div"), { unsetValue() {}, restoreValue() {} });
  expect(isUnsetTarget(plain)).toBe(false);
  expect(isUnsetTarget(target)).toBe(true);
});
