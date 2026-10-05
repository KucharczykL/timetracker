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
import { importModules, type ModuleLoader, prefixIds, resolveUrls } from "./form-dialog/rewrite.js";
import { browser } from "./form-dialog/navigation.js";
import { type RouteContext, routeOpen, routeSubmit } from "./form-dialog/routes.js";
import { type OpenerKey, openerKey, refocusAfterSwap, swapHostPage } from "./form-dialog/swap.js";
import { attachModal, type Modal, openModals, topModal } from "./modal-layer.js";

interface OpenDialog {
  readonly dialog: HTMLDialogElement;
  readonly body: HTMLElement;
  readonly chrome: FormDialogChrome;
  readonly opener: OpenerKey;
  /** Aborts the in-flight fetch on close. */
  readonly controller: AbortController;
  modal: Modal | null;
  submitting: boolean;
  /** A successful answer to swap in on close. */
  pendingSwap: AnswerPage | null;
}

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

function showToasts(messages: readonly unknown[]): void {
  if (messages.length === 0) return;
  window.dispatchEvent(new CustomEvent("show-toast", { detail: [...messages] }));
}

function report(detail: string): string {
  return reportClientError("form-dialog", detail, { toast: false });
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
  loadModule: ModuleLoader | undefined = undefined;
  private readonly stack: OpenDialog[] = [];
  /** A chain wrote; the host is stale. */
  private dirty = false;
  private opening = false;
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
      // A Cancel back to the host.
      event.preventDefault();
      entry.modal?.close();
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

  private context(entry: OpenDialog | null): RouteContext {
    const open = openModals();
    return {
      hostUrl: location.href,
      alone: entry !== null && open.length === 1 && open[0] === entry.dialog,
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

  private async openFrom(link: HTMLAnchorElement): Promise<void> {
    this.opening = true;
    link.setAttribute("aria-busy", "true");
    const topAtClick = topModal();
    const url = new URL(link.href);
    try {
      let answer: Answer;
      try {
        answer = await this.fetchAnswer(url);
      } catch (error) {
        report(`open failed: ${String(error)}`);
        browser.assign(url.href);
        return;
      }
      if (topModal() !== topAtClick) return;
      const route = routeOpen(answer, this.context(null));
      if (route.kind === "toast") {
        showToasts(answer.page?.messages ?? []);
      } else if (route.kind === "navigate") {
        handOffMessages(answer.page?.messages ?? []);
        browser.assign(route.url.href);
      } else if (route.kind === "follow") {
        browser.assign(url.href);
      } else {
        const chrome =
          link.getAttribute(FORM_DIALOG_ATTRIBUTE) === FORM_DIALOG_CHROME.bare
            ? "bare"
            : "header";
        if (!(await this.openDialog(answer, link, chrome))) browser.assign(url.href);
      }
    } finally {
      this.opening = false;
      link.removeAttribute("aria-busy");
    }
  }

  /** False when the dialog could not open. */
  private async openDialog(
    answer: Answer,
    opener: HTMLElement | null,
    chrome: FormDialogChrome,
  ): Promise<boolean> {
    const page = answer.page;
    const template = this.querySelector<HTMLTemplateElement>(
      `template[${FORM_DIALOG_PARTS.template}]`,
    );
    if (!page || !template) {
      report(template ? "no page to present" : "the host has no template");
      return false;
    }
    const content = await this.prepare(page, answer.url);
    if (!content) return false;
    const chromeFragment = template.content.cloneNode(true) as DocumentFragment;
    prefixIds(chromeFragment, this.nextPrefix());
    const dialog = chromeFragment.querySelector("dialog");
    const body = dialog?.querySelector<HTMLElement>(`[${FORM_DIALOG_PARTS.body}]`);
    if (!dialog || !body) {
      report("the template has no dialog or body");
      return false;
    }
    const entry: OpenDialog = {
      dialog,
      body,
      chrome,
      opener: opener ? openerKey(opener) : { id: "", href: "" },
      controller: new AbortController(),
      modal: null,
      submitting: false,
      pendingSwap: null,
    };
    if (chrome === "bare") {
      dialog.querySelector(`[${FORM_DIALOG_PARTS.header}]`)?.remove();
      dialog.removeAttribute("aria-labelledby");
    }
    this.fill(entry, page, content);
    this.append(dialog);
    const modal = attachModal(dialog, {
      initialFocus: () => initialFocus(dialog, body),
      dismiss: () => {
        if (!entry.submitting) modal.close();
      },
      onClosed: () => this.closed(entry),
    });
    entry.modal = modal;
    this.stack.push(entry);
    if (!modal.open(opener ?? undefined)) {
      this.stack.pop();
      dialog.remove();
      report("the layer refused to open the dialog");
      return false;
    }
    showToasts(page.messages);
    return true;
  }

  private nextPrefix(): string {
    this.presentations += 1;
    return `form-dialog-${this.presentations}-`;
  }

  /** Null, reported, when a module fails. */
  private async prepare(page: AnswerPage, url: URL): Promise<DocumentFragment | null> {
    try {
      await importModules(page.modules, this.loadModule);
    } catch (error) {
      report(`a module failed: ${String(error)}`);
      return null;
    }
    prefixIds(page.content, this.nextPrefix());
    resolveUrls(page.content, url);
    return page.content;
  }

  private fill(entry: OpenDialog, page: AnswerPage, content: DocumentFragment): void {
    if (entry.chrome === "header") {
      // The header states the title.
      content.querySelector("h1")?.remove();
      const title = entry.dialog.querySelector(`[${FORM_DIALOG_PARTS.title}]`);
      if (title) title.textContent = page.title;
    } else {
      entry.dialog.setAttribute("aria-label", page.title);
    }
    entry.body.replaceChildren(content);
  }

  private async present(entry: OpenDialog, answer: Answer): Promise<void> {
    const page = answer.page;
    if (!page) return;
    const content = await this.prepare(page, answer.url);
    if (!content) {
      handOffMessages(page.messages);
      browser.assign(answer.url.href);
      return;
    }
    if (!this.stack.includes(entry)) return;
    this.fill(entry, page, content);
    entry.modal?.focusInitial();
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
    const target =
      submitter?.getAttribute("formaction") ?? form.getAttribute("action") ?? location.href;
    try {
      let answer: Answer;
      try {
        answer = await this.fetchAnswer(new URL(target, location.href), {
          method: "POST",
          body: new FormData(form, submitter),
          signal: entry.controller.signal,
        });
      } catch (error) {
        if (!entry.controller.signal.aborted) this.failed(`submit failed: ${String(error)}`);
        return;
      }
      if (!this.stack.includes(entry)) return;
      if (answer.redirected) this.dirty = true;
      await this.routeSubmitAnswer(entry, answer);
    } finally {
      entry.submitting = false;
      form.removeAttribute("aria-busy");
    }
  }

  private async routeSubmitAnswer(entry: OpenDialog, answer: Answer): Promise<void> {
    const route = routeSubmit(answer, this.context(entry));
    const messages = answer.page?.messages ?? [];
    switch (route.kind) {
      case "present":
        await this.present(entry, answer);
        return;
      case "error":
        this.failed(`the answer had no page (status ${answer.status})`, answer.status);
        return;
      case "swap":
        entry.pendingSwap = answer.page;
        entry.modal?.close();
        return;
      case "navigate":
        handOffMessages(messages);
        browser.assign(route.url.href);
        return;
      case "closeTop":
        entry.modal?.close();
        showToasts(messages);
        return;
    }
  }

  private failed(detail: string, status?: number): void {
    const id = report(detail);
    const reason = status === undefined ? "the request failed" : `the server answered ${status}`;
    showToasts([{ message: `Nothing was saved: ${reason} (error ${id}).`, type: "error" }]);
  }

  private async submitUndo(form: HTMLFormElement): Promise<void> {
    const target = form.getAttribute("action") ?? location.href;
    let answer: Answer;
    try {
      answer = await this.fetchAnswer(new URL(target, location.href), {
        method: "POST",
        body: new FormData(form),
      });
    } catch (error) {
      this.failed(`undo failed: ${String(error)}`);
      return;
    }
    if (answer.redirected) {
      this.dirty = true;
      showToasts(answer.page?.messages ?? []);
    } else if (answer.page) {
      // A batch waypoint continues in a dialog.
      if (!(await this.openDialog(answer, null, "header"))) {
        this.failed("the undo page could not open");
      }
    } else {
      this.failed(`undo answered ${answer.status} without a page`, answer.status);
    }
  }

  private closed(entry: OpenDialog): void {
    entry.controller.abort();
    entry.dialog.remove();
    const index = this.stack.indexOf(entry);
    if (index !== -1) this.stack.splice(index, 1);
    if (this.stack.length > 0) return;
    if (entry.pendingSwap || this.dirty) void this.refresh(entry);
  }

  /** Brings the host page up to date. */
  private async refresh(entry: OpenDialog): Promise<void> {
    if (csrfCookie() !== this.csrfAtLoad) {
      // Every host form holds the old token.
      browser.reload();
      return;
    }
    let page = entry.pendingSwap;
    if (!page) {
      try {
        const answer = await this.fetchAnswer(new URL(location.href));
        page = answer.page && sameUrl(answer.url, location.href) ? answer.page : null;
      } catch (error) {
        report(`refresh failed: ${String(error)}`);
      }
    }
    if (!page) {
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
    this.dirty = false;
    refocusAfterSwap(entry.opener);
    showToasts(page.messages);
  }
}

customElements.define("form-dialog", FormDialogElement);
