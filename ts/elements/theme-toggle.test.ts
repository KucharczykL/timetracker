// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTheme } from "./theme-toggle.js";
import "./theme-toggle.js";

type MediaListener = (event: MediaQueryListEvent) => void;

let systemDark = false;
let mediaListener: MediaListener | null = null;

function mount(apiUrl = "", theme = "auto", migrating = false): HTMLElement {
  document.documentElement.dataset.themePreference = theme;
  if (migrating) document.documentElement.dataset.themeMigration = "true";
  document.body.innerHTML = `
    <theme-toggle api-url="${apiUrl}" csrf="token" cookie-secure="false">
      <button type="button" data-theme-toggle>
        <span data-theme-icon="auto"></span>
        <span data-theme-icon="light" hidden></span>
        <span data-theme-icon="dark" hidden></span>
      </button>
    </theme-toggle>`;
  return document.querySelector("theme-toggle")!;
}

beforeEach(() => {
  localStorage.clear();
  document.cookie = "color-theme=; Max-Age=0; Path=/";
  document.cookie = "color-theme-migrate=; Max-Age=0; Path=/";
  document.documentElement.classList.remove("dark");
  delete document.documentElement.dataset.themeMigration;
  systemDark = false;
  mediaListener = null;
  window.matchMedia = vi.fn().mockImplementation(() => ({
    get matches() {
      return systemDark;
    },
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: (_type: string, listener: MediaListener) => {
      mediaListener = listener;
    },
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  window.toast = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("nextTheme", () => {
  it("cycles auto to light to dark to auto", () => {
    expect(nextTheme("auto")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("auto");
  });
});

describe("<theme-toggle>", () => {
  it("persists anonymous cycles in localStorage and the readable cookie", () => {
    const host = mount();
    const button = host.querySelector<HTMLButtonElement>("[data-theme-toggle]")!;

    button.click();

    expect(document.documentElement.dataset.themePreference).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("color-theme")).toBe("light");
    expect(document.cookie).toContain("color-theme=light");
    expect(button.getAttribute("aria-label")).toBe("Theme: Light — switch to Dark");
    expect(button.getAttribute("title")).toBe("Theme: Light — switch to Dark");
  });

  it("reacts to operating-system changes while preference is auto", () => {
    mount();
    systemDark = true;
    mediaListener?.({ matches: true } as MediaQueryListEvent);

    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("rolls back an authenticated optimistic change after a rejected PATCH", async () => {
    window.fetchWithHtmxTriggers = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);
    const host = mount("/api/settings/user/THEME", "dark");
    const button = host.querySelector<HTMLButtonElement>("[data-theme-toggle]")!;

    button.click();

    await vi.waitFor(() => expect(window.toast).toHaveBeenCalled());
    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("color-theme")).toBeNull();
  });

  it("applies successful settings-page saves through the shared event", () => {
    mount("/api/settings/user/THEME");

    document.body.dispatchEvent(
      new CustomEvent("setting-saved", {
        detail: { key: "THEME", value: "dark" },
      }),
    );

    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("color-theme")).toBe("dark");
  });

  it("applies theme changes received from another tab", () => {
    mount();

    window.dispatchEvent(
      new StorageEvent("storage", { key: "color-theme", newValue: "dark" }),
    );

    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("migrates the legacy localStorage value for an authenticated account", async () => {
    localStorage.setItem("color-theme", "dark");
    document.documentElement.dataset.themePreference = "dark";
    document.documentElement.dataset.themeMigration = "true";
    window.fetchWithHtmxTriggers = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ key: "THEME", value: "dark", source: "user", locked: false }),
    } as Response);

    mount("/api/settings/user/THEME", "dark", true);

    await vi.waitFor(() => expect(window.fetchWithHtmxTriggers).toHaveBeenCalled());
    const options = vi.mocked(window.fetchWithHtmxTriggers).mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(options.body))).toEqual({ value: "dark" });
  });
});
