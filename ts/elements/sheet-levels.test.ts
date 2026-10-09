// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearLevel, dropLevel, popLevel, pushLevel } from "./sheet-levels.js";

interface FakeAnimation {
  element: HTMLElement;
  frames: Keyframe[];
  options: KeyframeAnimationOptions;
  cancel: ReturnType<typeof vi.fn>;
  finished: Promise<void>;
  end: () => void;
}

let animations: FakeAnimation[];
let reducedMotion = false;

function sheet(): HTMLDialogElement {
  const dialog = document.createElement("dialog");
  dialog.setAttribute("data-dropdown-sheet", "");
  dialog.innerHTML = `<div data-sheet-panel><button data-sheet-back hidden type="button"><span data-sheet-back-label></span></button></div>`;
  document.body.append(dialog);
  return dialog;
}

function panelOf(dialog: HTMLDialogElement): HTMLElement {
  return dialog.querySelector<HTMLElement>("[data-sheet-panel]")!;
}

beforeEach(() => {
  animations = [];
  reducedMotion = false;
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: reducedMotion, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
  document.documentElement.style.setProperty("--duration-slow", "360ms");
  document.documentElement.style.setProperty("--duration-slow-exit", "240ms");
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true,
    value(this: HTMLElement, frames: Keyframe[], options: KeyframeAnimationOptions) {
      let end = (): void => {};
      const finished = new Promise<void>((resolve) => {
        end = resolve;
      });
      const animation = { element: this, frames, options, cancel: vi.fn(), finished, end };
      animations.push(animation);
      return animation;
    },
  });
});

afterEach(() => {
  document.body.replaceChildren();
  document.documentElement.removeAttribute("style");
  delete (HTMLElement.prototype as Partial<HTMLElement>).animate;
  vi.unstubAllGlobals();
});

async function settle(): Promise<void> {
  for (const animation of animations) animation.end();
  await Promise.resolve();
  await Promise.resolve();
}

describe("level slides", () => {
  it("hold their last frame until the level settles", () => {
    pushLevel(sheet(), { below: sheet(), belowTitle: "More filters" });
    expect(animations.map((animation) => animation.options.fill)).toEqual([
      "forwards",
      "forwards",
      "forwards",
    ]);
  });

  it("darken the sheet below, never fade it", () => {
    const below = sheet();
    pushLevel(sheet(), { below, belowTitle: "More filters" });
    const onBelow = animations.filter((animation) => animation.element === panelOf(below));
    const panelFrames = onBelow.filter((animation) => !animation.options.pseudoElement);
    const scrimFrames = onBelow.filter((animation) => animation.options.pseudoElement === "::after");
    for (const animation of panelFrames) {
      for (const frame of animation.frames) expect(frame).not.toHaveProperty("opacity");
    }
    expect(scrimFrames.map((animation) => animation.frames.map((frame) => frame.opacity))).toEqual([
      [0, 0.3],
    ]);
  });

  it("hide the sheet below before a push lets go of it", async () => {
    const below = sheet();
    pushLevel(sheet(), { below, belowTitle: "More filters" });
    await settle();
    expect(panelOf(below).style.visibility).toBe("hidden");
    for (const animation of animations) expect(animation.cancel).toHaveBeenCalled();
  });

  it("keep a popped level slid out until it is cleared", async () => {
    const level = sheet();
    const below = sheet();
    pushLevel(level, { below, belowTitle: "More filters" });
    await settle();
    animations = [];
    const done = vi.fn();
    popLevel(level, below, done);
    await settle();
    expect(done).toHaveBeenCalled();
    for (const animation of animations) expect(animation.cancel).not.toHaveBeenCalled();
    clearLevel(level);
    for (const animation of animations) expect(animation.cancel).toHaveBeenCalled();
  });

  it("keep the sheet below shown when a pop beats the push", async () => {
    const level = sheet();
    const below = sheet();
    pushLevel(level, { below, belowTitle: "More filters" });
    const done = vi.fn();
    popLevel(level, below, done);
    await settle();
    expect(panelOf(below).style.visibility).toBe("");
    expect(done).toHaveBeenCalled();
  });

  it("keep the sheet below shown when a clear beats the push", async () => {
    const level = sheet();
    const below = sheet();
    pushLevel(level, { below, belowTitle: "More filters" });
    clearLevel(level);
    await settle();
    expect(panelOf(below).style.visibility).toBe("");
  });

  it("fade a level over a still sheet under reduced motion", () => {
    reducedMotion = true;
    document.documentElement.style.setProperty("--duration-reduced", "100ms");
    const below = sheet();
    pushLevel(sheet(), { below, belowTitle: "More filters" });
    const moved = animations.filter((animation) =>
      animation.frames.some((frame) => "transform" in frame),
    );
    expect(moved).toEqual([]);
    const level = animations.find((animation) => animation.element !== panelOf(below))!;
    expect(level.frames.map((frame) => frame.opacity)).toEqual([0, 1]);
  });

  it("drop down when the whole chain closes", async () => {
    const level = sheet();
    pushLevel(level, { below: sheet(), belowTitle: "More filters" });
    await settle();
    animations = [];
    const done = vi.fn();
    dropLevel(level, done);
    expect(animations.map((animation) => animation.frames.map((frame) => frame.transform))).toEqual([
      ["translateY(0)", "translateY(100%)"],
    ]);
    await settle();
    expect(done).toHaveBeenCalled();
  });

  it("survive an animation the engine refuses", () => {
    Object.defineProperty(HTMLElement.prototype, "animate", {
      configurable: true,
      value() {
        throw new TypeError("bad easing");
      },
    });
    const below = sheet();
    expect(() => pushLevel(sheet(), { below, belowTitle: "More filters" })).not.toThrow();
    expect(panelOf(below).style.visibility).toBe("hidden");
  });
});

describe("the back control", () => {
  it("names the sheet below, or reads Back without a title", () => {
    const level = sheet();
    pushLevel(level, { below: sheet(), belowTitle: "" });
    const back = level.querySelector<HTMLElement>("[data-sheet-back]")!;
    expect(back.hidden).toBe(false);
    expect(back.getAttribute("aria-label")).toBe("Back");
  });

  it("hides again once the level clears", () => {
    const level = sheet();
    pushLevel(level, { below: sheet(), belowTitle: "More filters" });
    clearLevel(level);
    const back = level.querySelector<HTMLElement>("[data-sheet-back]")!;
    expect(back.hidden).toBe(true);
    expect(back.hasAttribute("aria-label")).toBe(false);
    expect(level.hasAttribute("data-sheet-level")).toBe(false);
  });
});
