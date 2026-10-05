// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AnswerPage } from "./answer.js";
import { refocusAfterSwap, swapHostPage, SWAPPED } from "./swap.js";

function fragmentOf(html: string): DocumentFragment {
  const template = document.createElement("template");
  template.innerHTML = html;
  return template.content;
}

function page(content: string, overrides: Partial<AnswerPage> = {}): AnswerPage {
  return {
    content: fragmentOf(content),
    title: "Devices",
    readOnly: true,
    messages: [],
    modules: [],
    navbar: fragmentOf("<a href='/'>Played 2h</a>"),
    htmlData: { "data-library-conversion-state": "{}" },
    documentTitle: "Timetracker - Devices",
    ...overrides,
  };
}

beforeEach(() => {
  document.body.innerHTML = `
    <nav id="navbar"><a href="/">Played 1h</a></nav>
    <div id="main-container" tabindex="-1" data-page-title="Old"><p>Old</p></div>
    <toast-stack></toast-stack><form-dialog></form-dialog>`;
});

afterEach(() => {
  document.documentElement.removeAttribute("data-library-conversion-state");
});

describe("swapHostPage", () => {
  it("replaces the page and its stamps, leaving the hosts", async () => {
    const toastStack = document.querySelector("toast-stack");
    const swapped = vi.fn();
    document.addEventListener(SWAPPED, swapped, { once: true });
    await swapHostPage(page("<p>New</p>"), () => Promise.resolve());
    const main = document.getElementById("main-container")!;
    expect(main.textContent).toBe("New");
    expect(main.getAttribute("data-page-title")).toBe("Devices");
    expect(main.hasAttribute("data-read-only")).toBe(true);
    expect(document.getElementById("navbar")!.textContent).toBe("Played 2h");
    expect(document.title).toBe("Timetracker - Devices");
    expect(document.documentElement.getAttribute("data-library-conversion-state")).toBe("{}");
    expect(document.querySelector("toast-stack")).toBe(toastStack);
    expect(swapped).toHaveBeenCalledOnce();
  });

  it("imports the page's modules first", async () => {
    const load = vi.fn(() => Promise.resolve());
    await swapHostPage(page("", { modules: ["/a.js"] }), load);
    expect(load).toHaveBeenCalledWith("/a.js");
  });

  it("changes nothing when a module fails", async () => {
    const load = () => Promise.reject(new Error("404"));
    await expect(swapHostPage(page("<p>New</p>", { modules: ["/a.js"] }), load)).rejects.toThrow("404");
    expect(document.getElementById("main-container")!.textContent).toBe("Old");
  });
});

describe("refocusAfterSwap", () => {
  it("focuses the twin with the opener's id", async () => {
    await swapHostPage(page("<button id='row-1'>Row</button>"), () => Promise.resolve());
    refocusAfterSwap({ id: "row-1", href: "" });
    expect(document.activeElement?.id).toBe("row-1");
  });

  it("focuses the toggle of a closed menu holding the twin", async () => {
    await swapHostPage(
      page(`<drop-down><button data-toggle>Menu</button>
        <div hidden><a href="/device/1/edit">Edit</a></div></drop-down>`),
      () => Promise.resolve(),
    );
    refocusAfterSwap({ id: "", href: "/device/1/edit" });
    expect(document.activeElement?.hasAttribute("data-toggle")).toBe(true);
  });

  it("falls back to the main container", async () => {
    await swapHostPage(page("<p>Gone</p>"), () => Promise.resolve());
    refocusAfterSwap({ id: "", href: "/device/9/edit" });
    expect(document.activeElement?.id).toBe("main-container");
  });
});
