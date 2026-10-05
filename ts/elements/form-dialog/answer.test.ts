// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "../../client-errors.js";
import { normalizedUrl, readAnswer, sameUrl } from "./answer.js";

afterEach(() => vi.restoreAllMocks());

function htmlResponse(body: string, url: string, redirected = false, status = 200): Response {
  const response = new Response(body, {
    status,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
  Object.defineProperty(response, "url", { value: url });
  Object.defineProperty(response, "redirected", { value: redirected });
  return response;
}

const PAGE = `<!doctype html><html data-theme-mode="account" lang="en"><head>
  <title>Timetracker - Edit device</title>
  <script id="django-messages" type="application/json">[{"message":"Saved"}]</script>
  </head><body>
  <nav id="navbar"><a href="/">Home</a></nav>
  <div id="main-container" data-page-title="Edit device" data-read-only>
    <form><input name="name"></form>
    <script>window.ran = true</script>
    <script type="application/json" id="props">{}</script>
  </div>
  <script type="module" src="/static/js/dist/elements/drop-down.js"></script>
  </body></html>`;

describe("normalizedUrl", () => {
  it("ignores the hash and the order of the query", () => {
    expect(sameUrl("http://x.test/a?b=2&a=1#top", "http://x.test/a?a=1&b=2")).toBe(true);
    expect(sameUrl("http://x.test/a?a=1", "http://x.test/a?a=2")).toBe(false);
  });

  it("keeps a repeated key in value order", () => {
    expect(normalizedUrl("http://x.test/a?k=2&k=1")).toBe("http://x.test/a?k=1&k=2");
  });
});

describe("readAnswer", () => {
  it("reads the page's parts", async () => {
    const answer = await readAnswer(
      htmlResponse(PAGE, "http://x.test/device/1/edit", true),
      new URL("http://x.test/device/1/edit"),
    );
    expect(answer.redirected).toBe(true);
    const page = answer.page!;
    expect(page.title).toBe("Edit device");
    expect(page.readOnly).toBe(true);
    expect(page.messages).toEqual([{ message: "Saved" }]);
    expect(page.modules).toEqual(["http://x.test/static/js/dist/elements/drop-down.js"]);
    expect(page.documentTitle).toBe("Timetracker - Edit device");
    expect(page.htmlData).toEqual({ "data-theme-mode": "account" });
    expect(page.navbar?.querySelector("a")?.getAttribute("href")).toBe("/");
    expect(page.content.querySelector("form")).not.toBeNull();
  });

  it("drops runnable scripts but keeps data scripts", async () => {
    const answer = await readAnswer(htmlResponse(PAGE, "http://x.test/e"), new URL("http://x.test/e"));
    const scripts = answer.page!.content.querySelectorAll("script");
    expect(Array.from(scripts, (script) => script.id)).toEqual(["props"]);
  });

  it("reports dropped scripts and classic scripts it cannot load", async () => {
    const reported = vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id");
    const page = PAGE.replace("</body>", '<script src="/static/js/legacy.js"></script></body>');
    await readAnswer(htmlResponse(page, "http://x.test/e"), new URL("http://x.test/e"));
    const details = reported.mock.calls.map(([, detail]) => detail);
    expect(details).toContain("dropped 1 script(s) from page content");
    expect(details).toContain("classic script not loaded: http://x.test/static/js/legacy.js");
  });

  it("answers no page without the main container", async () => {
    const answer = await readAnswer(
      htmlResponse("<h1>Not Found</h1>", "http://x.test/gone", false, 404),
      new URL("http://x.test/gone"),
    );
    expect(answer.status).toBe(404);
    expect(answer.page).toBeNull();
  });

  it("answers no page for a body that is not HTML", async () => {
    const response = new Response("{}", { headers: { "content-type": "application/json" } });
    const answer = await readAnswer(response, new URL("http://x.test/api"));
    expect(answer.url.href).toBe("http://x.test/api");
    expect(answer.page).toBeNull();
  });

  it("reports unreadable messages", async () => {
    const reported = vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id");
    const broken = PAGE.replace('[{"message":"Saved"}]', "[");
    const answer = await readAnswer(htmlResponse(broken, "http://x.test/e"), new URL("http://x.test/e"));
    expect(answer.page!.messages).toEqual([]);
    expect(reported).toHaveBeenCalledWith(
      "form-dialog[answer]",
      expect.stringContaining("unreadable messages"),
      { toast: false },
    );
  });
});
