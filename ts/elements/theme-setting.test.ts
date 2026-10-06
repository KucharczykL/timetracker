// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getThemeCoordinator,
  resetThemeCoordinatorForTests,
} from "../theme-coordinator.js";
import "./theme-setting.js";
import "./theme-toggle.js";

Element.prototype.scrollIntoView = () => {};

const THEME_NONE = "Use site default (Dark)";

const SETTING = `
    <theme-setting><drop-down behavior="inline-combobox"><search-select name="theme"
        multi="false" none-label="${THEME_NONE}" data-setting-key="THEME">
      <div data-search-select-pills>
        <input type="hidden" name="theme" value="" data-search-select-none></div>
      <input data-search-select-search value="${THEME_NONE}">
      <button type="button" data-search-select-clear>×</button>
      <div data-search-select-options hidden>
        <div data-search-select-none-option data-label="${THEME_NONE}">${THEME_NONE}</div>
        <div data-search-select-option data-value="system" data-label="System">System</div>
        <div data-search-select-option data-value="light" data-label="Light">Light</div>
        <div data-search-select-option data-value="dark" data-label="Dark">Dark</div>
      </div>
    </search-select></drop-down></theme-setting>`;

function mountPicker(): { host: HTMLElement; picker: HTMLElement; search: HTMLInputElement } {
  document.body.innerHTML = SETTING;
  const picker = document.querySelector<HTMLElement>("search-select")!;
  return {
    host: document.querySelector("theme-setting")!,
    picker,
    search: picker.querySelector("[data-search-select-search]")!,
  };
}

/** Each picker's held value, "" for none. */
const heldThemes = () =>
  Array.from(
    document.querySelectorAll<HTMLInputElement>(
      "theme-setting [data-search-select-pills] input[type=hidden]",
    ),
  ).map((input) => input.value);

const pick = (picker: HTMLElement, selector: string) => {
  picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();
  picker.querySelector<HTMLElement>(selector)!.click();
};

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
  window.fetchWithEvents = vi.fn();
  window.dispatchResponseEvents = vi.fn();
});

afterEach(() => {
  resetThemeCoordinatorForTests();
  vi.restoreAllMocks();
});

describe("<theme-setting>", () => {
  it("saves through the coordinator, busy until it answers", async () => {
    configureInheritedDark();
    let resolve!: (value: Response) => void;
    vi.mocked(window.fetchWithEvents).mockReturnValue(new Promise((done) => {
      resolve = done;
    }));
    const { picker, search } = mountPicker();

    expect(heldThemes()).toEqual([""]);
    pick(picker, '[data-search-select-option][data-value="light"]');

    expect(search.disabled).toBe(true);
    expect(search.getAttribute("aria-busy")).toBe("true");
    expect(document.documentElement.dataset.themePreference).toBe("light");
    expect(JSON.parse(String(
      (vi.mocked(window.fetchWithEvents).mock.calls[0][1] as RequestInit).body,
    ))).toEqual({ value: "light" });

    resolve({
      ok: true,
      status: 200,
      json: async () => ({
        key: "THEME", value: "light", source: "user", locked: false, namespace: "user",
      }),
    } as Response);
    await vi.waitFor(() => expect(search.disabled).toBe(false));
    expect(heldThemes()).toEqual(["light"]);
  });

  it.each(["toggle-first", "setting-first"])(
    "synchronizes presenters connected in %s order",
    async (order) => {
      configureInheritedDark();
      vi.mocked(window.fetchWithEvents).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          key: "THEME", value: "light", source: "user", locked: false, namespace: "user",
        }),
      } as Response);
      const setting = SETTING;
      const toggle = `<theme-toggle><button data-pop-over-control data-pop-over-trigger>
        <svg data-theme-icon="system"></svg><svg data-theme-icon="light"></svg>
        <svg data-theme-icon="dark"></svg></button><span data-theme-tooltip></span>
        </theme-toggle>`;
      document.body.innerHTML = order === "toggle-first"
        ? toggle + setting
        : setting + toggle;

      pick(
        document.querySelector<HTMLElement>("theme-setting search-select")!,
        '[data-search-select-option][data-value="light"]',
      );

      await vi.waitFor(() => expect(heldThemes()).toEqual(["light"]));
      expect(document.querySelector('[data-theme-icon="light"]')?.hasAttribute("hidden"))
        .toBe(false);
    },
  );

  it("keeps multiple instances of both presenters synchronized", async () => {
    configureInheritedDark();
    vi.mocked(window.fetchWithEvents).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "THEME", value: "system", source: "user", locked: false, namespace: "user",
      }),
    } as Response);
    const setting = SETTING;
    const toggle = `<theme-toggle><button data-pop-over-control data-pop-over-trigger>
      <svg data-theme-icon="system"></svg><svg data-theme-icon="light"></svg>
      <svg data-theme-icon="dark"></svg></button><span data-theme-tooltip></span>
      </theme-toggle>`;
    document.body.innerHTML = toggle + setting + toggle + setting;

    document.querySelector<HTMLButtonElement>("theme-toggle button")!.click();

    await vi.waitFor(() => expect(heldThemes()).toEqual(["system", "system"]));
    expect(Array.from(document.querySelectorAll("[data-theme-icon=system]"))
      .every((icon) => !icon.hasAttribute("hidden"))).toBe(true);
  });

  it("receives changes made by another coordinator presenter", async () => {
    configureInheritedDark();
    vi.mocked(window.fetchWithEvents).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "THEME", value: "system", source: "user", locked: false, namespace: "user",
      }),
    } as Response);
    mountPicker();

    await getThemeCoordinator().requestPreferenceChange("system");

    expect(heldThemes()).toEqual(["system"]);
  });

  it("saves a picker's pick and none through the coordinator", async () => {
    configureInheritedDark();
    vi.mocked(window.fetchWithEvents)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          key: "THEME", value: "light", source: "user", locked: false, namespace: "user",
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          key: "THEME", value: "dark", source: "database", locked: false, namespace: "user",
        }),
      } as Response);
    const { host, picker, search } = mountPicker();
    const bubbled = vi.fn();
    host.parentElement?.addEventListener("search-select:change", bubbled);

    pick(picker, '[data-search-select-option][data-value="light"]');
    expect(search.disabled).toBe(true);
    await vi.waitFor(() => expect(search.disabled).toBe(false));
    expect(search.value).toBe("Light");
    pick(picker, "[data-search-select-none-option]");
    await vi.waitFor(() =>
      expect(vi.mocked(window.fetchWithEvents)).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(search.disabled).toBe(false));

    const sent = vi.mocked(window.fetchWithEvents).mock.calls.map(
      (call) => JSON.parse(String((call[1] as RequestInit).body)).value,
    );
    expect(sent).toEqual(["light", null]);
    expect(search.value).toBe(THEME_NONE);
    expect(bubbled).not.toHaveBeenCalled();
  });

  it("ignores a keystroke in the picker", () => {
    configureInheritedDark();
    const { search } = mountPicker();
    search.focus();
    search.value = "Li";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    expect(window.fetchWithEvents).not.toHaveBeenCalled();
  });

  it("holds none again after a failed picker save, silently", async () => {
    configureInheritedDark();
    vi.mocked(window.fetchWithEvents).mockResolvedValue({ ok: false, status: 500 } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { picker, search } = mountPicker();
    const changes = vi.fn();
    picker.addEventListener("search-select:change", changes);

    pick(picker, '[data-search-select-option][data-value="light"]');
    await vi.waitFor(() => expect(search.disabled).toBe(false));

    expect(search.value).toBe(THEME_NONE);
    expect(picker.querySelector("input[data-search-select-none]")).not.toBeNull();
    expect(changes).toHaveBeenCalledTimes(1);
    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
