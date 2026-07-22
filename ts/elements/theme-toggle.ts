import { readThemeToggleProps } from "../generated/props.js";

export type ThemePreference = "auto" | "light" | "dark";

const THEMES: readonly ThemePreference[] = ["auto", "light", "dark"];
const STORAGE_KEY = "color-theme";
const COOKIE_MAX_AGE = 365 * 24 * 60 * 60;

function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && THEMES.includes(value as ThemePreference);
}

export function nextTheme(theme: ThemePreference): ThemePreference {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
}

function label(theme: ThemePreference): string {
  return theme === "auto" ? "Auto" : theme[0].toUpperCase() + theme.slice(1);
}

function safeWriteStorage(theme: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch (_error) {
    // A privacy policy may disable storage; the cookie still carries preference.
  }
}

class ThemeToggleElement extends HTMLElement {
  private apiUrl = "";
  private csrf = "";
  private cookieSecure = false;
  private button: HTMLButtonElement | null = null;
  private theme: ThemePreference = "auto";
  private saving = false;
  private readonly media = window.matchMedia("(prefers-color-scheme: dark)");

  connectedCallback(): void {
    const props = readThemeToggleProps(this);
    this.apiUrl = props.apiUrl;
    this.csrf = props.csrf;
    this.cookieSecure = props.cookieSecure;
    this.button = this.querySelector<HTMLButtonElement>("[data-theme-toggle]");
    const initial = document.documentElement.dataset.themePreference;
    this.theme = isThemePreference(initial) ? initial : "auto";
    this.apply(this.theme);

    this.button?.addEventListener("click", this.onClick);
    this.media.addEventListener("change", this.onSystemChange);
    window.addEventListener("storage", this.onStorage);
    document.body.addEventListener("setting-saved", this.onSettingSaved);

    if (this.apiUrl && document.documentElement.dataset.themeMigration === "true") {
      this.syncSettingsControl(this.theme);
      void this.persist(this.theme, this.theme);
    }
  }

  disconnectedCallback(): void {
    this.button?.removeEventListener("click", this.onClick);
    this.media.removeEventListener("change", this.onSystemChange);
    window.removeEventListener("storage", this.onStorage);
    document.body.removeEventListener("setting-saved", this.onSettingSaved);
  }

  private readonly onClick = (): void => {
    if (this.saving) return;
    const previous = this.theme;
    const desired = nextTheme(previous);
    this.apply(desired);
    if (this.apiUrl) {
      void this.persist(desired, previous);
    } else {
      safeWriteStorage(desired);
      this.writeBrowserCookie(desired);
    }
  };

  private readonly onSystemChange = (): void => {
    if (this.theme === "auto") this.applyEffectiveClass();
  };

  private readonly onStorage = (event: StorageEvent): void => {
    if (event.key === STORAGE_KEY && isThemePreference(event.newValue)) {
      this.apply(event.newValue);
    }
  };

  private readonly onSettingSaved = (event: Event): void => {
    const detail = (event as CustomEvent<{ key?: string; value?: unknown }>).detail;
    if (detail?.key !== "THEME" || !isThemePreference(detail.value)) return;
    this.apply(detail.value);
    safeWriteStorage(detail.value);
  };

  private apply(theme: ThemePreference): void {
    this.theme = theme;
    document.documentElement.dataset.themePreference = theme;
    this.applyEffectiveClass();
    this.querySelectorAll<HTMLElement>("[data-theme-icon]").forEach((icon) => {
      icon.hidden = icon.dataset.themeIcon !== theme;
    });
    const next = nextTheme(theme);
    const description = `Theme: ${label(theme)} — switch to ${label(next)}`;
    this.button?.setAttribute("aria-label", description);
    this.button?.setAttribute("title", description);
  }

  private applyEffectiveClass(): void {
    const dark = this.theme === "dark" || (this.theme === "auto" && this.media.matches);
    document.documentElement.classList.toggle("dark", dark);
  }

  private async persist(
    desired: ThemePreference,
    previous: ThemePreference,
  ): Promise<void> {
    this.saving = true;
    if (this.button) {
      this.button.disabled = true;
      this.button.setAttribute("aria-busy", "true");
    }
    try {
      const response = await window.fetchWithHtmxTriggers(this.apiUrl, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.csrf,
        },
        body: JSON.stringify({ value: desired }),
      });
      if (!response.ok) throw new Error(`PATCH ${this.apiUrl} → ${response.status}`);
      const resolved = await response.json() as { value?: unknown };
      const committed = isThemePreference(resolved.value) ? resolved.value : desired;
      this.apply(committed);
      safeWriteStorage(committed);
      delete document.documentElement.dataset.themeMigration;
      this.syncSettingsControl(committed);
    } catch (error) {
      console.error("Failed to update theme", error);
      this.apply(previous);
      window.toast("Couldn't save your theme — please try again.", "error");
    } finally {
      this.saving = false;
      if (this.button) {
        this.button.disabled = false;
        this.button.removeAttribute("aria-busy");
      }
    }
  }

  private syncSettingsControl(theme: ThemePreference): void {
    const control = document.querySelector<HTMLSelectElement>('[data-setting-key="THEME"]');
    if (control) control.value = theme;
  }

  private writeBrowserCookie(theme: ThemePreference): void {
    const secure = this.cookieSecure ? "; Secure" : "";
    document.cookie = `${STORAGE_KEY}=${theme}; Max-Age=${COOKIE_MAX_AGE}; Path=/; SameSite=Lax${secure}`;
  }
}

customElements.define("theme-toggle", ThemeToggleElement);
