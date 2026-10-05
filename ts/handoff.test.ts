// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "./client-errors.js";
import {
  handOffMessages,
  handOffOpener,
  takeHandedOffMessages,
  takeHandedOffOpener,
} from "./handoff.js";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

function reported(): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id");
}

describe("message hand-off", () => {
  it("returns the handed messages once", () => {
    handOffMessages([{ message: "Saved", type: "success" }]);
    expect(takeHandedOffMessages()).toEqual([{ message: "Saved", type: "success" }]);
    expect(takeHandedOffMessages()).toEqual([]);
  });

  it("appends to waiting messages", () => {
    handOffMessages([{ message: "One" }]);
    handOffMessages([{ message: "Two" }]);
    expect(takeHandedOffMessages()).toEqual([{ message: "One" }, { message: "Two" }]);
  });

  it("writes nothing for no messages", () => {
    handOffMessages([]);
    expect(sessionStorage.length).toBe(0);
  });

  it("reaches whatever page loads next", () => {
    handOffMessages([{ message: "Saved" }]);
    history.replaceState(null, "", "/elsewhere?page=2");
    expect(takeHandedOffMessages()).toEqual([{ message: "Saved" }]);
  });

  it("drops messages that waited too long", () => {
    const report = reported();
    vi.useFakeTimers();
    handOffMessages([{ message: "Saved" }]);
    vi.advanceTimersByTime(61_000);
    expect(takeHandedOffMessages()).toEqual([]);
    expect(report).toHaveBeenCalledOnce();
  });

  it("reports storage that throws", () => {
    const report = reported();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    handOffMessages([{ message: "Saved" }]);
    expect(report).toHaveBeenCalledWith("handoff", "quota", { toast: false });
  });

  it("reports and clears an unreadable entry", () => {
    const report = reported();
    sessionStorage.setItem("handoff:messages", "{");
    expect(takeHandedOffMessages()).toEqual([]);
    expect(report).toHaveBeenCalledOnce();
    expect(sessionStorage.length).toBe(0);
  });
});

describe("opener hand-off", () => {
  it("returns the opener once, apart from the messages", () => {
    handOffMessages([{ message: "Saved" }]);
    handOffOpener({ id: "row-menu", href: "/device/1/edit" });
    expect(takeHandedOffOpener()).toEqual({ id: "row-menu", href: "/device/1/edit" });
    expect(takeHandedOffOpener()).toBeNull();
    expect(takeHandedOffMessages()).toEqual([{ message: "Saved" }]);
  });

  it("drops an opener that waited too long", () => {
    reported();
    vi.useFakeTimers();
    handOffOpener({ id: null, href: "/a" });
    vi.advanceTimersByTime(61_000);
    expect(takeHandedOffOpener()).toBeNull();
  });

  it("refuses a malformed opener", () => {
    const report = reported();
    sessionStorage.setItem("handoff:opener", JSON.stringify({ at: Date.now(), value: { id: 3 } }));
    expect(takeHandedOffOpener()).toBeNull();
    expect(report).toHaveBeenCalledOnce();
  });
});
