import { defineConfig } from "vitest/config";

// Vitest/Vite resolves `./foo.js` import specifiers to the sibling `foo.ts`,
// so the module's NodeNext-style `.js` imports work without a compile step.
//
// The global environment stays `node` so the pure-function suites run fast; the
// few DOM/custom-element tests opt into jsdom per-file via `// @vitest-environment
// jsdom` (e.g. ts/elements/filter-group.test.ts).
export default defineConfig({
  test: {
    include: ["ts/**/*.test.ts"],
    environment: "node",
  },
});
