import { describe, expect, it } from "vitest";

import { selectPayloadValue } from "./select.js";

describe("selectPayloadValue", () => {
  it("maps an empty value to null when empty_is_null is enabled", () => {
    expect(selectPayloadValue("", true)).toBeNull();
  });

  it("keeps a UUID string unchanged when empty_is_null is enabled", () => {
    const value = "018f5e66-e800-7000-8000-000000000001";
    expect(selectPayloadValue(value, true)).toBe(value);
  });

  it("passes the empty string through for an ordinary selector", () => {
    expect(selectPayloadValue("", false)).toBe("");
  });

  it("passes strings through untouched for an ordinary selector", () => {
    expect(selectPayloadValue("f", false)).toBe("f");
  });
});
