import { defineConfig } from "vitest/config";

// Vitest/Vite resolves `./foo.js` import specifiers to the sibling `foo.ts`,
// so the module's NodeNext-style `.js` imports work without a compile step.
export default defineConfig({
  test: {
    include: ["ts/**/*.test.ts"],
    environment: "node",
  },
});
