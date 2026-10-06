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

function mountPicker(): { host: HTMLElement; picker: HTMLElement; search: HTMLInputElement } {
  document.body.innerHTML = `
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
  const picker = document.querySelector<HTMLElement>("search-select")!;
  return {
    host: document.querySelector("theme-setting")!,
    picker,
    search: picker.querySelector("[data-search-select-search]")!,
  };
}

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
  window.fetchWithEvents = vi.fn();
  window.dispatchResponseEvents = vi.fn();
});

afterEach(() => {
  resetThemeCoordinatorForTests();
  vi.restoreAllMocks();
});

describe("<theme-setting>", () => {
  it("maps the inherited blank choice to null and stops generic live save", async () => {
    configureInheritedDark();
    let resolve!: (value: Response) => void;
    vi.mocked(window.fetchWithEvents).mockReturnValue(new Promise((done) => {
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
      (vi.mocked(window.fetchWithEvents).mock.calls[0][1] as RequestInit).body,
    ))).toEqual({ value: "light" });

    resolve({
      ok: true,
      status: 200,
      json: async () => ({
        key: "THEME", value: "light", source: "user", locked: false, namespace: "user",
      }),
    } as Response);
    await vi.waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("light");
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
      const setting = `<theme-setting><select data-setting-key="THEME"><option value=""></option>
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
    vi.mocked(window.fetchWithEvents).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "THEME", value: "system", source: "user", locked: false, namespace: "user",
      }),
    } as Response);
    const setting = `<theme-setting><select data-setting-key="THEME"><option value=""></option>
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
    vi.mocked(window.fetchWithEvents).mockResolvedValue({
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
    vi.mocked(window.fetchWithEvents).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        key: "THEME", value: "system", source: "user", locked: false, namespace: "user",
      }),
    } as Response);
    const { select } = mount();

    await getThemeCoordinator().requestPreferenceChange("system");

    expect(select.value).toBe("system");
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
  });
});
