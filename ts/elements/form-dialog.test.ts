// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "../client-errors.js";
import "./form-dialog.js";

import type { FormDialogElement } from "./form-dialog.js";
import { PAGE_STALE } from "./form-dialog/events.js";
import { browser } from "./form-dialog/navigation.js";
import { attachModal, openModals, resetModalLayerForTests, topModal } from "./modal-layer.js";

const ORIGIN = "http://localhost:3000";
const HOST = `${ORIGIN}/device/list`;
const EDIT = `${ORIGIN}/device/1/edit`;

interface Reply {
  body: unknown;
  url: string;
  status?: number;
  /** Not JSON: an error page. */
  html?: boolean;
}

type FetchCall = [URL, RequestInit | undefined];

let replies: Reply[];
let calls: FetchCall[];
let toasts: unknown[][];
let assigned: string[];
let reloads: number;

const onToast = (event: Event): void => {
  toasts.push((event as CustomEvent<unknown[]>).detail);
};

function page(
  html: string,
  options: { title?: string; messages?: unknown[]; modules?: string[] } = {},
): unknown {
  return {
    kind: "page",
    title: options.title ?? "Edit device",
    html,
    modules: options.modules ?? [],
    messages: options.messages ?? [],
  };
}

function done(url: string, messages: unknown[] = []): unknown {
  return { kind: "done", url, messages };
}

function next(url: string): unknown {
  return { kind: "continue", url };
}

const EDIT_FORM = page(`
  <h1>Edit device</h1>
  <form method="post"><input name="name" id="name" value="Deck">
    <input type="hidden" name="csrfmiddlewaretoken" value="old">
    <button name="submit" value="save">Save</button>
    <a href="/device/list">Cancel</a></form>`);

const SAVED = [{ message: "Saved", type: "success" }];

function reply(body: unknown, url = EDIT, status = 200): Reply {
  return { body, url, status };
}

function errorPage(status: number, url = EDIT): Reply {
  return { body: "<h1>Error</h1>", url, status, html: true };
}

function respond(reply: Reply): Response {
  const response = new Response(reply.html ? String(reply.body) : JSON.stringify(reply.body), {
    status: reply.status ?? 200,
    headers: { "content-type": reply.html ? "text/html" : "application/json" },
  });
  Object.defineProperty(response, "url", { value: reply.url });
  return response;
}

function mountHost(): FormDialogElement {
  document.body.insertAdjacentHTML(
    "beforeend",
    `<form-dialog><template data-form-dialog-template>
      <dialog data-modal aria-labelledby="form-dialog-title">
        <div>
          <div data-form-dialog-header>
            <h2 id="form-dialog-title" data-form-dialog-title></h2>
            <button data-modal-dismiss aria-label="Close dialog">×</button>
          </div>
          <div data-form-dialog-body></div>
        </div>
      </dialog></template></form-dialog>`,
  );
  const host = document.querySelector<FormDialogElement>("form-dialog")!;
  host.loadModule = () => Promise.resolve();
  return host;
}

function remountHost(): FormDialogElement {
  document.querySelector("form-dialog")!.remove();
  return mountHost();
}

function mountLink(href = "/device/1/edit", chrome = ""): HTMLAnchorElement {
  const main = document.getElementById("main-container")!;
  main.insertAdjacentHTML(
    "beforeend",
    `<a id="edit-${main.children.length}" href="${href}" data-form-dialog="${chrome}">Edit</a>`,
  );
  return main.querySelector<HTMLAnchorElement>(`a[href="${href}"]`)!;
}

function handedOff(key: "messages" | "opener"): unknown {
  return JSON.parse(sessionStorage.getItem(`handoff:${key}`) ?? "null")?.value;
}

async function settle(): Promise<void> {
  for (let round = 0; round < 10; round += 1) await new Promise((resolve) => setTimeout(resolve));
}

function click(element: Element, init: MouseEventInit = {}): MouseEvent {
  const event = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init });
  element.dispatchEvent(event);
  return event;
}

function openDialog(): HTMLDialogElement {
  return topModal()!;
}

function body(dialog: HTMLDialogElement = openDialog()): HTMLElement {
  return dialog.querySelector<HTMLElement>("[data-form-dialog-body]")!;
}

function submit(form: HTMLFormElement = body().querySelector("form")!, submitter?: HTMLElement): void {
  form.requestSubmit(submitter);
}

function cancelTop(): void {
  openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
}

async function openPage(answer: unknown = EDIT_FORM): Promise<HTMLDialogElement> {
  replies.push(reply(answer));
  click(mountLink());
  await settle();
  return openDialog();
}

function coverWithModal(): { close(): void; open(): void } {
  const other = document.createElement("dialog");
  other.setAttribute("data-modal", "");
  document.body.append(other);
  const modal = attachModal(other);
  modal.open();
  return modal;
}

function pending(): void {
  vi.mocked(fetch).mockImplementationOnce(
    (_url, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      }),
  );
}

beforeEach(() => {
  window.history.replaceState(null, "", "/device/list");
  document.body.innerHTML = `<div id="main-container" tabindex="-1" data-read-only></div>`;
  replies = [];
  calls = [];
  toasts = [];
  assigned = [];
  reloads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: URL, init?: RequestInit) => {
      calls.push([url, init]);
      if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
      const queued = replies.shift();
      if (!queued) throw new TypeError("no reply queued");
      return respond(queued);
    }),
  );
  vi.spyOn(browser, "assign").mockImplementation((url) => {
    assigned.push(url);
  });
  vi.spyOn(browser, "reload").mockImplementation(() => {
    reloads += 1;
  });
  vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id-1");
  window.addEventListener("show-toast", onToast);
  mountHost();
});

afterEach(() => {
  window.removeEventListener("show-toast", onToast);
  resetModalLayerForTests();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  sessionStorage.clear();
});

describe("clicks", () => {
  it("leaves a modified or middle click native", () => {
    const link = mountLink();
    expect(click(link, { ctrlKey: true }).defaultPrevented).toBe(false);
    expect(click(link, { button: 1 }).defaultPrevented).toBe(false);
    expect(calls).toHaveLength(0);
  });

  it("ignores a second click while opening", async () => {
    replies.push(reply(EDIT_FORM));
    const link = mountLink();
    click(link);
    expect(link.getAttribute("aria-busy")).toBe("true");
    expect(click(link).defaultPrevented).toBe(true);
    await settle();
    expect(calls).toHaveLength(1);
    expect(link.hasAttribute("aria-busy")).toBe(false);
  });

  it("leaves another marked link native while one loads", () => {
    replies.push(reply(EDIT_FORM));
    click(mountLink("/device/1/edit"));
    expect(click(mountLink("/device/2/edit")).defaultPrevented).toBe(false);
  });

  it("leaves unmarked links alone", () => {
    const main = document.getElementById("main-container")!;
    main.innerHTML = `<a href="/games">Games</a>`;
    expect(click(main.querySelector("a")!).defaultPrevented).toBe(false);
  });

  it("leaves a marked link opening elsewhere native", () => {
    const blank = mountLink("/device/1/edit");
    blank.target = "_blank";
    expect(click(blank).defaultPrevented).toBe(false);
    const download = mountLink("/device/2/edit");
    download.setAttribute("download", "");
    expect(click(download).defaultPrevented).toBe(false);
  });
});

describe("open", () => {
  it("asks for dialog mode", async () => {
    await openPage();
    const headers = calls[0][1]?.headers as Record<string, string>;
    expect(headers["X-Form-Dialog"]).toBe("1");
    expect(headers.Accept).toBe("application/json");
  });

  it("presents the page with the title in the header", async () => {
    const dialog = await openPage();
    expect(dialog.querySelector("[data-form-dialog-title]")!.textContent).toBe("Edit device");
    expect(body(dialog).querySelector("h1")).toBeNull();
    expect(body(dialog).querySelector("form")!.getAttribute("action")).toBe(EDIT);
    expect(document.activeElement).toBe(body(dialog).querySelector("input"));
  });

  it("prefixes ids per dialog", async () => {
    const dialog = await openPage();
    const title = dialog.querySelector("[data-form-dialog-title]")!;
    expect(dialog.getAttribute("aria-labelledby")).toBe(title.id);
    expect(title.id).toMatch(/^form-dialog-\d+-form-dialog-title$/);
    expect(body(dialog).querySelector("input")!.id).toMatch(/^form-dialog-\d+-name$/);
  });

  it("names a bare dialog by label and drops the header", async () => {
    replies.push(reply(EDIT_FORM));
    click(mountLink("/device/1/edit", "bare"));
    await settle();
    const dialog = openDialog();
    expect(dialog.querySelector("[data-form-dialog-header]")).toBeNull();
    expect(dialog.getAttribute("aria-label")).toBe("Edit device");
    expect(dialog.hasAttribute("aria-labelledby")).toBe(false);
    expect(body(dialog).querySelector("h1")).not.toBeNull();
  });

  it("imports the page's modules before inserting", async () => {
    const loaded: string[] = [];
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = (url) => {
      loaded.push(url);
      return Promise.resolve();
    };
    await openPage(page("<form></form>", { modules: ["/static/js/x.js"] }));
    expect(loaded).toEqual([`${ORIGIN}/static/js/x.js`]);
  });

  it("focuses the first invalid control", async () => {
    await openPage(page(`<form method="post"><input name="a"><input name="b" aria-invalid="true"></form>`));
    expect(document.activeElement?.getAttribute("name")).toBe("b");
  });

  it("skips a hidden control for focus", async () => {
    await openPage(page(`<form method="post"><div hidden><input name="a"></div><input name="b"></form>`));
    expect(document.activeElement?.getAttribute("name")).toBe("b");
  });

  it("focuses the × of a page without a form", async () => {
    await openPage(page("<p>Nothing to fill</p>"));
    expect(document.activeElement?.hasAttribute("data-modal-dismiss")).toBe(true);
  });

  it("shows the page's messages", async () => {
    await openPage(page("<form></form>", { messages: [{ message: "Note", type: "info" }] }));
    expect(toasts).toEqual([[{ message: "Note", type: "info" }]]);
  });

  it("toasts a done answer", async () => {
    replies.push(reply(done(HOST, SAVED)));
    click(mountLink());
    await settle();
    expect(topModal()).toBeNull();
    expect(toasts).toEqual([SAVED]);
    expect(assigned).toEqual([]);
  });

  it("fetches a continue answer the same way", async () => {
    replies.push(reply(next(`${ORIGIN}/login/?next=/device/1/edit`)));
    replies.push(reply(page("<form></form>", { title: "Log in" }), `${ORIGIN}/login/?next=/device/1/edit`));
    click(mountLink());
    await settle();
    expect(String(calls[1][0])).toBe(`${ORIGIN}/login/?next=/device/1/edit`);
    expect(openDialog().querySelector("[data-form-dialog-title]")!.textContent).toBe("Log in");
  });

  it("follows the original link after five continue answers", async () => {
    for (let step = 0; step < 6; step += 1) replies.push(reply(next(`${ORIGIN}/loop`)));
    click(mountLink());
    await settle();
    expect(calls).toHaveLength(6);
    expect(assigned).toEqual([EDIT]);
  });

  it("follows the link when the answer has no kind", async () => {
    replies.push(errorPage(500));
    click(mountLink());
    await settle();
    expect(assigned).toEqual([EDIT]);
  });

  it("follows the link when the network fails", async () => {
    click(mountLink());
    await settle();
    expect(assigned).toEqual([EDIT]);
  });

  it("follows the link when a module fails", async () => {
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      Promise.reject(new Error("404"));
    replies.push(reply(page("<form></form>", { modules: ["/x.js"], messages: [{ message: "Note" }] })));
    click(mountLink());
    await settle();
    expect(topModal()).toBeNull();
    expect(assigned).toEqual([EDIT]);
    expect(handedOff("messages")).toEqual([{ message: "Note" }]);
  });

  it("follows a link whose chrome no table states", async () => {
    click(mountLink("/device/1/edit", "sideways"));
    await settle();
    expect(calls).toHaveLength(0);
    expect(assigned).toEqual([EDIT]);
  });

  it("follows the link when the page never answers", async () => {
    vi.useFakeTimers();
    pending();
    click(mountLink());
    await vi.advanceTimersByTimeAsync(15_000);
    vi.useRealTimers();
    await settle();
    expect(assigned).toEqual([EDIT]);
  });

  it("follows the link when a module never loads", async () => {
    vi.useFakeTimers();
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      new Promise(() => {});
    replies.push(reply(page("<form></form>", { modules: ["/x.js"] })));
    click(mountLink());
    await vi.advanceTimersByTimeAsync(15_000);
    vi.useRealTimers();
    await settle();
    expect(assigned).toEqual([EDIT]);
  });

  it("drops the answer when the top modal changed", async () => {
    replies.push(reply(EDIT_FORM));
    click(mountLink());
    const other = coverWithModal();
    await settle();
    expect(openModals()).toHaveLength(1);
    other.close();
  });

  it("removes a dialog the layer refuses", async () => {
    vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(() => {
      throw new DOMException("refused", "InvalidStateError");
    });
    await openPage();
    expect(document.querySelector("form-dialog dialog")).toBeNull();
    expect(assigned).toEqual([EDIT]);
  });
});

describe("links inside a dialog", () => {
  it("closes on a link back to the host without a reload", async () => {
    await openPage();
    const cancel = body().querySelector<HTMLAnchorElement>("a")!;
    expect(click(cancel).defaultPrevented).toBe(true);
    await settle();
    expect(topModal()).toBeNull();
    expect(reloads).toBe(0);
  });

  it("closes the top dialog on a link back to the one below", async () => {
    const lower = await openPage(page(`<a href="/platform/add" data-form-dialog="">New platform</a>`));
    replies.push(reply(page(`<a href="/device/1/edit">Cancel</a>`), `${ORIGIN}/platform/add`));
    click(body(lower).querySelector("a")!);
    await settle();
    expect(click(body().querySelector("a")!).defaultPrevented).toBe(true);
    expect(openModals()).toEqual([lower]);
  });

  it("leaves a link to another page native", async () => {
    const dialog = await openPage(page(`<a href="/games/1">View game</a>`));
    expect(click(body(dialog).querySelector("a")!).defaultPrevented).toBe(false);
  });

  it("leaves a fragment link native", async () => {
    const dialog = await openPage(page(`<a href="#notes">Notes</a><p id="notes"></p>`));
    expect(click(body(dialog).querySelector("a")!).defaultPrevented).toBe(false);
    expect(topModal()).toBe(dialog);
  });
});

describe("submit", () => {
  it("posts the form with its submitter, in dialog mode", async () => {
    await openPage();
    replies.push(reply(EDIT_FORM, EDIT, 409));
    const form = body().querySelector("form")!;
    submit(form, form.querySelector("button")!);
    await settle();
    const [url, init] = calls[1];
    expect(String(url)).toBe(EDIT);
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["X-Form-Dialog"]).toBe("1");
    const data = init?.body as FormData;
    expect(data.get("name")).toBe("Deck");
    expect(data.get("submit")).toBe("save");
  });

  it("posts to the submitter's formaction", async () => {
    await openPage(page(`<form method="post"><button formaction="/device/1/other">Other</button></form>`));
    replies.push(reply(EDIT_FORM, `${ORIGIN}/device/1/other`, 409));
    const form = body().querySelector("form")!;
    submit(form, form.querySelector("button")!);
    await settle();
    expect(String(calls[1][0])).toBe(`${ORIGIN}/device/1/other`);
  });

  it("presents a page in the same dialog", async () => {
    const dialog = await openPage();
    replies.push(
      reply(
        page(`<form method="post"><input name="name" aria-invalid="true"></form>`, {
          messages: [{ message: "Refused", type: "error" }],
        }),
        EDIT,
        409,
      ),
    );
    submit();
    await settle();
    expect(openDialog()).toBe(dialog);
    expect(document.activeElement?.getAttribute("aria-invalid")).toBe("true");
    expect(toasts.at(-1)).toEqual([{ message: "Refused", type: "error" }]);
  });

  it("fetches a continue answer into the same dialog", async () => {
    const dialog = await openPage();
    replies.push(reply(next(`${ORIGIN}/entry/add?game=1`)));
    replies.push(reply(page(`<form method="post"></form>`, { title: "Add to library" }), `${ORIGIN}/entry/add?game=1`));
    submit();
    await settle();
    expect(calls.at(-1)![1]?.method).toBeUndefined();
    expect(openDialog()).toBe(dialog);
    expect(dialog.querySelector("[data-form-dialog-title]")!.textContent).toBe("Add to library");
    expect(body().querySelector("form")!.getAttribute("action")).toBe(`${ORIGIN}/entry/add?game=1`);
  });

  it("stops a continue chain with an error toast", async () => {
    await openPage();
    for (let step = 0; step < 6; step += 1) replies.push(reply(next(`${ORIGIN}/loop`)));
    submit();
    await settle();
    expect(calls).toHaveLength(7);
    expect(JSON.stringify(toasts.at(-1))).toContain("kept moving");
    expect(topModal()).not.toBeNull();
  });

  it("closes and reloads the host on done, alone", async () => {
    const link = mountLink();
    replies.push(reply(EDIT_FORM));
    click(link);
    await settle();
    replies.push(reply(done(HOST, SAVED)));
    submit();
    await settle();
    expect(topModal()).toBeNull();
    expect(document.querySelector("form-dialog dialog")).toBeNull();
    expect(reloads).toBe(1);
    expect(assigned).toEqual([]);
    expect(handedOff("messages")).toEqual(SAVED);
    expect(handedOff("opener")).toEqual({ id: link.id, href: "/device/1/edit" });
  });

  it("navigates to a done URL elsewhere", async () => {
    await openPage();
    replies.push(reply(done(`${ORIGIN}/games`, SAVED)));
    submit();
    await settle();
    expect(assigned).toEqual([`${ORIGIN}/games`]);
    expect(reloads).toBe(0);
    expect(handedOff("messages")).toEqual(SAVED);
  });

  it("closes the top dialog and toasts below on a nested done", async () => {
    const lower = await openPage(page(`<a href="/platform/add" data-form-dialog="">New platform</a>`));
    replies.push(reply(EDIT_FORM, `${ORIGIN}/platform/add`));
    click(body(lower).querySelector("a")!);
    await settle();
    expect(openModals()).toHaveLength(2);
    replies.push(reply(done(EDIT, [{ message: "Platform added" }])));
    submit();
    await settle();
    expect(openModals()).toEqual([lower]);
    expect(toasts.at(-1)).toEqual([{ message: "Platform added" }]);
    expect(reloads).toBe(0);
  });

  it("reloads once the lower dialog closes after a nested write", async () => {
    const lower = await openPage(page(`<a href="/platform/add" data-form-dialog="">New platform</a>`));
    replies.push(reply(EDIT_FORM, `${ORIGIN}/platform/add`));
    click(body(lower).querySelector("a")!);
    await settle();
    replies.push(reply(done(EDIT)));
    submit();
    await settle();
    cancelTop();
    await settle();
    expect(reloads).toBe(1);
  });

  it("keeps the dialog and toasts an error on no kind", async () => {
    await openPage();
    replies.push(errorPage(403));
    submit();
    await settle();
    expect(topModal()).not.toBeNull();
    expect(JSON.stringify(toasts.at(-1))).toContain("403");
    cancelTop();
    await settle();
    expect(reloads).toBe(0);
  });

  it("names a success status without a kind as nothing to show", async () => {
    await openPage();
    replies.push(errorPage(200));
    submit();
    await settle();
    expect(JSON.stringify(toasts.at(-1))).toContain("answered 200 with nothing to show");
  });

  it("says a failed request may have saved, and reloads on close", async () => {
    await openPage();
    submit();
    await settle();
    expect(JSON.stringify(toasts.at(-1))).toContain("could not be confirmed");
    expect(topModal()).not.toBeNull();
    cancelTop();
    await settle();
    expect(reloads).toBe(1);
  });

  it("drops a late answer after close and reloads the host", async () => {
    await openPage();
    pending();
    submit();
    openDialog().close();
    await settle();
    expect(document.querySelector("form-dialog dialog")).toBeNull();
    expect(toasts).toEqual([]);
    expect(reloads).toBe(1);
  });

  it("reloads nothing after a refusal", async () => {
    await openPage();
    replies.push(reply(EDIT_FORM, EDIT, 409));
    submit();
    await settle();
    cancelTop();
    await settle();
    expect(reloads).toBe(0);
  });

  it("vetoes dismissal and Cancel while submitting", async () => {
    await openPage();
    pending();
    submit();
    cancelTop();
    click(body().querySelector<HTMLAnchorElement>("a")!);
    expect(topModal()).not.toBeNull();
  });

  it("submits once while a submit is pending, marked busy", async () => {
    await openPage();
    let release: (response: Response) => void = () => {};
    vi.mocked(fetch).mockImplementationOnce(
      () => new Promise<Response>((resolve) => (release = resolve)),
    );
    const form = body().querySelector("form")!;
    submit(form);
    submit(form);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(2);
    expect(form.getAttribute("aria-busy")).toBe("true");
    expect(body().getAttribute("aria-busy")).toBe("true");
    release(respond(reply(EDIT_FORM, EDIT, 409)));
    await settle();
    expect(body().hasAttribute("aria-busy")).toBe(false);
    cancelTop();
    expect(topModal()).toBeNull();
  });

  it("leaves a GET form and a form outside the dialog native", async () => {
    await openPage(page(`<form method="get"><button>Search</button></form>`));
    const getEvent = new SubmitEvent("submit", { bubbles: true, cancelable: true });
    body().querySelector("form")!.dispatchEvent(getEvent);
    expect(getEvent.defaultPrevented).toBe(false);
    const outside = document.createElement("form");
    outside.method = "post";
    document.body.append(outside);
    const postEvent = new SubmitEvent("submit", { bubbles: true, cancelable: true });
    outside.dispatchEvent(postEvent);
    expect(postEvent.defaultPrevented).toBe(false);
  });

  it("leaves a toast action form native", async () => {
    const dialog = await openPage();
    dialog.insertAdjacentHTML(
      "beforeend",
      `<form data-toast-action method="post" action="/device/1/restore"><button>Undo</button></form>`,
    );
    const event = new SubmitEvent("submit", { bubbles: true, cancelable: true });
    dialog.querySelector("form[data-toast-action]")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("follows formmethod over the form's method", async () => {
    const dialog = await openPage(
      page(`<form method="get"><button formmethod="post">Post</button></form>
        <form method="post"><button formmethod="get">Get</button></form>`),
    );
    const [getForm, postForm] = body(dialog).querySelectorAll("form");
    const posted = new SubmitEvent("submit", {
      bubbles: true,
      cancelable: true,
      submitter: getForm.querySelector("button"),
    });
    replies.push(reply(EDIT_FORM, EDIT, 409));
    getForm.dispatchEvent(posted);
    expect(posted.defaultPrevented).toBe(true);
    const got = new SubmitEvent("submit", {
      bubbles: true,
      cancelable: true,
      submitter: postForm.querySelector("button"),
    });
    postForm.dispatchEvent(got);
    expect(got.defaultPrevented).toBe(false);
    await settle();
  });

  it("keeps the input when a refusal's module fails", async () => {
    await openPage();
    body().querySelector("input")!.value = "Typed";
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      Promise.reject(new Error("404"));
    replies.push(reply(page("<form></form>", { modules: ["/x.js"] }), EDIT, 409));
    submit();
    await settle();
    expect(assigned).toEqual([]);
    expect(body().querySelector("input")!.value).toBe("Typed");
    expect(JSON.stringify(toasts.at(-1))).toContain("could not be shown");
  });

  it("says nothing was sent when the request cannot be built", async () => {
    const dialog = await openPage(page(`<form method="post"><input name="a"></form>`));
    body(dialog).querySelector("form")!.setAttribute("action", "http://[broken");
    submit();
    await settle();
    expect(calls).toHaveLength(1);
    expect(JSON.stringify(toasts.at(-1))).toContain("Nothing was sent");
  });

  it("continues content that submits on connect", async () => {
    if (!customElements.get("submits-on-connect")) {
      customElements.define(
        "submits-on-connect",
        class extends HTMLElement {
          connectedCallback(): void {
            this.closest("form")?.requestSubmit();
          }
        },
      );
    }
    replies.push(reply(page(`<form method="post"><submits-on-connect></submits-on-connect></form>`)));
    replies.push(reply(page("<p>Next chunk</p>")));
    click(mountLink());
    await settle();
    expect(calls.map(([, init]) => init?.method ?? "GET")).toEqual(["GET", "POST"]);
    expect(body().textContent).toContain("Next chunk");
  });
});

describe("reload", () => {
  async function staleDialog(): Promise<void> {
    await openPage();
    replies.push(reply(next(`${ORIGIN}/entry/add`)));
    replies.push(reply(page(`<form method="post"></form>`), `${ORIGIN}/entry/add`));
    submit();
    await settle();
  }

  it("reloads when a stale bottom dialog closes", async () => {
    await staleDialog();
    cancelTop();
    await settle();
    expect(reloads).toBe(1);
  });

  it("waits until no other modal covers the page", async () => {
    const other = coverWithModal();
    replies.push(reply(EDIT_FORM));
    click(mountLink());
    await settle();
    replies.push(reply(done(HOST, SAVED)));
    submit();
    await settle();
    expect(openModals()).toHaveLength(1);
    expect(reloads).toBe(0);
    other.close();
    await settle();
    expect(reloads).toBe(1);
  });

  it("reloads once for a stale close and a page:stale", async () => {
    const other = coverWithModal();
    await staleDialog();
    document.dispatchEvent(new Event(PAGE_STALE));
    cancelTop();
    await settle();
    expect(reloads).toBe(0);
    other.close();
    await settle();
    expect(reloads).toBe(1);
    other.open();
    other.close();
    await settle();
    expect(reloads).toBe(1);
  });

  it("reloads on page:stale with no dialog open", async () => {
    document.dispatchEvent(new Event(PAGE_STALE));
    await settle();
    expect(reloads).toBe(1);
  });

  it("leaves a form host in place and shows its messages", async () => {
    document.getElementById("main-container")!.removeAttribute("data-read-only");
    await openPage();
    replies.push(reply(done(`${ORIGIN}/games`, SAVED)));
    submit();
    await settle();
    expect(topModal()).toBeNull();
    expect(reloads).toBe(0);
    expect(assigned).toEqual([]);
    expect(toasts.at(-1)).toEqual(SAVED);
  });

  it("focuses the handed-off opener after the load", () => {
    const main = document.getElementById("main-container")!;
    main.innerHTML = `<a id="row-edit" href="/device/1/edit">Edit</a>`;
    sessionStorage.setItem(
      "handoff:opener",
      JSON.stringify({ at: Date.now(), value: { id: "row-edit", href: "/device/1/edit" } }),
    );
    remountHost();
    expect(document.activeElement?.id).toBe("row-edit");
  });

  it("finds the opener by href when its id is gone", () => {
    const main = document.getElementById("main-container")!;
    main.innerHTML = `<a href="/device/1/edit">Edit</a>`;
    sessionStorage.setItem(
      "handoff:opener",
      JSON.stringify({ at: Date.now(), value: { id: "gone", href: "/device/1/edit" } }),
    );
    remountHost();
    expect(document.activeElement?.getAttribute("href")).toBe("/device/1/edit");
  });

  it("focuses the page when the opener is gone", () => {
    sessionStorage.setItem(
      "handoff:opener",
      JSON.stringify({ at: Date.now(), value: { id: "gone", href: "/gone" } }),
    );
    remountHost();
    expect(document.activeElement?.id).toBe("main-container");
  });
});

describe("CSRF", () => {
  it("rewrites every token once a sign-in rotated the cookie", async () => {
    document.cookie = "csrftoken=before";
    remountHost();
    document.getElementById("main-container")!.innerHTML =
      `<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="old"></form>`;
    await openPage();
    document.cookie = "csrftoken=after";
    replies.push(reply(page(`<form method="post"></form>`), EDIT, 409));
    submit();
    await settle();
    const sent = (calls[1][1]?.body as FormData).get("csrfmiddlewaretoken");
    expect(sent).toBe("after");
    const tokens = Array.from(
      document.querySelectorAll<HTMLInputElement>("input[name=csrfmiddlewaretoken]"),
      (input) => input.value,
    );
    expect(tokens).toContain("after");
    expect(tokens.filter((token) => token !== "after")).toEqual([]);
  });

  it("leaves tokens alone while the cookie holds", async () => {
    document.cookie = "csrftoken=same";
    remountHost();
    await openPage();
    replies.push(reply(EDIT_FORM, EDIT, 409));
    submit();
    await settle();
    expect((calls[1][1]?.body as FormData).get("csrfmiddlewaretoken")).toBe("old");
  });
});
