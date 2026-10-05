// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import * as clientErrors from "./client-errors.js";
import { handOffMessages, takeHandedOffMessages } from "./toast-handoff.js";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("toast hand-off", () => {
  it("returns the handed messages once", () => {
    handOffMessages([{ message: "Saved", type: "success" }]);
    expect(takeHandedOffMessages()).toEqual([{ message: "Saved", type: "success" }]);
    expect(takeHandedOffMessages()).toEqual([]);
  });

  it("writes nothing for no messages", () => {
    handOffMessages([]);
    expect(sessionStorage.length).toBe(0);
  });

  it("reports storage that throws", () => {
    const reported = vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    handOffMessages([{ message: "Saved" }]);
    expect(reported).toHaveBeenCalledWith("toast-handoff", "quota", { toast: false });
  });

  it("reports an unreadable entry and clears nothing else", () => {
    const reported = vi.spyOn(clientErrors, "reportClientError").mockImplementation(() => "id");
    sessionStorage.setItem("toast-handoff", "{");
    expect(takeHandedOffMessages()).toEqual([]);
    expect(reported).toHaveBeenCalledOnce();
  });
});
