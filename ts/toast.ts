declare const Alpine: any;

interface Toast {
  id: number;
  message: string;
  type: string;
  visible: boolean;
  timer: ReturnType<typeof setTimeout> | null;
  pausedAt: number | null;
}

interface ToastStore {
  toasts: Toast[];
  addToast(message: string, type?: string): void;
  dismissToast(id: number): void;
  clearToastTimer(id: number): void;
  resumeToastTimer(id: number, duration: number): void;
}

interface ToastMessage {
  message: string;
  type?: string;
}

document.addEventListener("alpine:init", () => {
  let idCounter = 0;

  console.log("[toast] Alpine available:", typeof Alpine !== "undefined");

  const store: ToastStore = {
    toasts: [],

    addToast(message: string, type?: string) {
      console.log("[toast] addToast called:", { message, type });
      if (!type) type = "info";
      const validTypes = ["success", "error", "info", "warning", "debug"];
      if (!validTypes.includes(type)) type = "info";

      if (this.toasts.length >= 3) {
        console.log("[toast] max 3 toasts reached, removing oldest");
        this.toasts.shift();
      }

      const id = ++idCounter;
      console.log("[toast] toast added, count:", this.toasts.length);
      this.toasts.push({ id, message, type, visible: true, timer: null, pausedAt: null });

      if (type !== "error") {
        const toast = this.toasts[this.toasts.length - 1];
        const autoDismissDelay = type === "debug" ? 3000 : 5000;
        toast.timer = setTimeout(() => {
          console.log("[toast] auto-dismiss after " + autoDismissDelay / 1000 + "s");
          this.dismissToast(id);
        }, autoDismissDelay);
      }
    },

    dismissToast(id: number) {
      console.log("[toast] dismissToast for id:", id);
      const index = this.toasts.findIndex((toast) => toast.id === id);
      if (index === -1) {
        console.log("[toast] toast not found");
        return;
      }

      const toast = this.toasts[index];
      if (toast.timer) clearTimeout(toast.timer);
      toast.visible = false;

      setTimeout(() => {
        this.toasts = this.toasts.filter((toast) => toast.id !== id);
        console.log("[toast] after dismiss, count:", this.toasts.length);
      }, 300);
    },

    clearToastTimer(id: number) {
      const toast = this.toasts.find((toast) => toast.id === id);
      if (toast?.timer) {
        console.log("[toast] pause timer for toast id:", id);
        clearTimeout(toast.timer);
        toast.timer = null;
        toast.pausedAt = Date.now();
      }
    },

    resumeToastTimer(id: number, duration: number) {
      const toast = this.toasts.find((toast) => toast.id === id);
      if (toast?.pausedAt && toast.timer === null) {
        console.log("[toast] resume timer for toast id:", id);
        toast.timer = setTimeout(() => {
          this.dismissToast(id);
        }, duration);
        toast.pausedAt = null;
      }
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
            Alpine.store("toasts").addToast(message.message, message.type);
          });
        } else {
          Alpine.store("toasts").addToast(detail.message, detail.type);
        }
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
              Alpine.store("toasts").addToast(message.message, message.type || "info");
            });
          }
        }
      } catch (error) {
        console.error("[toast] localStorage restore failed:", error);
        // ignore parse errors
      }
    },

    addToast(message: string, type?: string) {
      console.log("[toast] toastStore.addToast delegating:", { message, type });
      Alpine.store("toasts").addToast(message, type);
    },

    dismissToast(id: number) {
      console.log("[toast] toastStore.dismissToast delegating:", id);
      Alpine.store("toasts").dismissToast(id);
    },
  }));
});

function toast(message: string, type?: string): void {
  console.log("[toast] toast() called:", { message, type });
  const event = new CustomEvent("show-toast", {
    detail: { message, type },
    bubbles: true,
  });
  document.dispatchEvent(event);
  console.log("[toast] CustomEvent dispatched, type:", event.type);
}
window.toast = toast;

/**
 * Wrapper around fetch() that dispatches HTMX HX-Trigger events.
 * Use this for any fetch() call that expects HX-Trigger headers
 * (e.g., to show toasts via the HTMX middleware).
 *
 * @todo Migrate these call sites to hx-post + hx-on::after-request
 * for HTMX-native toast handling.
 */
window.fetchWithHtmxTriggers = function fetchWithHtmxTriggers(
  url: RequestInfo | URL,
  options: RequestInit = {}
): Promise<Response> {
  return fetch(url, options).then(async (response) => {
    const htmxTrigger = response.headers.get("HX-Trigger");
    if (htmxTrigger) {
      let triggers;
      try {
        triggers = JSON.parse(htmxTrigger);
      } catch {
        console.warn("[fetchWithHtmxTriggers] failed to parse HX-Trigger JSON");
        return response;
      }
      // Handle both single object and array of events
      const events = Array.isArray(triggers) ? triggers : [triggers];
      events.forEach((triggerObject: Record<string, unknown>) => {
        Object.entries(triggerObject).forEach(([name, detail]) => {
          let parsedDetail: unknown = detail;
          try {
            parsedDetail = JSON.parse(detail as string);
          } catch {
            // keep as string
          }
          document.dispatchEvent(
            new CustomEvent(name, {
              detail: parsedDetail,
              bubbles: true,
            })
          );
        });
      });
    }
    return response;
  });
};
