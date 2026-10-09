/** A dropdown sheet opened over another sheet: its level. */
import { SHEET_ATTRIBUTES } from "../generated/sheet-attributes.js";
import { motionDuration, prefersReducedMotion, type CancelLeave, type MotionToken } from "../motion.js";

/** The sheet a level covers, and the title its back control names. */
export interface LevelPlacement {
  below: HTMLDialogElement;
  belowTitle: string;
}

/** Each level's sheet below, while it covers one. */
const coveredSheets = new WeakMap<HTMLDialogElement, HTMLDialogElement>();
/** A level's running animations; a pop replaces a push's. */
const runningAnimations = new WeakMap<HTMLDialogElement, Animation[]>();

function panelOf(dialog: HTMLDialogElement): HTMLElement | null {
  return dialog.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.panel}]`);
}

/** Hides the sheet's panel; its layout stays for the sentinel. */
function setPanelShown(sheet: HTMLDialogElement, shown: boolean): void {
  const panel = panelOf(sheet);
  if (panel) panel.style.visibility = shown ? "" : "hidden";
}

function backControlOf(level: HTMLDialogElement): HTMLElement | null {
  return level.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.back}]`);
}

/** The open sheet a dropdown host sits in, unless it is leaving. */
export function enclosingSheet(host: HTMLElement): HTMLDialogElement | null {
  const sheet = host.parentElement?.closest<HTMLDialogElement>(
    `dialog[${SHEET_ATTRIBUTES.sheet}]`,
  );
  if (!sheet || !sheet.open) return null;
  if (sheet.dataset.sheetState === "closing") return null;
  return sheet;
}

/** The sheet a sheet's host sits in. */
function sheetAbove(sheet: HTMLDialogElement): HTMLDialogElement | null {
  return sheet.parentElement ? enclosingSheet(sheet.parentElement) : null;
}

/** The lowest sheet of the chain a level belongs to. */
export function bottomSheet(sheet: HTMLDialogElement): HTMLDialogElement {
  let current = sheet;
  for (let above = sheetAbove(current); above; above = sheetAbove(current)) {
    current = above;
  }
  return current;
}

/** Shows the back control, naming the sheet below. */
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

/** The scrim darkens the sheet below; the page never shows. */
const BELOW_SCRIM = 0.3;

interface LevelFrames {
  level: Keyframe[];
  /** Empty: the sheet below stays still. */
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

/** The level slides; the sheet below moves aside, darkening. */
function framesFor(direction: Direction): LevelFrames {
  return reversedFor(direction, {
    level: [{ transform: "translateX(100%)" }, { transform: "translateX(0)" }],
    below: [{ transform: "translateX(0)" }, { transform: "translateX(-30%)" }],
    scrim: [{ opacity: 0 }, { opacity: BELOW_SCRIM }],
  });
}

/** Reduced motion: the level fades over a still sheet. */
function crossfadeFor(direction: Direction): LevelFrames {
  return reversedFor(direction, {
    level: [{ opacity: 0 }, { opacity: 1 }],
    below: [],
    scrim: [{ opacity: 0 }, { opacity: BELOW_SCRIM }],
  });
}

/** Plays the slide; no animation where the API or the duration is absent. */
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

/** Runs once every animation ends; at once when there are none. */
function whenPlayed(animations: readonly Animation[], run: () => void): void {
  if (animations.length === 0) {
    run();
    return;
  }
  void Promise.allSettled(animations.map((animation) => animation.finished)).then(run);
}

/** Presents a level over the sheet below, which then goes hidden. */
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
    // A pop that started meanwhile owns the animations now.
    if (runningAnimations.get(level) !== animations) return;
    if (coveredSheets.get(level) === below) setPanelShown(below, false);
    cancelAll(animations);
  });
}

/** Backs out of a level; `done` runs once it has slid out. */
export function popLevel(
  level: HTMLDialogElement,
  below: HTMLDialogElement,
  done: () => void,
): CancelLeave {
  cancelAll(runningAnimations.get(level) ?? []);
  // Shown first, so the slide-back has the panel to move.
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

/** Removes a level's marks; a sheet that is not a level clears nothing. */
export function clearLevel(level: HTMLDialogElement): void {
  const below = coveredSheets.get(level);
  coveredSheets.delete(level);
  cancelAll(runningAnimations.get(level) ?? []);
  runningAnimations.delete(level);
  if (below) setPanelShown(below, true);
  level.removeAttribute(SHEET_ATTRIBUTES.level);
  hideBackControl(level);
}
