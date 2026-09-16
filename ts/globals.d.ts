import type { ToastId, ToastOptions } from "./elements/toast-stack.js";

export {};

declare global {
  interface Window {
    dispatchHtmxTriggers(response: Response): void;
    fetchWithHtmxTriggers(
      input: RequestInfo | URL,
      init?: RequestInit,
      triggerDispatch?: "immediate" | "deferred",
    ): Promise<Response>;
    toast(message: string, type?: string, options?: ToastOptions): void;
    removeToast(id: ToastId): void;
  }
}
