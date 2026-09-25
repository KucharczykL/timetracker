// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { sectionFrom } from "./refreshing-section.js";

const answer = `<!DOCTYPE html><html><body>
  <main>
    <refreshing-section id="history-container" event="status-changed">
      <h1>History</h1><ul><li>Changed status</li></ul>
    </refreshing-section>
  </main>
</body></html>`;

let fetchStub: ReturnType<typeof vi.fn>;

beforeEach(() => {
  document.body.innerHTML = `
    <refreshing-section id="history-container" event="status-changed">
      <h1>History</h1><ul></ul>
    </refreshing-section>`;
  fetchStub = vi.fn().mockResolvedValue({
    ok: true,
    text: () => Promise.resolve(answer),
  });
  vi.stubGlobal("fetch", fetchStub);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("finds the section's children in an answer by id", () => {
  const children = sectionFrom(answer, "history-container");
  expect(children?.map((node) => node.textContent).join("")).toContain(
    "Changed status",
  );
  expect(sectionFrom(answer, "no-such-section")).toBeNull();
});

it("reads the page again when its event reaches the body", async () => {
  const section = document.getElementById("history-container")!;
  expect(section.querySelectorAll("li")).toHaveLength(0);

  document.body.dispatchEvent(new CustomEvent("status-changed"));

  await vi.waitFor(() => expect(section.querySelectorAll("li")).toHaveLength(1));
  expect(fetchStub).toHaveBeenCalledWith(window.location.href, {
    headers: { Accept: "text/html" },
  });
});

it("ignores other events", async () => {
  document.body.dispatchEvent(new CustomEvent("device-changed"));
  await Promise.resolve();
  expect(fetchStub).not.toHaveBeenCalled();
});
