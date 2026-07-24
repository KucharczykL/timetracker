/** Optimistic live-save for native Django setting controls (issue #384). */
import { readLiveSettingFieldsProps } from "../generated/props.js";
import {
  dispatchSettingCommitted,
  parseResolvedSetting,
  type ResolvedSetting,
} from "../settings-events.js";
import { reloadAfterSettingSave } from "../settings-reload.js";

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

function resolvedSnapshot(
  control: SettingControl,
  attempt: SaveAttempt,
  resolved: ResolvedSetting,
): ControlSnapshot {
  // A blank select is intentional UI state: it means "Use site default" even
  // when the effective value returned by the API matches another option.
  if (control instanceof HTMLSelectElement && attempt.value === null) {
    return attempt.state;
  }
  if (control instanceof HTMLInputElement && control.type === "checkbox") {
    return {
      ...attempt.state,
      checked: typeof resolved.value === "boolean"
        ? resolved.value
        : attempt.state.checked,
    };
  }
  return { value: resolved.value === null ? "" : String(resolved.value) };
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
  private namespace = "";
  private committed = new Map<SettingControl, ControlSnapshot>();
  private pending = new Map<SettingControl, PendingSave>();

  connectedCallback(): void {
    const props = readLiveSettingFieldsProps(this);
    this.patchUrlTemplate = props.patchUrlTemplate;
    this.csrf = props.csrf;
    this.namespace = props.namespace;
    this.querySelectorAll<HTMLElement>("[data-live-setting-control]").forEach((candidate) => {
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
    const control = target.closest<HTMLElement>("[data-live-setting-control]");
    if (!isSettingControl(control) || !this.contains(control)) return;
    const readOnly =
      (control instanceof HTMLInputElement ||
        control instanceof HTMLTextAreaElement) &&
      control.readOnly;
    if (control.disabled || readOnly) return;
    this.save(control);
  };

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
      const resolved = parseResolvedSetting(await response.json());
      if (resolved.key !== key) throw new Error(`PATCH ${url} returned ${resolved.key}`);
      if (resolved.namespace !== this.namespace) {
        throw new Error(`PATCH ${url} returned namespace ${resolved.namespace}`);
      }
      if (this.pending.get(control) !== pending) return;
      const committedState = resolvedSnapshot(control, attempt, resolved);
      this.committed.set(control, committedState);
      if (pending.restoreAfterSettle && pending.queued === null) {
        restore(control, committedState);
      } else if (
        pending.queued === null &&
        snapshotsEqual(snapshot(control), attempt.state)
      ) {
        // Reconcile server normalization/fallback only while this response
        // still represents the visible edit. Preserve newer unsubmitted input.
        restore(control, committedState);
      }
      dispatchSettingCommitted(resolved);
      if (control.hasAttribute("data-reload-after-save")) {
        reloadAfterSettingSave();
      }
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
