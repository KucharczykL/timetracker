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
  expect(fetchStub).toHaveBeenCalledWith(
    window.location.href,
    expect.objectContaining({ headers: { Accept: "text/html" } }),
  );
});

it("ignores other events", async () => {
  document.body.dispatchEvent(new CustomEvent("device-changed"));
  await Promise.resolve();
  expect(fetchStub).not.toHaveBeenCalled();
});

it("keeps its children and toasts when the answer fails", async () => {
  const toast = vi.fn();
  vi.stubGlobal("toast", toast);
  fetchStub.mockResolvedValue({ ok: false, status: 500, text: () => Promise.resolve("") });
  const section = document.getElementById("history-container")!;

  document.body.dispatchEvent(new CustomEvent("status-changed"));

  await vi.waitFor(() => expect(toast).toHaveBeenCalledOnce());
  expect(toast.mock.calls[0][1]).toBe("error");
  expect(section.querySelector("h1")?.textContent).toBe("History");
});

it("treats a redirected answer as a failure", async () => {
  const toast = vi.fn();
  vi.stubGlobal("toast", toast);
  fetchStub.mockResolvedValue({
    ok: true,
    redirected: true,
    url: "/login/",
    text: () => Promise.resolve(answer),
  });
  const section = document.getElementById("history-container")!;

  document.body.dispatchEvent(new CustomEvent("status-changed"));

  await vi.waitFor(() => expect(toast).toHaveBeenCalledOnce());
  expect(section.querySelectorAll("li")).toHaveLength(0);
});

it("lets only the latest of two refreshes land", async () => {
  const stale = answer.replace("Changed status", "Stale");
  let releaseFirst: (value: unknown) => void = () => {};
  fetchStub
    .mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise((resolve, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
          releaseFirst = resolve;
        }),
    )
    .mockResolvedValueOnce({ ok: true, text: () => Promise.resolve(answer) });
  const toast = vi.fn();
  vi.stubGlobal("toast", toast);
  const section = document.getElementById("history-container")!;

  document.body.dispatchEvent(new CustomEvent("status-changed"));
  document.body.dispatchEvent(new CustomEvent("status-changed"));
  releaseFirst({ ok: true, text: () => Promise.resolve(stale) });

  await vi.waitFor(() => expect(section.textContent).toContain("Changed status"));
  expect(section.textContent).not.toContain("Stale");
  expect(toast).not.toHaveBeenCalled();
});
