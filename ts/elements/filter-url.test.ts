import { describe, expect, it } from "vitest";
import { applyUrl } from "./filter-url.js";

const LIST_URL = "/tracker/session/list";

describe("applyUrl", () => {
  it("returns the bare list URL for an empty filter and no sort", () => {
    expect(applyUrl(LIST_URL, {})).toBe(LIST_URL);
    expect(applyUrl(LIST_URL, {}, "")).toBe(LIST_URL);
  });

  it("emits ?filter= for a non-empty filter", () => {
    const filter = { name: { modifier: "INCLUDES", value: "x" } };
    expect(applyUrl(LIST_URL, filter)).toBe(
      LIST_URL + "?filter=" + encodeURIComponent(JSON.stringify(filter)),
    );
  });

  it("emits ?sort= alone when the filter is empty but a sort is present", () => {
    expect(applyUrl(LIST_URL, {}, "-playtime,name")).toBe(
      LIST_URL + "?sort=" + encodeURIComponent("-playtime,name"),
    );
  });

  it("joins filter and sort with & when both are present", () => {
    const filter = { name: { modifier: "INCLUDES", value: "x" } };
    expect(applyUrl(LIST_URL, filter, "-playtime")).toBe(
      LIST_URL +
        "?filter=" +
        encodeURIComponent(JSON.stringify(filter)) +
        "&sort=" +
        encodeURIComponent("-playtime"),
    );
  });
});
