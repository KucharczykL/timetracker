import { describe, expect, it } from "vitest";

import { malformedNumericValue, selectPayloadValue } from "./select.js";

describe("selectPayloadValue", () => {
  it("maps an empty value to null in numeric mode (the clear entry)", () => {
    // Number("") === 0, so without the explicit branch the clear entry would
    // silently PATCH {device_id: 0}.
    expect(selectPayloadValue("", true)).toBeNull();
  });

  it("converts non-empty values to numbers in numeric mode", () => {
    expect(selectPayloadValue("5", true)).toBe(5);
  });

  it("passes the empty string through in non-numeric mode", () => {
    expect(selectPayloadValue("", false)).toBe("");
  });

  it("passes strings through untouched in non-numeric mode", () => {
    expect(selectPayloadValue("f", false)).toBe("f");
  });
});

describe("malformedNumericValue", () => {
  it("accepts the empty string (the clear entry, handled upstream)", () => {
    expect(malformedNumericValue("")).toBe(false);
  });

  it("accepts numeric strings", () => {
    expect(malformedNumericValue("5")).toBe(false);
  });

  it("rejects non-numeric strings", () => {
    expect(malformedNumericValue("abc")).toBe(true);
  });

  it("rejects whitespace-only values (Number(' ') === 0 would PATCH 0)", () => {
    expect(malformedNumericValue(" ")).toBe(true);
    expect(malformedNumericValue("\t\n")).toBe(true);
  });
});
