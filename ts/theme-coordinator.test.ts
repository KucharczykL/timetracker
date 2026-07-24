// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SETTING_COMMITTED_EVENT } from "./settings-events.js";
import { ThemeCoordinator } from "./theme-coordinator.js";

type MediaListener = (event: MediaQueryListEvent) => void;

let systemDark = false;
let mediaListener: MediaListener | null = null;
let dispatchHtmxTriggers: ReturnType<typeof vi.fn>;

function configureBrowser(preference = "system"): void {
  const root = document.documentElement;
  root.dataset.themeMode = "browser";
  root.dataset.themePreferences = "system light dark";
  root.dataset.themePreference = preference;
}

function configureAccount(options: {
  preference?: string;
  personal?: string;
  inherited?: string;
  source?: string;
} = {}): void {
  const root = document.documentElement;
  root.dataset.themeMode = "account";
  root.dataset.themePreferences = "system light dark";
  root.dataset.themePreference = options.preference ?? "dark";
  root.dataset.themePersonalPreference = options.personal ?? "dark";
  root.dataset.themeInheritedPreference = options.inherited ?? "system";
  root.dataset.themeSource = options.source ?? "user";
  root.dataset.themeUpdateUrl = "/api/settings/user/THEME";
  root.dataset.themeCsrf = "csrf-token";
}

function response(body: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  document.body.replaceChildren();
  document.documentElement.className = "";
  for (const key of Object.keys(document.documentElement.dataset)) {
    delete document.documentElement.dataset[key];
  }
  localStorage.clear();
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
  window.fetchWithHtmxTriggers = vi.fn();
  dispatchHtmxTriggers = vi.fn();
  Object.assign(window, { dispatchHtmxTriggers });
});

afterEach(() => vi.restoreAllMocks());

describe("ThemeCoordinator browser state", () => {
  it("publishes synchronously, persists requests, and follows System OS changes", async () => {
    configureBrowser();
    const coordinator = new ThemeCoordinator();
    const states: unknown[] = [];

    const unsubscribe = coordinator.subscribe((state) => states.push(state));
    expect(states.at(-1)).toMatchObject({
      status: "browser",
      preference: "system",
      saving: false,
    });

    systemDark = true;
    mediaListener?.({ matches: true } as MediaQueryListEvent);
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    expect(await coordinator.requestPreferenceChange("light")).toBe("committed");
    expect(localStorage.getItem("color-theme")).toBe("light");
    expect(document.documentElement.dataset.themePreference).toBe("light");
    expect(window.fetchWithHtmxTriggers).not.toHaveBeenCalled();
    unsubscribe();
    coordinator.destroy();
  });

  it("applies valid storage events and treats removal/invalid values as System", () => {
    configureBrowser("light");
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const coordinator = new ThemeCoordinator();

    window.dispatchEvent(new StorageEvent("storage", {
      key: "color-theme",
      newValue: "dark",
    }));
    expect(coordinator.currentState()).toMatchObject({ preference: "dark" });
    window.dispatchEvent(new StorageEvent("storage", {
      key: "color-theme",
      newValue: null,
    }));
    expect(coordinator.currentState()).toMatchObject({ preference: "system" });
    window.dispatchEvent(new StorageEvent("storage", {
      key: "color-theme",
      newValue: "auto",
    }));
    expect(coordinator.currentState()).toMatchObject({ preference: "system" });
    expect(error).toHaveBeenCalled();
    expect(localStorage.getItem("color-theme")).toBeNull();
    coordinator.destroy();
  });
});

describe("ThemeCoordinator account state", () => {
  it("notifies all subscribers optimistically and commits a validated response", async () => {
    configureAccount();
    let resolve!: (value: Response) => void;
    vi.mocked(window.fetchWithHtmxTriggers).mockReturnValue(new Promise((done) => {
      resolve = done;
    }));
    const committed = vi.fn();
    document.body.addEventListener(SETTING_COMMITTED_EVENT, committed);
    const coordinator = new ThemeCoordinator();
    const first = vi.fn();
    const second = vi.fn();
    coordinator.subscribe(first);
    coordinator.subscribe(second);

    const saving = coordinator.requestPreferenceChange("light");
    expect(first).toHaveBeenLastCalledWith(expect.objectContaining({
      status: "account",
      preference: "light",
      personalPreference: "light",
      saving: true,
    }));
    expect(second).toHaveBeenLastCalledWith(expect.objectContaining({ saving: true }));
    expect(document.documentElement.dataset.themePreference).toBe("light");
    expect(await coordinator.requestPreferenceChange("dark")).toBe("busy");

    const savedResponse = response({
      key: "THEME", value: "light", source: "user", locked: false, namespace: "user",
    });
    resolve(savedResponse);
    expect(await saving).toBe("committed");
    expect(coordinator.currentState()).toMatchObject({
      preference: "light",
      personalPreference: "light",
      source: "user",
      saving: false,
    });
    expect(committed).toHaveBeenCalledTimes(1);
    expect(window.fetchWithHtmxTriggers).toHaveBeenCalledWith(
      "/api/settings/user/THEME",
      expect.any(Object),
      "deferred",
    );
    expect(dispatchHtmxTriggers).toHaveBeenCalledWith(savedResponse);
    expect(JSON.parse(String(
      (vi.mocked(window.fetchWithHtmxTriggers).mock.calls[0][1] as RequestInit).body,
    ))).toEqual({ value: "light" });
    expect(localStorage.getItem("color-theme")).toBeNull();
    coordinator.destroy();
  });

  it("commits null as inherited while retaining a null personal selection", async () => {
    configureAccount({ preference: "light", personal: "light", inherited: "dark" });
    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValue(response({
      key: "THEME",
      value: "dark",
      source: "database",
      locked: false,
      namespace: "user",
    }));
    const coordinator = new ThemeCoordinator();

    expect(await coordinator.requestPreferenceChange(null)).toBe("committed");

    expect(coordinator.currentState()).toMatchObject({
      preference: "dark",
      personalPreference: null,
      source: "database",
      saving: false,
    });
    expect(document.documentElement.dataset.themePersonalPreference).toBe("");
    coordinator.destroy();
  });

  it.each([
    ["network failure", () => Promise.reject(new Error("offline"))],
    ["malformed response", () => Promise.resolve(response({ key: "THEME" }))],
    ["contract mismatch", () => Promise.resolve(response({
      key: "THEME", value: "dark", source: "user", locked: false, namespace: "user",
    }))],
  ])("rolls back committed state after %s and allows retry", async (_name, fetchResult) => {
    configureAccount();
    vi.mocked(window.fetchWithHtmxTriggers).mockImplementationOnce(fetchResult);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const coordinator = new ThemeCoordinator();

    expect(await coordinator.requestPreferenceChange("light")).toBe("rolled-back");
    expect(coordinator.currentState()).toMatchObject({
      preference: "dark",
      personalPreference: "dark",
      saving: false,
    });
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your theme — please try again.",
      "error",
    );
    expect(dispatchHtmxTriggers).not.toHaveBeenCalled();

    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValueOnce(response({
      key: "THEME", value: "light", source: "user", locked: false, namespace: "user",
    }));
    expect(await coordinator.requestPreferenceChange("light")).toBe("committed");
    expect(dispatchHtmxTriggers).toHaveBeenCalledTimes(1);
    coordinator.destroy();
  });

  it("rolls back when the response namespace is not user", async () => {
    configureAccount();
    vi.mocked(window.fetchWithHtmxTriggers).mockResolvedValueOnce(response({
      key: "THEME", value: "light", source: "user", locked: false, namespace: "site",
    }));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const coordinator = new ThemeCoordinator();

    expect(await coordinator.requestPreferenceChange("light")).toBe("rolled-back");
    expect(window.toast).toHaveBeenCalledWith(
      "Couldn't save your theme — please try again.",
      "error",
    );
    coordinator.destroy();
  });

  it("does not cancel a save when subscribers disconnect and resynchronizes on reconnect", async () => {
    configureAccount();
    let resolve!: (value: Response) => void;
    vi.mocked(window.fetchWithHtmxTriggers).mockReturnValue(new Promise((done) => {
      resolve = done;
    }));
    const coordinator = new ThemeCoordinator();
    const first = vi.fn();
    const unsubscribe = coordinator.subscribe(first);
    const saving = coordinator.requestPreferenceChange("light");
    unsubscribe();

    resolve(response({
      key: "THEME", value: "light", source: "user", locked: false, namespace: "user",
    }));
    expect(await saving).toBe("committed");
    const reconnected = vi.fn();
    coordinator.subscribe(reconnected);
    expect(reconnected).toHaveBeenCalledWith(expect.objectContaining({
      preference: "light",
      saving: false,
    }));
    coordinator.destroy();
  });

  it("ignores anonymous storage events", () => {
    configureAccount();
    const coordinator = new ThemeCoordinator();
    window.dispatchEvent(new StorageEvent("storage", {
      key: "color-theme",
      newValue: "light",
    }));
    expect(coordinator.currentState()).toMatchObject({ preference: "dark" });
    coordinator.destroy();
  });
});

describe("ThemeCoordinator unavailable state", () => {
  it("reports invalid document configuration without guessing", async () => {
    configureAccount({ preference: "sepia" });
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const coordinator = new ThemeCoordinator();

    expect(coordinator.currentState()).toMatchObject({ status: "unavailable" });
    expect(await coordinator.requestPreferenceChange("dark")).toBe("rolled-back");
    expect(window.fetchWithHtmxTriggers).not.toHaveBeenCalled();
    expect(error).toHaveBeenCalled();
    coordinator.destroy();
  });
});
