/** The toast API and the HX-Trigger bridge; <toast-stack> renders. */
import { reportClientError } from "./client-errors.js";
import type { ToastId, ToastOptions } from "./elements/toast-stack.js";

function toast(message: string, type?: string, options: ToastOptions = {}): void {
  document.dispatchEvent(
    new CustomEvent("show-toast", {
      detail: { message, type, ...options },
      bubbles: true,
    }),
  );
}
window.toast = toast;
window.removeToast = (id: ToastId): void => {
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
    // Circular through the toast: report without it.
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

/** fetch() that dispatches HX-Trigger events; "deferred" lets the caller validate first. */
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
