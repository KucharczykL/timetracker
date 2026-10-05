/** Opens marked links' form pages in a modal. */
import { reportClientError } from "../client-errors.js";
import {
  FORM_DIALOG_ATTRIBUTE,
  FORM_DIALOG_CHROME_BY_MARKER,
  FORM_DIALOG_PARTS,
  type FormDialogChrome,
} from "../generated/form-dialog.js";
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import { handOffMessages } from "../toast-handoff.js";
import {
  type Answer,
  type AnswerPage,
  type Messages,
  normalizedUrl,
  readAnswer,
  sameUrl,
} from "./form-dialog/answer.js";
import { browser } from "./form-dialog/navigation.js";
import {
  type IdPrefix,
  importModules,
  type ModuleLoader,
  prefixIds,
  resolveUrls,
} from "./form-dialog/rewrite.js";
import {
  assertNever,
  routeMessages,
  routeOpen,
  routeSubmit,
  type SubmitContext,
} from "./form-dialog/routes.js";
import { type OpenerKey, openerKey, refocusAfterSwap, swapHostPage } from "./form-dialog/swap.js";
import {
  attachModal,
  isModalOpen,
  type Modal,
  MODAL_CHANGE,
  openModals,
  topModal,
} from "./modal-layer.js";
import type { ToastMessage } from "./toast-stack.js";

interface OpenDialog {
  readonly dialog: HTMLDialogElement;
  readonly body: HTMLElement;
  readonly chrome: FormDialogChrome;
  readonly opener: OpenerKey | null;
  readonly modal: Modal;
  /** Aborts the in-flight submit on close. */
  readonly controller: AbortController;
  /** The presented page's URL. */
  url: URL;
  submitting: boolean;
  /** A saved answer to swap in on close. */
  pendingSwap: AnswerPage | null;
}

/** What the host refresh needs. */
interface Refresh {
  readonly swap: AnswerPage | null;
  readonly opener: OpenerKey | null;
}

/** What a POST sends. */
interface FormRequest {
  readonly url: URL;
  readonly body: FormData;
}

/** Past this, a load gives up. */
const LOAD_TIMEOUT_MS = 15_000;

const TABBABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/** Lives on the dialog, outside its body. */
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
  const toast: ToastMessage = { message, type: "error" };
  showToasts([toast]);
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
  if (marker === null || !Object.hasOwn(FORM_DIALOG_CHROME_BY_MARKER, marker)) return null;
  return FORM_DIALOG_CHROME_BY_MARKER[marker];
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

/** Throws on a malformed target or submitter. */
function formRequest(form: HTMLFormElement, submitter: HTMLElement | null): FormRequest {
  const target =
    submitter?.getAttribute("formaction") ?? form.getAttribute("action") ?? location.href;
  return { url: new URL(target, location.href), body: new FormData(form, submitter) };
}

/** Rejects once `signal` aborts. */
function raceAbort<Result>(work: Promise<Result>, signal: AbortSignal | undefined): Promise<Result> {
  if (!signal) return work;
  return new Promise((resolve, reject) => {
    const abort = (): void => reject(new DOMException("timed out", "AbortError"));
    if (signal.aborted) abort();
    signal.addEventListener("abort", abort, { once: true });
    work.then(resolve, reject);
  });
}

/** Aborts after `milliseconds`; fake timers reach it. */
function deadlineAfter(milliseconds: number): AbortSignal {
  const controller = new AbortController();
  window.setTimeout(() => controller.abort(), milliseconds);
  return controller.signal;
}

export class FormDialogElement extends HTMLElement {
  /** Swapped in by tests. */
  loadModule?: ModuleLoader;
  private readonly stack: OpenDialog[] = [];
  /** Something wrote; the host is stale. */
  private stale = false;
  /** The link whose page is loading. */
  private opening: HTMLAnchorElement | null = null;
  private readonly undoing = new Set<HTMLFormElement>();
  /** Waiting for the covering modal to close. */
  private pendingRefresh: Refresh | null = null;
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
      // Another link stays a link meanwhile.
      if (this.opening && this.opening !== link) return;
      event.preventDefault();
      if (!this.opening) void this.openFrom(link);
      return;
    }
    const entry = this.entryHolding(link);
    if (!entry || link.getAttribute("href")?.startsWith("#")) return;
    if (this.leadsBack(entry, link.href)) {
      event.preventDefault();
      if (!entry.submitting) entry.modal.close();
    }
  };

  /** To the host, or to a dialog below. */
  private leadsBack(entry: OpenDialog, href: string): boolean {
    if (sameUrl(href, location.href)) return true;
    const below = this.stack.slice(0, this.stack.indexOf(entry));
    return below.some((lower) => sameUrl(href, lower.url));
  }

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
      hostUrl: normalizedUrl(location.href),
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

  private postRequest(request: FormRequest, signal?: AbortSignal): Promise<Answer> {
    return this.fetchAnswer(request.url, { method: "POST", body: request.body, signal });
  }

  private async openFrom(link: HTMLAnchorElement): Promise<void> {
    this.opening = link;
    link.setAttribute("aria-busy", "true");
    const topAtClick = topModal();
    const url = new URL(link.href);
    const deadline = deadlineAfter(LOAD_TIMEOUT_MS);
    try {
      const marker = link.getAttribute(FORM_DIALOG_ATTRIBUTE);
      const chrome = chromeOf(marker);
      if (!chrome) {
        report(`unknown chrome "${marker}"`);
        browser.assign(url.href);
        return;
      }
      const answer = await this.fetchAnswer(url, { signal: deadline });
      const route = routeOpen(answer, normalizedUrl(location.href));
      if (topModal() !== topAtClick) {
        // Another modal took over; show the answer's messages.
        if (route.kind === "follow") report(`a modal overtook the link to ${url.href}`);
        showToasts(routeMessages(route));
        return;
      }
      switch (route.kind) {
        case "toast":
          showToasts(route.messages);
          return;
        case "navigate":
          handOffMessages(route.messages, route.url);
          browser.assign(route.url.href);
          return;
        case "follow":
          browser.assign(url.href);
          return;
        case "present":
          if (!(await this.openDialog(route.page, answer.url, link, chrome, deadline))) {
            handOffMessages(route.page.messages, url);
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
      this.opening = null;
      link.removeAttribute("aria-busy");
    }
  }

  /** False when the dialog could not open. */
  private async openDialog(
    page: AnswerPage,
    url: URL,
    opener: HTMLElement | null,
    chrome: FormDialogChrome,
    deadline?: AbortSignal,
  ): Promise<boolean> {
    const template = this.querySelector<HTMLTemplateElement>(
      `template[${FORM_DIALOG_PARTS.template}]`,
    );
    if (!template) {
      report("the host has no template");
      return false;
    }
    if (!(await this.prepare(page, url, deadline))) return false;
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
      url,
      submitting: false,
      pendingSwap: null,
    };
    // Registered first: content may submit on connect.
    this.stack.push(entry);
    try {
      this.fill(entry, page, url);
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

  private nextPrefix(): IdPrefix {
    this.presentations += 1;
    return `form-dialog-${this.presentations}-`;
  }

  /** False, reported, when the page cannot be fitted. */
  private async prepare(page: AnswerPage, url: URL, deadline?: AbortSignal): Promise<boolean> {
    try {
      await raceAbort(importModules(page.modules, this.loadModule), deadline);
      prefixIds(page.content, this.nextPrefix());
      resolveUrls(page.content, url);
      return true;
    } catch (error) {
      report(`the page could not be fitted: ${String(error)}`);
      return false;
    }
  }

  private fill(entry: OpenDialog, page: AnswerPage, url: URL): void {
    if (entry.chrome === "header") {
      // The header states the title.
      page.content.querySelector("h1")?.remove();
      const title = entry.dialog.querySelector(`[${FORM_DIALOG_PARTS.title}]`);
      if (title) title.textContent = page.title;
    } else {
      entry.dialog.setAttribute("aria-label", page.title);
    }
    entry.body.replaceChildren(page.content);
    entry.url = url;
  }

  private async present(entry: OpenDialog, page: AnswerPage, url: URL): Promise<void> {
    if (!(await this.prepare(page, url))) {
      // The person's input stays on screen.
      showToasts(page.messages);
      this.unshown("the answered form could not be shown");
      return;
    }
    if (this.stack.includes(entry)) {
      this.fill(entry, page, url);
      entry.modal.focusInitial();
    }
    showToasts(page.messages);
  }

  /** Null, toasted, when nothing could be sent. */
  private buildRequest(form: HTMLFormElement, submitter: HTMLElement | null): FormRequest | null {
    try {
      return formRequest(form, submitter);
    } catch (error) {
      const id = report(`the request could not be built: ${String(error)}`);
      errorToast(`Nothing was sent: the form could not be read (error ${id}).`);
      return null;
    }
  }

  private async submit(
    entry: OpenDialog,
    form: HTMLFormElement,
    submitter: HTMLElement | null,
  ): Promise<void> {
    if (entry.submitting) return;
    const request = this.buildRequest(form, submitter);
    if (!request) return;
    entry.submitting = true;
    form.setAttribute("aria-busy", "true");
    entry.body.setAttribute("aria-busy", "true");
    try {
      let answer: Answer;
      try {
        answer = await this.postRequest(request, entry.controller.signal);
      } catch (error) {
        // The close already counted it as a write.
        if (entry.controller.signal.aborted) return;
        this.unconfirmed(`submit failed: ${String(error)}`);
        return;
      }
      if (answer.redirected) this.stale = true;
      try {
        await this.routeSubmitAnswer(entry, answer);
      } catch (error) {
        this.answerBroke(answer, `routing the answer failed: ${String(error)}`);
      }
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
        handOffMessages(route.messages, route.url);
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

  /** The server answered; showing it failed. */
  private answerBroke(answer: Answer, detail: string): void {
    if (answer.redirected) {
      this.unconfirmed(detail);
    } else {
      this.unshown(detail);
    }
  }

  /** An answer arrived that cannot be shown. */
  private unshown(detail: string): void {
    const id = report(detail);
    errorToast(`The answer could not be shown. Reload the page to see it (error ${id}).`);
  }

  private refused(status: number): void {
    const id = report(`the answer had no page (status ${status})`);
    if (status < 400) {
      errorToast(
        `The server answered ${status} with nothing to show. Reload the page to check (error ${id}).`,
      );
      return;
    }
    const remedy = status === 403 ? " Your session may have expired; reload the page." : "";
    errorToast(`The save failed: the server answered ${status}.${remedy} (error ${id})`);
  }

  private async submitUndo(form: HTMLFormElement): Promise<void> {
    if (this.undoing.has(form)) return;
    const request = this.buildRequest(form, null);
    if (!request) return;
    this.undoing.add(form);
    form.setAttribute("aria-busy", "true");
    try {
      let answer: Answer;
      try {
        answer = await this.postRequest(request);
      } catch (error) {
        this.unconfirmed(`undo failed: ${String(error)}`);
        this.refreshIfClosed();
        return;
      }
      try {
        await this.routeUndoAnswer(form, answer);
      } catch (error) {
        this.answerBroke(answer, `routing the undo answer failed: ${String(error)}`);
      }
    } finally {
      this.undoing.delete(form);
      form.removeAttribute("aria-busy");
    }
  }

  private async routeUndoAnswer(form: HTMLFormElement, answer: Answer): Promise<void> {
    if (!answer.redirected && !answer.page) {
      this.refused(answer.status);
      return;
    }
    // Answered: its press is spent.
    form.remove();
    this.stale = true;
    if (answer.redirected) {
      showToasts(answer.page?.messages ?? []);
      this.refreshIfClosed();
    } else if (answer.page) {
      // A batch waypoint continues in a dialog.
      if (!(await this.openDialog(answer.page, answer.url, null, "header"))) {
        handOffMessages(answer.page.messages, answer.url);
        browser.assign(answer.url.href);
      }
    }
  }

  /** A write landed after its dialog closed. */
  private refreshIfClosed(): void {
    if (this.stack.length === 0) this.refreshWhenAlone({ swap: null, opener: null });
  }

  private closed(entry: OpenDialog): void {
    if (entry.submitting) this.stale = true;
    entry.controller.abort();
    entry.dialog.remove();
    const index = this.stack.indexOf(entry);
    if (index !== -1) this.stack.splice(index, 1);
    if (this.stack.length === 0 && (entry.pendingSwap || this.stale)) {
      this.refreshWhenAlone({ swap: entry.pendingSwap, opener: entry.opener });
    }
  }

  /** Waits until no modal covers the page. */
  private refreshWhenAlone(refresh: Refresh): void {
    if (isModalOpen()) {
      this.pendingRefresh = refresh;
      window.addEventListener(MODAL_CHANGE, this.onModalChange);
      return;
    }
    this.pendingRefresh = null;
    window.removeEventListener(MODAL_CHANGE, this.onModalChange);
    void this.refresh(refresh);
  }

  private readonly onModalChange = (): void => {
    if (isModalOpen() || this.stack.length > 0) return;
    window.removeEventListener(MODAL_CHANGE, this.onModalChange);
    const refresh = this.pendingRefresh;
    this.pendingRefresh = null;
    if (refresh) void this.refresh(refresh);
  };

  /** Brings the host page up to date. */
  private async refresh(refresh: Refresh): Promise<void> {
    const main = document.getElementById("main-container");
    if (!main?.hasAttribute("data-read-only")) {
      // A form host keeps the person's input.
      this.stale = false;
      showToasts(refresh.swap?.messages ?? []);
      return;
    }
    if (csrfCookie() !== this.csrfAtLoad) {
      // Every host form holds the old token.
      handOffMessages(refresh.swap?.messages ?? [], location.href);
      browser.reload();
      return;
    }
    main.setAttribute("aria-busy", "true");
    try {
      await this.swapIn(refresh);
    } finally {
      main.removeAttribute("aria-busy");
    }
  }

  private async swapIn(refresh: Refresh): Promise<void> {
    let page = refresh.swap;
    if (!page) {
      try {
        const answer = await this.fetchAnswer(new URL(location.href), {
          signal: deadlineAfter(LOAD_TIMEOUT_MS),
        });
        if (answer.page && !sameUrl(answer.url, location.href)) {
          handOffMessages(answer.page.messages, answer.url);
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
      handOffMessages(page.messages, location.href);
      browser.reload();
      return;
    }
    this.stale = false;
    showToasts(page.messages);
    try {
      refocusAfterSwap(refresh.opener);
    } catch (error) {
      report(`refocus failed: ${String(error)}`);
    }
  }
}

customElements.define("form-dialog", FormDialogElement);
