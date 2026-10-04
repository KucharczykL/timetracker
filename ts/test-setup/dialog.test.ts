// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { isDialogModal } from "./dialog.js";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

function mountDialog(): HTMLDialogElement {
  const dialog = document.createElement("dialog");
  document.body.append(dialog);
  return dialog;
}

describe("dialog shim", () => {
  it("opens as a modal and closes with a queued close event", () => {
    vi.useFakeTimers();
    const dialog = mountDialog();
    const closed = vi.fn();
    dialog.addEventListener("close", closed);
    dialog.showModal();
    expect(dialog.open).toBe(true);
    expect(isDialogModal(dialog)).toBe(true);
    expect(dialog.matches(":modal")).toBe(true);
    dialog.close();
    expect(dialog.open).toBe(false);
    expect(isDialogModal(dialog)).toBe(false);
    expect(closed).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it("returns on a dialog already open as a modal", () => {
    const dialog = mountDialog();
    dialog.showModal();
    expect(() => dialog.showModal()).not.toThrow();
    expect(isDialogModal(dialog)).toBe(true);
  });

  it("refuses a dialog open without a modal", () => {
    const dialog = mountDialog();
    dialog.setAttribute("open", "");
    expect(() => dialog.showModal()).toThrow(
      expect.objectContaining({ name: "InvalidStateError" }),
    );
  });

  it("refuses a disconnected dialog", () => {
    const dialog = document.createElement("dialog");
    expect(() => dialog.showModal()).toThrow(
      expect.objectContaining({ name: "InvalidStateError" }),
    );
  });

  it("fires nothing when closing a closed dialog", () => {
    vi.useFakeTimers();
    const dialog = mountDialog();
    const closed = vi.fn();
    dialog.addEventListener("close", closed);
    dialog.close();
    vi.runAllTimers();
    expect(closed).not.toHaveBeenCalled();
  });

  it("is no longer modal once removed", () => {
    const dialog = mountDialog();
    dialog.showModal();
    dialog.remove();
    expect(isDialogModal(dialog)).toBe(false);
  });
});
