// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../toast.js";
import { attachModal, type Modal } from "./modal-layer.js";
import { pushSurface } from "./surface-stack.js";
import "./toast-stack.js";

type Payload = { message: string; type?: string; id?: number | string; duration?: number | null };

function show(detail: Payload | Payload[]): void {
  document.dispatchEvent(new CustomEvent("show-toast", { detail, bubbles: true }));
}

function toasts(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("[data-toast-id]"));
}

function messageOf(toast: HTMLElement): string {
  return toast.querySelector("[data-toast-message]")?.textContent ?? "";
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = "<toast-stack></toast-stack>";
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("rendering", () => {
  it("renders a show-toast payload as one status toast with its message", () => {
    show({ message: "Saved", type: "success" });

    const [toast] = toasts();
    expect(toasts()).toHaveLength(1);
    expect(toast.getAttribute("role")).toBe("status");
    expect(toast.hasAttribute("aria-live")).toBe(false);
    expect(toast.getAttribute("tabindex")).toBe("0");
    expect(toast.classList.contains("success")).toBe(true);
    expect(messageOf(toast)).toBe("Saved");
  });

  it("renders a list payload as several toasts and keeps three at most", () => {
    show([
      { message: "one" },
      { message: "two" },
      { message: "three" },
      { message: "four" },
    ]);

    expect(toasts().map(messageOf)).toEqual(["two", "three", "four"]);
  });

  it("error and warning are alerts", () => {
    show([
      { message: "bad", type: "error" },
      { message: "hmm", type: "warning" },
    ]);

    const [error, warning] = toasts();
    expect(error.getAttribute("role")).toBe("alert");
    expect(warning.getAttribute("role")).toBe("alert");
  });

  it("an error never dismisses on its own", () => {
    show({ message: "bad", type: "error" });

    vi.advanceTimersByTime(60_000);

    expect(toasts()[0].classList.contains("opacity-0")).toBe(false);
  });

  it("reports a payload with no message and keeps the rest", () => {
    const report = vi.fn();
    vi.stubGlobal("fetch", report);
    show([{ nope: 1 } as unknown as Payload, { message: "kept" }]);

    expect(toasts().map(messageOf)).toEqual(["kept"]);
    expect(report).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("reads the django-messages script on connect", () => {
    document.body.innerHTML = `
      <script id="django-messages" type="application/json">[{"message":"Hello","type":"info"}]</script>
      <toast-stack></toast-stack>`;

    expect(toasts().map(messageOf)).toEqual(["Hello"]);
  });

  it("shows handed-off messages once, after the page's own", () => {
    sessionStorage.setItem(
      "toast-handoff",
      JSON.stringify({ target: location.href, at: Date.now(), messages: [{ message: "Moved" }] }),
    );
    document.body.innerHTML = `
      <script id="django-messages" type="application/json">[{"message":"Hello"}]</script>
      <toast-stack></toast-stack>`;

    expect(toasts().map(messageOf)).toEqual(["Hello", "Moved"]);
    expect(sessionStorage.getItem("toast-handoff")).toBeNull();
  });

  it("detaches its listeners on disconnect", () => {
    document.body.innerHTML = "";
    show({ message: "lost" });
    document.body.innerHTML = "<toast-stack></toast-stack>";

    expect(toasts()).toHaveLength(0);
  });
});

describe("lifecycle", () => {
  it("replaces a stable string id in place and clears its previous timer", () => {
    window.toast("first", "info", { id: "conversion", duration: 5_000 });
    expect(vi.getTimerCount()).toBe(1);

    window.toast("second", "warning", { id: "conversion", duration: null });

    expect(toasts()).toHaveLength(1);
    expect(toasts()[0].getAttribute("data-toast-id")).toBe("conversion");
    expect(messageOf(toasts()[0])).toBe("second");
    expect(toasts()[0].classList.contains("warning")).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("removes stable toasts through window.removeToast whether visible or dismissed", () => {
    window.toast("running", "info", { id: "job", duration: null });
    window.removeToast("job");
    expect(toasts()).toEqual([]);

    window.toast("again", "info", { id: "job", duration: null });
    toasts()[0].click();
    expect(toasts()[0].classList.contains("opacity-0")).toBe(true);
    window.removeToast("job");
    expect(toasts()).toEqual([]);
  });

  it("uses defaults and resumes only the remaining duration after pause", () => {
    show({ message: "notice", type: "info" });
    const [toast] = toasts();

    vi.advanceTimersByTime(2_000);
    toast.dispatchEvent(new Event("mouseenter"));
    vi.advanceTimersByTime(10_000);
    expect(toast.classList.contains("opacity-0")).toBe(false);

    toast.dispatchEvent(new Event("mouseleave"));
    vi.advanceTimersByTime(2_999);
    expect(toast.classList.contains("opacity-0")).toBe(false);
    vi.advanceTimersByTime(1);
    expect(toast.classList.contains("opacity-0")).toBe(true);
    vi.advanceTimersByTime(300);
    expect(toasts()).toEqual([]);
  });

  it("dismisses on click, on Escape, and on the close button without reaching the wrapper", () => {
    const dismissed = vi.fn();
    window.addEventListener("toast-dismissed", dismissed);
    show([{ message: "a" }, { message: "b" }, { message: "c" }]);
    const [first, second, third] = toasts();
    const wrapperClick = vi.fn();
    third.addEventListener("click", wrapperClick);

    first.click();
    second.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    third.querySelector<HTMLButtonElement>("[data-toast-dismiss]")!.click();

    expect(toasts().every((toast) => toast.classList.contains("opacity-0"))).toBe(true);
    expect(wrapperClick).not.toHaveBeenCalled();
    expect(dismissed).toHaveBeenCalledTimes(3);
    vi.advanceTimersByTime(300);
    expect(toasts()).toEqual([]);
    window.removeEventListener("toast-dismissed", dismissed);
  });

  it("keeps a toast when Escape closed a panel first", () => {
    show({ message: "stays" });
    const [toast] = toasts();
    pushSurface({ host: document.createElement("div"), kind: "panel", close: () => {} });
    toast.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
    expect(toast.classList.contains("opacity-0")).toBe(false);
  });

  it("a second dismiss while leaving neither fires nor reschedules", () => {
    const dismissed = vi.fn();
    window.addEventListener("toast-dismissed", dismissed);
    show({ message: "twice" });
    const [toast] = toasts();

    toast.click();
    vi.advanceTimersByTime(100);
    toast.click();
    toast.dispatchEvent(new Event("mouseenter"));
    toast.dispatchEvent(new Event("mouseleave"));

    expect(dismissed).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(200);
    expect(toasts()).toEqual([]);
    window.removeEventListener("toast-dismissed", dismissed);
  });

  it("does not fire toast-dismissed when the timer dismisses", () => {
    const dismissed = vi.fn();
    window.addEventListener("toast-dismissed", dismissed);
    show({ message: "quiet", type: "debug" });

    vi.advanceTimersByTime(3_000);

    expect(toasts()[0].classList.contains("opacity-0")).toBe(true);
    expect(dismissed).not.toHaveBeenCalled();
    window.removeEventListener("toast-dismissed", dismissed);
  });
});

describe("an action", () => {
  function clearCsrfCookie(): void {
    document.cookie = "csrftoken=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  }

  beforeEach(() => {
    document.cookie = "csrftoken=t; path=/";
    history.replaceState({}, "", "/session/list?page=2");
    document.body.innerHTML = '<toast-stack action-class="ghost-look"></toast-stack>';
  });

  afterEach(() => {
    clearCsrfCookie();
    history.replaceState({}, "", "/");
  });

  function showUndo(): HTMLElement {
    show({
      message: "Session removed.",
      type: "success",
      action: { label: "Undo", url: "/session/x/restore" },
    } as Payload);
    return toasts()[0];
  }

  it("renders an Undo form whose action carries the page as origin", () => {
    const toast = showUndo();

    const form = toast.querySelector<HTMLFormElement>("form[data-toast-action]")!;
    expect(form.getAttribute("method")).toBe("post");
    expect(form.getAttribute("action")).toBe(
      "/session/x/restore?origin=%2Fsession%2Flist%3Fpage%3D2",
    );
    const token = form.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]')!;
    expect(token.type).toBe("hidden");
    expect(token.value).toBe("t");
    const button = form.querySelector<HTMLButtonElement>("button[type=submit]")!;
    expect(button.textContent).toBe("Undo");
    expect(button.className).toBe("ghost-look");
  });

  it("a toast with an action lives ten seconds", () => {
    const toast = showUndo();

    vi.advanceTimersByTime(9_999);
    expect(toast.classList.contains("opacity-0")).toBe(false);
    vi.advanceTimersByTime(1);
    expect(toast.classList.contains("opacity-0")).toBe(true);
  });

  it("a toast without an action keeps its default", () => {
    show({ message: "plain", type: "success" });

    vi.advanceTimersByTime(5_000);
    expect(toasts()[0].classList.contains("opacity-0")).toBe(true);
  });

  it("resumes only when neither hovered nor focused", () => {
    const toast = showUndo();

    vi.advanceTimersByTime(4_000);
    toast.dispatchEvent(new Event("mouseenter"));
    toast.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    toast.dispatchEvent(new Event("mouseleave"));
    vi.advanceTimersByTime(20_000);
    expect(toast.classList.contains("opacity-0")).toBe(false);

    toast.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    vi.advanceTimersByTime(5_999);
    expect(toast.classList.contains("opacity-0")).toBe(false);
    vi.advanceTimersByTime(1);
    expect(toast.classList.contains("opacity-0")).toBe(true);
  });

  it("a stable id gains, changes and loses its action", () => {
    window.toast("a", "info", { id: "k" });
    expect(toasts()[0].querySelector("[data-toast-action]")).toBeNull();

    window.toast("b", "success", {
      id: "k",
      action: { label: "Undo", url: "/x/restore" },
    });
    expect(toasts()).toHaveLength(1);
    let form = toasts()[0].querySelector<HTMLFormElement>("[data-toast-action]")!;
    expect(form.getAttribute("action")).toBe("/x/restore?origin=%2Fsession%2Flist%3Fpage%3D2");
    vi.advanceTimersByTime(9_999);
    expect(toasts()[0].classList.contains("opacity-0")).toBe(false);

    window.toast("c", "success", {
      id: "k",
      action: { label: "Restore", url: "/y/restore" },
    });
    form = toasts()[0].querySelector<HTMLFormElement>("[data-toast-action]")!;
    expect(form.querySelector("button")!.textContent).toBe("Restore");

    window.toast("d", "info", { id: "k" });
    expect(toasts()[0].querySelector("[data-toast-action]")).toBeNull();
  });

  it("a toast replaced under the pointer stays until the pointer leaves", () => {
    window.toast("first", "info", { id: "k" });
    const [toast] = toasts();
    toast.dispatchEvent(new Event("mouseenter"));

    window.toast("second", "info", { id: "k" });
    vi.advanceTimersByTime(20_000);
    expect(toast.classList.contains("opacity-0")).toBe(false);

    toast.dispatchEvent(new Event("mouseleave"));
    vi.advanceTimersByTime(5_000);
    expect(toast.classList.contains("opacity-0")).toBe(true);
  });

  it("an action whose URL is no route path is dropped and reported", () => {
    const report = vi.fn();
    vi.stubGlobal("fetch", report);
    show({
      message: "odd",
      type: "success",
      action: { label: "Undo", url: "https://evil.example/x" },
    } as Payload);

    expect(toasts()[0].querySelector("[data-toast-action]")).toBeNull();
    expect(report).toHaveBeenCalled();
    vi.advanceTimersByTime(5_000);
    expect(toasts()[0].classList.contains("opacity-0")).toBe(true);
    vi.unstubAllGlobals();
  });

  it("without a CSRF token the form is not drawn", () => {
    clearCsrfCookie();
    const report = vi.fn();
    vi.stubGlobal("fetch", report);

    const toast = showUndo();

    expect(toast.querySelector("[data-toast-action]")).toBeNull();
    expect(report).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("clicking Undo does not dismiss the toast", () => {
    const toast = showUndo();
    const form = toast.querySelector<HTMLFormElement>("form[data-toast-action]")!;
    form.addEventListener("submit", (event) => event.preventDefault());

    form.querySelector<HTMLButtonElement>("button[type=submit]")!.click();

    expect(toast.classList.contains("opacity-0")).toBe(false);
  });
});

describe("under a modal", () => {
  const STACK = `<toast-stack role="region" aria-label="Notifications" aria-live="polite"
    aria-atomic="false" modal-region-class="region-look"></toast-stack>`;

  function mountModal(): { dialog: HTMLDialogElement; modal: Modal } {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("data-modal", "");
    dialog.innerHTML = "<div><button>Inside</button></div>";
    document.body.append(dialog);
    return { dialog, modal: attachModal(dialog) };
  }

  function region(dialog: HTMLDialogElement): HTMLElement | null {
    return dialog.querySelector<HTMLElement>(".region-look");
  }

  beforeEach(() => {
    document.body.innerHTML = STACK;
  });

  it("moves the toasts into a region in the top modal", () => {
    show({ message: "Saved" });
    const { dialog, modal } = mountModal();
    modal.open();
    const hosted = region(dialog)!;
    expect(hosted.parentElement).toBe(dialog);
    expect(toasts()[0].parentElement).toBe(hosted);
    expect(hosted.getAttribute("role")).toBe("region");
    expect(hosted.getAttribute("aria-label")).toBe("Notifications");
    expect(hosted.getAttribute("aria-live")).toBe("polite");
    expect(hosted.getAttribute("aria-atomic")).toBe("false");
  });

  it("puts a new toast in the top modal", () => {
    const { dialog, modal } = mountModal();
    modal.open();
    show({ message: "Saved" });
    expect(toasts()[0].closest("dialog")).toBe(dialog);
  });

  it("follows the top modal and back to the page", () => {
    show([{ message: "one" }, { message: "two" }]);
    const lower = mountModal();
    const upper = mountModal();
    lower.modal.open();
    upper.modal.open();
    expect(region(lower.dialog)).toBeNull();
    expect(toasts().every((toast) => toast.closest("dialog") === upper.dialog)).toBe(true);
    upper.modal.close();
    expect(toasts().every((toast) => toast.closest("dialog") === lower.dialog)).toBe(true);
    lower.modal.close();
    const stack = document.querySelector("toast-stack")!;
    expect(toasts().map(messageOf)).toEqual(["one", "two"]);
    expect(toasts().every((toast) => toast.parentElement === stack)).toBe(true);
    expect(region(lower.dialog)).toBeNull();
  });

  it("clears a hover the move hides", () => {
    show({ message: "Saved", duration: 1_000 });
    toasts()[0].dispatchEvent(new MouseEvent("mouseenter"));
    const { modal } = mountModal();
    modal.open();
    vi.advanceTimersByTime(1_000 + 300);
    expect(toasts()).toHaveLength(0);
  });

  it("hosts in a modal open before it connects", () => {
    document.body.innerHTML = "";
    const { dialog, modal } = mountModal();
    modal.open();
    document.body.insertAdjacentHTML("beforeend", STACK);
    show({ message: "Saved" });
    expect(toasts()[0].closest("dialog")).toBe(dialog);
  });

  it("moves the toasts back when their dialog leaves the document", async () => {
    show({ message: "Undo it", type: "error" });
    const { dialog, modal } = mountModal();
    modal.open();
    dialog.remove();
    await Promise.resolve();
    const stack = document.querySelector("toast-stack")!;
    expect(toasts()[0].parentElement).toBe(stack);
    show({ message: "Next" });
    expect(toasts().map((toast) => toast.parentElement)).toEqual([stack, stack]);
  });

  it("moves the toasts back when the last leave starts", () => {
    show({ message: "Saved" });
    const dialog = document.createElement("dialog");
    dialog.setAttribute("data-modal", "");
    document.body.append(dialog);
    const modal = attachModal(dialog, { leave: () => {} });
    modal.open();
    modal.close();
    expect(dialog.open).toBe(true);
    expect(toasts()[0].parentElement).toBe(document.querySelector("toast-stack"));
  });

  it("takes its toasts back when it leaves the document", () => {
    show({ message: "Saved" });
    const { dialog, modal } = mountModal();
    modal.open();
    const stack = document.querySelector("toast-stack")!;
    stack.remove();
    expect(region(dialog)).toBeNull();
    expect(stack.querySelectorAll("[data-toast-id]")).toHaveLength(1);
  });

  it("clears a focus the move hides", () => {
    show({ message: "Saved", duration: 1_000 });
    toasts()[0].dispatchEvent(new FocusEvent("focusin"));
    const { modal } = mountModal();
    modal.open();
    vi.advanceTimersByTime(1_000 + 300);
    expect(toasts()).toHaveLength(0);
  });

  it("rebuilds a region the modal's content swap removed", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const { dialog, modal } = mountModal();
    modal.open();
    show({ message: "First" });
    dialog.replaceChildren();
    show({ message: "Second" });
    expect(region(dialog)).not.toBeNull();
    expect(toasts().every((toast) => toast.closest("dialog") === dialog)).toBe(true);
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("region was detached"));
  });

  it("mutes its own live region while hosting", () => {
    const stack = document.querySelector("toast-stack")!;
    const { modal } = mountModal();
    modal.open();
    expect(stack.getAttribute("aria-live")).toBe("off");
    modal.close();
    expect(stack.getAttribute("aria-live")).toBe("polite");
  });
});

