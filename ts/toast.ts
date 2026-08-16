import { reportClientError } from "./client-errors.js";

declare const Alpine: any;

type ToastId = number | string;

interface ToastOptions {
  id?: ToastId;
  duration?: number | null;
}

interface Toast {
  id: ToastId;
  message: string;
  type: string;
  visible: boolean;
  duration: number | null;
  remaining: number | null;
  deadline: number | null;
  timer: ReturnType<typeof setTimeout> | null;
  removalTimer: ReturnType<typeof setTimeout> | null;
}

interface ToastStore {
  toasts: Toast[];
  addToast(message: string, type?: string, options?: ToastOptions): void;
  dismissToast(id: ToastId, notify?: boolean): void;
  removeToast(id: ToastId): void;
  clearToastTimer(id: ToastId): void;
  resumeToastTimer(id: ToastId): void;
  startToastTimer(toast: Toast): void;
}

interface ToastMessage extends ToastOptions {
  message: string;
  type?: string;
}

function defaultDuration(type: string): number | null {
  if (type === "error") return null;
  return type === "debug" ? 3_000 : 5_000;
}

document.addEventListener("alpine:init", () => {
  let idCounter = 0;

  console.log("[toast] Alpine available:", typeof Alpine !== "undefined");

  const store: ToastStore = {
    toasts: [],

    addToast(message: string, type?: string, options: ToastOptions = {}) {
      console.log("[toast] addToast called:", { message, type, options });
      if (!type) type = "info";
      const validTypes = ["success", "error", "info", "warning", "debug"];
      if (!validTypes.includes(type)) type = "info";
      const id = options.id ?? ++idCounter;
      const duration = options.duration === undefined
        ? defaultDuration(type)
        : options.duration;
      const existing = this.toasts.find((toast) => toast.id === id);

      if (existing) {
        if (existing.timer) clearTimeout(existing.timer);
        if (existing.removalTimer) clearTimeout(existing.removalTimer);
        Object.assign(existing, {
          message,
          type,
          visible: true,
          duration,
          remaining: duration,
          deadline: null,
          timer: null,
          removalTimer: null,
        });
        this.startToastTimer(existing);
        return;
      }

      if (this.toasts.length >= 3) {
        console.log("[toast] max 3 toasts reached, removing oldest");
        const oldest = this.toasts.shift();
        if (oldest?.timer) clearTimeout(oldest.timer);
        if (oldest?.removalTimer) clearTimeout(oldest.removalTimer);
      }

      console.log("[toast] toast added, count:", this.toasts.length);
      const toast: Toast = {
        id,
        message,
        type,
        visible: true,
        duration,
        remaining: duration,
        deadline: null,
        timer: null,
        removalTimer: null,
      };
      this.toasts.push(toast);
      this.startToastTimer(toast);
    },

    startToastTimer(toast: Toast) {
      if (toast.remaining === null) return;
      toast.deadline = Date.now() + toast.remaining;
      toast.timer = setTimeout(() => this.dismissToast(toast.id, false), toast.remaining);
    },

    dismissToast(id: ToastId, notify = true) {
      console.log("[toast] dismissToast for id:", id);
      const index = this.toasts.findIndex((toast) => toast.id === id);
      if (index === -1) return;

      const toast = this.toasts[index];
      if (toast.timer) clearTimeout(toast.timer);
      toast.timer = null;
      toast.visible = false;
      if (notify) {
        window.dispatchEvent(new CustomEvent("toast-dismissed", { detail: { id } }));
      }

      toast.removalTimer = setTimeout(() => {
        this.removeToast(id);
      }, 300);
    },

    removeToast(id: ToastId) {
      const toast = this.toasts.find((candidate) => candidate.id === id);
      if (toast?.timer) clearTimeout(toast.timer);
      if (toast?.removalTimer) clearTimeout(toast.removalTimer);
      this.toasts = this.toasts.filter((candidate) => candidate.id !== id);
    },

    clearToastTimer(id: ToastId) {
      const toast = this.toasts.find((toast) => toast.id === id);
      if (toast?.timer) {
        console.log("[toast] pause timer for toast id:", id);
        clearTimeout(toast.timer);
        toast.timer = null;
        toast.remaining = Math.max(0, (toast.deadline ?? Date.now()) - Date.now());
        toast.deadline = null;
      }
    },

    resumeToastTimer(id: ToastId) {
      const toast = this.toasts.find((toast) => toast.id === id);
      if (!toast || toast.timer !== null || toast.remaining === null) return;
      console.log("[toast] resume timer for toast id:", id);
      this.startToastTimer(toast);
    },
  };

  Alpine.store("toasts", store);

  Alpine.data("toastStore", () => ({
    init() {
      console.log("[toast] toastStore.init running");
      console.log("[toast] Alpine store toasts:", Alpine.store("toasts").toasts);

      window.addEventListener("show-toast", (event) => {
        const detail = (event as CustomEvent<ToastMessage | ToastMessage[]>).detail;
        console.log("[toast] show-toast event received:", detail);
        if (Array.isArray(detail)) {
          detail.forEach((message) => {
            Alpine.store("toasts").addToast(message.message, message.type, message);
          });
        } else {
          Alpine.store("toasts").addToast(detail.message, detail.type, detail);
        }
      });
      window.addEventListener("remove-toast", (event) => {
        const { id } = (event as CustomEvent<{ id: ToastId }>).detail;
        Alpine.store("toasts").removeToast(id);
      });

      try {
        const script = document.getElementById("django-messages");
        if (script) {
          const messages: ToastMessage[] = JSON.parse(
            script.textContent || (script as HTMLElement).innerText || "[]"
          );
          console.log("[toast] django-messages script found:", messages);
          if (Array.isArray(messages)) {
            messages.forEach((message) => {
              console.log("[toast] loading django-message:", message);
              Alpine.store("toasts").addToast(message.message, message.type || "info", message);
            });
          }
        }
      } catch (error) {
        // A failed toast-payload parse can't report via the toast (circular):
        // route through the client-error seam with the toast suppressed.
        reportClientError(
          "toast[django-messages]",
          String((error as Error)?.message ?? error),
          { toast: false }
        );
      }
    },

    addToast(message: string, type?: string, options?: ToastOptions) {
      console.log("[toast] toastStore.addToast delegating:", { message, type, options });
      Alpine.store("toasts").addToast(message, type, options);
    },

    dismissToast(id: ToastId) {
      console.log("[toast] toastStore.dismissToast delegating:", id);
      Alpine.store("toasts").dismissToast(id);
    },
  }));
});

function toast(message: string, type?: string, options: ToastOptions = {}): void {
  console.log("[toast] toast() called:", { message, type, options });
  const event = new CustomEvent("show-toast", {
    detail: { message, type, ...options },
    bubbles: true,
  });
  document.dispatchEvent(event);
  console.log("[toast] CustomEvent dispatched, type:", event.type);
}
window.toast = toast;
window.removeToast = (id: ToastId): void => {
  const store = typeof Alpine === "undefined" ? null : Alpine.store("toasts");
  if (store) {
    store.removeToast(id);
    return;
  }
  window.dispatchEvent(new CustomEvent("remove-toast", { detail: { id } }));
};

/** Dispatch the Django/HTMX events carried by one fetch response. */
function dispatchHtmxTriggers(response: Response): void {
  const htmxTrigger = response.headers.get("HX-Trigger");
  if (!htmxTrigger) return;

  let triggers;
  try {
    triggers = JSON.parse(htmxTrigger);
  } catch (error) {
    // Reporting through the toast would be circular. Suppress it and use the
    // best-effort client-error reporting channel.
    reportClientError(
      "fetchWithHtmxTriggers[HX-Trigger]",
      String((error as Error)?.message ?? error),
      { toast: false },
    );
    return;
  }
  // Handle both single object and array of events.
  const events = Array.isArray(triggers) ? triggers : [triggers];
  events.forEach((triggerObject: Record<string, unknown>) => {
    Object.entries(triggerObject).forEach(([name, detail]) => {
      let parsedDetail: unknown = detail;
      try {
        parsedDetail = JSON.parse(detail as string);
      } catch {
        // Keep non-JSON detail as-is.
      }
      document.dispatchEvent(new CustomEvent(name, {
        detail: parsedDetail,
        bubbles: true,
      }));
    });
  });
}
window.dispatchHtmxTriggers = dispatchHtmxTriggers;

/**
 * Wrapper around fetch() that dispatches HTMX HX-Trigger events. Callers that
 * must validate the response first can defer dispatch, then explicitly call
 * dispatchHtmxTriggers() after accepting it.
 *
 * @todo Migrate these call sites to hx-post + hx-on::after-request
 * for HTMX-native toast handling.
 */
window.fetchWithHtmxTriggers = function fetchWithHtmxTriggers(
  url: RequestInfo | URL,
  options: RequestInit = {},
  triggerDispatch: "immediate" | "deferred" = "immediate",
): Promise<Response> {
  return fetch(url, options).then((response) => {
    if (triggerDispatch === "immediate") dispatchHtmxTriggers(response);
    return response;
  });
};
