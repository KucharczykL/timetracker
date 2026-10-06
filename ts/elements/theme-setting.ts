import { settingControlOf, type SettingControl } from "../setting-control.js";
import {
  isThemePreference,
  getThemeCoordinator,
  type ThemeCoordinatorState,
} from "../theme-coordinator.js";

class ThemeSettingElement extends HTMLElement {
  private control: SettingControl | null = null;
  private unsubscribe: (() => void) | null = null;

  connectedCallback(): void {
    const element = this.querySelector("[data-setting-key]");
    this.control = element ? settingControlOf(element) : null;
    if (!this.control) console.error("theme-setting: no readable control");
    this.control?.element.addEventListener(this.control.changeEvent, this.onChange);
    this.unsubscribe = getThemeCoordinator().subscribe(this.renderState);
  }

  disconnectedCallback(): void {
    this.control?.element.removeEventListener(this.control.changeEvent, this.onChange);
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  private readonly onChange = (event: Event): void => {
    // The coordinator saves, not the generic element.
    event.stopPropagation();
    const value = this.control?.read();
    if (value === undefined) return;
    if (value !== null && (typeof value !== "string" || !isThemePreference(value))) {
      console.error("theme-setting: not a theme preference", value);
      this.renderState(getThemeCoordinator().currentState());
      return;
    }
    void getThemeCoordinator().requestPreferenceChange(value);
  };

  private readonly renderState = (state: ThemeCoordinatorState): void => {
    const control = this.control;
    if (!control) return;
    if (state.status === "unavailable") {
      control.setDisabled(true);
      return;
    }
    control.write(state.status === "account" ? state.personalPreference : state.preference);
    control.setDisabled(state.saving);
    control.setBusy(state.saving);
  };
}

customElements.define("theme-setting", ThemeSettingElement);
