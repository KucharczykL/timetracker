/**
 * Cross-language contract artifact for the behavioral filter tokens (#152).
 *
 * Writes filter-tokens.canonical.json = the actual token arrays this module
 * exports. `tests/test_filter_tokens_contract.py` reads it and asserts every
 * token is a real `common.criteria.Modifier`, so a renamed/removed Python
 * modifier fails CI instead of orphaning a TS literal (the #141 failure mode).
 * Mirrors how serializer.test.ts emits fixtures.canonical.json.
 */
import { describe, it, expect } from "vitest";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  PRESENCE_MODIFIERS,
  RANGE_MODIFIERS,
  isPresenceModifier,
  isRangeModifier,
} from "./filter-tokens.js";

describe("filter behavioral tokens", () => {
  it("presence/range membership helpers reflect their token sets", () => {
    // Pin every token individually so accidentally dropping one (e.g. NOT_BETWEEN,
    // which no e2e exercises) fails here rather than silently regressing the
    // value2 read / value-less-criterion behavior keyed on it.
    expect(isPresenceModifier("IS_NULL")).toBe(true);
    expect(isPresenceModifier("NOT_NULL")).toBe(true);
    expect(isPresenceModifier("EQUALS")).toBe(false);
    expect(isRangeModifier("BETWEEN")).toBe(true);
    expect(isRangeModifier("NOT_BETWEEN")).toBe(true);
    expect(isRangeModifier("EQUALS")).toBe(false);
  });

  it("writes the canonical artifact for the Python contract", () => {
    const tokens = {
      PRESENCE_MODIFIERS: [...PRESENCE_MODIFIERS],
      RANGE_MODIFIERS: [...RANGE_MODIFIERS],
    };
    const canonicalPath = fileURLToPath(
      new URL("./filter-tokens.canonical.json", import.meta.url),
    );
    writeFileSync(canonicalPath, JSON.stringify(tokens, null, 2));
    expect(tokens.PRESENCE_MODIFIERS.length).toBeGreaterThan(0);
    expect(tokens.RANGE_MODIFIERS.length).toBeGreaterThan(0);
  });
});
