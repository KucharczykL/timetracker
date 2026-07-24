// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getThemeCoordinator,
  resetThemeCoordinatorForTests,
} from "../theme-coordinator.js";
import "./theme-setting.js";
import "./theme-toggle.js";

function configureInheritedDark(): void {
  const root = document.documentElement;
  root.dataset.themeMode = "account";
  root.dataset.themePreferences = "system light dark";
  root.dataset.themePreference = "dark";
  root.dataset.themePersonalPreference = "";
  root.dataset.themeInheritedPreference = "dark";
  root.dataset.themeSource = "database";
  root.dataset.themeUpdateUrl = "/api/settings/user/THEME";
  root.dataset.themeCsrf = "token";
}

function mount(): { host: HTMLElement; select: HTMLSelectElement } {
  document.body.innerHTML = `
    <theme-setting class="block w-full"><select data-setting-key="THEME">
      <option value="">Use site default (Dark)</option>
      <option value="system">System</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select></theme-setting>`;
  return {
    host: document.querySelector("theme-setting")!,
    select: document.querySelector("select")!,
  };
}

beforeEach(() => {
  document.body.replaceChildren();
  document.documentElement.className = "";
  for (const key of Object.keys(document.documentElement.dataset)) {
    delete document.documentElement.dataset[key];
  }
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  });
  window.toast = vi.fn();
  window.fetchWithHtmxTriggers = vi.fn();
  window.dispatchHtmxTriggers = vi.fn();
});

afterEach(() => {
  resetThemeCoordinatorForTests();
  vi.restoreAllMocks();
});

describe("<theme-setting>", () => {
  it("maps the inherited blank choice to null and stops generic live save", async () => {
    configureInheritedDark();
    let resolve!: (value: Response) => void;
    vi.mocked(window.fetchWithHtmxTriggers).mockReturnValue(new Promise((done) => {
      resolve = done;
    }));
    const { host, select } = mount();
    const bubbled = vi.fn();
    host.parentElement?.addEventListener("change", bubbled);

    expect(select.value).toBe("");
    select.value = "light";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    expect(bubbled).not.toHaveBeenCalled();
    expect(select.disabled).toBe(true);
    expect(select.getAttribute("aria-busy")).toBe("true");
    expect(document.documentElement.dataset.themePreference).toBe("light");
    expect(JSON.parse(String(
      (vi.mocked(window.fetchWithHtmxTriggers).mock.calls[0][1] as RequestInit).body,
    ))).toEqual({ value: "light" });

    resolve({
      ok: true,
      status: 200,
      json: async () => ({ key: "THEME", value: "light", source: "user", locked: false }),
    } as Response);
    await vi.waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("light");
  });

  it.each(["toggle-first", "setting-first"])(
    "synchronizes presenters connected in %s order",
    async (order) => {
      configureInheritedDark();
      vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          key: "THEME", value: "light", source: "user", locked: false,
        }),
      } as Response);
      const setting = `<theme-setting><select><option value=""></option>
        <option value="system">System</option><option value="light">Light</option>
        <option value="dark">Dark</option></select></theme-setting>`;
      const toggle = `<theme-toggle><button data-pop-over-control data-pop-over-trigger>
        <svg data-theme-icon="system"></svg><svg data-theme-icon="light"></svg>
        <svg data-theme-icon="dark"></svg></button><span data-theme-tooltip></span>
        </theme-toggle>`;
      document.body.innerHTML = order === "toggle-first"
        ? toggle + setting
        : setting + toggle;

      const select = document.querySelector<HTMLSelectElement>("theme-setting select")!;
      select.value = "light";
      select.dispatchEvent(new Event("change", { bubbles: true }));

      await vi.waitFor(() => {
        expect(document.querySelector<HTMLSelectElement>("theme-setting select")?.value)
          .toBe("light");
      });
      expect(document.querySelector('[data-theme-icon="light"]')?.hasAttribute("hidden"))
        .toBe(false);
    },
  );

  it("keeps multiple instances of both presenters synchronized", async () => {
    configureInheritedDark();
    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "THEME", value: "system", source: "user", locked: false,
      }),
    } as Response);
    const setting = `<theme-setting><select><option value=""></option>
      <option value="system">System</option><option value="dark">Dark</option>
      </select></theme-setting>`;
    const toggle = `<theme-toggle><button data-pop-over-control data-pop-over-trigger>
      <svg data-theme-icon="system"></svg><svg data-theme-icon="light"></svg>
      <svg data-theme-icon="dark"></svg></button><span data-theme-tooltip></span>
      </theme-toggle>`;
    document.body.innerHTML = toggle + setting + toggle + setting;

    document.querySelector<HTMLButtonElement>("theme-toggle button")!.click();

    await vi.waitFor(() => {
      expect(Array.from(document.querySelectorAll<HTMLSelectElement>("theme-setting select"))
        .map((select) => select.value)).toEqual(["system", "system"]);
    });
    expect(Array.from(document.querySelectorAll("[data-theme-icon=system]"))
      .every((icon) => !icon.hasAttribute("hidden"))).toBe(true);
  });

  it("restores the blank personal selection and inherited Dark after failure", async () => {
    configureInheritedDark();
    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { select } = mount();

    select.value = "light";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    await vi.waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("");
    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("receives changes made by another coordinator presenter", async () => {
    configureInheritedDark();
    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ key: "THEME", value: "system", source: "user", locked: false }),
    } as Response);
    const { select } = mount();

    await getThemeCoordinator().requestPreferenceChange("system");

    expect(select.value).toBe("system");
  });
});
