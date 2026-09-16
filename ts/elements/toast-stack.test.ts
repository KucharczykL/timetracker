// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../toast.js";
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
    expect(toast.getAttribute("aria-live")).toBe("polite");
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

  it("error and warning are alerts; error is assertive", () => {
    show([
      { message: "bad", type: "error" },
      { message: "hmm", type: "warning" },
    ]);

    const [error, warning] = toasts();
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.getAttribute("aria-live")).toBe("assertive");
    expect(warning.getAttribute("role")).toBe("alert");
    expect(warning.getAttribute("aria-live")).toBe("polite");
  });

  it("reads the django-messages script on connect", () => {
    document.body.innerHTML = `
      <script id="django-messages" type="application/json">[{"message":"Hello","type":"info"}]</script>
      <toast-stack></toast-stack>`;

    expect(toasts().map(messageOf)).toEqual(["Hello"]);
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
