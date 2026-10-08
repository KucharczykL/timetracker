import { describe, expect, it } from "vitest";
import { durationBucketHint } from "./duration-bucket.js";

// Same table as duration_bucket_hint in common/components/filters.py.
describe("the duration bucket hint", () => {
  it.each([
    ["EQUALS", "0", "0 h up to 1 h"],
    ["EQUALS", "0.5", "0.5 h up to 1.5 h"],
    ["NOT_EQUALS", "1", "outside 1 h up to 2 h"],
    ["EQUALS", "", ""],
    ["EQUALS", "x", ""],
    ["GREATER_THAN", "1", ""],
    ["EQUALS", "1.0", "1 h up to 2 h"],
    ["EQUALS", " 1 ", "1 h up to 2 h"],
    ["EQUALS", "nan", ""],
    ["EQUALS", "inf", ""],
    ["EQUALS", "1e16", ""],
  ])("%s %j reads %j", (modifier, value, text) => {
    expect(durationBucketHint(modifier, value)).toBe(text);
  });
});
