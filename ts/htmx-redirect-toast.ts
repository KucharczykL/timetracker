/**
 * htmx "hx-redirect-toast" extension.
 *
 * A custom swap style that performs no DOM swap. On an HX-Redirect response it
 * navigates immediately (the toast shows on the destination page); otherwise it
 * turns the HX-Trigger header into CustomEvents so toasts fire in place.
 *
 * ES module (not classic): importing the client-error seam forces module scope,
 * so Page() must load it as a <script type="module"> or the top-level import
 * SyntaxErrors the file inert.
 */
import { reportClientError } from "./client-errors.js";

declare const htmx: any;

(() => {
  htmx.defineExtension("hx-redirect-toast", {
    isInlineSwap(swapStyle: string): boolean {
      return swapStyle === "hx-redirect-toast";
    },
    handleSwap(
      swapStyle: string,
      target: HTMLElement,
      fragment: Node,
      settleInfo: unknown,
      htmxConfig: { xhr: XMLHttpRequest }
    ): null {
      const xhr = htmxConfig.xhr;
      const hxRedirect = xhr.getResponseHeader("HX-Redirect");
      const hxTrigger = xhr.getResponseHeader("HX-Trigger");

      // Redirect immediately (toast will be shown on the new page)
      if (hxRedirect) {
        window.location.href = hxRedirect;
      }

      // Only dispatch HX-Trigger events for toasts when not redirecting
      if (!hxRedirect && hxTrigger) {
        let triggers;
        try {
          triggers = JSON.parse(hxTrigger);
        } catch (error) {
          // A broken toast trigger can't announce itself via a toast (circular):
          // report through the seam with the toast suppressed, then bail.
          reportClientError(
            "hx-redirect-toast[HX-Trigger]",
            String((error as Error)?.message ?? error),
            { toast: false }
          );
          return null;
        }
        const events = Array.isArray(triggers) ? triggers : [triggers];
        events.forEach((triggerObject: Record<string, unknown>) => {
          Object.entries(triggerObject).forEach(([name, rawDetail]) => {
            let detail: unknown = rawDetail;
            try {
              detail = JSON.parse(rawDetail as string);
            } catch {
              // keep as-is
            }
            target.dispatchEvent(
              new CustomEvent(name, {
                detail,
                bubbles: true,
                cancelable: true,
              })
            );
          });
        });
      }
      // Return null to prevent any DOM swap
      return null;
    },
  });
})();
