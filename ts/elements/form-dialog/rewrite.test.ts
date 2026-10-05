// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import { importModules, prefixIds, resolveUrls } from "./rewrite.js";

function fragmentOf(html: string): DocumentFragment {
  const template = document.createElement("template");
  template.innerHTML = html;
  return template.content;
}

describe("prefixIds", () => {
  it("prefixes ids and their references", () => {
    const root = fragmentOf(`
      <label for="name">Name</label><input id="name" aria-describedby="name-help other">
      <p id="name-help">Help</p><a href="#name-help">Skip</a><a href="/x">Out</a>`);
    prefixIds(root, "d1-");
    expect(root.querySelector("label")!.getAttribute("for")).toBe("d1-name");
    expect(root.querySelector("input")!.id).toBe("d1-name");
    expect(root.querySelector("input")!.getAttribute("aria-describedby")).toBe(
      "d1-name-help other",
    );
    expect(root.querySelector("a")!.getAttribute("href")).toBe("#d1-name-help");
    expect(root.querySelectorAll("a")[1].getAttribute("href")).toBe("/x");
  });

  it("reaches into templates", () => {
    const root = fragmentOf(
      `<template><template><span id="row" aria-controls="row"></span></template></template>`,
    );
    prefixIds(root, "d2-");
    const outer = root.querySelector("template")!.content;
    const span = outer.querySelector("template")!.content.querySelector("span")!;
    expect(span.id).toBe("d2-row");
    expect(span.getAttribute("aria-controls")).toBe("d2-row");
  });

  it("includes the root element", () => {
    const root = document.createElement("dialog");
    root.id = "title-owner";
    root.setAttribute("aria-labelledby", "title-owner");
    prefixIds(root, "d3-");
    expect(root.id).toBe("d3-title-owner");
    expect(root.getAttribute("aria-labelledby")).toBe("d3-title-owner");
  });
});

describe("resolveUrls", () => {
  const base = new URL("http://x.test/device/1/edit?origin=%2Fdevice%2Flist");

  it("stamps a form without action with the answer's URL", () => {
    const root = fragmentOf(`<form method="post"></form><form action="other"></form>`);
    resolveUrls(root, base);
    const [own, other] = root.querySelectorAll("form");
    expect(own.getAttribute("action")).toBe(base.href);
    expect(other.getAttribute("action")).toBe("http://x.test/device/1/other");
  });

  it("resolves links and submitters but leaves fragments", () => {
    const root = fragmentOf(
      `<a href="../list">List</a><a href="#top">Top</a><button formaction="?step=2"></button>`,
    );
    resolveUrls(root, base);
    const [list, top] = root.querySelectorAll("a");
    expect(list.getAttribute("href")).toBe("http://x.test/device/list");
    expect(top.getAttribute("href")).toBe("#top");
    expect(root.querySelector("button")!.getAttribute("formaction")).toBe(
      "http://x.test/device/1/edit?step=2",
    );
  });
});

describe("importModules", () => {
  it("loads every module", async () => {
    const load = vi.fn(() => Promise.resolve({}));
    await importModules(["/a.js", "/b.js"], load);
    expect(load.mock.calls).toEqual([["/a.js"], ["/b.js"]]);
  });

  it("rejects when one fails", async () => {
    const load = vi.fn((url: string) =>
      url === "/b.js" ? Promise.reject(new Error("404")) : Promise.resolve({}),
    );
    await expect(importModules(["/a.js", "/b.js"], load)).rejects.toThrow("404");
  });
});
