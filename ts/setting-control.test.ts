// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { changedSettingControl, settingControlOf, snapshotsEqual } from "./setting-control.js";
import type { ResolvedSetting } from "./settings-events.js";

Element.prototype.scrollIntoView = () => {};

const NONE_LABEL = "Use site default (UTC)";

function mountPicker(held: string | null): HTMLElement {
  const pills =
    held === null
      ? '<input type="hidden" name="zone" value="" data-search-select-none>'
      : `<input type="hidden" name="zone" value="${held}">`;
  document.body.innerHTML = `
    <drop-down behavior="inline-combobox"><search-select name="zone" multi="false"
        none-label="${NONE_LABEL}" data-setting-key="DISPLAY_TIME_ZONE"
        data-live-setting-control>
      <div data-search-select-pills>${pills}</div>
      <input data-search-select-search value="${held ?? NONE_LABEL}">
      <button type="button" data-search-select-clear>×</button>
      <div data-search-select-options hidden>
        <div data-search-select-none-option data-label="${NONE_LABEL}">${NONE_LABEL}</div>
        <div data-search-select-option data-value="Europe/Prague" data-label="Europe/Prague">Europe/Prague</div>
        <div data-search-select-option data-value="25" data-label="25">25</div>
      </div>
    </search-select></drop-down>`;
  return document.querySelector("search-select")!;
}

const searchBox = () => document.querySelector<HTMLInputElement>("[data-search-select-search]")!;

function resolved(value: ResolvedSetting["value"]): ResolvedSetting {
  return { key: "DISPLAY_TIME_ZONE", value, source: "user", locked: false, namespace: "user" };
}

const readOf = (element: HTMLElement) => settingControlOf(element)!.read();

describe("a native control's payload", () => {
  it("serializes checkbox, number, and text setting controls", () => {
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    expect(readOf(checkbox)).toBe(true);

    const number = document.createElement("input");
    number.type = "number";
    number.value = "12";
    expect(readOf(number)).toBe(12);
    number.value = "";
    expect(readOf(number)).toBeNull();

    const text = document.createElement("input");
    text.value = "hello";
    expect(readOf(text)).toBe("hello");
    text.value = "";
    expect(readOf(text)).toBeNull();
  });
});

describe("settingControlOf a native control", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <input type="checkbox" data-live-setting-control>
      <input type="number" value="10">
      <input type="text" value="" readonly>
      <select><option value="a">A</option></select>
      <div></div>`;
  });

  it("reads each kind as before", () => {
    const [checkbox, number, text] = Array.from(
      document.querySelectorAll<HTMLElement>("input")
    ).map(element => settingControlOf(element)!);
    expect(checkbox.read()).toBe(false);
    expect(number.read()).toBe(10);
    expect(text.read()).toBeNull();
    expect(text.editable()).toBe(false);
    expect(text.changeEvent).toBe("change");
  });

  it("is none for anything else, a native select included", () => {
    expect(settingControlOf(document.querySelector("div")!)).toBeNull();
    expect(settingControlOf(document.querySelector("select")!)).toBeNull();
  });

  it("writes and restores", () => {
    const text = settingControlOf(document.querySelector<HTMLElement>("input[readonly]")!)!;
    text.write("a");
    expect(text.read()).toBe("a");
    text.restore({ kind: "native", value: "" });
    expect(text.read()).toBeNull();
  });
});

describe("settingControlOf a <search-select>", () => {
  it("reads a held value, none, and nothing", () => {
    const picker = mountPicker("Europe/Prague");
    const control = settingControlOf(picker)!;
    expect(control.changeEvent).toBe("search-select:change");
    expect(control.read()).toBe("Europe/Prague");
    control.write(null);
    expect(control.read()).toBeNull();
    expect(searchBox().value).toBe(NONE_LABEL);
    searchBox().focus();
    control.write("Europe/Prague");
    searchBox().value = "Eu";
    searchBox().dispatchEvent(new Event("input", { bubbles: true }));
    expect(control.read()).toBeUndefined();
  });

  it("restores silently", () => {
    const picker = mountPicker("Europe/Prague");
    const control = settingControlOf(picker)!;
    const events: Event[] = [];
    picker.addEventListener("search-select:change", event => events.push(event));
    const held = control.snapshot();
    control.write(null);
    control.restore(held);
    expect(control.read()).toBe("Europe/Prague");
    expect(snapshotsEqual(control.snapshot(), held)).toBe(true);
    expect(events).toEqual([]);
  });

  it("keeps a none attempt and holds a resolved value", () => {
    const control = settingControlOf(mountPicker("Europe/Prague"))!;
    control.write(null);
    const noneState = control.snapshot();
    expect(control.resolvedSnapshot({ value: null, state: noneState }, resolved("UTC"))).toEqual(
      noneState
    );
    const committed = control.resolvedSnapshot(
      { value: "25", state: control.snapshot() },
      resolved(25)
    );
    control.restore(committed);
    expect(control.read()).toBe("25");
  });

  it("disables and marks busy on the search box", () => {
    const control = settingControlOf(mountPicker(null))!;
    control.setDisabled(true);
    control.setBusy(true);
    expect(searchBox().disabled).toBe(true);
    expect(searchBox().getAttribute("aria-busy")).toBe("true");
    expect(control.editable()).toBe(false);
  });
});

describe("changedSettingControl", () => {
  it("maps the picker's change and ignores the search box's blur change", () => {
    const picker = mountPicker("Europe/Prague");
    const seen: (HTMLElement | undefined)[] = [];
    document.body.addEventListener("change", event =>
      seen.push(changedSettingControl(event)?.element)
    );
    document.body.addEventListener("search-select:change", event =>
      seen.push(changedSettingControl(event)?.element)
    );
    searchBox().dispatchEvent(new Event("change", { bubbles: true }));
    picker.dispatchEvent(new CustomEvent("search-select:change", { bubbles: true }));
    expect(seen).toEqual([undefined, picker]);
  });
});

describe("the reader refuses what it cannot serve", () => {
  it("refuses a checkbox write that is no boolean", () => {
    document.body.innerHTML = '<input type="checkbox">';
    const checkbox = settingControlOf(document.querySelector("input")!)!;
    expect(() => checkbox.write("yes")).toThrow();
    checkbox.write(true);
    expect(checkbox.read()).toBe(true);
  });

  it("refuses another kind's snapshot", () => {
    const picker = settingControlOf(mountPicker("Europe/Prague"))!;
    expect(() => picker.restore({ kind: "native", value: "x" })).toThrow();
  });

  it("refuses a multi-select picker", () => {
    const picker = mountPicker("Europe/Prague");
    picker.setAttribute("multi", "true");
    expect(() => settingControlOf(picker)).toThrow();
  });

  it("holds none for a resolved value no row offers, and says so", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const control = settingControlOf(mountPicker("Europe/Prague"))!;
    const state = control.resolvedSnapshot(
      { value: "Mars/Olympus", state: control.snapshot() },
      resolved("Mars/Olympus")
    );
    expect(state).toEqual({ kind: "held", value: "", none: true });
    expect(errors).toHaveBeenCalled();
    errors.mockRestore();
  });

  it("round-trips a snapshot for each kind", () => {
    const picker = settingControlOf(mountPicker(null))!;
    const none = picker.snapshot();
    picker.restore(none);
    expect(snapshotsEqual(picker.snapshot(), none)).toBe(true);
    document.body.innerHTML = '<input type="checkbox" checked value="on">';
    const checkbox = settingControlOf(document.querySelector("input")!)!;
    const checked = checkbox.snapshot();
    checkbox.restore(checked);
    expect(snapshotsEqual(checkbox.snapshot(), checked)).toBe(true);
  });
});
