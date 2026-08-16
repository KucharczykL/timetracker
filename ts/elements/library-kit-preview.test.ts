// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./library-kit-preview.js";

beforeEach(() => {
  document.body.innerHTML = "";
  window.toast = vi.fn();
  window.removeToast = vi.fn();
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

it("renders static conversion toast appearances without conversion work", () => {
  document.body.innerHTML = `
    <library-kit-preview>
      <button data-preview-conversion-toast="running">Running</button>
      <button data-preview-conversion-toast="failed">Failed</button>
      <button data-preview-conversion-toast="complete">Complete</button>
    </library-kit-preview>`;

  const fetchSpy = vi.spyOn(globalThis, "fetch");
  const buttons = Array.from(
    document.querySelectorAll<HTMLButtonElement>("[data-preview-conversion-toast]"),
  );
  buttons[0].click();
  expect(window.toast).toHaveBeenCalledWith(
    "Prices are being converted. Totals will update when conversion is complete.",
    "info",
    { id: "library-kit-preview:conversion", duration: null },
  );
  buttons[1].click();
  expect(window.toast).toHaveBeenCalledWith(
    "Prices couldn't be converted. Existing totals are still available. We'll retry automatically.",
    "error",
    { id: "library-kit-preview:conversion", duration: null },
  );
  buttons[2].click();
  expect(window.removeToast).toHaveBeenCalledWith("library-kit-preview:conversion");
  expect(window.toast).toHaveBeenCalledWith(
    "Prices converted. Totals are now up to date.",
    "success",
  );

  const host = document.querySelector<HTMLElement>("library-kit-preview")!;
  host.remove();
  document.body.append(host);
  vi.mocked(window.toast).mockClear();
  host
    .querySelector<HTMLButtonElement>(
      '[data-preview-conversion-toast="running"]',
    )!
    .click();
  expect(window.toast).toHaveBeenCalledTimes(1);
  expect(fetchSpy).not.toHaveBeenCalled();
});
