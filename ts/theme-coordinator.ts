import {
  THEME_PREFERENCES,
  type ThemePreference,
} from "./generated/theme-preferences.js";
import {
  dispatchSettingCommitted,
  parseResolvedSetting,
  SETTING_SOURCES,
  type SettingSource,
} from "./settings-events.js";

const STORAGE_KEY = "color-theme";

export interface ThemeSnapshot {
  readonly preference: ThemePreference;
  readonly personalPreference: ThemePreference | null;
  readonly source: SettingSource;
}

export type ThemeCoordinatorState =
  | {
    readonly status: "browser";
    readonly preference: ThemePreference;
    readonly saving: false;
  }
  | ({ readonly status: "account"; readonly saving: boolean } & ThemeSnapshot)
  | {
    readonly status: "unavailable";
    readonly reason: string;
    readonly saving: false;
  };

export type ThemeChangeResult = "committed" | "rolled-back" | "busy";
type Subscriber = (state: ThemeCoordinatorState) => void;

interface BrowserConfiguration {
  mode: "browser";
}

interface AccountConfiguration {
  mode: "account";
  inheritedPreference: ThemePreference;
  updateUrl: string;
  csrf: string;
}

interface UnavailableConfiguration {
  mode: "unavailable";
  reason: string;
}

type Configuration =
  | BrowserConfiguration
  | AccountConfiguration
  | UnavailableConfiguration;

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" &&
    THEME_PREFERENCES.includes(value as ThemePreference);
}

function unavailable(reason: string): {
  configuration: UnavailableConfiguration;
  state: ThemeCoordinatorState;
} {
  return {
    configuration: { mode: "unavailable", reason },
    state: { status: "unavailable", reason, saving: false },
  };
}

function readConfiguration(root: HTMLElement): {
  configuration: Configuration;
  state: ThemeCoordinatorState;
  committed: ThemeSnapshot | null;
} {
  if (root.dataset.themePreferences !== THEME_PREFERENCES.join(" ")) {
    return { ...unavailable("Invalid data-theme-preferences."), committed: null };
  }
  const preference = root.dataset.themePreference;
  if (!isThemePreference(preference)) {
    return { ...unavailable("Invalid data-theme-preference."), committed: null };
  }
  if (root.dataset.themeMode === "browser") {
    return {
      configuration: { mode: "browser" },
      state: { status: "browser", preference, saving: false },
      committed: null,
    };
  }
  if (root.dataset.themeMode !== "account") {
    return { ...unavailable("Invalid data-theme-mode."), committed: null };
  }

  const personalRaw = root.dataset.themePersonalPreference;
  const personalPreference = personalRaw === "" ? null : personalRaw;
  const inheritedPreference = root.dataset.themeInheritedPreference;
  const source = root.dataset.themeSource;
  const updateUrl = root.dataset.themeUpdateUrl ?? "";
  const csrf = root.dataset.themeCsrf ?? "";
  if (
    !isThemePreference(personalPreference) && personalPreference !== null ||
    !isThemePreference(inheritedPreference) ||
    !SETTING_SOURCES.includes(source as SettingSource) ||
    updateUrl.length === 0 ||
    csrf.length === 0 ||
    (personalPreference === null && source === "user") ||
    (personalPreference !== null && (
      source !== "user" || personalPreference !== preference
    )) ||
    (personalPreference === null && preference !== inheritedPreference)
  ) {
    return { ...unavailable("Invalid account theme configuration."), committed: null };
  }
  const snapshot: ThemeSnapshot = {
    preference,
    personalPreference,
    source: source as SettingSource,
  };
  return {
    configuration: {
      mode: "account",
      inheritedPreference,
      updateUrl,
      csrf,
    },
    state: { status: "account", ...snapshot, saving: false },
    committed: snapshot,
  };
}

export class ThemeCoordinator {
  private readonly root: HTMLElement;
  private readonly media: MediaQueryList;
  private readonly subscribers = new Set<Subscriber>();
  private configuration: Configuration;
  private state: ThemeCoordinatorState;
  private committed: ThemeSnapshot | null;

  constructor(root: HTMLElement = document.documentElement) {
    this.root = root;
    this.media = window.matchMedia("(prefers-color-scheme: dark)");
    const parsed = readConfiguration(root);
    this.configuration = parsed.configuration;
    this.state = parsed.state;
    this.committed = parsed.committed;
    if (this.configuration.mode === "unavailable") {
      console.error(`Theme controls unavailable: ${this.configuration.reason}`);
      return;
    }
    this.media.addEventListener("change", this.onSystemChange);
    if (this.configuration.mode === "browser") {
      window.addEventListener("storage", this.onStorage);
    }
    this.applyState();
  }

  currentState(): ThemeCoordinatorState {
    return this.state;
  }

  subscribe(subscriber: Subscriber): () => void {
    this.subscribers.add(subscriber);
    subscriber(this.state);
    return () => this.subscribers.delete(subscriber);
  }

  async requestPreferenceChange(
    desired: ThemePreference | null,
  ): Promise<ThemeChangeResult> {
    if (this.configuration.mode === "unavailable") return "rolled-back";
    if (this.state.saving) return "busy";
    if (this.configuration.mode === "browser") {
      if (desired === null) return "rolled-back";
      this.state = { status: "browser", preference: desired, saving: false };
      this.applyState();
      this.notify();
      try {
        localStorage.setItem(STORAGE_KEY, desired);
      } catch (error) {
        console.error("Failed to save browser theme preference", error);
      }
      return "committed";
    }

    const previous = this.committed;
    if (!previous) return "rolled-back";
    const optimistic: ThemeSnapshot = {
      preference: desired ?? this.configuration.inheritedPreference,
      personalPreference: desired,
      source: desired === null ? previous.source : "user",
    };
    this.state = { status: "account", ...optimistic, saving: true };
    this.applyState();
    this.notify();

    try {
      const response = await window.fetchWithHtmxTriggers(
        this.configuration.updateUrl,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": this.configuration.csrf,
          },
          body: JSON.stringify({ value: desired }),
        },
        "deferred",
      );
      if (!response.ok) {
        throw new Error(
          `PATCH ${this.configuration.updateUrl} → ${response.status}`,
        );
      }
      const resolved = parseResolvedSetting(await response.json());
      if (
        resolved.key !== "THEME" ||
        resolved.namespace !== "user" ||
        !isThemePreference(resolved.value) ||
        resolved.locked ||
        (desired === null && resolved.source === "user") ||
        (desired !== null && (
          resolved.source !== "user" || resolved.value !== desired
        ))
      ) {
        throw new Error("Theme PATCH response violated its contract");
      }
      const committed: ThemeSnapshot = {
        preference: resolved.value,
        personalPreference: desired,
        source: resolved.source,
      };
      if (desired === null) {
        this.configuration.inheritedPreference = resolved.value;
      }
      this.committed = committed;
      this.state = { status: "account", ...committed, saving: false };
      this.applyState();
      this.notify();
      dispatchSettingCommitted(resolved);
      window.dispatchHtmxTriggers(response);
      return "committed";
    } catch (error) {
      console.error("Failed to update theme", error);
      this.state = { status: "account", ...previous, saving: false };
      this.applyState();
      this.notify();
      window.toast("Couldn't save your theme — please try again.", "error");
      return "rolled-back";
    }
  }

  destroy(): void {
    this.media.removeEventListener("change", this.onSystemChange);
    window.removeEventListener("storage", this.onStorage);
    this.subscribers.clear();
  }

  private notify(): void {
    this.subscribers.forEach((subscriber) => subscriber(this.state));
  }

  private applyState(): void {
    if (this.state.status === "unavailable") return;
    this.root.dataset.themePreference = this.state.preference;
    if (this.state.status === "account") {
      this.root.dataset.themePersonalPreference =
        this.state.personalPreference ?? "";
      this.root.dataset.themeSource = this.state.source;
    }
    const dark = this.state.preference === "dark" ||
      (this.state.preference === "system" && this.media.matches);
    this.root.classList.toggle("dark", dark);
  }

  private readonly onSystemChange = (): void => {
    if (this.state.status !== "unavailable" && this.state.preference === "system") {
      this.applyState();
    }
  };

  private readonly onStorage = (event: StorageEvent): void => {
    if (event.key !== STORAGE_KEY || this.state.status !== "browser") return;
    let preference: ThemePreference = "system";
    if (event.newValue !== null) {
      if (isThemePreference(event.newValue)) {
        preference = event.newValue;
      } else {
        console.error(`Ignoring invalid browser theme preference: ${event.newValue}`);
      }
    }
    this.state = { status: "browser", preference, saving: false };
    this.applyState();
    this.notify();
  };
}

let coordinator: ThemeCoordinator | null = null;

export function getThemeCoordinator(): ThemeCoordinator {
  coordinator ??= new ThemeCoordinator();
  return coordinator;
}

export function resetThemeCoordinatorForTests(): void {
  coordinator?.destroy();
  coordinator = null;
}
