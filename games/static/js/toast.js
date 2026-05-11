document.addEventListener("alpine:init", () => {
  let idCounter = 0;

  console.log("[toast] Alpine available:", typeof Alpine !== "undefined");

  Alpine.store("toasts", {
    toasts: [],

    addToast(message, type) {
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
          console.log("[toast] auto-dismiss after " + (autoDismissDelay / 1000) + "s");
          this.dismissToast(id);
        }, autoDismissDelay);
      }
    },

    dismissToast(id) {
      console.log("[toast] dismissToast for id:", id);
      const idx = this.toasts.findIndex((t) => t.id === id);
      if (idx === -1) { console.log("[toast] toast not found"); return; }

      const toast = this.toasts[idx];
      if (toast.timer) clearTimeout(toast.timer);
      toast.visible = false;

      setTimeout(() => {
        this.toasts = this.toasts.filter((t) => t.id !== id);
        console.log("[toast] after dismiss, count:", this.toasts.length);
      }, 300);
    },

    clearToastTimer(id) {
      const toast = this.toasts.find((t) => t.id === id);
      if (toast?.timer) {
        console.log("[toast] pause timer for toast id:", id);
        clearTimeout(toast.timer);
        toast.timer = null;
        toast.pausedAt = Date.now();
      }
    },

    resumeToastTimer(id, duration) {
      const toast = this.toasts.find((t) => t.id === id);
      if (toast?.pausedAt && toast.timer === null) {
        console.log("[toast] resume timer for toast id:", id);
        toast.timer = setTimeout(() => {
          this.dismissToast(id);
        }, duration);
        toast.pausedAt = null;
      }
    },
  });

  Alpine.data("toastStore", () => ({
    init() {
      console.log("[toast] toastStore.init running");
      console.log("[toast] Alpine store toasts:", Alpine.store("toasts").toasts);

      window.addEventListener("show-toast", (e) => {
        console.log("[toast] show-toast event received:", e.detail);
        if (Array.isArray(e.detail)) {
          e.detail.forEach((msg) => {
            Alpine.store("toasts").addToast(msg.message, msg.type);
          });
        } else {
          Alpine.store("toasts").addToast(e.detail.message, e.detail.type);
        }
      });

      try {
        const script = document.getElementById("django-messages");
        if (script) {
          const msgs = JSON.parse(
            script.textContent || script.innerText || "[]"
          );
          console.log("[toast] django-messages script found:", msgs);
          if (Array.isArray(msgs)) {
            msgs.forEach((msg) => {
              console.log("[toast] loading django-message:", msg);
              Alpine.store("toasts").addToast(msg.message, msg.type || "info");
            });
          }
        }
      } catch (e) {
        console.error("[toast] localStorage restore failed:", e);
        // ignore parse errors
      }
    },

    addToast(message, type) {
      console.log("[toast] toastStore.addToast delegating:", { message, type });
      Alpine.store("toasts").addToast(message, type);
    },

    dismissToast(id) {
      console.log("[toast] toastStore.dismissToast delegating:", id);
      Alpine.store("toasts").dismissToast(id);
    },
  }));
});

function toast(message, type) {
  console.log("[toast] toast() called:", { message, type });
  const evt = new CustomEvent("show-toast", {
    detail: { message, type },
    bubbles: true,
  });
  document.dispatchEvent(evt);
  console.log("[toast] CustomEvent dispatched, type:", evt.type);
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
window.fetchWithHtmxTriggers = function fetchWithHtmxTriggers(url, options = {}) {
  console.log("[fetchWithHtmxTriggers] fetching:", url);
  return fetch(url, options).then(async (response) => {
    console.log("[fetchWithHtmxTriggers] response status:", response.status);
    const htmxTrigger = response.headers.get("HX-Trigger");
    console.log("[fetchWithHtmxTriggers] HX-Trigger header:", htmxTrigger);
    if (htmxTrigger) {
      let triggers;
      try {
        triggers = JSON.parse(htmxTrigger);
        console.log("[fetchWithHtmxTriggers] parsed triggers:", triggers);
      } catch {
        console.warn("[fetchWithHtmxTriggers] failed to parse HX-Trigger JSON");
        return response;
      }
      // Handle both single object and array of events
      const events = Array.isArray(triggers) ? triggers : [triggers];
      events.forEach((triggerObj) => {
        Object.entries(triggerObj).forEach(([name, detail]) => {
          console.log("[fetchWithHtmxTriggers] dispatching event:", name, detail);
          let parsedDetail = detail;
          try {
            parsedDetail = JSON.parse(detail);
          } catch {
            // keep as string
          }
          document.dispatchEvent(new CustomEvent(name, {
            detail: parsedDetail,
            bubbles: true,
          }));
        });
      });
    }
    return response;
  });
};
