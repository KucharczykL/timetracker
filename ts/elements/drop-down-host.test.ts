// @vitest-environment jsdom
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Host callers import it; page order is unreliable.

const SOURCE_ROOT = "ts";
const HOST_LOOKUP = /closest(<[^>]*>)?\(\s*"drop-down"\s*\)/;
const HOST_IMPORT = /^import\s+(?:[^"]*\sfrom\s+)?"[^"]*\/drop-down\.js";/m;
const RELATIVE_IMPORT = /^import\s+(?:[^"]*from\s+)?"\.\/([^"]+)\.js";/gm;

function sourceModules(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "generated" ? [] : sourceModules(path);
    return entry.name.endsWith(".ts") && !entry.name.endsWith(".test.ts") ? [path] : [];
  });
}

//: drop-down.ts's own imports; importing back cycles.
function dropdownOwnModules(): Set<string> {
  const source = readFileSync(join(SOURCE_ROOT, "elements", "drop-down.ts"), "utf8");
  const own = new Set([join(SOURCE_ROOT, "elements", "drop-down.ts")]);
  for (const match of source.matchAll(RELATIVE_IMPORT)) {
    own.add(join(SOURCE_ROOT, "elements", `${match[1]}.ts`));
  }
  return own;
}

describe("<drop-down> host dependency", () => {
  it("search-select defines its host before itself", async () => {
    await import("./search-select.js");
    expect(customElements.get("drop-down")).toBeDefined();
  });

  it("every module that looks up a host imports it", () => {
    const own = dropdownOwnModules();
    const missing = sourceModules(SOURCE_ROOT).filter((path) => {
      if (own.has(path)) return false;
      const source = readFileSync(path, "utf8");
      return HOST_LOOKUP.test(source) && !HOST_IMPORT.test(source);
    });
    expect(missing).toEqual([]);
  });
});
