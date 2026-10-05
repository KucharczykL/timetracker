/** Opens marked links' form pages in a modal. */
import { reportClientError } from "../client-errors.js";
import {
  FORM_DIALOG_ATTRIBUTE,
  FORM_DIALOG_CHROME,
  FORM_DIALOG_PARTS,
  type FormDialogChrome,
} from "../generated/form-dialog.js";
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import { handOffMessages } from "../toast-handoff.js";
import { type Answer, type AnswerPage, readAnswer, sameUrl } from "./form-dialog/answer.js";
import { browser } from "./form-dialog/navigation.js";
import { importModules, type ModuleLoader, prefixIds, resolveUrls } from "./form-dialog/rewrite.js";
import {
  assertNever,
  type Messages,
  routeOpen,
  routeSubmit,
  type SubmitContext,
} from "./form-dialog/routes.js";
import { type OpenerKey, openerKey, refocusAfterSwap, swapHostPage } from "./form-dialog/swap.js";
import { attachModal, isModalOpen, type Modal, MODAL_CHANGE, openModals, topModal } from "./modal-layer.js";

interface OpenDialog {
  readonly dialog: HTMLDialogElement;
  readonly body: HTMLElement;
  readonly chrome: FormDialogChrome;
  readonly opener: OpenerKey | null;
  readonly modal: Modal;
  /** Aborts the in-flight submit on close. */
  readonly controller: AbortController;
  submitting: boolean;
  /** A saved answer to swap in on close. */
  pendingSwap: AnswerPage | null;
}

/** Past this, the link is followed. */
const OPEN_TIMEOUT_MS = 15_000;

const TABBABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const TOAST_ACTION_FORM = "form[data-toast-action]";

function csrfCookie(): string {
  return document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ?? "";
}

function showToasts(messages: Messages): void {
  if (messages.length === 0) return;
  window.dispatchEvent(new CustomEvent("show-toast", { detail: [...messages] }));
}

function report(detail: string): string {
  return reportClientError("form-dialog", detail, { toast: false });
}

function errorToast(message: string): void {
  showToasts([{ message, type: "error" }]);
}

function isPlainPrimaryClick(event: MouseEvent): boolean {
  return (
    !event.defaultPrevented &&
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}

/** Null for a marker no chrome states. */
function chromeOf(marker: string | null): FormDialogChrome | null {
  const chromes = Object.keys(FORM_DIALOG_CHROME) as FormDialogChrome[];
  return chromes.find((chrome) => FORM_DIALOG_CHROME[chrome] === marker) ?? null;
}

function initialFocus(dialog: HTMLDialogElement, body: HTMLElement): HTMLElement | null {
  const invalid = body.querySelector<HTMLElement>('[aria-invalid="true"]');
  if (invalid) return invalid;
  const form = body.querySelector("form");
  const first = form
    ? Array.from(form.querySelectorAll<HTMLElement>(TABBABLE)).find(
        (element) => !element.closest("[hidden], [inert]"),
      )
    : undefined;
  return first ?? dialog.querySelector<HTMLElement>(`[${MODAL_ATTRIBUTES.dismiss}]`);
}

export class FormDialogElement extends HTMLElement {
  /** Swapped in by tests. */
  loadModule?: ModuleLoader;
  private readonly stack: OpenDialog[] = [];
  /** Something wrote; the host is stale. */
  private stale = false;
  private opening = false;
  private readonly undoing = new Set<HTMLFormElement>();
  /** Closed last while another modal covered the page. */
  private pendingRefresh: OpenDialog | null = null;
  private presentations = 0;
  private csrfAtLoad = "";

  connectedCallback(): void {
    this.csrfAtLoad = csrfCookie();
    document.addEventListener("click", this.onClick);
    document.addEventListener("submit", this.onSubmit);
  }

  disconnectedCallback(): void {
    document.removeEventListener("click", this.onClick);
    document.removeEventListener("submit", this.onSubmit);
    window.removeEventListener(MODAL_CHANGE, this.onModalChange);
  }

  private readonly onClick = (event: MouseEvent): void => {
    if (!isPlainPrimaryClick(event)) return;
    const link = (event.target as Element | null)?.closest?.<HTMLAnchorElement>("a[href]");
    if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
    if (link.hasAttribute(FORM_DIALOG_ATTRIBUTE)) {
      event.preventDefault();
      if (!this.opening) void this.openFrom(link);
      return;
    }
    const entry = this.entryHolding(link);
    if (entry && sameUrl(link.href, location.href)) {
      // A link back to the host closes.
      event.preventDefault();
      if (!entry.submitting) entry.modal.close();
    }
  };

  private readonly onSubmit = (event: SubmitEvent): void => {
    if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
    const form = event.target;
    const submitter = event.submitter instanceof HTMLElement ? event.submitter : null;
    const method = (
      submitter?.getAttribute("formmethod") ??
      form.getAttribute("method") ??
      "get"
    ).toLowerCase();
    if (method !== "post") return;
    const entry = this.entryHolding(form);
    if (entry) {
      event.preventDefault();
      void this.submit(entry, form, submitter);
    } else if (this.stack.length > 0 && form.matches(TOAST_ACTION_FORM)) {
      event.preventDefault();
      void this.submitUndo(form);
    }
  };

  private entryHolding(node: Node): OpenDialog | undefined {
    return this.stack.find((entry) => entry.body.contains(node));
  }

  private submitContext(entry: OpenDialog): SubmitContext {
    const open = openModals();
    return {
      hostUrl: location.href,
      alone: open.length === 1 && open[0] === entry.dialog,
    };
  }

  private async fetchAnswer(url: URL, init: RequestInit = {}): Promise<Answer> {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...init,
      headers: { Accept: "text/html" },
    });
    return readAnswer(response, url);
  }

  private postForm(
    form: HTMLFormElement,
    submitter: HTMLElement | null,
    signal?: AbortSignal,
  ): Promise<Answer> {
    const target =
      submitter?.getAttribute("formaction") ?? form.getAttribute("action") ?? location.href;
    return this.fetchAnswer(new URL(target, location.href), {
      method: "POST",
      body: new FormData(form, submitter),
      signal,
    });
  }

  private async openFrom(link: HTMLAnchorElement): Promise<void> {
    this.opening = true;
    link.setAttribute("aria-busy", "true");
    const topAtClick = topModal();
    const url = new URL(link.href);
    const timeout = new AbortController();
    const timer = window.setTimeout(() => timeout.abort(), OPEN_TIMEOUT_MS);
    try {
      const chrome = chromeOf(link.getAttribute(FORM_DIALOG_ATTRIBUTE));
      if (!chrome) {
        report(`unknown chrome "${link.getAttribute(FORM_DIALOG_ATTRIBUTE)}"`);
        browser.assign(url.href);
        return;
      }
      const answer = await this.fetchAnswer(url, { signal: timeout.signal });
      const route = routeOpen(answer, location.href);
      if (topModal() !== topAtClick) {
        // Another modal took over; keep its news.
        if (route.kind !== "follow") showToasts(route.kind === "present" ? route.page.messages : route.messages);
        return;
      }
      switch (route.kind) {
        case "toast":
          showToasts(route.messages);
          return;
        case "navigate":
          handOffMessages(route.messages);
          browser.assign(route.url.href);
          return;
        case "follow":
          browser.assign(url.href);
          return;
        case "present":
          if (!(await this.openDialog(route.page, answer.url, link, chrome))) {
            browser.assign(url.href);
          }
          return;
        default:
          assertNever(route);
      }
    } catch (error) {
      report(`open failed: ${String(error)}`);
      browser.assign(url.href);
    } finally {
      window.clearTimeout(timer);
      this.opening = false;
      link.removeAttribute("aria-busy");
    }
  }

  /** False when the dialog could not open. */
  private async openDialog(
    page: AnswerPage,
    url: URL,
    opener: HTMLElement | null,
    chrome: FormDialogChrome,
  ): Promise<boolean> {
    const template = this.querySelector<HTMLTemplateElement>(
      `template[${FORM_DIALOG_PARTS.template}]`,
    );
    if (!template) {
      report("the host has no template");
      return false;
    }
    if (!(await this.prepare(page, url))) return false;
    const chromeFragment = template.content.cloneNode(true) as DocumentFragment;
    prefixIds(chromeFragment, this.nextPrefix());
    const dialog = chromeFragment.querySelector("dialog");
    const body = dialog?.querySelector<HTMLElement>(`[${FORM_DIALOG_PARTS.body}]`);
    if (!dialog || !body) {
      report("the template has no dialog or body");
      return false;
    }
    if (chrome === "bare") {
      dialog.querySelector(`[${FORM_DIALOG_PARTS.header}]`)?.remove();
      dialog.removeAttribute("aria-labelledby");
    }
    const modal = attachModal(dialog, {
      initialFocus: () => initialFocus(dialog, body),
      dismiss: () => {
        if (!entry.submitting) modal.close();
      },
      onClosed: () => this.closed(entry),
    });
    const entry: OpenDialog = {
      dialog,
      body,
      chrome,
      opener: opener ? openerKey(opener) : null,
      modal,
      controller: new AbortController(),
      submitting: false,
      pendingSwap: null,
    };
    // Registered first: content may submit on connect.
    this.stack.push(entry);
    try {
      this.fill(entry, page);
      this.append(dialog);
      if (!modal.open(opener ?? undefined)) throw new Error("the layer refused to open");
    } catch (error) {
      this.stack.splice(this.stack.indexOf(entry), 1);
      dialog.remove();
      report(`the dialog could not open: ${String(error)}`);
      return false;
    }
    showToasts(page.messages);
    return true;
  }

  private nextPrefix(): string {
    this.presentations += 1;
    return `form-dialog-${this.presentations}-`;
  }

  /** False, reported, when a module fails. */
  private async prepare(page: AnswerPage, url: URL): Promise<boolean> {
    try {
      await importModules(page.modules, this.loadModule);
    } catch (error) {
      report(`a module failed: ${String(error)}`);
      return false;
    }
    prefixIds(page.content, this.nextPrefix());
    resolveUrls(page.content, url);
    return true;
  }

  private fill(entry: OpenDialog, page: AnswerPage): void {
    if (entry.chrome === "header") {
      // The header states the title.
      page.content.querySelector("h1")?.remove();
      const title = entry.dialog.querySelector(`[${FORM_DIALOG_PARTS.title}]`);
      if (title) title.textContent = page.title;
    } else {
      entry.dialog.setAttribute("aria-label", page.title);
    }
    entry.body.replaceChildren(page.content);
  }

  private async present(entry: OpenDialog, page: AnswerPage, url: URL): Promise<void> {
    if (!(await this.prepare(page, url))) {
      // The person's input stays on screen.
      showToasts(page.messages);
      const id = report("the answered form could not be shown");
      errorToast(`The answer could not be shown. Reload the page to see it (error ${id}).`);
      return;
    }
    if (this.stack.includes(entry)) {
      this.fill(entry, page);
      entry.modal.focusInitial();
    }
    showToasts(page.messages);
  }

  private async submit(
    entry: OpenDialog,
    form: HTMLFormElement,
    submitter: HTMLElement | null,
  ): Promise<void> {
    if (entry.submitting) return;
    entry.submitting = true;
    form.setAttribute("aria-busy", "true");
    entry.body.setAttribute("aria-busy", "true");
    try {
      let answer: Answer;
      try {
        answer = await this.postForm(form, submitter, entry.controller.signal);
      } catch (error) {
        // The close already counted it as a write.
        if (entry.controller.signal.aborted) return;
        this.unconfirmed(`submit failed: ${String(error)}`);
        return;
      }
      if (answer.redirected) this.stale = true;
      await this.routeSubmitAnswer(entry, answer);
    } finally {
      entry.submitting = false;
      form.removeAttribute("aria-busy");
      entry.body.removeAttribute("aria-busy");
    }
  }

  private async routeSubmitAnswer(entry: OpenDialog, answer: Answer): Promise<void> {
    const route = routeSubmit(answer, this.submitContext(entry));
    switch (route.kind) {
      case "present":
        await this.present(entry, route.page, answer.url);
        return;
      case "error":
        this.refused(route.status);
        return;
      case "swap":
        entry.pendingSwap = route.page;
        entry.modal.close();
        return;
      case "navigate":
        handOffMessages(route.messages);
        browser.assign(route.url.href);
        return;
      case "closeTop":
        entry.modal.close();
        showToasts(route.messages);
        return;
      default:
        assertNever(route);
    }
  }

  /** A write may have landed unseen. */
  private unconfirmed(detail: string): void {
    this.stale = true;
    const id = report(detail);
    errorToast(`The save could not be confirmed. Close this to see the current page (error ${id}).`);
  }

  private refused(status: number): void {
    const id = report(`the answer had no page (status ${status})`);
    const remedy = status === 403 ? " Reload the page and try again." : "";
    errorToast(`The save failed: the server answered ${status}.${remedy} (error ${id})`);
  }

  private async submitUndo(form: HTMLFormElement): Promise<void> {
    if (this.undoing.has(form)) return;
    this.undoing.add(form);
    form.setAttribute("aria-busy", "true");
    try {
      let answer: Answer;
      try {
        answer = await this.postForm(form, null);
      } catch (error) {
        this.unconfirmed(`undo failed: ${String(error)}`);
        return;
      }
      if (answer.redirected) {
        this.stale = true;
        showToasts(answer.page?.messages ?? []);
      } else if (answer.page) {
        // A batch waypoint continues in a dialog.
        this.stale = true;
        if (!(await this.openDialog(answer.page, answer.url, null, "header"))) {
          handOffMessages(answer.page.messages);
          browser.assign(answer.url.href);
        }
      } else {
        this.refused(answer.status);
      }
    } finally {
      this.undoing.delete(form);
      form.removeAttribute("aria-busy");
    }
  }

  private closed(entry: OpenDialog): void {
    if (entry.submitting) this.stale = true;
    entry.controller.abort();
    entry.dialog.remove();
    const index = this.stack.indexOf(entry);
    if (index !== -1) this.stack.splice(index, 1);
    if (this.stack.length === 0 && (entry.pendingSwap || this.stale)) this.refreshWhenAlone(entry);
  }

  /** Waits until no modal covers the page. */
  private refreshWhenAlone(entry: OpenDialog): void {
    if (!isModalOpen()) {
      void this.refresh(entry);
      return;
    }
    this.pendingRefresh = entry;
    window.addEventListener(MODAL_CHANGE, this.onModalChange);
  }

  private readonly onModalChange = (): void => {
    if (isModalOpen() || this.stack.length > 0) return;
    window.removeEventListener(MODAL_CHANGE, this.onModalChange);
    const entry = this.pendingRefresh;
    this.pendingRefresh = null;
    if (entry) void this.refresh(entry);
  };

  /** Brings the host page up to date. */
  private async refresh(entry: OpenDialog): Promise<void> {
    if (csrfCookie() !== this.csrfAtLoad) {
      // Every host form holds the old token.
      handOffMessages(entry.pendingSwap?.messages ?? []);
      browser.reload();
      return;
    }
    let page = entry.pendingSwap;
    if (!page) {
      try {
        const answer = await this.fetchAnswer(new URL(location.href));
        if (answer.page && !sameUrl(answer.url, location.href)) {
          handOffMessages(answer.page.messages);
          browser.assign(answer.url.href);
          return;
        }
        page = answer.page;
      } catch (error) {
        report(`refresh failed: ${String(error)}`);
      }
    }
    if (!page) {
      report("the refresh had no page");
      browser.reload();
      return;
    }
    try {
      await swapHostPage(page, this.loadModule);
    } catch (error) {
      report(`swap failed: ${String(error)}`);
      handOffMessages(page.messages);
      browser.reload();
      return;
    }
    this.stale = false;
    refocusAfterSwap(entry.opener);
    showToasts(page.messages);
  }
}

customElements.define("form-dialog", FormDialogElement);
