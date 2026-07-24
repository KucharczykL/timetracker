import { readSettingSourceBadgeProps } from "../generated/props.js";
import {
  parseResolvedSetting,
  SETTING_COMMITTED_EVENT,
  type ResolvedSetting,
} from "../settings-events.js";

const SOURCE_METADATA: Record<string, { label: string; description: string }> = {
  user: {
    label: "Personal",
    description: "Saved for your account and overrides the site default.",
  },
  database: {
    label: "Database",
    description: "Saved in the application database as the current site-wide value.",
  },
  env: { label: "Environment", description: "Loaded from an environment variable." },
  env_file: {
    label: "Environment file",
    description: "Loaded from a file referenced by an environment variable.",
  },
  dotenv: {
    label: ".env",
    description: "Loaded from the application's .env file.",
  },
  ini: {
    label: "settings.ini",
    description: "Loaded from the application's settings.ini file.",
  },
  default: {
    label: "Default",
    description: "The built-in default, used because no higher-priority value is set.",
  },
};

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
    const metadata = SOURCE_METADATA[resolved.source];
    const label = this.querySelector<HTMLElement>("[data-setting-source-label]");
    if (label) label.textContent = metadata.label;
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
      `${metadata.label} source${resolved.locked ? ", locked" : ""}`,
    );
    const description = this.querySelector<HTMLElement>(
      "[data-setting-source-description] dd",
    );
    if (description) description.textContent = metadata.description;
    const status = this.querySelector<HTMLElement>("[data-setting-source-status]");
    if (status) status.hidden = resolved.locked || resolved.source === "default";
  }
}

customElements.define("setting-source-badge", SettingSourceBadgeElement);

