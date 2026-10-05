// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "../client-errors.js";
import "./field-mirror.js";

afterEach(() => vi.restoreAllMocks());

function type(input: HTMLInputElement, value: string): void {
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function mount(): HTMLFormElement {
  document.body.innerHTML = `
    <form><input name="name"><input name="sort_name">
      <field-mirror source-field="name" target-field="sort_name" hidden></field-mirror>
    </form>
    <form><input name="name"><input name="sort_name"></form>`;
  return document.querySelector("form")!;
}

function field(form: HTMLFormElement, name: string): HTMLInputElement {
  return form.querySelector<HTMLInputElement>(`[name="${name}"]`)!;
}

describe("field-mirror", () => {
  it("copies the source into the target of its own form", () => {
    const form = mount();
    type(field(form, "name"), "Halo");
    expect(field(form, "sort_name").value).toBe("Halo");
    const other = document.querySelectorAll("form")[1];
    expect(field(other, "sort_name").value).toBe("");
  });

  it("stops once the target is edited", () => {
    const form = mount();
    type(field(form, "name"), "Halo");
    type(field(form, "sort_name"), "Custom");
    type(field(form, "name"), "Halo 2");
    expect(field(form, "sort_name").value).toBe("Custom");
  });

  it("stops listening once removed", () => {
    const form = mount();
    form.querySelector("field-mirror")!.remove();
    type(field(form, "name"), "Halo");
    expect(field(form, "sort_name").value).toBe("");
  });

  it("reports a missing form or target", () => {
    const report = vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id");
    document.body.innerHTML = `
      <field-mirror source-field="name" target-field="sort_name" hidden></field-mirror>
      <form><input name="name">
        <field-mirror source-field="name" target-field="missing" hidden></field-mirror>
      </form>`;
    expect(report.mock.calls.map(([, detail]) => detail)).toEqual([
      "no enclosing form",
      'no [name="missing"] in its form',
    ]);
  });
});
