// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { changedForms, fieldValue, snapshotForms } from "./unsaved.js";

function mount(html: string): HTMLElement {
  const body = document.createElement("div");
  body.innerHTML = html;
  document.body.replaceChildren(body);
  return body;
}

function input(body: HTMLElement, name: string): HTMLInputElement {
  return body.querySelector<HTMLInputElement>(`[name=${name}]`)!;
}

beforeEach(() => {
  document.body.replaceChildren();
});

describe("changedForms", () => {
  it("leaves a nested dialog's forms to that dialog", () => {
    const body = mount(`
      <form><input name="name" value="Deck"></form>
      <dialog><form><input name="undo" value=""></form></dialog>`);
    const baseline = snapshotForms(body);
    input(body, "undo").value = "token";
    expect(changedForms(body, baseline)).toEqual([]);
    input(body, "name").value = "Deck OLED";
    expect(changedForms(body, baseline)).toEqual([body.querySelector("form")]);
  });

  it("reads a typed value as a change, typed back as none", () => {
    const body = mount(`<form><input name="name" value="Deck"></form>`);
    const baseline = snapshotForms(body);
    input(body, "name").value = "Deck OLED";
    expect(changedForms(body, baseline)).toEqual([body.querySelector("form")]);
    input(body, "name").value = "Deck";
    expect(changedForms(body, baseline)).toEqual([]);
  });

  it("reads an added empty field as no change", () => {
    const body = mount(`<form><input name="name" value="Deck"></form>`);
    const baseline = snapshotForms(body);
    body.querySelector("form")!.append(Object.assign(document.createElement("input"), { name: "note" }));
    expect(changedForms(body, baseline)).toEqual([]);
  });

  it("reads a removed empty field as no change", () => {
    const body = mount(`<form><input name="name" value="Deck"><input name="note"></form>`);
    const baseline = snapshotForms(body);
    input(body, "note").remove();
    expect(changedForms(body, baseline)).toEqual([]);
  });

  it("reads a list of empty strings as empty", () => {
    const body = mount(`<form><input name="tag"></form>`);
    const baseline = snapshotForms(body);
    body.querySelector("form")!.append(Object.assign(document.createElement("input"), { name: "tag" }));
    expect(changedForms(body, baseline)).toEqual([]);
  });

  it("counts the order of one name's values", () => {
    const body = mount(`<form><input name="tag" value="a"><input name="tag" value="b"></form>`);
    const baseline = snapshotForms(body);
    const [first, second] = body.querySelectorAll<HTMLInputElement>("[name=tag]");
    first.value = "b";
    second.value = "a";
    expect(changedForms(body, baseline)).toHaveLength(1);
  });

  it("leaves the CSRF token out", () => {
    const body = mount(
      `<form><input type="hidden" name="csrfmiddlewaretoken" value="one"></form>`,
    );
    const baseline = snapshotForms(body);
    input(body, "csrfmiddlewaretoken").value = "two";
    expect(changedForms(body, baseline)).toEqual([]);
  });

  it("counts hidden controls", () => {
    const body = mount(`<form><input type="hidden" name="device" value="1"></form>`);
    const baseline = snapshotForms(body);
    input(body, "device").value = "2";
    expect(changedForms(body, baseline)).toHaveLength(1);
  });

  it("leaves disabled controls out", () => {
    const body = mount(`<form><input name="name" value="Deck" disabled></form>`);
    const baseline = snapshotForms(body);
    input(body, "name").value = "Other";
    expect(changedForms(body, baseline)).toEqual([]);
  });

  it("names only the form that changed", () => {
    const body = mount(
      `<form><input name="name" value="a"></form><form><input name="name" value="a"></form>`,
    );
    const baseline = snapshotForms(body);
    body.querySelectorAll<HTMLInputElement>("[name=name]")[1].value = "b";
    expect(changedForms(body, baseline)).toEqual([body.querySelectorAll("form")[1]]);
  });
});

describe("fieldValue", () => {
  it("keeps a string", () => {
    expect(fieldValue("x")).toBe("x");
  });

  it("reads a file by name, size and date", () => {
    const file = new File(["abc"], "cover.png", { lastModified: 7 });
    expect(fieldValue(file)).toBe("file:cover.png:3:7");
  });

  it("reads an empty file input as empty", () => {
    expect(fieldValue(new File([], ""))).toBe("");
  });
});
