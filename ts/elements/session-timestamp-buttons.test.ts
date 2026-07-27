// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

const nowInPresentationZone = vi.hoisted(() => vi.fn<() => string | null>());

vi.mock("../date-time-presentation.js", () => ({ nowInPresentationZone }));

import "./session-timestamp-buttons.js";

function mount(targets: string[]): void {
  const fields = targets
    .map((name) => `<input id="id_${name}" name="${name}" type="datetime-local">`)
    .join("");
  document.body.innerHTML = `
    ${fields}
    <session-timestamp-buttons>
      <button data-target="timestamp_start" data-type="now"></button>
      <button data-target="timestamp_end" data-type="now"></button>
      <button data-target="timestamp_start" data-type="copy"></button>
    </session-timestamp-buttons>`;
}

function click(target: string, type: string): void {
  document.querySelector<HTMLButtonElement>(
    `[data-target="${target}"][data-type="${type}"]`,
  )!.click();
}

function field(name: string): HTMLInputElement {
  return document.querySelector<HTMLInputElement>(`#id_${name}`)!;
}

describe("session-timestamp-buttons", () => {
  beforeEach(() => {
    nowInPresentationZone.mockReset();
  });

  it("sets the field to the account zone's wall clock", () => {
    nowInPresentationZone.mockReturnValue("2026-07-27T08:34");
    mount(["timestamp_start", "timestamp_end"]);

    click("timestamp_start", "now");

    expect(field("timestamp_start").value).toBe("2026-07-27T08:34");
  });

  it("falls back to the browser clock when the contract is unusable", () => {
    nowInPresentationZone.mockReturnValue(null);
    mount(["timestamp_start", "timestamp_end"]);

    click("timestamp_start", "now");

    expect(field("timestamp_start").value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  });

  it("keeps wiring the remaining buttons when one target is missing", () => {
    nowInPresentationZone.mockReturnValue("2026-07-27T08:34");
    mount(["timestamp_end"]);

    click("timestamp_end", "now");

    expect(field("timestamp_end").value).toBe("2026-07-27T08:34");
  });

  it("copies a value to the opposite timestamp", () => {
    nowInPresentationZone.mockReturnValue("2026-07-27T08:34");
    mount(["timestamp_start", "timestamp_end"]);

    click("timestamp_start", "now");
    click("timestamp_start", "copy");

    expect(field("timestamp_end").value).toBe("2026-07-27T08:34");
  });
});
