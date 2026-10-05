// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import type { Answer, AnswerPage } from "./answer.js";
import { routeOpen, routeSubmit } from "./routes.js";

const HOST = "http://x.test/device/list";

function page(readOnly: boolean, messages: unknown[] = []): AnswerPage {
  return {
    content: document.createDocumentFragment(),
    title: "",
    readOnly,
    messages,
    modules: [],
    navbar: null,
    htmlData: {},
    documentTitle: "",
  };
}

function answer(url: string, options: Partial<Answer> = {}): Answer {
  return { url: new URL(url), redirected: false, status: 200, page: page(false), ...options };
}

const alone = { hostUrl: HOST, alone: true };
const nested = { hostUrl: HOST, alone: false };
const SAVED = [{ message: "Saved" }];

describe("routeOpen", () => {
  it("toasts a redirect back to the host", () => {
    expect(
      routeOpen(answer(`${HOST}#x`, { redirected: true, page: page(true, SAVED) }), HOST),
    ).toEqual({ kind: "toast", messages: SAVED });
  });

  it("navigates to a read-only page, carrying its messages", () => {
    const route = routeOpen(
      answer("http://x.test/games", { redirected: true, page: page(true, SAVED) }),
      HOST,
    );
    expect(route).toEqual({
      kind: "navigate",
      url: new URL("http://x.test/games"),
      messages: SAVED,
    });
  });

  it("presents a form page with its page", () => {
    const form = answer("http://x.test/device/1/edit");
    expect(routeOpen(form, HOST)).toEqual({ kind: "present", page: form.page });
  });

  it("follows the link without a page", () => {
    expect(routeOpen(answer("http://x.test/x", { status: 404, page: null }), HOST)).toEqual({
      kind: "follow",
    });
  });
});

describe("routeSubmit", () => {
  it("presents a refusal in place", () => {
    const refusal = answer("http://x.test/e", { status: 409 });
    expect(routeSubmit(refusal, alone)).toEqual({ kind: "present", page: refusal.page });
  });

  it("answers an error with the status without a page", () => {
    expect(routeSubmit(answer("http://x.test/e", { status: 403, page: null }), alone)).toEqual({
      kind: "error",
      status: 403,
    });
  });

  it("follows a redirect to a page outside the layout", () => {
    expect(
      routeSubmit(answer("http://x.test/export", { redirected: true, page: null }), alone),
    ).toEqual({ kind: "navigate", url: new URL("http://x.test/export"), messages: [] });
  });

  it("presents a redirect to a form page, such as login", () => {
    const login = answer("http://x.test/login/?next=/e", { redirected: true });
    expect(routeSubmit(login, alone)).toEqual({ kind: "present", page: login.page });
  });

  it("swaps on a redirect to the host", () => {
    const host = answer(HOST, { redirected: true, page: page(true) });
    expect(routeSubmit(host, alone)).toEqual({ kind: "swap", page: host.page });
  });

  it("navigates on a redirect to another read-only page", () => {
    const url = "http://x.test/games/1";
    expect(
      routeSubmit(answer(url, { redirected: true, page: page(true, SAVED) }), alone),
    ).toEqual({ kind: "navigate", url: new URL(url), messages: SAVED });
  });

  it("closes only the top dialog when nested", () => {
    expect(
      routeSubmit(
        answer("http://x.test/games/1", { redirected: true, page: page(true, SAVED) }),
        nested,
      ),
    ).toEqual({ kind: "closeTop", messages: SAVED });
    expect(
      routeSubmit(answer(HOST, { redirected: true, page: page(true) }), nested),
    ).toEqual({ kind: "closeTop", messages: [] });
  });
});
