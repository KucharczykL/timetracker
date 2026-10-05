// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "./client-errors.js";
import { handOffMessages, takeHandedOffMessages } from "./toast-handoff.js";

const HERE = () => location.href;

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

function reported(): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id");
}

describe("toast hand-off", () => {
  it("returns the handed messages once, on their page", () => {
    handOffMessages([{ message: "Saved", type: "success" }], HERE());
    expect(takeHandedOffMessages()).toEqual([{ message: "Saved", type: "success" }]);
    expect(takeHandedOffMessages()).toEqual([]);
  });

  it("appends to messages waiting for the same page", () => {
    handOffMessages([{ message: "One" }], HERE());
    handOffMessages([{ message: "Two" }], HERE());
    expect(takeHandedOffMessages()).toEqual([{ message: "One" }, { message: "Two" }]);
  });

  it("writes nothing for no messages", () => {
    handOffMessages([], HERE());
    expect(sessionStorage.length).toBe(0);
  });

  it("drops and reports messages meant for another page", () => {
    const report = reported();
    handOffMessages([{ message: "Saved" }], "http://elsewhere.test/games");
    expect(takeHandedOffMessages()).toEqual([]);
    expect(report).toHaveBeenCalledWith(
      "toast-handoff",
      "dropped messages for http://elsewhere.test/games",
      { toast: false },
    );
    expect(sessionStorage.length).toBe(0);
  });

  it("drops messages that waited too long", () => {
    const report = reported();
    vi.useFakeTimers();
    handOffMessages([{ message: "Saved" }], HERE());
    vi.advanceTimersByTime(61_000);
    expect(takeHandedOffMessages()).toEqual([]);
    expect(report).toHaveBeenCalledOnce();
  });

  it("reports storage that throws", () => {
    const report = reported();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    handOffMessages([{ message: "Saved" }], HERE());
    expect(report).toHaveBeenCalledWith("toast-handoff", "quota", { toast: false });
  });

  it("reports and clears an unreadable entry", () => {
    const report = reported();
    sessionStorage.setItem("toast-handoff", "{");
    expect(takeHandedOffMessages()).toEqual([]);
    expect(report).toHaveBeenCalledOnce();
    expect(sessionStorage.length).toBe(0);
  });
});
