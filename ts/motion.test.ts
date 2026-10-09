// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { holdLeave, motionDuration, settleEntry } from "./motion.js";

function setDuration(token: string, value: string): void {
  document.documentElement.style.setProperty(`--duration-${token}`, value);
}

function stubAnimations(element: Element, finished: Promise<unknown>): void {
  Object.defineProperty(element, "getAnimations", {
    configurable: true,
    value: () => [{ finished }],
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setDuration("fast-exit", "100ms");
  setDuration("reduced", "100ms");
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.removeAttribute("style");
  document.body.innerHTML = "";
});

describe("holdLeave", () => {
  it("finishes at once when getAnimations is missing", () => {
    const element = document.createElement("div");
    Object.defineProperty(element, "getAnimations", { value: undefined });
    const finish = vi.fn();
    holdLeave(element, "fast-exit", finish);
    expect(finish).toHaveBeenCalledTimes(1);
    expect(element.hasAttribute("data-motion")).toBe(false);
  });

  it("finishes at once when the duration is zero", () => {
    setDuration("fast-exit", "0ms");
    const element = document.createElement("div");
    stubAnimations(element, new Promise(() => {}));
    const finish = vi.fn();
    holdLeave(element, "fast-exit", finish);
    expect(finish).toHaveBeenCalledTimes(1);
  });

  it("stamps leaving while it waits", () => {
    const element = document.createElement("div");
    stubAnimations(element, new Promise(() => {}));
    const finish = vi.fn();
    holdLeave(element, "fast-exit", finish);
    expect(element.getAttribute("data-motion")).toBe("leaving");
    expect(finish).not.toHaveBeenCalled();
  });

  it("waits for a subtree animation to finish", async () => {
    const element = document.createElement("div");
    let resolve: () => void = () => {};
    const finished = new Promise<void>((done) => {
      resolve = done;
    });
    stubAnimations(element, finished);
    const finish = vi.fn();
    holdLeave(element, "fast-exit", finish);
    await vi.advanceTimersByTimeAsync(50);
    expect(finish).not.toHaveBeenCalled();
    resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(finish).toHaveBeenCalledTimes(1);
    expect(element.hasAttribute("data-motion")).toBe(false);
  });

  it("caps the wait at duration plus 100 ms", async () => {
    const element = document.createElement("div");
    stubAnimations(element, new Promise(() => {}));
    const finish = vi.fn();
    holdLeave(element, "fast-exit", finish);
    await vi.advanceTimersByTimeAsync(199);
    expect(finish).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(finish).toHaveBeenCalledTimes(1);
  });

  it("runs finish once when the animation and the cap both settle", async () => {
    const element = document.createElement("div");
    stubAnimations(element, Promise.resolve());
    const finish = vi.fn();
    holdLeave(element, "fast-exit", finish);
    await vi.advanceTimersByTimeAsync(500);
    expect(finish).toHaveBeenCalledTimes(1);
  });

  it("cancel stops finish and clears leaving", async () => {
    const element = document.createElement("div");
    stubAnimations(element, new Promise(() => {}));
    const finish = vi.fn();
    const cancel = holdLeave(element, "fast-exit", finish);
    cancel?.();
    expect(element.hasAttribute("data-motion")).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(finish).not.toHaveBeenCalled();
  });

  it("cancel leaves a different motion stamp alone", () => {
    const element = document.createElement("div");
    stubAnimations(element, new Promise(() => {}));
    const cancel = holdLeave(element, "fast-exit", () => {});
    element.setAttribute("data-motion", "entering");
    cancel?.();
    expect(element.getAttribute("data-motion")).toBe("entering");
  });
});

describe("settleEntry", () => {
  it("removes entering", () => {
    const element = document.createElement("div");
    element.setAttribute("data-motion", "entering");
    settleEntry(element);
    expect(element.hasAttribute("data-motion")).toBe(false);
  });

  it("keeps leaving", () => {
    const element = document.createElement("div");
    element.setAttribute("data-motion", "leaving");
    settleEntry(element);
    expect(element.getAttribute("data-motion")).toBe("leaving");
  });
});

describe("motionDuration", () => {
  it("parses milliseconds", () => {
    setDuration("medium", "240ms");
    expect(motionDuration("medium")).toBe(240);
  });

  it("parses seconds", () => {
    setDuration("slow", "0.36s");
    expect(motionDuration("slow")).toBe(360);
  });

  it("returns zero when the token is empty", () => {
    expect(motionDuration("slow-exit")).toBe(0);
  });

  it("returns the reduced duration under reduced motion", () => {
    setDuration("medium", "240ms");
    setDuration("reduced", "100ms");
    window.matchMedia = ((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
    })) as unknown as typeof window.matchMedia;
    expect(motionDuration("medium")).toBe(100);
    expect(motionDuration("reduced")).toBe(100);
    delete (window as { matchMedia?: unknown }).matchMedia;
  });
});
