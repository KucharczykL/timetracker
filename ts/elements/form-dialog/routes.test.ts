// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import type { Answer, AnswerPage } from "./answer.js";
import { routeOpen, routeSubmit } from "./routes.js";

const HOST = "http://x.test/device/list";

function page(readOnly: boolean): AnswerPage {
  return {
    content: document.createDocumentFragment(),
    title: "",
    readOnly,
    messages: [],
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

describe("routeOpen", () => {
  it("toasts a redirect back to the host", () => {
    expect(routeOpen(answer(`${HOST}#x`, { redirected: true }), alone)).toEqual({
      kind: "toast",
    });
  });

  it("navigates to a read-only page elsewhere", () => {
    const route = routeOpen(
      answer("http://x.test/games", { redirected: true, page: page(true) }),
      alone,
    );
    expect(route).toEqual({ kind: "navigate", url: new URL("http://x.test/games") });
  });

  it("presents a form page", () => {
    expect(routeOpen(answer("http://x.test/device/1/edit"), alone)).toEqual({
      kind: "present",
    });
  });

  it("follows the link without a page", () => {
    expect(routeOpen(answer("http://x.test/x", { status: 404, page: null }), alone)).toEqual({
      kind: "follow",
    });
  });
});

describe("routeSubmit", () => {
  it("presents a refusal in place", () => {
    expect(routeSubmit(answer("http://x.test/e", { status: 409 }), alone)).toEqual({
      kind: "present",
    });
  });

  it("answers an error without a page", () => {
    expect(routeSubmit(answer("http://x.test/e", { status: 404, page: null }), alone)).toEqual({
      kind: "error",
    });
  });

  it("presents a redirect to a form page, such as login", () => {
    expect(
      routeSubmit(answer("http://x.test/login/?next=/e", { redirected: true }), alone),
    ).toEqual({ kind: "present" });
  });

  it("swaps on a redirect to the host", () => {
    expect(
      routeSubmit(answer(HOST, { redirected: true, page: page(true) }), alone),
    ).toEqual({ kind: "swap" });
  });

  it("navigates on a redirect to another read-only page", () => {
    const url = "http://x.test/games/1";
    expect(routeSubmit(answer(url, { redirected: true, page: page(true) }), alone)).toEqual({
      kind: "navigate",
      url: new URL(url),
    });
  });

  it("closes only the top dialog when nested", () => {
    expect(
      routeSubmit(answer("http://x.test/games/1", { redirected: true, page: page(true) }), nested),
    ).toEqual({ kind: "closeTop" });
    expect(
      routeSubmit(answer(HOST, { redirected: true, page: page(true) }), nested),
    ).toEqual({ kind: "closeTop" });
  });
});
