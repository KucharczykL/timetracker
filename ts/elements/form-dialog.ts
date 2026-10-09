/** Opens marked links' form pages in a modal. */
import { reportClientError } from "../client-errors.js";
import {
  FORM_DIALOG_ATTRIBUTE,
  FORM_DIALOG_CHROME_BY_MARKER,
  FORM_DIALOG_HEADER,
  FORM_DIALOG_PARTS,
  FORM_ERRORS_ATTRIBUTE,
  type FormDialogChrome,
  PAGE_WIDTH_ATTRIBUTE,
  UNSAVED_WARNING_PARTS,
} from "../generated/form-dialog.js";
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import { ownChild } from "./own-child.js";
import {
  handOffMessages,
  handOffOpener,
  type OpenerKey,
  takeHandedOffOpener,
} from "../handoff.js";
import { type Answer, type Messages, type Page, readAnswer, sameUrl } from "./form-dialog/answer.js";
import {
  FORM_DIALOG_CREATED,
  type FormDialogCreatedDetail,
  FORM_DIALOG_RELOAD,
  type FormDialogReloadDetail,
  PAGE_STALE,
} from "./form-dialog/events.js";
import { browser } from "./form-dialog/navigation.js";
import { focusOpener, openerKey } from "./form-dialog/opener.js";
import {
  type IdPrefix,
  importModules,
  type ModuleLoader,
  prefixIds,
  resolveUrls,
} from "./form-dialog/rewrite.js";
import { assertNever, type DoneRoute, routeOpen, routeSubmit } from "./form-dialog/routes.js";
import { changedForms, type FormSnapshot, snapshotForms } from "./form-dialog/unsaved.js";
import {
  attachModal,
  isModalLeaving,
  isModalOpen,
  type Modal,
  MODAL_CHANGE,
  refreshModalStack,
  topModal,
  whenSettled,
} from "./modal-layer.js";

interface OpenDialog {
  readonly dialog: HTMLDialogElement;
  /** Takes the page's width. */
  readonly panel: HTMLElement;
  readonly body: HTMLElement;
  readonly chrome: FormDialogChrome;
  readonly openerKey: OpenerKey | null;
  /** The link; a created row goes there. */
  readonly opener: HTMLElement;
  readonly modal: Modal;
  /** Aborts the in-flight submit on close. */
  readonly controller: AbortController;
  /** The presented page's URL. */
  url: URL;
  submitting: boolean;
  /** What the forms held when presented. */
  baseline: FormSnapshot;
  /** A late baseline checks it. */
  baselineGeneration: number;
}

type SavingButton = HTMLButtonElement | HTMLInputElement;

/** What Save submits, with which button. */
interface SaveTarget {
  readonly form: HTMLFormElement;
  readonly button: SavingButton;
}

/** The person's answer to the warning. */
type UnsavedChoice =
  | { readonly kind: "discard" }
  | { readonly kind: "return" }
  | ({ readonly kind: "save" } & SaveTarget);

const DISCARD: UnsavedChoice = { kind: "discard" };
const RETURN: UnsavedChoice = { kind: "return" };

/** What the next reload carries. */
interface Reload {
  /** Null: the host page itself. */
  readonly target: URL | null;
  readonly messages: Messages;
  readonly opener: OpenerKey | null;
  /** A link the person leaves to. */
  readonly leave: URL | null;
}

/** What a POST sends. */
interface FormRequest {
  readonly url: URL;
  readonly body: FormData;
}

/** An element that takes created rows. */
const PICKER = "search-select";
//: A picker's face sits beside it.
const PICKER_FACE = "[data-search-select-face]";

/** Past this, a load gives up. */
const LOAD_TIMEOUT_MS = 15_000;
/** A longer `continue` chain is a loop. */
const CONTINUE_LIMIT = 5;

const TABBABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const CSRF_INPUT = "input[name=csrfmiddlewaretoken]";

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

// Past the layer's own leave cap.
const LEAVE_SETTLE_TIMEOUT_MS = 2_000;

/** Resolves once no modal leaves; else rejects. */
function whenLeaveSettles(): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cancel();
      reject(new Error("a modal leave never settled"));
    }, LEAVE_SETTLE_TIMEOUT_MS);
    const cancel = whenSettled(() => {
      window.clearTimeout(timer);
      resolve();
    });
  });
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
  if (marker === null || !Object.hasOwn(FORM_DIALOG_CHROME_BY_MARKER, marker)) return null;
  return FORM_DIALOG_CHROME_BY_MARKER[marker];
}

function initialFocus(dialog: HTMLDialogElement, body: HTMLElement): HTMLElement | null {
  const invalid = body.querySelector<HTMLElement>('[aria-invalid="true"]');
  if (invalid) return invalid;
  // A refusal no field owns.
  const errors = body.querySelector<HTMLElement>(`[${FORM_ERRORS_ATTRIBUTE}]`);
  if (errors) return errors;
  const form = body.querySelector("form");
  const first = form
    ? Array.from(form.querySelectorAll<HTMLElement>(TABBABLE)).find(
        (element) => !element.closest("[hidden], [inert]"),
      )
    : undefined;
  return first ?? dialog.querySelector<HTMLElement>(`[${MODAL_ATTRIBUTES.dismiss}]`);
}

/** Lowercased; a submitter's formmethod wins. */
function submitMethod(form: HTMLFormElement, submitter: HTMLElement | null): string {
  return (
    submitter?.getAttribute("formmethod") ??
    form.getAttribute("method") ??
    "get"
  ).toLowerCase();
}

function isSubmitButton(element: Element): element is SavingButton {
  if (element instanceof HTMLButtonElement) return element.type === "submit";
  return element instanceof HTMLInputElement && (element.type === "submit" || element.type === "image");
}

/** The default button, when it posts. */
function savingButton(form: HTMLFormElement): SavingButton | null {
  const button = Array.from(form.elements).find(isSubmitButton);
  if (!button || button.disabled || submitMethod(form, button) !== "post") return null;
  return button;
}

/** Only one changed form can be saved. */
function saveTarget(forms: readonly HTMLFormElement[]): SaveTarget | null {
  if (forms.length !== 1) return null;
  const button = savingButton(forms[0]);
  return button ? { form: forms[0], button } : null;
}

function whenClosed(entry: OpenDialog): Promise<void> {
  const signal = entry.controller.signal;
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
}

/** Throws on a malformed target or submitter. */
function formRequest(form: HTMLFormElement, submitter: HTMLElement | null): FormRequest {
  const target =
    submitter?.getAttribute("formaction") ?? form.getAttribute("action") ?? location.href;
  return { url: new URL(target, location.href), body: new FormData(form, submitter) };
}

/** Rejects once `signal` aborts, close included. */
function raceAbort<Result>(work: Promise<Result>, signal: AbortSignal | undefined): Promise<Result> {
  if (!signal) return work;
  return new Promise((resolve, reject) => {
    const abort = (): void => reject(new DOMException("aborted", "AbortError"));
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

function noReload(): Reload {
  return { target: null, messages: [], opener: null, leave: null };
}

/** Last target, every message, first opener. */
function mergeReload(current: Reload, more: Partial<Reload>): Reload {
  return {
    target: more.target ?? current.target,
    messages: [...current.messages, ...(more.messages ?? [])],
    opener: current.opener ?? more.opener ?? null,
    leave: more.leave === undefined ? current.leave : more.leave,
  };
}

/** Joins a dialog's abort with a deadline. */
function eitherAbort(first: AbortSignal, second: AbortSignal): AbortSignal {
  const controller = new AbortController();
  for (const signal of [first, second]) {
    if (signal.aborted) controller.abort();
    signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return controller.signal;
}

function isReadOnlyHost(): boolean {
  return document.getElementById("main-container")?.hasAttribute("data-read-only") ?? false;
}

function focusedOpener(): OpenerKey | null {
  const active = document.activeElement;
  return active instanceof HTMLElement && active !== document.body ? openerKey(active) : null;
}

export class FormDialogElement extends HTMLElement {
  /** Swapped in by tests. */
  loadModule?: ModuleLoader;
  private readonly stack: OpenDialog[] = [];
  /** Something wrote; the host is stale. */
  private stale = false;
  private reload: Reload = noReload();
  private reloadWaiting = false;
  /** The link whose page is loading. */
  private opening: HTMLAnchorElement | null = null;
  private presentations = 0;
  /** The token every form holds. */
  private csrfInForms = "";
  /** The warning is open. */
  private asking = false;

  connectedCallback(): void {
    this.csrfInForms = csrfCookie();
    document.addEventListener("click", this.onClick);
    document.addEventListener("submit", this.onSubmit);
    document.addEventListener(PAGE_STALE, this.onPageStale);
    document.addEventListener(FORM_DIALOG_RELOAD, this.onReload);
    window.addEventListener("beforeunload", this.onBeforeUnload);
    const opener = takeHandedOffOpener();
    if (opener) focusOpener(opener);
  }

  disconnectedCallback(): void {
    document.removeEventListener("click", this.onClick);
    document.removeEventListener("submit", this.onSubmit);
    document.removeEventListener(PAGE_STALE, this.onPageStale);
    document.removeEventListener(FORM_DIALOG_RELOAD, this.onReload);
    window.removeEventListener("beforeunload", this.onBeforeUnload);
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
    const firstAbove = this.firstAboveTarget(entry, link.href);
    if (firstAbove) {
      event.preventDefault();
      const closing = this.stack.slice(this.stack.indexOf(firstAbove)).reverse();
      void this.closeInTurn(closing);
      return;
    }
    if (!this.stack.some((open) => this.hasChanges(open))) return;
    event.preventDefault();
    void this.leaveFor(new URL(link.href));
  };

  private readonly onBeforeUnload = (event: BeforeUnloadEvent): void => {
    if (this.stack.some((entry) => this.hasChanges(entry))) event.preventDefault();
  };

  private hasChanges(entry: OpenDialog): boolean {
    return changedForms(entry.body, entry.baseline).length > 0;
  }

  /** Leaves once every dialog closes. */
  private async leaveFor(url: URL): Promise<void> {
    this.reload = mergeReload(this.reload, { leave: url });
    if (!(await this.closeInTurn([...this.stack].reverse()))) {
      this.reload = mergeReload(this.reload, { leave: null });
    }
  }

  /** Expects topmost first; false once one stays. */
  private async closeInTurn(entries: readonly OpenDialog[]): Promise<boolean> {
    for (const entry of entries) {
      if (!(await this.closeAsking(entry))) return false;
    }
    return true;
  }

  /** False when the dialog stays open. */
  private async closeAsking(entry: OpenDialog): Promise<boolean> {
    if (entry.submitting) return false;
    try {
      const forms = changedForms(entry.body, entry.baseline);
      if (forms.length > 0) {
        const choice = await this.askAbout(entry, forms);
        if (choice.kind === "save") choice.form.requestSubmit(choice.button);
        if (choice.kind !== "discard") return false;
      }
    } catch (error) {
      this.lostChanges(`the unsaved-changes warning failed: ${String(error)}`);
    }
    entry.modal.close();
    await whenClosed(entry);
    return true;
  }

  /** A broken warning must not trap anyone. */
  private lostChanges(detail: string): void {
    const id = report(detail);
    errorToast(`Your changes were not kept: the warning could not open (error ${id}).`);
  }

  /** Broken: discard. Already asking or busy: return. */
  private askAbout(entry: OpenDialog, forms: readonly HTMLFormElement[]): Promise<UnsavedChoice> {
    // Already asking, or a modal leaving.
    if (this.asking || isModalLeaving()) return Promise.resolve(RETURN);
    const template = this.querySelector<HTMLTemplateElement>(
      `template[${UNSAVED_WARNING_PARTS.template}]`,
    );
    const fragment = template?.content.cloneNode(true) as DocumentFragment | undefined;
    const dialog = fragment?.querySelector("dialog");
    if (!fragment || !dialog) {
      this.lostChanges("the host has no unsaved-changes warning");
      return Promise.resolve(DISCARD);
    }
    prefixIds(fragment, this.nextPrefix());
    const target = saveTarget(forms);
    const save = dialog.querySelector<HTMLElement>(`[${UNSAVED_WARNING_PARTS.save}]`);
    if (save) save.hidden = target === null;
    return new Promise((resolve) => {
      let choice: UnsavedChoice = RETURN;
      const modal = attachModal(dialog, {
        onClosed: () => {
          this.asking = false;
          dialog.remove();
          resolve(choice);
        },
      });
      dialog.querySelector(`[${UNSAVED_WARNING_PARTS.discard}]`)?.addEventListener("click", () => {
        choice = DISCARD;
        // The layer closes the warning first.
        entry.modal.close();
      });
      save?.addEventListener("click", () => {
        if (target) choice = { kind: "save", ...target };
        modal.close();
      });
      this.append(dialog);
      this.asking = true;
      let opened = false;
      try {
        opened = modal.open();
      } finally {
        if (!opened) {
          this.asking = false;
          dialog.remove();
        }
      }
      if (!opened) {
        this.lostChanges("the layer refused the unsaved-changes warning");
        resolve(DISCARD);
      }
    });
  }

  /** Taken now, and again after late fills. */
  private rebaseline(entry: OpenDialog): void {
    entry.baselineGeneration += 1;
    const generation = entry.baselineGeneration;
    entry.baseline = snapshotForms(entry.body);
    window.setTimeout(() => {
      if (entry.baselineGeneration !== generation || !this.stack.includes(entry)) return;
      entry.baseline = snapshotForms(entry.body);
    });
  }

  /** Back to the host or a lower dialog. */
  private firstAboveTarget(entry: OpenDialog, href: string): OpenDialog | null {
    if (sameUrl(href, location.href)) return this.stack[0];
    const index = this.stack.indexOf(entry);
    for (let lower = index - 1; lower >= 0; lower -= 1) {
      if (sameUrl(href, this.stack[lower].url)) return this.stack[lower + 1];
    }
    return null;
  }

  private readonly onSubmit = (event: SubmitEvent): void => {
    if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
    const form = event.target;
    const submitter = event.submitter instanceof HTMLElement ? event.submitter : null;
    if (submitMethod(form, submitter) !== "post") return;
    const entry = this.entryHolding(form);
    if (!entry) return;
    event.preventDefault();
    void this.submit(entry, form, submitter);
  };

  private readonly onPageStale = (): void => {
    this.stale = true;
    // Focus inside a dialog dies with the reload.
    const opener = this.stack[0]?.openerKey ?? focusedOpener();
    this.reload = mergeReload(this.reload, { opener });
    this.requestReload();
  };

  /** Refetches a dialog's page in place; what it now shows is the baseline. */
  private readonly onReload = (event: Event): void => {
    const detail = (event as CustomEvent<FormDialogReloadDetail>).detail;
    const holding = event.target instanceof Node ? this.entryHolding(event.target) : undefined;
    const entry = holding ?? this.stack[this.stack.length - 1];
    if (!entry || !detail?.url) return;
    void this.reloadInto(entry, new URL(detail.url, location.href));
  };

  private async reloadInto(entry: OpenDialog, url: URL): Promise<void> {
    try {
      const route = routeOpen(await this.fetchAnswer(url));
      if (route.kind !== "present") {
        report(`reload of ${url.href} answered ${route.kind}`);
        return;
      }
      await this.present(entry, route.page, route.url, entry.controller.signal, false);
      if (this.stack.includes(entry)) this.rebaseline(entry);
    } catch (error) {
      report(`reload of ${url.href} failed: ${String(error)}`);
    }
  }

  private entryHolding(node: Node): OpenDialog | undefined {
    return this.stack.find((entry) => entry.body.contains(node));
  }

  /** No form dialog below; other modals wait. */
  private alone(entry: OpenDialog): boolean {
    return this.stack[0] === entry;
  }

  /** A sign-in rotated it; every form follows. */
  private rewriteCsrf(): void {
    const cookie = csrfCookie();
    if (!cookie || cookie === this.csrfInForms) return;
    for (const input of document.querySelectorAll<HTMLInputElement>(CSRF_INPUT)) {
      input.value = cookie;
    }
    this.csrfInForms = cookie;
  }

  private async fetchAnswer(url: URL, init: RequestInit = {}): Promise<Answer> {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...init,
      headers: { [FORM_DIALOG_HEADER]: "1", Accept: "application/json" },
    });
    const answer = await readAnswer(response, url);
    this.rewriteCsrf();
    return answer;
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
        this.followLink(url, [], `unknown chrome "${marker}"`);
        return;
      }
      let route = routeOpen(await this.fetchAnswer(url, { signal: deadline }));
      for (let step = 1; route.kind === "continue"; step += 1) {
        if (step > CONTINUE_LIMIT) {
          report(`open of ${url.href} looped`);
          route = { kind: "follow" };
          break;
        }
        route = routeOpen(await this.fetchAnswer(route.url, { signal: deadline }));
      }
      if (route.kind === "present" && !(await this.prepare(route.page, route.url, deadline))) {
        this.followLink(url, route.page.messages, `the page at ${url.href} could not be fitted`);
        return;
      }
      // Wait for a sheet leaving on click.
      if (isModalLeaving()) await whenLeaveSettles();
      if (topModal() !== topAtClick) {
        // The server consumed them; show them anyway.
        report(`a modal overtook the link to ${url.href}`);
        if (route.kind === "present") showToasts(route.page.messages);
        if (route.kind === "toast") showToasts(route.messages);
        return;
      }
      switch (route.kind) {
        case "toast":
          showToasts(route.messages);
          return;
        case "navigate":
          report(`opening ${url.href} finished at ${route.url.href}`);
          // A form host keeps the person's input.
          if (isReadOnlyHost()) browser.assign(route.url.href);
          return;
        case "follow":
          this.followLink(url, [], `opening ${url.href} answered no kind`);
          return;
        case "present":
          if (!this.openDialog(route.page, route.url, link, chrome)) {
            this.followLink(url, route.page.messages, `the dialog for ${url.href} failed`);
          }
          return;
        default:
          assertNever(route);
      }
    } catch (error) {
      this.followLink(url, [], `open failed: ${String(error)}`);
    } finally {
      this.opening = null;
      link.removeAttribute("aria-busy");
    }
  }

  /** On a form host, stays and says so. */
  private followLink(url: URL, messages: Messages, detail: string): void {
    const id = report(detail);
    if (isReadOnlyHost()) {
      handOffMessages(messages);
      browser.assign(url.href);
      return;
    }
    showToasts(messages);
    errorToast(`This could not open here. Open the link in a new tab (error ${id}).`);
  }

  /** False when the dialog could not open. */
  private openDialog(page: Page, url: URL, opener: HTMLElement, chrome: FormDialogChrome): boolean {
    const template = this.querySelector<HTMLTemplateElement>(
      `template[${FORM_DIALOG_PARTS.template}]`,
    );
    if (!template) {
      report("the host has no template");
      return false;
    }
    const chromeFragment = template.content.cloneNode(true) as DocumentFragment;
    prefixIds(chromeFragment, this.nextPrefix());
    const dialog = chromeFragment.querySelector("dialog");
    const panel = dialog?.querySelector<HTMLElement>(`[${MODAL_ATTRIBUTES.panel}]`);
    const body = dialog?.querySelector<HTMLElement>(`[${FORM_DIALOG_PARTS.body}]`);
    if (!dialog || !panel || !body) {
      report("the template has no dialog, panel or body");
      return false;
    }
    if (chrome === "bare") {
      dialog.querySelector(`[${FORM_DIALOG_PARTS.header}]`)?.remove();
      dialog.removeAttribute("aria-labelledby");
    }
    const modal = attachModal(dialog, {
      initialFocus: () => initialFocus(dialog, body),
      dismiss: () => void this.closeAsking(entry),
      onClosed: () => this.closed(entry),
    });
    const entry: OpenDialog = {
      dialog,
      panel,
      body,
      chrome,
      openerKey: openerKey(opener),
      opener,
      modal,
      controller: new AbortController(),
      url,
      submitting: false,
      baseline: [],
      baselineGeneration: 0,
    };
    // Registered first: content may submit on connect.
    this.stack.push(entry);
    try {
      this.fill(entry, page, url);
      this.append(dialog);
      if (!modal.open(opener)) throw new Error("the layer refused to open");
      this.rebaseline(entry);
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
  private async prepare(page: Page, url: URL, deadline?: AbortSignal): Promise<boolean> {
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

  private fill(entry: OpenDialog, page: Page, url: URL): void {
    if (entry.chrome === "header") {
      // The header states the title.
      page.content.querySelector("h1")?.remove();
      const title = entry.dialog.querySelector(`[${FORM_DIALOG_PARTS.title}]`);
      if (title) title.textContent = page.title;
    } else {
      entry.dialog.setAttribute("aria-label", page.title);
    }
    entry.panel.setAttribute(PAGE_WIDTH_ATTRIBUTE, page.width);
    entry.body.replaceChildren(page.content);
    entry.url = url;
    // A trail above may name it.
    refreshModalStack();
  }

  private async present(
    entry: OpenDialog,
    page: Page,
    url: URL,
    signal: AbortSignal,
    wrote: boolean,
  ): Promise<void> {
    if (!(await this.prepare(page, url, signal))) {
      // The person's input stays on screen.
      showToasts(page.messages);
      this.unshownAnswer(entry, wrote, "the answered form could not be shown");
      return;
    }
    if (this.stack.includes(entry)) {
      this.fill(entry, page, url);
      // A refusal keeps the person's input unsaved.
      if (wrote) this.rebaseline(entry);
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
    this.rewriteCsrf();
    const request = this.buildRequest(form, submitter);
    if (!request) return;
    entry.submitting = true;
    form.setAttribute("aria-busy", "true");
    entry.body.setAttribute("aria-busy", "true");
    // A hung submit must not trap the person.
    const signal = eitherAbort(entry.controller.signal, deadlineAfter(LOAD_TIMEOUT_MS));
    const closed = (): boolean => entry.controller.signal.aborted;
    try {
      let answer: Answer;
      try {
        answer = await this.fetchAnswer(request.url, {
          method: "POST",
          body: request.body,
          signal,
        });
      } catch (error) {
        // The close already counted it as a write.
        if (closed()) return;
        this.unconfirmed(`submit failed: ${String(error)}`);
        return;
      }
      const wrote =
        answer.kind === "done" || answer.kind === "continue" || answer.kind === "created";
      // A created row's route decides.
      if (answer.kind === "done" || answer.kind === "continue") this.stale = true;
      try {
        await this.routeSubmitAnswer(entry, answer, signal, wrote);
      } catch (error) {
        if (closed()) return;
        this.unshownAnswer(entry, wrote, `routing the answer failed: ${String(error)}`);
      }
    } finally {
      entry.submitting = false;
      form.removeAttribute("aria-busy");
      entry.body.removeAttribute("aria-busy");
    }
  }

  /** `wrote`: the first answer was a result. */
  private async routeSubmitAnswer(
    entry: OpenDialog,
    first: Answer,
    signal: AbortSignal,
    wrote: boolean,
  ): Promise<void> {
    let answer = first;
    for (let step = 0; ; step += 1) {
      const route = routeSubmit(answer, this.alone(entry));
      switch (route.kind) {
        case "present":
          await this.present(entry, route.page, route.url, signal, wrote);
          return;
        case "continue":
          if (step >= CONTINUE_LIMIT) {
            const id = report(`a submit looped at ${route.url.href}`);
            errorToast(`The answer kept moving. Reload the page to check (error ${id}).`);
            return;
          }
          answer = await this.fetchAnswer(route.url, { signal });
          continue;
        case "close":
        case "closeTop":
          this.finish(entry, route);
          return;
        case "created":
          if (this.handOver(entry, route.option)) {
            // Only a lower dialog's close reloads.
            if (this.lowerDialogHolds(entry)) this.stale = true;
            // Clear it, or closed() marks stale.
            entry.submitting = false;
            this.finish(entry, { kind: "closeTop", messages: route.fallback.messages });
          } else {
            this.stale = true;
            this.finish(entry, route.fallback);
          }
          return;
        case "error":
          if (wrote) {
            this.rebaseline(entry);
            this.unconfirmed(`the next answer had no kind (status ${route.status})`);
          } else {
            this.refused(entry, route.status);
          }
          return;
        default:
          assertNever(route);
      }
    }
  }

  private finish(entry: OpenDialog, route: DoneRoute): void {
    if (route.kind === "close") {
      this.reload = mergeReload(this.reload, {
        target: route.target,
        messages: route.messages,
      });
      entry.modal.close();
      return;
    }
    entry.modal.close();
    showToasts(route.messages);
  }

  /** True when the opener took the row. */
  private handOver(entry: OpenDialog, option: FormDialogCreatedDetail): boolean {
    const link = entry.opener;
    const face = link.closest(PICKER_FACE);
    //: The face's parent is the picker's host.
    const host = face?.parentElement;
    const picker = link.closest(PICKER) ?? (host ? ownChild(host, PICKER) : null);
    if (face && !picker) {
      this.declined("its face names no picker", option);
      return false;
    }
    if (!link.isConnected) {
      if (picker) this.declined("its picker left the page", option);
      return false;
    }
    const event = new CustomEvent<FormDialogCreatedDetail>(FORM_DIALOG_CREATED, {
      bubbles: true,
      cancelable: true,
      detail: option,
    });
    if (!link.dispatchEvent(event)) return true;
    // A plain link reads it as done.
    if (picker) this.declined("its picker declined it", option);
    return false;
  }

  /** Saved, yet the field stays empty. */
  private declined(reason: string, option: FormDialogCreatedDetail): void {
    const id = report(`created row ${option.value} not handed over: ${reason}`);
    errorToast(`Saved, but the field could not take it. Pick it from the list (error ${id}).`);
  }

  private lowerDialogHolds(entry: OpenDialog): boolean {
    return this.stack.some(
      (other) => other !== entry && other.body.contains(entry.opener),
    );
  }

  /** A write may have landed unseen. */
  private unconfirmed(detail: string): void {
    this.stale = true;
    const id = report(detail);
    const remedy = isReadOnlyHost() ? "Close this to see the current page" : "Reload the page to check";
    errorToast(`The save could not be confirmed. ${remedy} (error ${id}).`);
  }

  /** After a write, the save is unconfirmed. */
  private unshownAnswer(entry: OpenDialog, wrote: boolean, detail: string): void {
    if (wrote) {
      // The write landed; the input is saved.
      this.rebaseline(entry);
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

  private refused(entry: OpenDialog, status: number): void {
    if (status === 404) {
      // Gone, not failed: the server logged it.
      this.rebaseline(entry);
      this.stale = true;
      errorToast("This no longer exists. Close this to reload the page.");
      return;
    }
    const id = report(`the answer had no kind (status ${status})`);
    if (status < 400) {
      errorToast(
        `The server answered ${status} with nothing to show. Reload the page to check (error ${id}).`,
      );
      return;
    }
    const remedy = status === 403 ? " Your session may have expired; reload the page." : "";
    errorToast(`The save failed: the server answered ${status}.${remedy} (error ${id})`);
  }

  private closed(entry: OpenDialog): void {
    if (entry.submitting) this.stale = true;
    entry.controller.abort();
    entry.dialog.remove();
    const index = this.stack.indexOf(entry);
    if (index !== -1) this.stack.splice(index, 1);
    if (this.stack.length > 0 || !(this.stale || this.reload.leave)) return;
    this.reload = mergeReload(this.reload, { opener: entry.openerKey });
    this.requestReload();
  }

  /** Runs once no modal covers the page. */
  private requestReload(): void {
    if (this.reloadWaiting) return;
    if (isModalOpen()) {
      this.reloadWaiting = true;
      window.addEventListener(MODAL_CHANGE, this.onModalChange);
      return;
    }
    this.runReload();
  }

  private readonly onModalChange = (): void => {
    if (isModalOpen()) return;
    window.removeEventListener(MODAL_CHANGE, this.onModalChange);
    this.reloadWaiting = false;
    this.runReload();
  };

  private runReload(): void {
    const { target, messages, opener, leave } = this.reload;
    this.reload = noReload();
    this.stale = false;
    if (leave) {
      // Storage refused: the page leaves anyway.
      handOffMessages(messages);
      if (opener) handOffOpener(opener);
      browser.assign(leave.href);
      return;
    }
    // Form host, or storage refused: show here.
    if (!isReadOnlyHost() || !handOffMessages(messages)) {
      showToasts(messages);
      return;
    }
    if (opener) handOffOpener(opener);
    if (target && !sameUrl(target, location.href)) {
      browser.assign(target.href);
    } else {
      browser.reload();
    }
  }
}

customElements.define("form-dialog", FormDialogElement);
