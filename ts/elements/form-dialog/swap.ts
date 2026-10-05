/** Replaces the host page with a fetched one. */
import { focusReturnTarget } from "../modal-layer.js";
import type { AnswerPage } from "./answer.js";
import { SWAPPED } from "./events.js";
import { importModules, type ModuleLoader } from "./rewrite.js";

export { SWAPPED };

/** What finds the opener again after a swap. */
export interface OpenerKey {
  id: string;
  href: string;
}

export function openerKey(opener: Element): OpenerKey {
  return { id: opener.id, href: opener.getAttribute("href") ?? "" };
}

function mainContainer(): HTMLElement {
  const main = document.getElementById("main-container");
  if (!main) throw new Error("form-dialog: the host page has no #main-container");
  return main;
}

export async function swapHostPage(page: AnswerPage, load?: ModuleLoader): Promise<void> {
  await importModules(page.modules, load);
  const main = mainContainer();
  main.replaceChildren(page.content);
  main.setAttribute("data-page-title", page.title);
  main.toggleAttribute("data-read-only", page.readOnly);
  const navbar = document.getElementById("navbar");
  if (navbar && page.navbar) navbar.replaceChildren(page.navbar);
  document.title = page.documentTitle;
  // Overwrite only: scripts stamp their own.
  for (const [name, value] of Object.entries(page.htmlData)) {
    document.documentElement.setAttribute(name, value);
  }
  document.dispatchEvent(new Event(SWAPPED));
}

function linkWithHref(href: string): HTMLElement | null {
  if (!href) return null;
  for (const scope of [mainContainer(), document]) {
    for (const link of scope.querySelectorAll<HTMLElement>("a[href]")) {
      if (link.getAttribute("href") === href) return link;
    }
  }
  return null;
}

/** The opener's twin, its toggle, else the page. */
export function refocusAfterSwap(opener: OpenerKey): void {
  const twin = (opener.id && document.getElementById(opener.id)) || linkWithHref(opener.href);
  const target = focusReturnTarget(twin) ?? mainContainer();
  target.focus({ preventScroll: true });
}
