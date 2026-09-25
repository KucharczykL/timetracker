/** The toast API and the X-Events bridge; <toast-stack> renders. */
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

/** Dispatch the events one fetch response carries in its X-Events header. */
function dispatchResponseEvents(response: Response): void {
  const eventsHeader = response.headers.get("X-Events");
  if (!eventsHeader) return;

  let triggers;
  try {
    triggers = JSON.parse(eventsHeader);
  } catch (error) {
    // Circular through the toast: report without it.
    reportClientError(
      "fetchWithEvents[X-Events]",
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
window.dispatchResponseEvents = dispatchResponseEvents;

/** fetch() that dispatches X-Events events; "deferred" lets the caller validate first. */
window.fetchWithEvents = function fetchWithEvents(
  url: RequestInfo | URL,
  options: RequestInit = {},
  triggerDispatch: "immediate" | "deferred" = "immediate",
): Promise<Response> {
  return fetch(url, options).then((response) => {
    if (triggerDispatch === "immediate") dispatchResponseEvents(response);
    return response;
  });
};
