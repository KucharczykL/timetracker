// @vitest-environment node
import { describe, expect, it } from "vitest";
import { coarsestPrefix, decadeStart, temporalCodec } from "./temporal-codec.js";

describe("coarsestPrefix", () => {
  it("states nothing when no year is filled", () => {
    expect(coarsestPrefix({ year: "", month: "06", day: "22" })).toBe("");
  });

  it("states a year alone", () => {
    expect(coarsestPrefix({ year: "1984", month: "", day: "" })).toBe("1984");
  });

  it("stops at the first part nobody filled", () => {
    expect(coarsestPrefix({ year: "1984", month: "", day: "22" })).toBe("1984");
  });

  it("states a whole day", () => {
    expect(coarsestPrefix({ year: "1984", month: "06", day: "22" })).toBe("1984-06-22");
  });
});

describe("temporalCodec", () => {
  it("encodes a partial date the whole-day codec would drop", () => {
    expect(temporalCodec.encode({ year: "1984", month: "06", day: "" }, false)).toBe(
      "1984-06",
    );
  });

  it("round-trips every precision", () => {
    for (const wire of ["", "1984", "1984-06", "1984-06-22"]) {
      expect(temporalCodec.encode(temporalCodec.decode(wire), false)).toBe(wire);
    }
  });

  it("decodes missing parts as empty", () => {
    expect(temporalCodec.decode("1984")).toEqual({ year: "1984", month: "", day: "" });
  });
});

describe("decadeStart", () => {
  it("snaps a year down to the ten it belongs to", () => {
    expect(decadeStart("1982")).toBe("1980");
    expect(decadeStart("1980")).toBe("1980");
    expect(decadeStart("1989")).toBe("1980");
  });

  it("states nothing for text that is not a year", () => {
    expect(decadeStart("")).toBe("");
    expect(decadeStart("nineteen")).toBe("");
  });
});
