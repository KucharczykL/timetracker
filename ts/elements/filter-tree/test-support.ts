import { expect } from "vitest";

// A node carries a per-construction `id` (node-id.ts) that two independently-built
// trees never share, so a structural `toEqual` would spuriously fail on it. Register
// a vitest equality tester that compares two nodes ignoring `id` (recursing on the
// rest — children re-trigger the tester). `id` is only meaningful to <filter-group>'s
// DOM reconciliation, never to tree-shape assertions. Call once per test file.
function isNode(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value) && "kind" in value;
}

export function ignoreNodeIds(): void {
  expect.addEqualityTesters([
    function (a, b, customTesters) {
      if (!isNode(a) || !isNode(b)) return undefined; // defer to default equality
      // Compare every key except `id`, recursing per-value through this.equals so
      // child nodes re-trigger the tester (and drop their own id). Comparing the
      // sub-values — never the node objects themselves — avoids infinite recursion,
      // and works whether or not either side carries an id (expected literals omit it).
      const keys = new Set([...Object.keys(a), ...Object.keys(b)].filter((key) => key !== "id"));
      for (const key of keys) {
        if (!this.equals(a[key], b[key], customTesters)) return false;
      }
      return true;
    },
  ]);
}
