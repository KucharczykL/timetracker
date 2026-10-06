// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { reloadAfterSettingSave } from "../settings-reload.js";
import { SETTING_COMMITTED_EVENT } from "../settings-events.js";

vi.mock("../settings-reload.js", () => ({
  reloadAfterSettingSave: vi.fn(),
}));
import "./live-setting-fields.js";
import "./setting-source-badge.js";

Element.prototype.scrollIntoView = () => {};

function mountFields(): HTMLElement {
  document.body.innerHTML = `
    <live-setting-fields patch-url-template="/api/settings/user/__key__"
        csrf="token" namespace="user">
      <input data-setting-key="ENABLED" data-live-setting-control name="enabled" type="checkbox">
      <select data-setting-key="DESTINATION" data-live-setting-control name="destination">
        <option value="">Unset</option><option value="stats">Statistics</option>
        <option value="sessions">Sessions</option>
      </select>
      <setting-source-badge key="DESTINATION" namespace="user"><pop-over>
        <button data-pop-over-trigger aria-label="Default source">
          <span data-setting-origin="default"
              class="bg-neutral-quaternary text-heading"><span
              data-setting-source-label>Default</span></span>
        </button>
        <div data-pop-over-panel>
          <dl><div data-setting-source-description><dt>Source</dt>
            <dd>The built-in default.</dd></div>
            <div data-setting-source-status hidden>
              <dt>Status</dt>
              <dd>Non-default source (default source: “Default”)</dd>
            </div></dl>
        </div>
      </pop-over></setting-source-badge>
      <input data-setting-key="LIMIT" data-live-setting-control name="limit" type="number" value="10">
      <input data-setting-key="NAME" data-live-setting-control name="name" type="text" value="Before">
      <select data-setting-key="DISPLAY_TIME_ZONE" data-live-setting-control
          data-reload-after-save name="display-time-zone">
        <option value="">Use site default</option>
        <option value="Pacific/Kiritimati">Pacific/Kiritimati</option>
      </select>
      <select data-setting-key="DATETIME_FORMAT" data-live-setting-control
          data-reload-after-save name="datetime-format">
        <option value="">Use site default</option>
        <option value="mdy_12h">MM/DD/YYYY, 12-hour</option>
      </select>
      <input data-setting-key="IDENTITY_ONLY" name="identity-only" value="Not owned">
      <input data-setting-key="LOCKED" data-live-setting-control name="locked" value="Pinned" disabled>
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

describe("<live-setting-fields>", () => {
  it("PATCHes the changed key and dispatches the complete committed response", async () => {
    const resolved = {
      key: "NAME",
      value: "After",
      source: "user",
      locked: false,
      namespace: "user",
    };
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => resolved,
    } as Response);
    window.fetchWithEvents = fetchStub;
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;
    const saved = vi.fn();
    document.body.addEventListener(SETTING_COMMITTED_EVENT, saved);
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
    expect(saved.mock.calls[0][0]).toMatchObject({ detail: resolved });
    expect(input.hasAttribute("aria-busy")).toBe(false);
  });

  it("ignores setting identity without the positive live-save marker", async () => {
    const fetchStub = vi.fn();
    window.fetchWithEvents = fetchStub;
    const host = mountFields();

    change(host.querySelector<HTMLInputElement>('[name="identity-only"]')!);
    await Promise.resolve();

    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("rejects a malformed successful response and restores the committed value", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ key: "NAME", value: "After" }),
    } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;
    input.value = "After";

    change(input);

    await vi.waitFor(() => expect(input.value).toBe("Before"));
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your change — please try again.",
      "error",
    );
  });

  it("throws when the response namespace does not match its own", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "After",
        source: "user",
        locked: false,
        namespace: "site",
      }),
    } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;
    input.value = "After";

    change(input);

    await vi.waitFor(() => expect(input.value).toBe("Before"));
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your change — please try again.",
      "error",
    );
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
          namespace: "user",
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
          namespace: "user",
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
          namespace: "user",
        }),
      } as Response);
    window.fetchWithEvents = fetchStub;
    const host = mountFields();
    const select = host.querySelector<HTMLSelectElement>('[name="destination"]')!;
    const badge = host.querySelector<HTMLElement>("[data-setting-origin]")!;
    const label = badge.querySelector<HTMLElement>("[data-setting-source-label]")!;
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
    await vi.waitFor(() => expect(label.textContent).toBe("Personal"));
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
    await vi.waitFor(() => expect(label.textContent).toBe("Database"));
    expect(badge.dataset.settingOrigin).toBe("database");
    expect(trigger.getAttribute("aria-label")).toBe("Database source");
    expect(description.textContent).toBe(
      "Saved in the application database as the current site-wide value.",
    );

    select.value = "stats";
    change(select);
    await vi.waitFor(() => expect(label.textContent).toBe("Default"));
    expect(badge.dataset.settingOrigin).toBe("default");
    expect(trigger.getAttribute("aria-label")).toBe("Default source");
    expect(description.textContent).toBe(
      "The built-in default, used because no higher-priority value is set.",
    );
    expect(status.hidden).toBe(true);
  });

  it("reconciles normalized text values from the resolved PATCH response", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "EUR",
        source: "user",
        locked: false,
        namespace: "user",
      }),
    } as Response);
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;

    input.value = "eur";
    change(input);

    await vi.waitFor(() => expect(input.hasAttribute("aria-busy")).toBe(false));
    expect(input.value).toBe("EUR");
  });

  it("shows the effective fallback after clearing a text override", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "CZK",
        source: "database",
        locked: false,
        namespace: "user",
      }),
    } as Response);
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;

    input.value = "";
    change(input);

    await vi.waitFor(() => expect(input.hasAttribute("aria-busy")).toBe(false));
    expect(input.value).toBe("CZK");
  });

  it("keeps a cleared select on its use-default sentinel", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "DESTINATION",
        value: "sessions",
        source: "database",
        locked: false,
        namespace: "user",
      }),
    } as Response);
    const host = mountFields();
    const select = host.querySelector<HTMLSelectElement>('[name="destination"]')!;

    select.value = "";
    change(select);

    await vi.waitFor(() => expect(select.hasAttribute("aria-busy")).toBe(false));
    expect(select.value).toBe("");
  });

  it("reloads after a successful presentation setting save", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "DISPLAY_TIME_ZONE",
        value: "Pacific/Kiritimati",
        source: "user",
        locked: false,
        namespace: "user",
      }),
    } as Response);
    const host = mountFields();
    const select = host.querySelector<HTMLSelectElement>(
      '[name="display-time-zone"]',
    )!;

    select.value = "Pacific/Kiritimati";
    change(select);

    await vi.waitFor(() => expect(reloadAfterSettingSave).toHaveBeenCalledOnce());
  });

  it("reloads after a successful date/time format save", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "DATETIME_FORMAT",
        value: "mdy_12h",
        source: "user",
        locked: false,
        namespace: "user",
      }),
    } as Response);
    const host = mountFields();
    const select = host.querySelector<HTMLSelectElement>(
      '[name="datetime-format"]',
    )!;

    select.value = "mdy_12h";
    change(select);

    await vi.waitFor(() => expect(reloadAfterSettingSave).toHaveBeenCalledOnce());
  });

  it("does not reload after a malformed date/time format response", async () => {
    vi.mocked(reloadAfterSettingSave).mockClear();
    window.fetchWithEvents = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "DATETIME_FORMAT",
        value: "mdy_12h",
      }),
    } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mountFields();
    const select = host.querySelector<HTMLSelectElement>(
      '[name="datetime-format"]',
    )!;

    select.value = "mdy_12h";
    change(select);

    await vi.waitFor(() =>
      expect(window.toast).toHaveBeenCalledWith(
        "Couldn't save your change — please try again.",
        "error",
      ),
    );
    expect(reloadAfterSettingSave).not.toHaveBeenCalled();
  });

  it("preserves newer typing when an older successful response resolves", async () => {
    const response = deferredResponse();
    window.fetchWithEvents = vi.fn(() => response.promise);
    const host = mountFields();
    const input = host.querySelector<HTMLInputElement>('[name="name"]')!;

    input.value = "Submitted";
    change(input);
    input.value = "Still typing";
    response.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "SUBMITTED",
        source: "user",
        locked: false,
        namespace: "user",
      }),
    } as Response);

    await vi.waitFor(() => expect(input.hasAttribute("aria-busy")).toBe(false));
    expect(input.value).toBe("Still typing");
  });

  it("reverts to the last committed value and toasts on a rejected PATCH", async () => {
    window.fetchWithEvents = vi
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
    window.fetchWithEvents = fetchStub;
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

    first.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "FIRST",
        source: "user",
        locked: false,
        namespace: "user",
      }),
    } as Response);
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(2));
    expect(
      JSON.parse(String((fetchStub.mock.calls[1][1] as RequestInit).body)),
    ).toEqual({ value: "Latest" });
    expect(input.value).toBe("Latest");
    expect(input.getAttribute("aria-busy")).toBe("true");

    second.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "Latest",
        source: "user",
        locked: false,
        namespace: "user",
      }),
    } as Response);
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
    window.fetchWithEvents = fetchStub;
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

    second.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        key: "NAME",
        value: "Newer value",
        source: "user",
        locked: false,
        namespace: "user",
      }),
    } as Response);
    await vi.waitFor(() => expect(input.hasAttribute("aria-busy")).toBe(false));
    expect(input.value).toBe("Newer value");
  });

  it("preserves newer typing when an in-flight edit fails", async () => {
    const response = deferredResponse();
    window.fetchWithEvents = vi.fn(() => response.promise);
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
    window.fetchWithEvents = fetchStub;
    const host = mountFields();
    change(host.querySelector<HTMLInputElement>('[name="locked"]')!);
    await Promise.resolve();
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("sends native boolean, null, and numeric JSON values", async () => {
    const fetchStub = vi.fn((url: string, options: RequestInit) => {
      const key = url.split("/").pop()!;
      const value = JSON.parse(String(options.body)).value;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ key, value, source: "user", locked: false, namespace: "user" }),
      } as Response);
    });
    window.fetchWithEvents = fetchStub;
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

const ZONE_NONE = "Use site default (UTC)";

function mountPicker(): { host: HTMLElement; picker: HTMLElement; search: HTMLInputElement } {
  document.body.innerHTML = `
    <live-setting-fields patch-url-template="/api/settings/user/__key__"
        csrf="token" namespace="user">
      <drop-down behavior="inline-combobox"><search-select name="zone" multi="false"
          none-label="${ZONE_NONE}" revert-on-leave="true"
          data-setting-key="DISPLAY_TIME_ZONE" data-live-setting-control>
        <div data-search-select-pills><input type="hidden" name="zone" value="Europe/Prague"></div>
        <input data-search-select-search value="Europe/Prague">
        <button type="button" data-search-select-clear>×</button>
        <div data-search-select-options hidden>
          <div data-search-select-none-option data-label="${ZONE_NONE}">${ZONE_NONE}</div>
          <div data-search-select-option data-value="Europe/Prague" data-label="Europe/Prague">Europe/Prague</div>
          <div data-search-select-option data-value="Asia/Tokyo" data-label="Asia/Tokyo">Asia/Tokyo</div>
        </div>
      </search-select></drop-down>
    </live-setting-fields>`;
  const host = document.querySelector<HTMLElement>("live-setting-fields")!;
  const picker = host.querySelector<HTMLElement>("search-select")!;
  return { host, picker, search: picker.querySelector("[data-search-select-search]")! };
}

const pickRow = (picker: HTMLElement, selector: string) => {
  picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();
  picker.querySelector<HTMLElement>(selector)!.click();
};
const zoneRow = (zone: string) => `[data-search-select-option][data-value="${zone}"]`;
const sentValues = (fetchStub: ReturnType<typeof vi.fn>) =>
  fetchStub.mock.calls.map(call => JSON.parse(String((call[1] as RequestInit).body)).value);
const zoneAnswer = (value: string): Response =>
  ({
    ok: true,
    status: 200,
    json: async () => ({
      key: "DISPLAY_TIME_ZONE",
      value,
      source: "user",
      locked: false,
      namespace: "user",
    }),
  }) as Response;

describe("<live-setting-fields> over a <search-select>", () => {
  it("saves a pick, then none as null and keeps the none label", async () => {
    const fetchStub = vi
      .fn()
      .mockResolvedValueOnce(zoneAnswer("Asia/Tokyo"))
      .mockResolvedValueOnce(zoneAnswer("UTC"));
    window.fetchWithEvents = fetchStub;
    const { picker, search } = mountPicker();

    pickRow(picker, zoneRow("Asia/Tokyo"));
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(search.hasAttribute("aria-busy")).toBe(false));
    pickRow(picker, "[data-search-select-none-option]");
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(search.hasAttribute("aria-busy")).toBe(false));

    expect(sentValues(fetchStub)).toEqual(["Asia/Tokyo", null]);
    expect(search.value).toBe(ZONE_NONE);
    expect(reloadAfterSettingSave).not.toHaveBeenCalled();
  });

  it("sends nothing for a keystroke, a blur, or a re-pick", async () => {
    const fetchStub = vi.fn();
    window.fetchWithEvents = fetchStub;
    const { picker, search } = mountPicker();

    search.focus();
    search.value = "Asi";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    search.dispatchEvent(new Event("change", { bubbles: true }));
    search.dispatchEvent(new FocusEvent("focusout", { bubbles: true, relatedTarget: null }));
    pickRow(picker, zoneRow("Europe/Prague"));
    await Promise.resolve();

    expect(fetchStub).not.toHaveBeenCalled();
    expect(search.value).toBe("Europe/Prague");
  });

  it("restores the held value and toasts on a failure", async () => {
    window.fetchWithEvents = vi.fn().mockResolvedValue({ ok: false, status: 500 } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { picker, search } = mountPicker();
    const changes: Event[] = [];
    picker.addEventListener("search-select:change", event => changes.push(event));

    pickRow(picker, zoneRow("Asia/Tokyo"));

    await vi.waitFor(() => expect(search.value).toBe("Europe/Prague"));
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your change — please try again.",
      "error",
    );
    expect(changes).toHaveLength(1);
  });

  it("queues a return to the old value behind an in-flight pick", async () => {
    const first = deferredResponse();
    const fetchStub = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce(zoneAnswer("Europe/Prague"));
    window.fetchWithEvents = fetchStub;
    const { picker, search } = mountPicker();

    pickRow(picker, zoneRow("Asia/Tokyo"));
    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(1));
    pickRow(picker, zoneRow("Europe/Prague"));
    first.resolve(zoneAnswer("Asia/Tokyo"));

    await vi.waitFor(() => expect(fetchStub).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(search.hasAttribute("aria-busy")).toBe(false));
    expect(sentValues(fetchStub)).toEqual(["Asia/Tokyo", "Europe/Prague"]);
    expect(search.value).toBe("Europe/Prague");
  });

  it("shows the committed value after a failed save and a leave mid-edit", async () => {
    const first = deferredResponse();
    window.fetchWithEvents = vi.fn().mockImplementationOnce(() => first.promise);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { picker, search } = mountPicker();

    pickRow(picker, zoneRow("Asia/Tokyo"));
    search.value = "Eu";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    first.resolve({ ok: false, status: 500 } as Response);
    await vi.waitFor(() => expect(window.toast).toHaveBeenCalled());
    search.dispatchEvent(new FocusEvent("focusout", { bubbles: true, relatedTarget: null }));

    expect(search.value).toBe("Europe/Prague");
    expect(picker.querySelector<HTMLInputElement>('input[type="hidden"]')!.value).toBe(
      "Europe/Prague"
    );
  });

  it("saves null for × pressed mid-edit and does not revert on leave", async () => {
    const fetchStub = vi.fn().mockResolvedValue(zoneAnswer("UTC"));
    window.fetchWithEvents = fetchStub;
    const { picker, search } = mountPicker();

    search.focus();
    search.value = "As";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    picker.querySelector<HTMLButtonElement>("[data-search-select-clear]")!.click();
    await vi.waitFor(() => expect(search.hasAttribute("aria-busy")).toBe(false));
    search.dispatchEvent(new FocusEvent("focusout", { bubbles: true, relatedTarget: null }));

    expect(sentValues(fetchStub)).toEqual([null]);
    expect(search.value).toBe(ZONE_NONE);
  });

  it("does not PATCH a disabled picker", async () => {
    const fetchStub = vi.fn();
    window.fetchWithEvents = fetchStub;
    const { picker, search } = mountPicker();
    search.disabled = true;

    picker.dispatchEvent(new CustomEvent("search-select:change", { bubbles: true }));
    await Promise.resolve();

    expect(fetchStub).not.toHaveBeenCalled();
  });
});
