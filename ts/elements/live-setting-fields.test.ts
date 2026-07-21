// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { settingPayloadValue } from "./live-setting-fields.js";
import "./live-setting-fields.js";

function mountFields(): HTMLElement {
  document.body.innerHTML = `
    <live-setting-fields patch-url-template="/api/settings/user/__key__"
        csrf="token" event="setting-saved">
      <input data-setting-key="ENABLED" name="enabled" type="checkbox">
      <select data-setting-key="DESTINATION" name="destination">
        <option value="">Unset</option><option value="stats">Statistics</option>
      </select>
      <input data-setting-key="LIMIT" name="limit" type="number" value="10">
      <input data-setting-key="NAME" name="name" type="text" value="Before">
      <input data-setting-key="LOCKED" name="locked" value="Pinned" disabled>
    </live-setting-fields>`;
  return document.querySelector("live-setting-fields")!;
}

function change(control: HTMLElement): void {
  control.dispatchEvent(new Event("change", { bubbles: true }));
}

beforeEach(() => {
  document.body.replaceChildren();
  window.toast = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("settingPayloadValue", () => {
  it("serializes checkbox, select, number, and text setting controls", () => {
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    expect(settingPayloadValue(checkbox)).toBe(true);

    const select = document.createElement("select");
    select.innerHTML = '<option value="">Unset</option><option value="x">X</option>';
    expect(settingPayloadValue(select)).toBeNull();
    select.value = "x";
    expect(settingPayloadValue(select)).toBe("x");

    const number = document.createElement("input");
    number.type = "number";
    number.value = "12";
    expect(settingPayloadValue(number)).toBe(12);
    number.value = "";
    expect(settingPayloadValue(number)).toBeNull();

    const text = document.createElement("input");
    text.value = "hello";
    expect(settingPayloadValue(text)).toBe("hello");
    text.value = "";
    expect(settingPayloadValue(text)).toBeNull();
  });
});

describe("<live-setting-fields>", () => {
  it("PATCHes the changed key and dispatches the configured success event", async () => {
    const fetchStub = vi.fn().mockResolvedValue({ ok: true, status: 204 } as Response);
    window.fetchWithHtmxTriggers = fetchStub;
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;
    const saved = vi.fn();
    document.body.addEventListener("setting-saved", saved);
    input.value = "After";
    change(input);

    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(1));
    expect(fetchStub.mock.calls[0][0]).toBe("/api/settings/user/NAME");
    const options = fetchStub.mock.calls[0][1] as RequestInit;
    expect(options.method).toBe("PATCH");
    expect(options.headers).toEqual({
      "Content-Type": "application/json",
      "X-CSRFToken": "token",
    });
    expect(JSON.parse(String(options.body))).toEqual({ value: "After" });
    await vi.waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    expect(input.hasAttribute("aria-busy")).toBe(false);
  });

  it("reverts to the last committed value and toasts on a rejected PATCH", async () => {
    window.fetchWithHtmxTriggers = vi
      .fn()
      .mockResolvedValue({ ok: false, status: 422 } as Response);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;
    input.value = "Rejected";
    change(input);

    await vi.waitFor(() => expect(input.value).toBe("Before"));
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your change — please try again.",
      "error",
    );
    expect(consoleError).toHaveBeenCalled();
  });

  it("does not PATCH a disabled locked field", async () => {
    const fetchStub = vi.fn().mockResolvedValue({ ok: true } as Response);
    window.fetchWithHtmxTriggers = fetchStub;
    const host = mountFields();
    change(host.querySelector<HTMLInputElement>('[name="locked"]')!);
    await Promise.resolve();
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("sends native boolean, null, and numeric JSON values", async () => {
    const fetchStub = vi.fn().mockResolvedValue({ ok: true, status: 204 } as Response);
    window.fetchWithHtmxTriggers = fetchStub;
    const host = mountFields();
    const checkbox = host.querySelector<HTMLInputElement>('[name="enabled"]')!;
    const select = host.querySelector<HTMLSelectElement>('[name="destination"]')!;
    const number = host.querySelector<HTMLInputElement>('[name="limit"]')!;
    checkbox.checked = true;
    select.value = "";
    number.value = "25";
    change(checkbox);
    change(select);
    change(number);

    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(3));
    const bodies = fetchStub.mock.calls.map((call) =>
      JSON.parse(String((call[1] as RequestInit).body)),
    );
    expect(bodies).toEqual([{ value: true }, { value: null }, { value: 25 }]);
  });
});
