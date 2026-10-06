// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "../../client-errors.js";
import { normalizedUrl, readAnswer, sameUrl } from "./answer.js";

afterEach(() => vi.restoreAllMocks());

const FETCHED = new URL("http://x.test/device/add");

function jsonResponse(body: unknown, status = 200, url = FETCHED.href): Response {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
  Object.defineProperty(response, "url", { value: url });
  return response;
}

function htmlResponse(body: string, status: number): Response {
  return new Response(body, { status, headers: { "content-type": "text/html" } });
}

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
  it("reads a page at the fetched URL", async () => {
    const answer = await readAnswer(
      jsonResponse(
        {
          kind: "page",
          title: "Add device",
          width: "wide",
          html: '<h1>Add device</h1><form><input name="name"></form>',
          modules: ["/static/js/dist/elements/drop-down.js"],
          messages: [{ message: "Refused", type: "error" }],
        },
        409,
      ),
      FETCHED,
    );
    if (answer.kind !== "page") throw new Error(answer.kind);
    expect(answer.url.href).toBe(FETCHED.href);
    expect(answer.page.title).toBe("Add device");
    expect(answer.page.width).toBe("wide");
    expect(answer.page.content.querySelector("input")?.name).toBe("name");
    expect(answer.page.modules).toEqual(["http://x.test/static/js/dist/elements/drop-down.js"]);
    expect(answer.page.messages).toEqual([{ message: "Refused", type: "error" }]);
  });

  it("keeps leading templates and data scripts in place", async () => {
    const html =
      '<script type="application/json" id="props">{}</script><template id="row"><p>row</p></template><form></form>';
    const answer = await readAnswer(
      jsonResponse({ kind: "page", title: "", width: "form", html, modules: [], messages: [] }),
      FETCHED,
    );
    if (answer.kind !== "page") throw new Error(answer.kind);
    const tags = Array.from(answer.page.content.children, (child) => child.tagName);
    expect(tags).toEqual(["SCRIPT", "TEMPLATE", "FORM"]);
  });

  it("drops and reports a runnable script", async () => {
    const report = vi.spyOn(clientErrors, "reportClientError").mockReturnValue("id");
    const answer = await readAnswer(
      jsonResponse({
        kind: "page",
        title: "",
        width: "form",
        html: "<form></form><script>window.ran = true</script>",
        modules: [],
        messages: [],
      }),
      FETCHED,
    );
    if (answer.kind !== "page") throw new Error(answer.kind);
    expect(answer.page.content.querySelector("script")).toBeNull();
    expect(report).toHaveBeenCalledOnce();
  });

  it("refuses a width it does not know, naming it", async () => {
    const report = vi.spyOn(clientErrors, "reportClientError").mockReturnValue("id");
    const answer = await readAnswer(
      jsonResponse({ kind: "page", title: "", width: "huge", html: "", modules: [], messages: [] }),
      FETCHED,
    );
    expect(answer.kind).toBe("none");
    expect(report).toHaveBeenCalledWith(
      "form-dialog[answer]",
      'page answer with an unknown width: "huge"',
      { toast: false },
    );
  });

  it("reads done and continue", async () => {
    expect(
      await readAnswer(
        jsonResponse({ kind: "done", url: "http://x.test/devices", messages: [{ message: "Saved" }] }),
        FETCHED,
      ),
    ).toEqual({
      kind: "done",
      url: new URL("http://x.test/devices"),
      messages: [{ message: "Saved" }],
    });
    expect(
      await readAnswer(jsonResponse({ kind: "continue", url: "http://x.test/login/" }), FETCHED),
    ).toEqual({ kind: "continue", url: new URL("http://x.test/login/") });
  });

  it("reads created with its option", async () => {
    const option = { value: "1", label: "Outer Wilds", data: { platform: "" } };
    expect(
      await readAnswer(
        jsonResponse({ kind: "created", url: "http://x.test/games", messages: [], option }),
        FETCHED,
      ),
    ).toEqual({ kind: "created", url: new URL("http://x.test/games"), messages: [], option });
  });

  it("reads created with an unreadable option as done", async () => {
    vi.spyOn(clientErrors, "reportClientError").mockReturnValue("id");
    for (const option of [
      { value: 1, label: "", data: {} },
      { value: "1", label: "", data: { a: 1 } },
      null,
    ]) {
      expect(
        await readAnswer(
          jsonResponse({ kind: "created", url: "http://x.test/games", messages: [], option }),
          FETCHED,
        ),
      ).toEqual({ kind: "done", url: new URL("http://x.test/games"), messages: [] });
    }
    expect(clientErrors.reportClientError).toHaveBeenCalledTimes(3);
  });

  it("reads anything else as no kind", async () => {
    vi.spyOn(clientErrors, "reportClientError").mockReturnValue("id");
    for (const response of [
      htmlResponse("<h1>Forbidden</h1>", 403),
      htmlResponse("Bad gateway", 502),
      jsonResponse({ kind: "created" }),
      jsonResponse({ kind: "unknown" }),
      jsonResponse({ kind: "done", url: 3, messages: [] }),
      jsonResponse({ detail: "Not found" }, 404),
    ]) {
      expect(await readAnswer(response, FETCHED)).toEqual({
        kind: "none",
        status: response.status,
      });
    }
  });
});
