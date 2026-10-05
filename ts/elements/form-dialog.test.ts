// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "../client-errors.js";
import "./form-dialog.js";

import type { FormDialogElement } from "./form-dialog.js";
import { browser } from "./form-dialog/navigation.js";
import { attachModal, openModals, resetModalLayerForTests, topModal } from "./modal-layer.js";

const HOST = "http://localhost:3000/device/list";

interface Reply {
  body: string;
  url: string;
  redirected?: boolean;
  status?: number;
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

function page(content: string, options: { readOnly?: boolean; title?: string; messages?: string } = {}): string {
  return `<!doctype html><html data-library-conversion-state="{}"><head>
    <title>Timetracker - ${options.title ?? "Edit device"}</title>
    <script id="django-messages" type="application/json">${options.messages ?? "[]"}</script>
    </head><body><nav id="navbar">Played 2h</nav>
    <div id="main-container" data-page-title="${options.title ?? "Edit device"}"
      ${options.readOnly ? "data-read-only" : ""}>${content}</div></body></html>`;
}

const EDIT_FORM = page(`
  <h1>Edit device</h1>
  <form method="post"><input name="name" id="name" value="Deck">
    <button name="submit" value="save">Save</button>
    <a href="/device/list">Cancel</a></form>`);

function reply(body: string, url: string, redirected = false, status = 200): Reply {
  return { body, url, redirected, status };
}

function respond(reply: Reply): Response {
  const response = new Response(reply.body, {
    status: reply.status ?? 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
  Object.defineProperty(response, "url", { value: reply.url });
  Object.defineProperty(response, "redirected", { value: reply.redirected ?? false });
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

function mountLink(href = "/device/1/edit", chrome = ""): HTMLAnchorElement {
  const main = document.getElementById("main-container")!;
  main.insertAdjacentHTML(
    "beforeend",
    `<a id="edit-1" href="${href}" data-form-dialog="${chrome}">Edit</a>`,
  );
  return main.querySelector<HTMLAnchorElement>(`a[href="${href}"]`)!;
}

function handedOff(): unknown {
  return JSON.parse(sessionStorage.getItem("toast-handoff") ?? "null")?.messages;
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

function submit(form: HTMLFormElement, submitter?: HTMLElement): void {
  form.requestSubmit(submitter);
}

async function openEdit(): Promise<HTMLAnchorElement> {
  replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
  const link = mountLink();
  click(link);
  await settle();
  return link;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/device/list");
  document.body.innerHTML = `<nav id="navbar">Played 1h</nav>
    <div id="main-container" tabindex="-1" data-read-only data-page-title="Devices"></div>`;
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
      const next = replies.shift();
      if (!next) throw new TypeError("no reply queued");
      return respond(next);
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
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
    const link = mountLink();
    click(link);
    expect(link.getAttribute("aria-busy")).toBe("true");
    expect(click(link).defaultPrevented).toBe(true);
    await settle();
    expect(calls).toHaveLength(1);
    expect(link.hasAttribute("aria-busy")).toBe(false);
  });

  it("leaves unmarked links alone", () => {
    const main = document.getElementById("main-container")!;
    main.innerHTML = `<a href="/games">Games</a>`;
    expect(click(main.querySelector("a")!).defaultPrevented).toBe(false);
  });
});

describe("open", () => {
  it("presents the page with the title in the header", async () => {
    await openEdit();
    const dialog = openDialog();
    expect(dialog.querySelector("[data-form-dialog-title]")!.textContent).toBe("Edit device");
    expect(body(dialog).querySelector("h1")).toBeNull();
    expect(body(dialog).querySelector("form")!.getAttribute("action")).toBe(
      "http://localhost:3000/device/1/edit",
    );
    expect(document.activeElement).toBe(body(dialog).querySelector("input"));
  });

  it("prefixes ids per dialog", async () => {
    await openEdit();
    const dialog = openDialog();
    const title = dialog.querySelector("[data-form-dialog-title]")!;
    expect(dialog.getAttribute("aria-labelledby")).toBe(title.id);
    expect(title.id).toMatch(/^form-dialog-\d+-form-dialog-title$/);
    expect(body(dialog).querySelector("input")!.id).toMatch(/^form-dialog-\d+-name$/);
  });

  it("names a bare dialog by label and drops the header", async () => {
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
    click(mountLink("/device/1/edit", "bare"));
    await settle();
    const dialog = openDialog();
    expect(dialog.querySelector("[data-form-dialog-header]")).toBeNull();
    expect(dialog.getAttribute("aria-label")).toBe("Edit device");
    expect(dialog.hasAttribute("aria-labelledby")).toBe(false);
    expect(body(dialog).querySelector("h1")).not.toBeNull();
  });

  it("focuses the first invalid control", async () => {
    replies.push(
      reply(
        page(`<form method="post"><input name="a"><input name="b" aria-invalid="true"></form>`),
        "http://localhost:3000/device/1/edit",
      ),
    );
    click(mountLink());
    await settle();
    expect(document.activeElement?.getAttribute("name")).toBe("b");
  });

  it("toasts a redirect back to the host", async () => {
    replies.push(
      reply(page("", { readOnly: true, messages: '[{"message":"Done"}]' }), HOST, true),
    );
    click(mountLink());
    await settle();
    expect(topModal()).toBeNull();
    expect(toasts).toEqual([[{ message: "Done" }]]);
  });

  it("hands off and navigates to a read-only page elsewhere", async () => {
    replies.push(
      reply(
        page("", { readOnly: true, messages: '[{"message":"Moved"}]' }),
        "http://localhost:3000/games",
        true,
      ),
    );
    click(mountLink());
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/games"]);
    expect(handedOff()).toEqual([{"message":"Moved"}]);
  });

  it("follows the link when the answer has no page", async () => {
    replies.push(reply("<h1>Server Error</h1>", "http://localhost:3000/device/1/edit", false, 500));
    click(mountLink());
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/device/1/edit"]);
  });

  it("follows the link when the network fails", async () => {
    click(mountLink());
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/device/1/edit"]);
  });

  it("follows the link when a module fails", async () => {
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      Promise.reject(new Error("404"));
    replies.push(
      reply(
        EDIT_FORM.replace("</body>", '<script type="module" src="/x.js"></script></body>'),
        "http://localhost:3000/device/1/edit",
      ),
    );
    click(mountLink());
    await settle();
    expect(topModal()).toBeNull();
    expect(assigned).toEqual(["http://localhost:3000/device/1/edit"]);
  });

  it("drops the answer when the top modal changed", async () => {
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
    click(mountLink());
    const other = document.createElement("dialog");
    other.setAttribute("data-modal", "");
    document.body.append(other);
    attachModal(other).open();
    await settle();
    expect(openModals()).toEqual([other]);
  });

  it("removes a dialog the layer refuses", async () => {
    vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(() => {
      throw new DOMException("refused", "InvalidStateError");
    });
    await openEdit();
    expect(document.querySelector("form-dialog dialog")).toBeNull();
    expect(assigned).toEqual(["http://localhost:3000/device/1/edit"]);
  });
});

describe("submit", () => {
  it("posts the form with its submitter to the form's URL", async () => {
    await openEdit();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit", false, 409));
    const form = body().querySelector("form")!;
    submit(form, form.querySelector("button")!);
    await settle();
    const [url, init] = calls[1];
    expect(String(url)).toBe("http://localhost:3000/device/1/edit");
    expect(init?.method).toBe("POST");
    const data = init?.body as FormData;
    expect(data.get("name")).toBe("Deck");
    expect(data.get("submit")).toBe("save");
  });

  it("presents a refusal in the same dialog", async () => {
    await openEdit();
    const dialog = openDialog();
    replies.push(
      reply(
        page(`<form method="post"><input name="name" aria-invalid="true"></form>`, {
          messages: '[{"message":"Refused","type":"error"}]',
        }),
        "http://localhost:3000/device/1/edit",
        false,
        409,
      ),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(openDialog()).toBe(dialog);
    expect(document.activeElement?.getAttribute("aria-invalid")).toBe("true");
    expect(toasts.at(-1)).toEqual([{ message: "Refused", type: "error" }]);
  });

  it("keeps the dialog and toasts an error without a page", async () => {
    await openEdit();
    replies.push(reply("<h1>Forbidden</h1>", "http://localhost:3000/device/1/edit", false, 403));
    submit(body().querySelector("form")!);
    await settle();
    expect(topModal()).not.toBeNull();
    expect(JSON.stringify(toasts.at(-1))).toContain("403");
  });

  it("swaps the host after a redirect to it", async () => {
    await openEdit();
    replies.push(
      reply(
        page(`<a id="edit-1" href="/device/1/edit">Edit Deck 2</a>`, {
          readOnly: true,
          title: "Devices",
          messages: '[{"message":"Saved"}]',
        }),
        HOST,
        true,
      ),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(topModal()).toBeNull();
    expect(document.querySelector("form-dialog dialog")).toBeNull();
    expect(document.getElementById("main-container")!.textContent).toContain("Edit Deck 2");
    expect(document.getElementById("navbar")!.textContent).toBe("Played 2h");
    expect(document.activeElement?.id).toBe("edit-1");
    expect(toasts.at(-1)).toEqual([{ message: "Saved" }]);
    expect(calls).toHaveLength(2);
  });

  it("vetoes dismissal while submitting", async () => {
    await openEdit();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
    submit(body().querySelector("form")!);
    openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(topModal()).not.toBeNull();
    await settle();
  });

  it("presents a redirect to a form page and swaps on a later close", async () => {
    await openEdit();
    replies.push(
      reply(
        page(`<form method="post"><input name="copy"></form>`, { title: "Add to library" }),
        "http://localhost:3000/entry/add?game=1",
        true,
      ),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(openDialog().querySelector("[data-form-dialog-title]")!.textContent).toBe(
      "Add to library",
    );
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true, title: "Devices" }), HOST));
    openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
    await settle();
    expect(String(calls.at(-1)![0])).toBe(HOST);
    expect(document.getElementById("main-container")!.textContent).toBe("Fresh");
  });

  it("reloads a dirty host when the CSRF cookie changed", async () => {
    document.cookie = "csrftoken=before";
    document.querySelector("form-dialog")!.remove();
    mountHost();
    await openEdit();
    replies.push(
      reply(page(`<form method="post"></form>`), "http://localhost:3000/device/1/edit?x=1", true),
    );
    submit(body().querySelector("form")!);
    await settle();
    document.cookie = "csrftoken=after";
    openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
    await settle();
    expect(reloads).toBe(1);
  });

  it("drops a late answer after close and refreshes the host", async () => {
    await openEdit();
    vi.mocked(fetch).mockImplementationOnce(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    submit(body().querySelector("form")!);
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    openDialog().close();
    await settle();
    expect(document.querySelector("form-dialog dialog")).toBeNull();
    expect(toasts).toEqual([]);
    // A close mid-submit may have written.
    expect(document.getElementById("main-container")!.textContent).toBe("Fresh");
  });

  it("closes on a Cancel link back to the host without a refresh", async () => {
    await openEdit();
    const cancel = body().querySelector<HTMLAnchorElement>("a")!;
    expect(click(cancel).defaultPrevented).toBe(true);
    await settle();
    expect(topModal()).toBeNull();
    expect(calls).toHaveLength(1);
  });

  it("keeps a submitting dialog open on Cancel", async () => {
    await openEdit();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
    submit(body().querySelector("form")!);
    click(body().querySelector<HTMLAnchorElement>("a")!);
    expect(topModal()).not.toBeNull();
    await settle();
  });

  it("submits once while a submit is pending, marked busy", async () => {
    await openEdit();
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
    release(respond(reply(EDIT_FORM, "http://localhost:3000/device/1/edit")));
    await settle();
    expect(body().hasAttribute("aria-busy")).toBe(false);
  });

  it("allows dismissal again once the submit settles", async () => {
    await openEdit();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit", false, 409));
    submit(body().querySelector("form")!);
    await settle();
    openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(topModal()).toBeNull();
  });

  it("says a failed request may have saved, and refreshes on close", async () => {
    await openEdit();
    submit(body().querySelector("form")!);
    await settle();
    expect(JSON.stringify(toasts.at(-1))).toContain("could not be confirmed");
    expect(topModal()).not.toBeNull();
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
    await settle();
    expect(String(calls.at(-1)![0])).toBe(HOST);
  });

  it("posts to the submitter's formaction", async () => {
    replies.push(
      reply(
        page(`<form method="post"><button formaction="/device/1/other">Other</button></form>`),
        "http://localhost:3000/device/1/edit",
      ),
    );
    click(mountLink());
    await settle();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/other", false, 409));
    const form = body().querySelector("form")!;
    submit(form, form.querySelector("button")!);
    await settle();
    expect(String(calls[1][0])).toBe("http://localhost:3000/device/1/other");
  });

  it("leaves a GET form and a form outside the dialog native", async () => {
    replies.push(
      reply(page(`<form method="get"><button>Search</button></form>`), "http://localhost:3000/x"),
    );
    click(mountLink());
    await settle();
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

  it("navigates on a save that redirects elsewhere", async () => {
    await openEdit();
    replies.push(
      reply(
        page("", { readOnly: true, messages: '[{"message":"Saved"}]' }),
        "http://localhost:3000/games/1",
        true,
      ),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/games/1"]);
    expect(handedOff()).toEqual([{"message":"Saved"}]);
  });

  it("keeps the input when a refusal's module fails", async () => {
    await openEdit();
    body().querySelector("input")!.value = "Typed";
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      Promise.reject(new Error("404"));
    replies.push(
      reply(
        EDIT_FORM.replace("</body>", '<script type="module" src="/x.js"></script></body>'),
        "http://localhost:3000/device/1/edit",
        false,
        409,
      ),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(assigned).toEqual([]);
    expect(body().querySelector("input")!.value).toBe("Typed");
    expect(JSON.stringify(toasts.at(-1))).toContain("could not be shown");
  });
});

describe("nesting", () => {
  it("closes only the top dialog and toasts below", async () => {
    replies.push(
      reply(page(`<a href="/platform/add" data-form-dialog="">New platform</a>`), "http://localhost:3000/device/1/edit"),
    );
    click(mountLink());
    await settle();
    const lower = openDialog();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/platform/add"));
    click(body(lower).querySelector("a")!);
    await settle();
    expect(openModals()).toHaveLength(2);
    replies.push(
      reply(
        page("", { readOnly: true, messages: '[{"message":"Platform added"}]' }),
        "http://localhost:3000/device/1/edit",
        true,
      ),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(openModals()).toEqual([lower]);
    expect(toasts.at(-1)).toEqual([{ message: "Platform added" }]);
    expect(body(lower).querySelector("a")).not.toBeNull();
  });
});

describe("undo", () => {
  function mountUndo(dialog: HTMLDialogElement): HTMLFormElement {
    dialog.insertAdjacentHTML(
      "beforeend",
      `<form data-toast-action method="post" action="/device/1/restore?origin=%2Fdevice%2Flist">
        <button>Undo</button></form>`,
    );
    return dialog.querySelector<HTMLFormElement>("form[data-toast-action]")!;
  }

  it("fetches the Undo, toasts, and marks the host stale", async () => {
    await openEdit();
    const dialog = openDialog();
    replies.push(reply(page("", { readOnly: true, messages: '[{"message":"Restored"}]' }), HOST, true));
    submit(mountUndo(dialog));
    await settle();
    expect(String(calls.at(-1)![0])).toBe("http://localhost:3000/device/1/restore?origin=%2Fdevice%2Flist");
    expect(toasts.at(-1)).toEqual([{ message: "Restored" }]);
    expect(openDialog()).toBe(dialog);
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    await settle();
    expect(document.getElementById("main-container")!.textContent).toBe("Fresh");
  });

  it("opens a waypoint page in a dialog on top", async () => {
    await openEdit();
    replies.push(reply(page("<p>Undoing 120 rows</p>", { title: "Undo" }), "http://localhost:3000/bulk"));
    submit(mountUndo(openDialog()));
    await settle();
    expect(openModals()).toHaveLength(2);
    expect(body().textContent).toContain("Undoing 120 rows");
  });
});

describe("refresh", () => {
  async function staleClose(): Promise<void> {
    await openEdit();
    replies.push(
      reply(page(`<form method="post"></form>`), "http://localhost:3000/entry/add", true),
    );
    submit(body().querySelector("form")!);
    await settle();
  }

  function cancelTop(): void {
    openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
  }

  it("goes where the host now redirects, with its messages", async () => {
    await staleClose();
    replies.push(
      reply(page("", { readOnly: true, messages: '[{"message":"Gone"}]' }), "http://localhost:3000/games", true),
    );
    cancelTop();
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/games"]);
    expect(handedOff()).toEqual([{"message":"Gone"}]);
  });

  it("reloads when the refetch fails or has no page", async () => {
    await staleClose();
    cancelTop();
    await settle();
    expect(reloads).toBe(1);

    replies.push(reply("<h1>Error</h1>", HOST, false, 500));
    await staleCloseAgain();
    expect(reloads).toBe(2);
    expect(document.getElementById("main-container")!.textContent).not.toContain("Error");
  });

  async function staleCloseAgain(): Promise<void> {
    const stillQueued = replies.splice(0);
    await staleClose();
    replies.push(...stillQueued);
    cancelTop();
    await settle();
  }

  it("hands off and reloads when the swap fails", async () => {
    await staleClose();
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      Promise.reject(new Error("404"));
    replies.push(
      reply(
        page("<p>Fresh</p>", { readOnly: true, messages: '[{"message":"Saved"}]' }).replace(
          "</body>",
          '<script type="module" src="/x.js"></script></body>',
        ),
        HOST,
      ),
    );
    cancelTop();
    await settle();
    expect(reloads).toBe(1);
    expect(handedOff()).toEqual([{"message":"Saved"}]);
  });

  it("hands off the saved messages on a CSRF reload", async () => {
    document.cookie = "csrftoken=before";
    document.querySelector("form-dialog")!.remove();
    mountHost();
    await openEdit();
    document.cookie = "csrftoken=after";
    replies.push(
      reply(page("", { readOnly: true, messages: '[{"message":"Saved"}]' }), HOST, true),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(reloads).toBe(1);
    expect(handedOff()).toEqual([{"message":"Saved"}]);
  });

  it("refreshes no more once a swap made the host current", async () => {
    await staleClose();
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    cancelTop();
    await settle();
    const fetched = calls.length;
    await openEdit();
    cancelTop();
    await settle();
    expect(calls).toHaveLength(fetched + 1);
  });

  it("waits until no other modal covers the page", async () => {
    const other = document.createElement("dialog");
    other.setAttribute("data-modal", "");
    document.body.append(other);
    const otherModal = attachModal(other);
    otherModal.open();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
    click(mountLink());
    await settle();
    replies.push(
      reply(page("", { readOnly: true, messages: '[{"message":"Saved"}]' }), HOST, true),
    );
    submit(body().querySelector("form")!);
    await settle();
    expect(openModals()).toEqual([other]);
    expect(calls).toHaveLength(2);
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    otherModal.close();
    await settle();
    expect(document.getElementById("main-container")!.textContent).toBe("Fresh");
  });
});

describe("open paths", () => {
  it("follows a link whose chrome no table states", async () => {
    click(mountLink("/device/1/edit", "sideways"));
    await settle();
    expect(calls).toHaveLength(0);
    expect(assigned).toEqual(["http://localhost:3000/device/1/edit"]);
  });

  it("follows the link when the page never answers", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementationOnce(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    click(mountLink());
    await vi.advanceTimersByTimeAsync(15_000);
    vi.useRealTimers();
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/device/1/edit"]);
  });

  it("keeps the messages of an answer another modal overtook", async () => {
    replies.push(
      reply(
        page("<form></form>", { messages: '[{"message":"Note"}]' }),
        "http://localhost:3000/device/1/edit",
      ),
    );
    click(mountLink());
    const other = document.createElement("dialog");
    other.setAttribute("data-modal", "");
    document.body.append(other);
    attachModal(other).open();
    await settle();
    expect(toasts).toEqual([[{ message: "Note" }]]);
  });

  it("focuses the × of a page without a form", async () => {
    replies.push(reply(page("<p>Nothing to fill</p>"), "http://localhost:3000/x"));
    click(mountLink());
    await settle();
    expect(document.activeElement?.hasAttribute("data-modal-dismiss")).toBe(true);
  });

  it("skips a hidden control for focus", async () => {
    replies.push(
      reply(
        page(`<form method="post"><div hidden><input name="a"></div><input name="b"></form>`),
        "http://localhost:3000/x",
      ),
    );
    click(mountLink());
    await settle();
    expect(document.activeElement?.getAttribute("name")).toBe("b");
  });
});

describe("nested refresh", () => {
  it("refreshes the host once the lower dialog closes after a nested write", async () => {
    replies.push(
      reply(
        page(`<a href="/platform/add" data-form-dialog="">New platform</a>`),
        "http://localhost:3000/device/1/edit",
      ),
    );
    click(mountLink());
    await settle();
    const lower = openDialog();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/platform/add"));
    click(body(lower).querySelector("a")!);
    await settle();
    replies.push(reply(page("", { readOnly: true }), "http://localhost:3000/device/1/edit", true));
    submit(body().querySelector("form")!);
    await settle();
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    lower.dispatchEvent(new Event("cancel", { cancelable: true }));
    await settle();
    expect(String(calls.at(-1)![0])).toBe(HOST);
    expect(document.getElementById("main-container")!.textContent).toBe("Fresh");
  });
});

describe("undo edges", () => {
  function mountUndo(dialog: HTMLDialogElement): HTMLFormElement {
    dialog.insertAdjacentHTML(
      "beforeend",
      `<form data-toast-action method="post" action="/device/1/restore"><button>Undo</button></form>`,
    );
    return dialog.querySelector<HTMLFormElement>("form[data-toast-action]")!;
  }

  it("says an unanswered Undo may have worked", async () => {
    await openEdit();
    submit(mountUndo(openDialog()));
    await settle();
    expect(JSON.stringify(toasts.at(-1))).toContain("could not be confirmed");
  });

  it("toasts an Undo answered without a page", async () => {
    await openEdit();
    replies.push(reply("<h1>Forbidden</h1>", "http://localhost:3000/device/1/restore", false, 403));
    submit(mountUndo(openDialog()));
    await settle();
    expect(JSON.stringify(toasts.at(-1))).toContain("403");
  });

  it("posts one Undo per press", async () => {
    await openEdit();
    vi.mocked(fetch).mockImplementationOnce(() => new Promise<Response>(() => {}));
    const form = mountUndo(openDialog());
    submit(form);
    submit(form);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(2);
    expect(form.getAttribute("aria-busy")).toBe("true");
  });

  it("follows a waypoint it cannot open", async () => {
    await openEdit();
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      Promise.reject(new Error("404"));
    replies.push(
      reply(
        page("<p>Undoing</p>").replace("</body>", '<script type="module" src="/x.js"></script></body>'),
        "http://localhost:3000/bulk",
      ),
    );
    submit(mountUndo(openDialog()));
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/bulk"]);
  });

  it("continues a waypoint that submits on connect", async () => {
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
    await openEdit();
    replies.push(
      reply(
        page(`<form method="post"><submits-on-connect></submits-on-connect></form>`),
        "http://localhost:3000/bulk",
      ),
    );
    replies.push(reply(page("<p>Next chunk</p>"), "http://localhost:3000/bulk"));
    submit(mountUndo(openDialog()));
    await settle();
    expect(calls.map(([, init]) => init?.method ?? "GET")).toEqual(["GET", "POST", "POST"]);
    expect(body().textContent).toContain("Next chunk");
  });

  it("leaves an Undo native with no dialog open", () => {
    const form = document.createElement("form");
    form.setAttribute("data-toast-action", "");
    form.method = "post";
    document.body.append(form);
    const event = new SubmitEvent("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("second round", () => {
  function cancelTop(): void {
    openDialog().dispatchEvent(new Event("cancel", { cancelable: true }));
  }

  async function openPage(content: string): Promise<HTMLDialogElement> {
    replies.push(reply(page(content), "http://localhost:3000/device/1/edit"));
    click(mountLink());
    await settle();
    return openDialog();
  }

  it("leaves a link to another page native", async () => {
    const dialog = await openPage(`<a href="/games/1">View game</a>`);
    expect(click(body(dialog).querySelector("a")!).defaultPrevented).toBe(false);
    expect(topModal()).toBe(dialog);
  });

  it("leaves a fragment link native", async () => {
    const dialog = await openPage(`<a href="#notes">Notes</a><p id="notes"></p>`);
    expect(click(body(dialog).querySelector("a")!).defaultPrevented).toBe(false);
    expect(topModal()).toBe(dialog);
  });

  it("closes the top dialog on a link back to the one below", async () => {
    const lower = await openPage(`<a href="/platform/add" data-form-dialog="">New platform</a>`);
    replies.push(
      reply(page(`<a href="/device/1/edit">Cancel</a>`), "http://localhost:3000/platform/add"),
    );
    click(body(lower).querySelector("a")!);
    await settle();
    expect(click(body().querySelector("a")!).defaultPrevented).toBe(true);
    expect(openModals()).toEqual([lower]);
  });

  it("follows formmethod over the form's method", async () => {
    const dialog = await openPage(`
      <form method="get"><button formmethod="post">Post</button></form>
      <form method="post"><button formmethod="get">Get</button></form>`);
    const [getForm, postForm] = body(dialog).querySelectorAll("form");
    const posted = new SubmitEvent("submit", {
      bubbles: true,
      cancelable: true,
      submitter: getForm.querySelector("button"),
    });
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit", false, 409));
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

  it("leaves a marked link opening elsewhere native", () => {
    const blank = mountLink("/device/1/edit");
    blank.target = "_blank";
    expect(click(blank).defaultPrevented).toBe(false);
    const download = mountLink("/device/2/edit");
    download.setAttribute("download", "");
    expect(click(download).defaultPrevented).toBe(false);
  });

  it("leaves another marked link native while one loads", () => {
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit"));
    click(mountLink("/device/1/edit"));
    expect(click(mountLink("/device/2/edit")).defaultPrevented).toBe(false);
  });

  it("refreshes nothing after a refusal", async () => {
    await openEdit();
    replies.push(reply(EDIT_FORM, "http://localhost:3000/device/1/edit", false, 409));
    submit(body().querySelector("form")!);
    await settle();
    cancelTop();
    await settle();
    expect(calls).toHaveLength(2);
  });

  it("follows the link when a module never loads", async () => {
    vi.useFakeTimers();
    document.querySelector<FormDialogElement>("form-dialog")!.loadModule = () =>
      new Promise(() => {});
    replies.push(
      reply(
        page("<form></form>", { messages: '[{"message":"Note"}]' }).replace(
          "</body>",
          '<script type="module" src="/x.js"></script></body>',
        ),
        "http://localhost:3000/device/1/edit",
      ),
    );
    click(mountLink());
    await vi.advanceTimersByTimeAsync(15_000);
    vi.useRealTimers();
    await settle();
    expect(assigned).toEqual(["http://localhost:3000/device/1/edit"]);
    expect(handedOff()).toEqual([{ message: "Note" }]);
  });

  it("refreshes once, not again when another modal closes later", async () => {
    const other = document.createElement("dialog");
    other.setAttribute("data-modal", "");
    document.body.append(other);
    const otherModal = attachModal(other);
    otherModal.open();
    await openEdit();
    replies.push(reply(page("", { readOnly: true }), HOST, true));
    submit(body().querySelector("form")!);
    await settle();
    // Covered: the refresh waits.
    expect(calls).toHaveLength(2);
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    otherModal.close();
    await settle();
    expect(calls).toHaveLength(3);
    otherModal.open();
    otherModal.close();
    await settle();
    expect(calls).toHaveLength(3);
  });

  it("refreshes after an Undo answered once its dialog closed", async () => {
    await openEdit();
    const dialog = openDialog();
    dialog.insertAdjacentHTML(
      "beforeend",
      `<form data-toast-action method="post" action="/device/1/restore"><button>Undo</button></form>`,
    );
    let release: (response: Response) => void = () => {};
    vi.mocked(fetch).mockImplementationOnce(
      () => new Promise<Response>((resolve) => (release = resolve)),
    );
    const undo = dialog.querySelector<HTMLFormElement>("form[data-toast-action]")!;
    submit(undo);
    cancelTop();
    await settle();
    replies.push(reply(page("<p>Fresh</p>", { readOnly: true }), HOST));
    release(respond(reply(page("", { readOnly: true }), HOST, true)));
    await settle();
    expect(document.getElementById("main-container")!.textContent).toBe("Fresh");
    expect(undo.isConnected).toBe(false);
  });

  it("says nothing was sent when the request cannot be built", async () => {
    const dialog = await openPage(`<form method="post"><input name="a"></form>`);
    body(dialog).querySelector("form")!.setAttribute("action", "http://[broken");
    submit(body(dialog).querySelector("form")!);
    await settle();
    expect(calls).toHaveLength(1);
    expect(JSON.stringify(toasts.at(-1))).toContain("Nothing was sent");
    cancelTop();
    await settle();
    expect(calls).toHaveLength(1);
  });

  it("reports an answer it could not show after a redirect as unconfirmed", async () => {
    await openEdit();
    replies.push(
      reply(page(`<form method="post"></form>`), "http://localhost:3000/entry/add", true),
    );
    vi.spyOn(HTMLElement.prototype, "replaceChildren").mockImplementationOnce(() => {
      throw new Error("broken");
    });
    submit(body().querySelector("form")!);
    await settle();
    expect(JSON.stringify(toasts.at(-1))).toContain("could not be confirmed");
  });

  it("names a success status without a page as nothing to show", async () => {
    await openEdit();
    replies.push(reply("{}", "http://localhost:3000/device/1/edit"));
    submit(body().querySelector("form")!);
    await settle();
    expect(JSON.stringify(toasts.at(-1))).toContain("answered 200 with nothing to show");
  });

  it("leaves a form host alone after a write", async () => {
    document.getElementById("main-container")!.removeAttribute("data-read-only");
    await openEdit();
    replies.push(reply(page(`<form method="post"></form>`), "http://localhost:3000/x", true));
    submit(body().querySelector("form")!);
    await settle();
    cancelTop();
    await settle();
    expect(calls).toHaveLength(2);
  });

  it("reloads when the refresh never answers, busy meanwhile", async () => {
    await openEdit();
    replies.push(reply(page(`<form method="post"></form>`), "http://localhost:3000/x", true));
    submit(body().querySelector("form")!);
    await settle();
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementationOnce(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    cancelTop();
    await vi.advanceTimersByTimeAsync(0);
    expect(document.getElementById("main-container")!.getAttribute("aria-busy")).toBe("true");
    await vi.advanceTimersByTimeAsync(15_000);
    vi.useRealTimers();
    await settle();
    expect(reloads).toBe(1);
    expect(document.getElementById("main-container")!.hasAttribute("aria-busy")).toBe(false);
  });
});
