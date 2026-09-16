/** The page's toasts: the store and its element. */
import { reportClientError } from "../client-errors.js";

export type ToastType = "success" | "error" | "info" | "warning" | "debug";
export type ToastId = number | string;

export interface ToastOptions {
  id?: ToastId;
  duration?: number | null;
}

export interface ToastMessage extends ToastOptions {
  message: string;
  type?: string;
}

interface Toast {
  id: ToastId;
  message: string;
  type: ToastType;
  visible: boolean;
  duration: number | null;
  remaining: number | null;
  deadline: number | null;
  timer: ReturnType<typeof setTimeout> | null;
  removalTimer: ReturnType<typeof setTimeout> | null;
}

const TOAST_TYPES: readonly ToastType[] = ["success", "error", "info", "warning", "debug"];
const MAX_TOASTS = 3;
const LEAVE_MS = 300;

function isToastType(value: string): value is ToastType {
  return (TOAST_TYPES as readonly string[]).includes(value);
}

export function defaultDuration(type: ToastType): number | null {
  if (type === "error") return null;
  return type === "debug" ? 3_000 : 5_000;
}

export class ToastStore {
  toasts: Toast[] = [];
  private idCounter = 0;

  constructor(private readonly onChange: () => void) {}

  addToast(message: string, type?: string, options: ToastOptions = {}): void {
    const toastType: ToastType = type && isToastType(type) ? type : "info";
    const id = options.id ?? ++this.idCounter;
    const duration =
      options.duration === undefined ? defaultDuration(toastType) : options.duration;
    const existing = this.toasts.find((toast) => toast.id === id);

    if (existing) {
      this.clearTimers(existing);
      Object.assign(existing, {
        message,
        type: toastType,
        visible: true,
        duration,
        remaining: duration,
        deadline: null,
      });
      this.startToastTimer(existing);
      this.onChange();
      return;
    }

    if (this.toasts.length >= MAX_TOASTS) {
      const oldest = this.toasts.shift();
      if (oldest) this.clearTimers(oldest);
    }

    const toast: Toast = {
      id,
      message,
      type: toastType,
      visible: true,
      duration,
      remaining: duration,
      deadline: null,
      timer: null,
      removalTimer: null,
    };
    this.toasts.push(toast);
    this.startToastTimer(toast);
    this.onChange();
  }

  dismissToast(id: ToastId, notify = true): void {
    const toast = this.toasts.find((candidate) => candidate.id === id);
    if (!toast) return;
    if (toast.timer) clearTimeout(toast.timer);
    toast.timer = null;
    toast.visible = false;
    if (notify) {
      window.dispatchEvent(new CustomEvent("toast-dismissed", { detail: { id } }));
    }
    toast.removalTimer = setTimeout(() => this.removeToast(id), LEAVE_MS);
    this.onChange();
  }

  removeToast(id: ToastId): void {
    const toast = this.toasts.find((candidate) => candidate.id === id);
    if (toast) this.clearTimers(toast);
    this.toasts = this.toasts.filter((candidate) => candidate.id !== id);
    this.onChange();
  }

  clearToastTimer(id: ToastId): void {
    const toast = this.toasts.find((candidate) => candidate.id === id);
    if (!toast?.timer) return;
    clearTimeout(toast.timer);
    toast.timer = null;
    toast.remaining = Math.max(0, (toast.deadline ?? Date.now()) - Date.now());
    toast.deadline = null;
  }

  resumeToastTimer(id: ToastId): void {
    const toast = this.toasts.find((candidate) => candidate.id === id);
    if (!toast || toast.timer !== null || toast.remaining === null) return;
    this.startToastTimer(toast);
  }

  private startToastTimer(toast: Toast): void {
    if (toast.remaining === null) return;
    toast.deadline = Date.now() + toast.remaining;
    toast.timer = setTimeout(() => this.dismissToast(toast.id, false), toast.remaining);
  }

  private clearTimers(toast: Toast): void {
    if (toast.timer) clearTimeout(toast.timer);
    if (toast.removalTimer) clearTimeout(toast.removalTimer);
    toast.timer = null;
    toast.removalTimer = null;
  }
}

// Whole literals: Tailwind scans ts/ for them.
const WRAPPER_CLASS = "pointer-events-auto max-w-sm w-72 cursor-pointer mb-3 last:mb-0";
const LEAVE_CLASS = "transition ease-in duration-200 opacity-0 translate-x-8";
const PANEL_CLASS = "rounded-base shadow-lg p-4 flex items-start gap-3";
const PANEL_TYPE_CLASS: Record<ToastType, string> = {
  success: "bg-success-soft border border-success-subtle",
  error: "bg-danger-soft border border-danger-subtle",
  info: "bg-brand-softer border border-brand-subtle",
  warning: "bg-warning-soft border border-warning-subtle",
  debug: "bg-neutral-secondary-soft border border-default-medium",
};
const ICON_CLASS = "flex-shrink-0 mt-0.5";
const ICON_TYPE_CLASS: Record<ToastType, string> = {
  success: "text-fg-success",
  error: "text-fg-danger",
  info: "text-fg-brand",
  warning: "text-fg-warning-subtle",
  debug: "text-body-subtle",
};
const TEXT_CLASS = "flex-1 text-type-body";
const TEXT_TYPE_CLASS: Record<ToastType, string> = {
  success: "text-fg-success-strong",
  error: "text-fg-danger-strong",
  info: "text-fg-brand-strong",
  warning: "text-fg-warning",
  debug: "text-heading",
};
const DISMISS_CLASS = "flex-shrink-0";
const DISMISS_TYPE_CLASS: Record<ToastType, string> = {
  success: "text-fg-success hover:text-fg-success-strong",
  error: "text-fg-danger hover:text-fg-danger-strong",
  info: "text-fg-brand hover:text-fg-brand-strong",
  warning: "text-fg-warning-subtle hover:text-fg-warning",
  debug: "text-body-subtle hover:text-heading",
};

const SVG_NS = "http://www.w3.org/2000/svg";
const ICON_PATHS: Record<ToastType, readonly string[]> = {
  success: ["M5 13l4 4L19 7"],
  error: ["M6 18L18 6M6 6l12 12"],
  info: ["M13 16h-1v-4h-1m1-4h.01M12 20a8 8 0 100-16 8 8 0 000 16z"],
  warning: ["M7 13l5 5 5-5M7 6l5 5 5-5"],
  debug: [
    "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z",
    "M15 12a3 3 0 11-6 0 3 3 0 016 0z",
  ],
};
const CLOSE_PATH = "M6 18L18 6M6 6l12 12";

function svgIcon(paths: readonly string[], sizeClass: string): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", sizeClass);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("viewBox", "0 0 24 24");
  for (const definition of paths) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("d", definition);
    svg.appendChild(path);
  }
  return svg;
}

class ToastStackElement extends HTMLElement {
  readonly store = new ToastStore(() => this.render());
  private readonly nodes = new Map<ToastId, HTMLElement>();

  connectedCallback(): void {
    window.addEventListener("show-toast", this.onShowToast);
    window.addEventListener("remove-toast", this.onRemoveToast);
    this.readDjangoMessages();
  }

  disconnectedCallback(): void {
    window.removeEventListener("show-toast", this.onShowToast);
    window.removeEventListener("remove-toast", this.onRemoveToast);
  }

  private readonly onShowToast = (event: Event): void => {
    const detail = (event as CustomEvent<ToastMessage | ToastMessage[]>).detail;
    const payloads = Array.isArray(detail) ? detail : [detail];
    for (const payload of payloads) {
      this.store.addToast(payload.message, payload.type, payload);
    }
  };

  private readonly onRemoveToast = (event: Event): void => {
    const { id } = (event as CustomEvent<{ id: ToastId }>).detail;
    this.store.removeToast(id);
  };

  private readDjangoMessages(): void {
    const script = document.getElementById("django-messages");
    if (!script) return;
    try {
      const payloads: unknown = JSON.parse(script.textContent || "[]");
      if (!Array.isArray(payloads)) return;
      for (const payload of payloads as ToastMessage[]) {
        this.store.addToast(payload.message, payload.type || "info", payload);
      }
    } catch (error) {
      // The toast cannot report itself: toast off.
      reportClientError(
        "toast-stack[django-messages]",
        String((error as Error)?.message ?? error),
        { toast: false },
      );
    }
  }

  render(): void {
    const live = new Set<ToastId>();
    for (const toast of this.store.toasts) {
      live.add(toast.id);
      let node = this.nodes.get(toast.id);
      if (!node) {
        node = this.buildToast(toast);
        this.nodes.set(toast.id, node);
        this.appendChild(node);
      }
      this.updateToast(node, toast);
    }
    for (const [id, node] of this.nodes) {
      if (live.has(id)) continue;
      node.remove();
      this.nodes.delete(id);
    }
  }

  private buildToast(toast: Toast): HTMLElement {
    const wrapper = document.createElement("div");
    wrapper.dataset.toastId = String(toast.id);
    wrapper.tabIndex = 0;
    wrapper.addEventListener("click", () => this.store.dismissToast(toast.id));
    wrapper.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.store.dismissToast(toast.id);
    });
    wrapper.addEventListener("mouseenter", () => this.store.clearToastTimer(toast.id));
    wrapper.addEventListener("mouseleave", () => this.store.resumeToastTimer(toast.id));

    const panel = document.createElement("div");
    panel.dataset.toastPanel = "";
    const icon = document.createElement("span");
    icon.dataset.toastIcon = "";
    const text = document.createElement("p");
    text.dataset.toastMessage = "";
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.dataset.toastDismiss = "";
    dismiss.setAttribute("aria-label", "Dismiss");
    dismiss.appendChild(svgIcon([CLOSE_PATH], "w-4 h-4"));
    dismiss.addEventListener("click", (event) => {
      event.stopPropagation();
      this.store.dismissToast(toast.id);
    });

    panel.append(icon, text, dismiss);
    wrapper.appendChild(panel);
    return wrapper;
  }

  private updateToast(wrapper: HTMLElement, toast: Toast): void {
    const alert = toast.type === "error" || toast.type === "warning";
    wrapper.setAttribute("role", alert ? "alert" : "status");
    wrapper.setAttribute("aria-live", toast.type === "error" ? "assertive" : "polite");
    wrapper.className = `${WRAPPER_CLASS} ${toast.type}${toast.visible ? "" : ` ${LEAVE_CLASS}`}`;

    const panel = wrapper.querySelector<HTMLElement>("[data-toast-panel]")!;
    panel.className = `${PANEL_CLASS} ${PANEL_TYPE_CLASS[toast.type]}`;

    const icon = wrapper.querySelector<HTMLElement>("[data-toast-icon]")!;
    icon.className = `${ICON_CLASS} ${ICON_TYPE_CLASS[toast.type]}`;
    if (icon.dataset.toastIconType !== toast.type) {
      icon.replaceChildren(svgIcon(ICON_PATHS[toast.type], "w-5 h-5"));
      icon.dataset.toastIconType = toast.type;
    }

    const text = wrapper.querySelector<HTMLElement>("[data-toast-message]")!;
    text.className = `${TEXT_CLASS} ${TEXT_TYPE_CLASS[toast.type]}`;
    text.textContent = toast.message;

    const dismiss = wrapper.querySelector<HTMLElement>("[data-toast-dismiss]")!;
    dismiss.className = `${DISMISS_CLASS} ${DISMISS_TYPE_CLASS[toast.type]}`;
  }
}

customElements.define("toast-stack", ToastStackElement);
