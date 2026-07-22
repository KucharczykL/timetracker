import {
  isThemePreference,
  getThemeCoordinator,
  type ThemeCoordinatorState,
} from "../theme-coordinator.js";

class ThemeSettingElement extends HTMLElement {
  private select: HTMLSelectElement | null = null;
  private unsubscribe: (() => void) | null = null;

  connectedCallback(): void {
    this.select = this.querySelector<HTMLSelectElement>("select");
    this.select?.addEventListener("change", this.onChange);
    this.unsubscribe = getThemeCoordinator().subscribe(this.renderState);
  }

  disconnectedCallback(): void {
    this.select?.removeEventListener("change", this.onChange);
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  private readonly onChange = (event: Event): void => {
    event.stopPropagation();
    if (!this.select) return;
    const value = this.select.value;
    if (value !== "" && !isThemePreference(value)) {
      this.renderState(getThemeCoordinator().currentState());
      return;
    }
    void getThemeCoordinator().requestPreferenceChange(value === "" ? null : value);
  };

  private readonly renderState = (state: ThemeCoordinatorState): void => {
    if (!this.select) return;
    if (state.status === "unavailable") {
      this.select.disabled = true;
      return;
    }
    this.select.value = state.status === "account"
      ? state.personalPreference ?? ""
      : state.preference;
    this.select.disabled = state.saving;
    if (state.saving) {
      this.select.setAttribute("aria-busy", "true");
    } else {
      this.select.removeAttribute("aria-busy");
    }
  };
}

customElements.define("theme-setting", ThemeSettingElement);
