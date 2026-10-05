// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import type { Answer, Page } from "./answer.js";
import { routeOpen, routeSubmit } from "./routes.js";

const PAGE: Page = {
  content: document.createDocumentFragment(),
  title: "",
  modules: [],
  messages: [],
};
const SAVED = [{ message: "Saved", type: "success" as const }];
const URL_A = new URL("http://x.test/devices");

const page: Answer = { kind: "page", url: URL_A, page: PAGE };
const done: Answer = { kind: "done", url: URL_A, messages: SAVED };
const next: Answer = { kind: "continue", url: URL_A };
const none: Answer = { kind: "none", status: 403 };

describe("routeOpen", () => {
  it("presents a page", () => {
    expect(routeOpen(page)).toEqual({ kind: "present", page: PAGE, url: URL_A });
  });

  it("toasts a result", () => {
    expect(routeOpen(done)).toEqual({ kind: "toast", messages: SAVED });
  });

  it("goes to a result that says nothing", () => {
    expect(routeOpen({ kind: "done", url: URL_A, messages: [] })).toEqual({
      kind: "navigate",
      url: URL_A,
    });
  });

  it("continues", () => {
    expect(routeOpen(next)).toEqual({ kind: "continue", url: URL_A });
  });

  it("follows the link on no kind", () => {
    expect(routeOpen(none)).toEqual({ kind: "follow" });
  });
});

describe("routeSubmit", () => {
  it("presents a page in the same dialog", () => {
    expect(routeSubmit(page, true)).toEqual({ kind: "present", page: PAGE, url: URL_A });
  });

  it("continues in the same dialog", () => {
    expect(routeSubmit(next, false)).toEqual({ kind: "continue", url: URL_A });
  });

  it("closes and reloads when alone", () => {
    expect(routeSubmit(done, true)).toEqual({ kind: "close", target: URL_A, messages: SAVED });
  });

  it("closes the top dialog when nested", () => {
    expect(routeSubmit(done, false)).toEqual({ kind: "closeTop", messages: SAVED });
  });

  it("refuses no kind", () => {
    expect(routeSubmit(none, true)).toEqual({ kind: "error", status: 403 });
  });
});
