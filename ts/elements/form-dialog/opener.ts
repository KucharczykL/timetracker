/** The opener, found again after a load. */
import { reportClientError } from "../../client-errors.js";
import type { LinkHref, OpenerKey } from "../../handoff.js";
import { focusReturnTarget } from "../modal-layer.js";

const REPORT_CONTEXT = "form-dialog opener";

/** Null when nothing could find it again. */
export function openerKey(opener: Element): OpenerKey | null {
  const id = opener.id || null;
  const href = opener.getAttribute("href") || null;
  return id === null && href === null ? null : { id, href };
}

function linksWithHref(href: LinkHref | null): HTMLElement[] {
  if (href === null) return [];
  return Array.from(document.querySelectorAll<HTMLElement>("a[href]")).filter(
    (link) => link.getAttribute("href") === href,
  );
}

/** First link with href whose target is reachable. */
function focusTargetWithHref(href: LinkHref | null): HTMLElement | null {
  for (const link of linksWithHref(href)) {
    const target = focusReturnTarget(link);
    if (target) return target;
  }
  return null;
}

/** By id, else href link, else page. */
export function focusOpener(opener: OpenerKey): void {
  const byId = opener.id ? document.getElementById(opener.id) : null;
  const reachable =
    (byId ? focusReturnTarget(byId) : null) ?? focusTargetWithHref(opener.href);
  const target = reachable ?? document.getElementById("main-container");
  // A removed row names nothing in the page: the page is the right answer.
  const stillInPage = byId !== null || linksWithHref(opener.href).length > 0;
  if (reachable === null && stillInPage) {
    const described = `id=${opener.id ?? "-"} href=${opener.href ?? "-"}`;
    reportClientError(REPORT_CONTEXT, `no reachable opener, ${described}`, { toast: false });
  }
  target?.focus({ preventScroll: true });
  if (target && document.activeElement !== target) {
    reportClientError(REPORT_CONTEXT, `focus did not land on ${target.id || target.localName}`, {
      toast: false,
    });
  }
}
