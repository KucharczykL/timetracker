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
      <pop-over>
        <button data-pop-over-trigger aria-label="Default source">
          <span data-setting-origin="default"
              data-setting-source-key="DESTINATION"
              class="bg-neutral-quaternary text-heading">Default</span>
        </button>
        <div data-pop-over-panel>
          <dl><div data-setting-source-description><dt>Source</dt>
            <dd>The built-in default.</dd></div>
            <div data-setting-source-status hidden>
              <dt>Status</dt>
              <dd>Non-default source (default source: “Default”)</dd>
            </div></dl>
        </div>
      </pop-over>
      <input data-setting-key="LIMIT" name="limit" type="number" value="10">
      <input data-setting-key="NAME" name="name" type="text" value="Before">
      <input data-setting-key="LOCKED" name="locked" value="Pinned" disabled>
    </live-setting-fields>`;
  return document.querySelector("live-setting-fields")!;
}

function change(control: HTMLElement): void {
  control.dispatchEvent(new Event("change", { bubbles: true }));
}

function deferredResponse(): {
  promise: Promise<Response>;
  resolve: (response: Response) => void;
} {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
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

  it("updates source metadata from each resolved PATCH response", async () => {
    const fetchStub = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          key: "DESTINATION",
          value: "stats",
          source: "user",
          locked: false,
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          key: "DESTINATION",
          value: "sessions",
          source: "database",
          locked: false,
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          key: "DESTINATION",
          value: "stats",
          source: "default",
          locked: false,
        }),
      } as Response);
    window.fetchWithHtmxTriggers = fetchStub;
    const host = mountFields();
    const select = host.querySelector<HTMLSelectElement>('[name="destination"]')!;
    const badge = host.querySelector<HTMLElement>("[data-setting-source-key]")!;
    const trigger = badge.closest("pop-over")!.querySelector("[data-pop-over-trigger]")!;
    const description = badge.closest("pop-over")!
      .querySelector<HTMLElement>("[data-setting-source-description] dd")!;
    const status = badge.closest("pop-over")!
      .querySelector<HTMLElement>("[data-setting-source-status]")!;

    expect(badge.classList.contains("bg-neutral-quaternary")).toBe(true);
    expect(badge.classList.contains("bg-brand-soft")).toBe(false);
    expect(status.hidden).toBe(true);

    select.value = "stats";
    change(select);
    await vi.waitFor(() => expect(badge.textContent).toBe("Personal"));
    expect(badge.dataset.settingOrigin).toBe("user");
    expect(badge.classList.contains("bg-brand-soft")).toBe(true);
    expect(badge.classList.contains("bg-neutral-quaternary")).toBe(false);
    expect(trigger.getAttribute("aria-label")).toBe("Personal source");
    expect(description.textContent).toBe(
      "Saved for your account and overrides the site default.",
    );
    expect(status.hidden).toBe(false);

    select.value = "";
    change(select);
    await vi.waitFor(() => expect(badge.textContent).toBe("Database"));
    expect(badge.dataset.settingOrigin).toBe("database");
    expect(trigger.getAttribute("aria-label")).toBe("Database source");
    expect(description.textContent).toBe(
      "Saved in the application database as the current site-wide value.",
    );

    select.value = "stats";
    change(select);
    await vi.waitFor(() => expect(badge.textContent).toBe("Default"));
    expect(badge.dataset.settingOrigin).toBe("default");
    expect(trigger.getAttribute("aria-label")).toBe("Default source");
    expect(description.textContent).toBe(
      "The built-in default, used because no higher-priority value is set.",
    );
    expect(status.hidden).toBe(true);
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

  it("serializes rapid writes and sends only the latest queued value", async () => {
    const first = deferredResponse();
    const second = deferredResponse();
    const fetchStub = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    window.fetchWithHtmxTriggers = fetchStub;
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;

    input.value = "First";
    change(input);
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(1));

    input.value = "Intermediate";
    change(input);
    input.value = "Latest";
    change(input);
    expect(fetchStub).toHaveBeenCalledTimes(1);

    first.resolve({ ok: true, status: 204 } as Response);
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(2));
    expect(
      JSON.parse(String((fetchStub.mock.calls[1][1] as RequestInit).body)),
    ).toEqual({ value: "Latest" });
    expect(input.getAttribute("aria-busy")).toBe("true");

    second.resolve({ ok: true, status: 204 } as Response);
    await vi.waitFor(() => expect(input.hasAttribute("aria-busy")).toBe(false));
    expect(input.value).toBe("Latest");
  });

  it("does not let a superseded failure revert the newer queued edit", async () => {
    const first = deferredResponse();
    const second = deferredResponse();
    const fetchStub = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    window.fetchWithHtmxTriggers = fetchStub;
    vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;

    input.value = "Rejected older value";
    change(input);
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(1));
    input.value = "Newer value";
    change(input);

    first.resolve({ ok: false, status: 422 } as Response);
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(2));
    expect(input.value).toBe("Newer value");
    expect(window.toast).not.toHaveBeenCalled();

    second.resolve({ ok: true, status: 204 } as Response);
    await vi.waitFor(() => expect(input.hasAttribute("aria-busy")).toBe(false));
    expect(input.value).toBe("Newer value");
  });

  it("preserves newer typing when an in-flight edit fails", async () => {
    const response = deferredResponse();
    window.fetchWithHtmxTriggers = vi.fn(() => response.promise);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;

    input.value = "Submitted";
    change(input);
    input.value = "Still typing";
    response.resolve({ ok: false, status: 422 } as Response);

    await vi.waitFor(() => expect(window.toast).toHaveBeenCalledTimes(1));
    expect(input.value).toBe("Still typing");
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
