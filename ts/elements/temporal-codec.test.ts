// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decadeStart, temporalCodec } from "./temporal-codec.js";

describe("temporalCodec", () => {
  it("encodes a partial date the whole-day codec would drop", () => {
    expect(temporalCodec.encode({ year: "1984", month: "06", day: "" }, false)).toBe(
      "1984-06-",
    );
  });

  it("encodes a part typed before its coarser part", () => {
    expect(temporalCodec.encode({ year: "", month: "12", day: "01" }, false)).toBe(
      "-12-01",
    );
    expect(temporalCodec.encode({ year: "2024", month: "", day: "01" }, false)).toBe(
      "2024--01",
    );
  });

  it("encodes nothing typed as nothing", () => {
    expect(temporalCodec.encode({ year: "", month: "", day: "" }, false)).toBe("");
  });

  it("round-trips every shape", () => {
    for (const wire of ["", "1984--", "1984-06-", "1984-06-22", "-12-01", "2024--01"]) {
      expect(temporalCodec.encode(temporalCodec.decode(wire), false)).toBe(wire);
    }
  });

  it("gives every buffer state its own value", () => {
    // The rule the three cases above are examples of.
    const states = ["", "19", "1984"].flatMap((year) =>
      ["", "6", "06"].flatMap((month) =>
        ["", "2", "22"].map((day) => ({ year, month, day })),
      ),
    );
    const encoded = states.map((state) => temporalCodec.encode(state, false));

    expect(new Set(encoded).size).toBe(states.length);
  });

  it("decodes missing parts as empty", () => {
    expect(temporalCodec.decode("1984--")).toEqual({ year: "1984", month: "", day: "" });
    expect(temporalCodec.decode("")).toEqual({ year: "", month: "", day: "" });
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
