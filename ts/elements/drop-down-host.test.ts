// @vitest-environment jsdom
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

// Host callers import drop-down.js; page order varies.

const SOURCE_ROOT = "ts";
const HOST_LOOKUP = /\b(?:closest|querySelector)\s*(?:<[^>]*>)?\(\s*["']drop-down["']\s*\)/;
//: A bare import; type-only ones are erased.
const HOST_IMPORT = /^import\s+["'][^"']*\/drop-down\.js["'];/m;
const RELATIVE_IMPORT = /^import\s+(?:[^"']*\sfrom\s+)?["'](\.\.?\/[^"']+)\.js["'];/gm;
const KNOWN_CALLERS = [
  "date-calendar-core.ts",
  "search-field.ts",
  "search-select.ts",
  "section-nav.ts",
].map((name) => join(SOURCE_ROOT, "elements", name));

function sourceModules(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "generated" ? [] : sourceModules(path);
    return entry.name.endsWith(".ts") && !entry.name.endsWith(".test.ts") ? [path] : [];
  });
}

//: drop-down.ts and everything it imports; exempt, would cycle.
function dropdownOwnModules(): Set<string> {
  const own = new Set<string>();
  const pending = [join(SOURCE_ROOT, "elements", "drop-down.ts")];
  while (pending.length > 0) {
    const path = pending.pop()!;
    if (own.has(path)) continue;
    own.add(path);
    for (const match of readFileSync(path, "utf8").matchAll(RELATIVE_IMPORT)) {
      pending.push(join(dirname(path), `${match[1]}.ts`));
    }
  }
  return own;
}

function hostCallers(): string[] {
  const own = dropdownOwnModules();
  return sourceModules(SOURCE_ROOT).filter(
    (path) => !own.has(path) && HOST_LOOKUP.test(readFileSync(path, "utf8")),
  );
}

describe("<drop-down> host dependency", () => {
  it("search-select defines its host before itself", async () => {
    await import("./search-select.js");
    expect(customElements.get("drop-down")).toBeDefined();
  });

  it("finds every known host caller", () => {
    expect(hostCallers()).toEqual(expect.arrayContaining(KNOWN_CALLERS));
    expect(dropdownOwnModules()).toContain(
      join(SOURCE_ROOT, "elements", "behaviors", "inline-combobox.ts"),
    );
    expect(dropdownOwnModules()).toContain(join(SOURCE_ROOT, "elements", "modal-layer.ts"));
  });

  it("every host caller imports it bare", () => {
    const missing = hostCallers().filter(
      (path) => !HOST_IMPORT.test(readFileSync(path, "utf8")),
    );
    expect(missing).toEqual([]);
  });

  it("refuses a type-only or quoted-away import", () => {
    expect(HOST_IMPORT.test('import type { DropdownElement } from "./drop-down.js";')).toBe(false);
    expect(HOST_IMPORT.test('import { DropdownElement } from "./drop-down.js";')).toBe(false);
    expect(HOST_IMPORT.test("import './drop-down.js';")).toBe(true);
    expect(HOST_LOOKUP.test("element.closest('drop-down')")).toBe(true);
  });
});
