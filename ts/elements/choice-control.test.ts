// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { choiceControl, choiceOf, isChoicePick } from "./choice-control.js";
import { choicePicker, choicePickerHtml } from "../test-setup/choice-picker.js";
import type { SearchSelectElement } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

const MODES = [
  { value: "EQUALS", label: "is" },
  { value: "INCLUDES", label: "includes" },
];

function picker(root: ParentNode = document): SearchSelectElement {
  return root.querySelector<SearchSelectElement>("search-select")!;
}

function connected(held = "EQUALS"): SearchSelectElement {
  document.body.append(choicePicker({ name: "m", marker: "data-mode", rows: MODES, held }));
  return picker();
}

function search(element: HTMLElement): HTMLInputElement {
  return element.querySelector<HTMLInputElement>("[data-search-select-search]")!;
}

afterEach(() => document.body.replaceChildren());

describe("ChoiceControl on a wired picker", () => {
  it("reads and writes the held value", () => {
    const element = connected();
    const control = choiceControl(document, "data-mode")!;
    expect(control.read()).toBe("EQUALS");
    expect(control.write("INCLUDES")).toBe(true);
    expect(control.read()).toBe("INCLUDES");
    expect(search(element).value).toBe("includes");
  });

  it("refuses an unoffered value and keeps the held one", () => {
    connected();
    const control = choiceControl(document, "data-mode")!;
    expect(control.write("REGEX")).toBe(false);
    expect(control.read()).toBe("EQUALS");
  });

  it("emits no change on a write", () => {
    const element = connected();
    let changes = 0;
    element.addEventListener("search-select:change", () => (changes += 1));
    choiceOf(element).write("INCLUDES");
    expect(changes).toBe(0);
  });

  it("reads null mid-edit", () => {
    const element = connected();
    const box = search(element);
    box.focus();
    box.value = "inc";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    expect(choiceOf(element).read()).toBeNull();
  });

  it("replaces rows in groups", () => {
    const element = connected("");
    choiceOf(element).setChoices([
      { label: "Exact", options: [{ value: "EQUALS", label: "=", data: {} }] },
      { label: "", options: [{ value: "LESS_THAN", label: "<", data: {} }] },
    ]);
    const headers = [...element.querySelectorAll("[data-search-select-group-header]")];
    expect(headers.map((header) => header.textContent)).toEqual(["Exact"]);
    expect(choiceOf(element).write("LESS_THAN")).toBe(true);
  });

  it("disables the search box", () => {
    const element = connected();
    choiceOf(element).setDisabled(true);
    expect(search(element).disabled).toBe(true);
  });
});

describe("ChoiceControl before the picker wires", () => {
  function detached(): HTMLElement {
    const template = document.createElement("template");
    template.innerHTML = choicePickerHtml({ name: "m", marker: "data-mode", rows: MODES });
    return template.content.firstElementChild!.cloneNode(true) as HTMLElement;
  }

  it("writes markup that the picker adopts on connection", () => {
    const host = detached();
    const control = choiceControl(host, "data-mode")!;
    expect(control.read()).toBeNull();
    expect(control.write("INCLUDES")).toBe(true);
    expect(control.read()).toBe("INCLUDES");
    document.body.append(host);
    const element = picker();
    expect(element.wired).toBe(true);
    expect(element.heldLabel()).toBe("includes");
    expect(choiceOf(element).read()).toBe("INCLUDES");
  });

  it("refuses an unoffered value", () => {
    const control = choiceControl(detached(), "data-mode")!;
    expect(control.write("REGEX")).toBe(false);
    expect(control.read()).toBeNull();
  });

  it("refuses new choices", () => {
    expect(() => choiceControl(detached(), "data-mode")!.setChoices([])).toThrow();
  });
});

describe("a picker without its parts", () => {
  it("reads null and writes nothing", () => {
    const bare = document.createElement("search-select");
    const control = choiceOf(bare);
    expect(control.read()).toBeNull();
    expect(control.write("EQUALS")).toBe(false);
  });
});

describe("isChoicePick", () => {
  function change(element: HTMLElement, last: boolean): CustomEvent {
    const event = new CustomEvent("search-select:change", {
      bubbles: true,
      detail: last
        ? { name: "m", values: ["EQUALS"], last: { value: "EQUALS", label: "is", data: {} }, none: false }
        : { name: "m", values: [], last: null, none: false },
    });
    element.dispatchEvent(event);
    return event;
  }

  it("takes a pick and ignores a keystroke drop", () => {
    const element = connected();
    expect(isChoicePick(change(element, true), "data-mode")).toBe(true);
    expect(isChoicePick(change(element, false), "data-mode")).toBe(false);
  });

  it("ignores another marker", () => {
    const element = connected();
    expect(isChoicePick(change(element, true), "data-other")).toBe(false);
  });
});

describe("a cloned prototype", () => {
  it("takes its own ids on each clone", () => {
    const template = document.createElement("template");
    template.innerHTML = choicePickerHtml({ name: "m", rows: MODES, held: "EQUALS" });
    for (let copy = 0; copy < 2; copy += 1) {
      document.body.append(template.content.firstElementChild!.cloneNode(true));
    }
    const pickers = [...document.querySelectorAll<HTMLElement>("search-select")];
    const ids = pickers.flatMap((element) =>
      [...element.querySelectorAll("[id]")].map((node) => node.id),
    );
    expect(ids.length).toBeGreaterThanOrEqual(4);
    expect(new Set(ids).size).toBe(ids.length);
    for (const element of pickers) {
      const box = search(element);
      const references = [
        box.getAttribute("aria-controls") ?? "",
        ...(box.getAttribute("aria-describedby") ?? "").split(/\s+/),
      ].filter(Boolean);
      expect(references.length).toBe(2);
      for (const id of references) {
        expect(element.querySelector(`#${id}`)).not.toBeNull();
      }
    }
  });
});
