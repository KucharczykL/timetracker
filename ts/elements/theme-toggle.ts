import {
  THEME_LABELS,
  THEME_PREFERENCES,
  type ThemePreference,
} from "../generated/theme-preferences.js";
import {
  getThemeCoordinator,
  type ThemeCoordinatorState,
} from "../theme-coordinator.js";

export function nextTheme(theme: ThemePreference): ThemePreference {
  return THEME_PREFERENCES[
    (THEME_PREFERENCES.indexOf(theme) + 1) % THEME_PREFERENCES.length
  ];
}

class ThemeToggleElement extends HTMLElement {
  private button: HTMLButtonElement | null = null;
  private tooltip: HTMLElement | null = null;
  private preference: ThemePreference = "system";
  private unsubscribe: (() => void) | null = null;

  connectedCallback(): void {
    this.button = this.querySelector<HTMLButtonElement>("[data-pop-over-trigger]");
    this.tooltip = this.querySelector<HTMLElement>("[data-theme-tooltip]");
    this.button?.addEventListener("click", this.onClick);
    this.unsubscribe = getThemeCoordinator().subscribe(this.renderState);
  }

  disconnectedCallback(): void {
    this.button?.removeEventListener("click", this.onClick);
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  private readonly onClick = (): void => {
    void getThemeCoordinator().requestPreferenceChange(nextTheme(this.preference));
  };

  private readonly renderState = (state: ThemeCoordinatorState): void => {
    if (state.status === "unavailable") {
      if (this.button) this.button.disabled = true;
      return;
    }
    this.preference = state.preference;
    this.querySelectorAll<SVGElement>("[data-theme-icon]").forEach((icon) => {
      icon.toggleAttribute(
        "hidden",
        icon.dataset.themeIcon !== this.preference,
      );
    });
    const next = nextTheme(this.preference);
    const description =
      `Theme: ${THEME_LABELS[this.preference]} — switch to ${THEME_LABELS[next]}`;
    this.button?.setAttribute("aria-label", description);
    if (this.tooltip) this.tooltip.textContent = description;
    if (this.button) {
      this.button.disabled = state.saving;
      if (state.saving) {
        this.button.setAttribute("aria-busy", "true");
      } else {
        this.button.removeAttribute("aria-busy");
      }
    }
  };
}

customElements.define("theme-toggle", ThemeToggleElement);
