import { readSettingSourceBadgeProps } from "../generated/props.js";
import { SETTING_SOURCE_LABELS } from "../generated/settings-vocabulary.js";
import {
  parseResolvedSetting,
  SETTING_COMMITTED_EVENT,
  type ResolvedSetting,
  type SettingSource,
} from "../settings-events.js";

const SOURCE_DESCRIPTIONS = {
  user: "Saved for your account and overrides the site default.",
  database: "Saved in the application database as the current site-wide value.",
  env: "Loaded from an environment variable.",
  env_file: "Loaded from a file referenced by an environment variable.",
  dotenv: "Loaded from the application's .env file.",
  ini: "Loaded from the application's settings.ini file.",
  default: "The built-in default, used because no higher-priority value is set.",
} satisfies Record<SettingSource, string>;

const SOURCE_TONE_CLASSES = {
  brand: ["bg-brand-soft", "text-heading"],
  neutral: ["bg-neutral-quaternary", "text-heading"],
  warning: ["bg-warning-soft", "text-fg-warning"],
};
const ALL_SOURCE_TONE_CLASSES = Object.values(SOURCE_TONE_CLASSES).flat();

class SettingSourceBadgeElement extends HTMLElement {
  private settingKey = "";
  private namespace = "";

  connectedCallback(): void {
    const props = readSettingSourceBadgeProps(this);
    this.settingKey = props.key;
    this.namespace = props.namespace;
    document.body.addEventListener(SETTING_COMMITTED_EVENT, this.onCommitted);
  }

  disconnectedCallback(): void {
    document.body.removeEventListener(SETTING_COMMITTED_EVENT, this.onCommitted);
  }

  private onCommitted = (event: Event): void => {
    if (!(event instanceof CustomEvent)) return;
    let resolved: ResolvedSetting;
    try {
      resolved = parseResolvedSetting(event.detail);
    } catch (error) {
      console.error("Ignoring malformed setting-committed event", error);
      return;
    }
    if (resolved.key !== this.settingKey || resolved.namespace !== this.namespace) {
      return;
    }
    this.update(resolved);
  };

  private update(resolved: ResolvedSetting): void {
    const badge = this.querySelector<HTMLElement>("[data-setting-origin]");
    if (!badge) return;
    const label = SETTING_SOURCE_LABELS[resolved.source];
    const description = SOURCE_DESCRIPTIONS[resolved.source];
    const labelElement = this.querySelector<HTMLElement>("[data-setting-source-label]");
    if (labelElement) labelElement.textContent = label;
    badge.dataset.settingOrigin = resolved.source;
    badge.toggleAttribute("data-setting-locked", resolved.locked);
    badge.classList.remove(...ALL_SOURCE_TONE_CLASSES);
    badge.classList.add(...(
      resolved.locked
        ? SOURCE_TONE_CLASSES.warning
        : resolved.source === "default"
          ? SOURCE_TONE_CLASSES.neutral
          : SOURCE_TONE_CLASSES.brand
    ));

    this.querySelector<HTMLElement>("[data-pop-over-trigger]")?.setAttribute(
      "aria-label",
      `${label} source${resolved.locked ? ", locked" : ""}`,
    );
    const descriptionElement = this.querySelector<HTMLElement>(
      "[data-setting-source-description] dd",
    );
    if (descriptionElement) descriptionElement.textContent = description;
    const status = this.querySelector<HTMLElement>("[data-setting-source-status]");
    if (status) status.hidden = resolved.locked || resolved.source === "default";
  }
}

customElements.define("setting-source-badge", SettingSourceBadgeElement);

