/** The opener, found again after a load. */
import type { LinkHref, OpenerKey } from "../../handoff.js";
import { focusReturnTarget } from "../modal-layer.js";

/** Null when nothing could find it again. */
export function openerKey(opener: Element): OpenerKey | null {
  const id = opener.id || null;
  const href = opener.getAttribute("href") || null;
  return id === null && href === null ? null : { id, href };
}

function linkWithHref(href: LinkHref | null): HTMLElement | null {
  if (href === null) return null;
  for (const link of document.querySelectorAll<HTMLElement>("a[href]")) {
    if (link.getAttribute("href") === href) return link;
  }
  return null;
}

/** By id, href, toggle, else the page. */
export function focusOpener(opener: OpenerKey): void {
  const found = (opener.id && document.getElementById(opener.id)) || linkWithHref(opener.href);
  const target = focusReturnTarget(found) ?? document.getElementById("main-container");
  target?.focus({ preventScroll: true });
}
