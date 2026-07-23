// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getThemeCoordinator,
  resetThemeCoordinatorForTests,
} from "../theme-coordinator.js";
import { nextTheme } from "./theme-toggle.js";
import "./theme-toggle.js";

function configure(mode: "browser" | "account", preference = "system"): void {
  const root = document.documentElement;
  root.dataset.themeMode = mode;
  root.dataset.themePreferences = "system light dark";
  root.dataset.themePreference = preference;
  if (mode === "account") {
    root.dataset.themePersonalPreference = preference;
    root.dataset.themeInheritedPreference = "system";
    root.dataset.themeSource = "user";
    root.dataset.themeUpdateUrl = "/api/settings/user/THEME";
    root.dataset.themeCsrf = "token";
  }
}

function mount(permanentlyDisabled = false): HTMLElement {
  const disabledHostAttribute = permanentlyDisabled ? ' disabled="true"' : "";
  const triggerStart = permanentlyDisabled
    ? '<span data-pop-over-trigger tabindex="0">'
    : "";
  const triggerEnd = permanentlyDisabled ? "</span>" : "";
  const buttonTriggerAttribute = permanentlyDisabled
    ? ""
    : " data-pop-over-trigger";
  const disabledButtonAttribute = permanentlyDisabled ? " disabled" : "";
  document.body.innerHTML = `
    <theme-toggle class="block"${disabledHostAttribute}>
      <pop-over>${triggerStart}<button type="button" data-pop-over-control${buttonTriggerAttribute}${disabledButtonAttribute}>
        <svg data-theme-icon="system"></svg>
        <svg data-theme-icon="light" hidden></svg>
        <svg data-theme-icon="dark" hidden></svg>
      </button>${triggerEnd}<div data-pop-over-panel><span data-theme-tooltip></span></div></pop-over>
    </theme-toggle>`;
  return document.querySelector("theme-toggle")!;
}

beforeEach(() => {
  document.body.replaceChildren();
  document.documentElement.className = "";
  for (const key of Object.keys(document.documentElement.dataset)) {
    delete document.documentElement.dataset[key];
  }
  localStorage.clear();
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

describe("nextTheme", () => {
  it("cycles the generated System, Light, and Dark vocabulary", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });
});

describe("<theme-toggle>", () => {
  it("keeps a permanently disabled toggle disabled after coordinator updates", async () => {
    configure("browser");
    const host = mount(true);
    const button = host.querySelector<HTMLButtonElement>("button")!;
    const tooltipTrigger = host.querySelector<HTMLElement>(
      "[data-pop-over-trigger]",
    )!;

    await getThemeCoordinator().requestPreferenceChange("light");

    expect(button.disabled).toBe(true);
    expect(tooltipTrigger).not.toBe(button);
    expect(tooltipTrigger.tabIndex).toBe(0);
    expect(host.querySelector('[data-theme-icon="light"]')?.hasAttribute("hidden"))
      .toBe(false);
  });

  it("does not request a preference change from a permanently disabled toggle", async () => {
    configure("account", "dark");
    const fetchStub = vi.fn();
    window.fetchWithHtmxTriggers = fetchStub;
    const host = mount(true);
    const button = host.querySelector<HTMLButtonElement>("button")!;
    const requestPreferenceChange = vi.spyOn(
      getThemeCoordinator(),
      "requestPreferenceChange",
    );

    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await Promise.resolve();

    expect(requestPreferenceChange).not.toHaveBeenCalled();
    expect(fetchStub).not.toHaveBeenCalled();
    expect(button.disabled).toBe(true);
  });

  it("presents coordinator state with distinct icons, tooltip text, and labels", async () => {
    configure("browser");
    const host = mount();
    const button = host.querySelector<HTMLButtonElement>("button")!;

    expect(button.getAttribute("aria-label")).toBe(
      "Theme: System — switch to Light",
    );
    button.click();
    await vi.waitFor(() => expect(localStorage.getItem("color-theme")).toBe("light"));

    expect(host.querySelector('[data-theme-icon="system"]')?.hasAttribute("hidden"))
      .toBe(true);
    expect(host.querySelector('[data-theme-icon="light"]')?.hasAttribute("hidden"))
      .toBe(false);
    expect(host.querySelector('[data-theme-icon="dark"]')?.hasAttribute("hidden"))
      .toBe(true);
    expect(host.querySelector("[data-theme-tooltip]")?.textContent).toBe(
      "Theme: Light — switch to Dark",
    );
    expect(document.cookie).not.toContain("color-theme=");
  });

  it("disables while an account save is pending and reflects rollback", async () => {
    configure("account", "dark");
    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mount();
    const button = host.querySelector<HTMLButtonElement>("button")!;

    button.click();
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(window.fetchWithHtmxTriggers).toHaveBeenCalledTimes(1);
    expect(document.documentElement.dataset.themePreference).toBe("system");

    await vi.waitFor(() => expect(button.disabled).toBe(false));
    expect(button.hasAttribute("aria-busy")).toBe(false);
    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(host.querySelector('[data-theme-icon="dark"]')?.hasAttribute("hidden"))
      .toBe(false);
  });

  it("disables when document theme configuration is unavailable", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mount();
    expect(host.querySelector<HTMLButtonElement>("button")?.disabled).toBe(true);
    expect(error).toHaveBeenCalled();
  });
});
