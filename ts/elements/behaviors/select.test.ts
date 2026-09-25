// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../drop-down.js";
import { selectPayloadValue } from "./select.js";

describe("selectPayloadValue", () => {
  it("maps an empty value to null when empty_is_null is enabled", () => {
    expect(selectPayloadValue("", true)).toBeNull();
  });

  it("keeps a UUID string unchanged when empty_is_null is enabled", () => {
    const value = "018f5e66-e800-7000-8000-000000000001";
    expect(selectPayloadValue(value, true)).toBe(value);
  });

  it("passes the empty string through for an ordinary selector", () => {
    expect(selectPayloadValue("", false)).toBe("");
  });

  it("passes strings through untouched for an ordinary selector", () => {
    expect(selectPayloadValue("f", false)).toBe("f");
  });
});

describe("select behavior on a refused PATCH", () => {
  const mount = (): HTMLElement => {
    const host = document.createElement("drop-down");
    host.setAttribute("behavior", "select");
    host.dataset.patchUrl = "/api/games/1/status";
    host.dataset.bodyKey = "status";
    host.dataset.event = "status-changed";
    host.innerHTML = `
      <button data-toggle aria-expanded="false" type="button">
        <span data-label>Unplayed</span>
      </button>
      <div data-menu hidden role="listbox">
        <a data-option data-value="u" aria-selected="true">Unplayed</a>
        <a data-option data-value="f" aria-selected="false">Finished</a>
      </div>`;
    document.body.replaceChildren(host);
    return host;
  };

  beforeEach(() => {
    vi.stubGlobal("toast", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const choose = (headers: Record<string, string>) => {
    window.fetchWithEvents = vi.fn().mockResolvedValue(
      new Response(null, { status: 409, headers }),
    );
    const host = mount();
    host.querySelector<HTMLElement>('[data-value="f"]')!.click();
    return host;
  };

  it("adds no second toast when the refusal carries its own", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const host = choose({ "X-Events": '{"show-toast": []}' });
    expect(host.querySelector("[data-label]")!.textContent).toBe("Finished");
    await vi.waitFor(() => expect(consoleError).toHaveBeenCalled());
    expect(host.querySelector("[data-label]")!.textContent).toBe("Unplayed");
    expect(window.toast).not.toHaveBeenCalled();
  });

  it("toasts when the refusal says nothing", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    choose({});
    await vi.waitFor(() => expect(window.toast).toHaveBeenCalledOnce());
  });
});
