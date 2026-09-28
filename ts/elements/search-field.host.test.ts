// @vitest-environment jsdom
import { expect, it } from "vitest";

// Own file: the registry outlives tests.
it("search-field defines its host before itself", async () => {
  await import("./search-field.js");
  expect(customElements.get("drop-down")).toBeDefined();
});
