/** Optimistic live-save for every setting control. */
import { readLiveSettingFieldsProps } from "../generated/props.js";
import {
  changedSettingControl,
  SETTING_CHANGE_EVENTS,
  settingControlOf,
  snapshotsEqual,
  type ControlSnapshot,
  type SaveAttempt,
  type SettingControl,
} from "../setting-control.js";
import {
  dispatchSettingCommitted,
  parseResolvedSetting,
  type ResolvedSetting,
} from "../settings-events.js";
import { reloadAfterSettingSave } from "../settings-reload.js";

interface PendingSave {
  controller: AbortController;
  queued: SaveAttempt | null;
  restoreAfterSettle: boolean;
}

class LiveSettingFieldsElement extends HTMLElement {
  private patchUrlTemplate = "";
  private csrf = "";
  private namespace = "";
  private committed = new Map<HTMLElement, ControlSnapshot>();
  private pending = new Map<HTMLElement, PendingSave>();

  connectedCallback(): void {
    const props = readLiveSettingFieldsProps(this);
    this.patchUrlTemplate = props.patchUrlTemplate;
    this.csrf = props.csrf;
    this.namespace = props.namespace;
    this.querySelectorAll<HTMLElement>("[data-live-setting-control]").forEach((candidate) => {
      const control = settingControlOf(candidate);
      if (control) this.committed.set(candidate, control.snapshot());
      else console.error("live-setting-fields: no reader for", candidate);
    });
    SETTING_CHANGE_EVENTS.forEach(type => this.addEventListener(type, this.onChange));
    this.addEventListener("focusout", this.onLeave);
  }

  disconnectedCallback(): void {
    SETTING_CHANGE_EVENTS.forEach(type => this.removeEventListener(type, this.onChange));
    this.removeEventListener("focusout", this.onLeave);
    this.pending.forEach(({ controller }) => controller.abort());
    this.pending.clear();
  }

  private onChange = (event: Event): void => {
    const control = changedSettingControl(event);
    if (!control || !this.contains(control.element) || !control.editable()) return;
    this.save(control);
  };

  //: Leaving shows the committed value again.
  private onLeave = (event: FocusEvent): void => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const element = target.closest<HTMLElement>("[data-live-setting-control]");
    if (!element || !this.contains(element)) return;
    if (element.contains(event.relatedTarget as Node | null)) return;
    // A settling save reconciles on its own.
    if (this.pending.has(element)) return;
    const committed = this.committed.get(element);
    const control = settingControlOf(element);
    if (!committed || !control) return;
    if (!snapshotsEqual(control.snapshot(), committed)) control.restore(committed);
  };

  private save(control: SettingControl): void {
    const element = control.element;
    const key = element.dataset.settingKey ?? "";
    if (!key || !this.patchUrlTemplate.includes("__key__")) return;
    const value = control.read();
    // A first keystroke's drop is no reset.
    if (value === undefined) return;
    if (typeof value === "number" && !Number.isFinite(value)) {
      window.toast("Enter a valid number before saving.", "error");
      control.restore(this.committed.get(element) ?? control.snapshot());
      const active = this.pending.get(element);
      if (active) {
        // The invalid edit supersedes any queued valid edit. Let the active
        // request settle, then reflect whichever value really committed.
        active.queued = null;
        active.restoreAfterSettle = true;
      }
      return;
    }

    const attempt = { value, state: control.snapshot() };
    const active = this.pending.get(element);
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
    const element = control.element;
    const controller = new AbortController();
    const pending: PendingSave = {
      controller,
      queued: null,
      restoreAfterSettle: false,
    };
    this.pending.set(element, pending);
    control.setBusy(true);
    const url = this.patchUrlTemplate.replace("__key__", encodeURIComponent(key));

    try {
      const response = await window.fetchWithEvents(url, {
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
      if (this.pending.get(element) !== pending) return;
      const committedState = control.resolvedSnapshot(attempt, resolved);
      this.committed.set(element, committedState);
      if (pending.restoreAfterSettle && pending.queued === null) {
        control.restore(committedState);
      } else if (
        pending.queued === null &&
        snapshotsEqual(control.snapshot(), attempt.state)
      ) {
        // Reconcile server normalization/fallback only while this response
        // still represents the visible edit. Preserve newer unsubmitted input.
        control.restore(committedState);
      }
      dispatchSettingCommitted(resolved);
      if (element.hasAttribute("data-reload-after-save")) {
        reloadAfterSettingSave();
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      console.error("Failed to update setting", key, error);
      if (this.pending.get(element) !== pending) return;
      // A superseded failure must not overwrite or alarm for the newer value
      // waiting behind it. If the user is editing but has not committed
      // yet, preserve that newer DOM state while still reporting the failure.
      if (pending.queued === null) {
        const previous = this.committed.get(element);
        if (previous && snapshotsEqual(control.snapshot(), attempt.state)) {
          control.restore(previous);
        }
        window.toast("Couldn't save your change — please try again.", "error");
      }
    } finally {
      if (this.pending.get(element) === pending) {
        const next = pending.queued;
        this.pending.delete(element);
        if (next && this.isConnected) {
          void this.performSave(control, key, next);
        } else {
          control.setBusy(false);
        }
      }
    }
  }
}

customElements.define("live-setting-fields", LiveSettingFieldsElement);
