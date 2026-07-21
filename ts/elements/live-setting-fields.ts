/** Optimistic live-save for native Django setting controls (issue #384). */
import { readLiveSettingFieldsProps } from "../generated/props.js";

type SettingControl = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

interface ControlSnapshot {
  value: string;
  checked?: boolean;
}

type SettingValue = string | number | boolean | null;

interface SaveAttempt {
  value: SettingValue;
  state: ControlSnapshot;
}

interface PendingSave {
  controller: AbortController;
  queued: SaveAttempt | null;
  restoreAfterSettle: boolean;
}

interface ResolvedSetting {
  key: string;
  value: SettingValue;
  source: string;
  locked: boolean;
}

const SOURCE_METADATA: Record<string, { label: string; description: string }> = {
  user: {
    label: "Personal",
    description: "Saved for your account and overrides the site default.",
  },
  database: {
    label: "Database",
    description: "Saved in the application database as the current site-wide value.",
  },
  env: {
    label: "Environment",
    description: "Loaded from an environment variable.",
  },
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

function isSettingControl(element: Element | null): element is SettingControl {
  return (
    element instanceof HTMLInputElement ||
    element instanceof HTMLSelectElement ||
    element instanceof HTMLTextAreaElement
  );
}

export function settingPayloadValue(
  control: SettingControl,
): SettingValue {
  if (control instanceof HTMLInputElement) {
    if (control.type === "checkbox") return control.checked;
    if (control.type === "number") {
      return control.value === "" ? null : control.valueAsNumber;
    }
  }
  // The settings API's clearing contract is value:null. Treat an empty native
  // control consistently across select/text/textarea so clearing a personal
  // override falls through to its site/default layer instead of storing "".
  if (control.value === "") return null;
  return control.value;
}

function snapshot(control: SettingControl): ControlSnapshot {
  return {
    value: control.value,
    ...(control instanceof HTMLInputElement && control.type === "checkbox"
      ? { checked: control.checked }
      : {}),
  };
}

function restore(control: SettingControl, state: ControlSnapshot): void {
  control.value = state.value;
  if (
    control instanceof HTMLInputElement &&
    control.type === "checkbox" &&
    state.checked !== undefined
  ) {
    control.checked = state.checked;
  }
}

function snapshotsEqual(left: ControlSnapshot, right: ControlSnapshot): boolean {
  return left.value === right.value && left.checked === right.checked;
}

class LiveSettingFieldsElement extends HTMLElement {
  private patchUrlTemplate = "";
  private csrf = "";
  private successEvent = "setting-saved";
  private committed = new Map<SettingControl, ControlSnapshot>();
  private pending = new Map<SettingControl, PendingSave>();

  connectedCallback(): void {
    const props = readLiveSettingFieldsProps(this);
    this.patchUrlTemplate = props.patchUrlTemplate;
    this.csrf = props.csrf;
    this.successEvent = props.event || "setting-saved";
    this.querySelectorAll<HTMLElement>("[data-setting-key]").forEach((candidate) => {
      if (isSettingControl(candidate)) this.committed.set(candidate, snapshot(candidate));
    });
    this.addEventListener("change", this.onChange);
  }

  disconnectedCallback(): void {
    this.removeEventListener("change", this.onChange);
    this.pending.forEach(({ controller }) => controller.abort());
    this.pending.clear();
  }

  private onChange = (event: Event): void => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const control = target.closest<HTMLElement>("[data-setting-key]");
    if (!isSettingControl(control) || !this.contains(control)) return;
    const readOnly =
      (control instanceof HTMLInputElement ||
        control instanceof HTMLTextAreaElement) &&
      control.readOnly;
    if (control.disabled || readOnly) return;
    this.save(control);
  };

  private updateSourceMetadata(resolved: ResolvedSetting): void {
    const badge = Array.from(
      this.querySelectorAll<HTMLElement>("[data-setting-source-key]"),
    ).find((candidate) => candidate.dataset.settingSourceKey === resolved.key);
    if (!badge) return;

    const source = resolved.source;
    const metadata = SOURCE_METADATA[source] ?? {
      label: source
        .replaceAll("_", " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase()),
      description: `Provided by ${source}.`,
    };
    badge.dataset.settingOrigin = source;
    badge.textContent = metadata.label;
    badge.classList.remove(...ALL_SOURCE_TONE_CLASSES);
    const tone = resolved.locked
      ? SOURCE_TONE_CLASSES.warning
      : source === "default"
        ? SOURCE_TONE_CLASSES.neutral
        : SOURCE_TONE_CLASSES.brand;
    badge.classList.add(...tone);

    const popover = badge.closest("pop-over");
    popover
      ?.querySelector<HTMLElement>("[data-pop-over-trigger]")
      ?.setAttribute("aria-label", `${metadata.label} source`);
    const description = popover?.querySelector<HTMLElement>(
      "[data-setting-source-description] dd",
    );
    if (description) description.textContent = metadata.description;
    const status = popover?.querySelector<HTMLElement>(
      "[data-setting-source-status]",
    );
    if (status) status.hidden = resolved.locked || source === "default";
  }

  private save(control: SettingControl): void {
    const key = control.dataset.settingKey ?? "";
    if (!key || !this.patchUrlTemplate.includes("__key__")) return;
    const value = settingPayloadValue(control);
    if (typeof value === "number" && !Number.isFinite(value)) {
      window.toast("Enter a valid number before saving.", "error");
      restore(control, this.committed.get(control) ?? snapshot(control));
      const active = this.pending.get(control);
      if (active) {
        // The invalid edit supersedes any queued valid edit. Let the active
        // request settle, then reflect whichever value really committed.
        active.queued = null;
        active.restoreAfterSettle = true;
      }
      return;
    }

    const attempt = { value, state: snapshot(control) };
    const active = this.pending.get(control);
    if (active) {
      // Never overlap writes for one setting. Aborting fetch only stops the
      // browser from observing a response; a Django handler may already be
      // committing it. Coalesce rapid edits to the latest desired value and
      // send it after the current request has completed server-side.
      active.queued = attempt;
      active.restoreAfterSettle = false;
      return;
    }

    void this.performSave(control, key, attempt);
  }

  private async performSave(
    control: SettingControl,
    key: string,
    attempt: SaveAttempt,
  ): Promise<void> {
    const controller = new AbortController();
    const pending: PendingSave = {
      controller,
      queued: null,
      restoreAfterSettle: false,
    };
    this.pending.set(control, pending);
    control.setAttribute("aria-busy", "true");
    const url = this.patchUrlTemplate.replace("__key__", encodeURIComponent(key));

    try {
      const response = await window.fetchWithHtmxTriggers(url, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.csrf,
        },
        body: JSON.stringify({ value: attempt.value }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`PATCH ${url} → ${response.status}`);
      const resolved = response.status === 204
        ? null
        : (await response.json()) as ResolvedSetting;
      if (this.pending.get(control) !== pending) return;
      // Record the exact value represented by this response. The user may have
      // already edited the DOM again while it was in flight.
      this.committed.set(control, attempt.state);
      if (resolved) this.updateSourceMetadata(resolved);
      if (pending.restoreAfterSettle && pending.queued === null) {
        restore(control, attempt.state);
      }
      document.body.dispatchEvent(
        new CustomEvent(this.successEvent, {
          detail: { key, value: attempt.value },
          bubbles: true,
        }),
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      console.error("Failed to update setting", key, error);
      if (this.pending.get(control) !== pending) return;
      // A superseded failure must not overwrite or alarm for the newer value
      // waiting behind it. If the user is typing but has not fired `change`
      // yet, preserve that newer DOM state while still reporting the failure.
      if (pending.queued === null) {
        const previous = this.committed.get(control);
        if (previous && snapshotsEqual(snapshot(control), attempt.state)) {
          restore(control, previous);
        }
        window.toast("Couldn't save your change — please try again.", "error");
      }
    } finally {
      if (this.pending.get(control) === pending) {
        const next = pending.queued;
        this.pending.delete(control);
        if (next && this.isConnected) {
          void this.performSave(control, key, next);
        } else {
          control.removeAttribute("aria-busy");
        }
      }
    }
  }
}

customElements.define("live-setting-fields", LiveSettingFieldsElement);
