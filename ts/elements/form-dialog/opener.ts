/** The opener, found again after a load. */
import type { LinkHref, OpenerKey } from "../../handoff.js";
import { focusReturnTarget } from "../modal-layer.js";

/** Null when nothing could find it again. */
export function openerKey(opener: Element): OpenerKey | null {
  const id = opener.id || null;
  const href = opener.getAttribute("href") || null;
  return id === null && href === null ? null : { id, href };
}

/** First link with href and reachable return. */
function focusTargetWithHref(href: LinkHref | null): HTMLElement | null {
  if (href === null) return null;
  for (const link of document.querySelectorAll<HTMLElement>("a[href]")) {
    if (link.getAttribute("href") !== href) continue;
    const target = focusReturnTarget(link);
    if (target) return target;
  }
  return null;
}

/** By id, href, toggle, else the page. */
export function focusOpener(opener: OpenerKey): void {
  const byId = opener.id ? document.getElementById(opener.id) : null;
  const target =
    (byId ? focusReturnTarget(byId) : focusTargetWithHref(opener.href)) ??
    document.getElementById("main-container");
  target?.focus({ preventScroll: true });
}
