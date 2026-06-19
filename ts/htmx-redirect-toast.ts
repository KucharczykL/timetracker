/**
 * htmx "hx-redirect-toast" extension.
 *
 * A custom swap style that performs no DOM swap. On an HX-Redirect response it
 * navigates immediately (the toast shows on the destination page); otherwise it
 * turns the HX-Trigger header into CustomEvents so toasts fire in place.
 *
 * Classic (non-module) script: it only touches the global htmx and registers an
 * extension, so it stays a plain <script> like the other vendored-adjacent glue.
 */
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
        const triggers = JSON.parse(hxTrigger);
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
