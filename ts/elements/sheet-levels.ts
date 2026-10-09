/** Dropdown sheet opened over another sheet. */
import { SHEET_ATTRIBUTES } from "../generated/sheet-attributes.js";
import { motionDuration, prefersReducedMotion, type CancelLeave, type MotionToken } from "../motion.js";

/** Covered sheet and its back-control title. */
export interface LevelPlacement {
  below: HTMLDialogElement;
  belowTitle: string;
}

/** Sheet below a level, while covered. */
const coveredSheets = new WeakMap<HTMLDialogElement, HTMLDialogElement>();
/** Running animations of a level. */
const runningAnimations = new WeakMap<HTMLDialogElement, Animation[]>();

function panelOf(dialog: HTMLDialogElement): HTMLElement | null {
  return dialog.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.panel}]`);
}

/** Hides the panel; keeps its layout. */
function setPanelShown(sheet: HTMLDialogElement, shown: boolean): void {
  const panel = panelOf(sheet);
  if (panel) panel.style.visibility = shown ? "" : "hidden";
}

function backControlOf(level: HTMLDialogElement): HTMLElement | null {
  return level.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.back}]`);
}

/** Open sheet holding this host, not leaving. */
export function enclosingSheet(host: HTMLElement): HTMLDialogElement | null {
  const sheet = host.parentElement?.closest<HTMLDialogElement>(
    `dialog[${SHEET_ATTRIBUTES.sheet}]`,
  );
  if (!sheet || !sheet.open) return null;
  if (sheet.dataset.sheetState === "closing") return null;
  return sheet;
}

/** Sheet holding this sheet's host. */
function sheetAbove(sheet: HTMLDialogElement): HTMLDialogElement | null {
  return sheet.parentElement ? enclosingSheet(sheet.parentElement) : null;
}

/** Lowest sheet of a level's chain. */
export function bottomSheet(sheet: HTMLDialogElement): HTMLDialogElement {
  let current = sheet;
  for (let above = sheetAbove(current); above; above = sheetAbove(current)) {
    current = above;
  }
  return current;
}

/** Shows back control naming sheet below. */
function showBackControl(level: HTMLDialogElement, belowTitle: string): void {
  const back = backControlOf(level);
  if (!back) return;
  back.hidden = false;
  back.setAttribute("aria-label", `Back to ${belowTitle}`);
  const label = back.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.back_label}]`);
  if (label) label.textContent = belowTitle;
}

function hideBackControl(level: HTMLDialogElement): void {
  const back = backControlOf(level);
  if (!back) return;
  back.hidden = true;
  back.removeAttribute("aria-label");
  const label = back.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.back_label}]`);
  if (label) label.textContent = "";
}

function easingOf(): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue("--ease-sheet")
    .trim();
  return value || "linear";
}

type Direction = "push" | "pop";

/** Scrim darkens the sheet below. */
const BELOW_SCRIM = 0.3;

interface LevelFrames {
  level: Keyframe[];
  /** Empty: the sheet below stays put. */
  below: Keyframe[];
  scrim: Keyframe[];
}

function reversedFor(direction: Direction, frames: LevelFrames): LevelFrames {
  if (direction === "push") return frames;
  return {
    level: [...frames.level].reverse(),
    below: [...frames.below].reverse(),
    scrim: [...frames.scrim].reverse(),
  };
}

/** Level slides; sheet below darkens. */
function framesFor(direction: Direction): LevelFrames {
  return reversedFor(direction, {
    level: [{ transform: "translateX(100%)" }, { transform: "translateX(0)" }],
    below: [{ transform: "translateX(0)" }, { transform: "translateX(-30%)" }],
    scrim: [{ opacity: 0 }, { opacity: BELOW_SCRIM }],
  });
}

/** Reduced motion: level fades. */
function crossfadeFor(direction: Direction): LevelFrames {
  return reversedFor(direction, {
    level: [{ opacity: 0 }, { opacity: 1 }],
    below: [],
    scrim: [{ opacity: 0 }, { opacity: BELOW_SCRIM }],
  });
}

/** Plays the slide where animations exist. */
function playLevel(
  level: HTMLDialogElement,
  below: HTMLDialogElement,
  direction: Direction,
): Animation[] {
  const levelPanel = panelOf(level);
  const belowPanel = panelOf(below);
  if (!levelPanel || !belowPanel || typeof levelPanel.animate !== "function") return [];
  const token: MotionToken = direction === "push" ? "slow" : "slow-exit";
  const duration = motionDuration(token);
  if (duration === 0) return [];
  const frames = prefersReducedMotion() ? crossfadeFor(direction) : framesFor(direction);
  const timing: KeyframeAnimationOptions = {
    duration,
    easing: easingOf(),
    // No snap back before the settle.
    fill: "forwards",
  };
  const animations = [
    levelPanel.animate(frames.level, timing),
    belowPanel.animate(frames.scrim, { ...timing, pseudoElement: "::after" }),
  ];
  if (frames.below.length > 0) animations.push(belowPanel.animate(frames.below, timing));
  return animations;
}

function cancelAll(animations: readonly Animation[]): void {
  for (const animation of animations) animation.cancel();
}

/** Runs once all animations end. */
function whenPlayed(animations: readonly Animation[], run: () => void): void {
  if (animations.length === 0) {
    run();
    return;
  }
  void Promise.allSettled(animations.map((animation) => animation.finished)).then(run);
}

/** Presents a level over the sheet below. */
export function pushLevel(
  level: HTMLDialogElement,
  below: HTMLDialogElement,
  belowTitle: string,
): void {
  level.setAttribute(SHEET_ATTRIBUTES.level, "");
  showBackControl(level, belowTitle);
  coveredSheets.set(level, below);
  const animations = playLevel(level, below, "push");
  runningAnimations.set(level, animations);
  whenPlayed(animations, () => {
    // Pop started meanwhile owns animations.
    if (runningAnimations.get(level) !== animations) return;
    if (coveredSheets.get(level) === below) setPanelShown(below, false);
    cancelAll(animations);
  });
}

/** Slides a level out; then done. */
export function popLevel(
  level: HTMLDialogElement,
  below: HTMLDialogElement,
  done: () => void,
): CancelLeave {
  cancelAll(runningAnimations.get(level) ?? []);
  // Shown first, so the slide can run.
  setPanelShown(below, true);
  const animations = playLevel(level, below, "pop");
  runningAnimations.set(level, animations);
  let cancelled = false;
  whenPlayed(animations, () => {
    if (!cancelled) done();
  });
  return () => {
    cancelled = true;
    cancelAll(animations);
  };
}

/** Clears a level's marks. */
export function clearLevel(level: HTMLDialogElement): void {
  const below = coveredSheets.get(level);
  coveredSheets.delete(level);
  cancelAll(runningAnimations.get(level) ?? []);
  runningAnimations.delete(level);
  if (below) setPanelShown(below, true);
  level.removeAttribute(SHEET_ATTRIBUTES.level);
  hideBackControl(level);
}
