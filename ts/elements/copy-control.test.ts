// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./copy-control.js";

beforeEach(() => {
  document.body.innerHTML = "";
  window.toast = vi.fn();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("copies, announces success, and restores the original label after two seconds", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  document.body.innerHTML = `
    <copy-control value="full-value">
      <button data-copy-control aria-label="Copy Library ID">
        <span data-copy-label aria-live="polite" aria-atomic="true">Copy ID</span>
      </button>
    </copy-control>`;

  document.querySelector<HTMLButtonElement>("[data-copy-control]")!.click();
  await Promise.resolve();
  expect(writeText).toHaveBeenCalledWith("full-value");
  const label = document.querySelector("[data-copy-label]") as HTMLElement;
  expect(label.textContent).toBe("Copied!");
  expect(label.classList.contains("sr-only")).toBe(false);
  expect(window.toast).not.toHaveBeenCalled();
  vi.advanceTimersByTime(2_000);
  expect(label.textContent).toBe("Copy ID");
  expect(label.classList.contains("sr-only")).toBe(true);
});

it("keeps failure visible until a new attempt", async () => {
  const writeText = vi.fn().mockRejectedValueOnce(new Error("denied"));
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  document.body.innerHTML = `
    <copy-control value="full-value">
      <button data-copy-control>
        <span data-copy-label aria-live="polite">Copy</span>
      </button>
    </copy-control>`;

  const button = document.querySelector<HTMLButtonElement>("[data-copy-control]")!;
  button.click();
  await Promise.resolve();
  await Promise.resolve();
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Couldn't copy");
  vi.advanceTimersByTime(10_000);
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Couldn't copy");
  expect(window.toast).not.toHaveBeenCalled();

  writeText.mockResolvedValueOnce(undefined);
  button.click();
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Copy");
  await Promise.resolve();
  expect(document.querySelector("[data-copy-label]")?.textContent).toBe("Copied!");
});

it("restores the original label when disconnected during a reset delay", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  document.body.innerHTML = `
    <copy-control value="full-value">
      <button data-copy-control>
        <span data-copy-label aria-live="polite">Copy</span>
      </button>
    </copy-control>`;

  const control = document.querySelector<HTMLElement>("copy-control")!;
  control.querySelector<HTMLButtonElement>("[data-copy-control]")!.click();
  await Promise.resolve();
  expect(control.querySelector("[data-copy-label]")?.textContent).toBe("Copied!");

  control.remove();
  vi.advanceTimersByTime(2_000);
  document.body.append(control);
  expect(control.querySelector("[data-copy-label]")?.textContent).toBe("Copy");
});
