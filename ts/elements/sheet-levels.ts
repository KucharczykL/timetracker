/** Dropdown sheet opened over another sheet. */
import { reportClientError } from "../client-errors.js";
import { SHEET_ATTRIBUTES } from "../generated/sheet-attributes.js";
import { motionDuration, prefersReducedMotion, type CancelLeave, type MotionToken } from "../motion.js";

/** Covered sheet and its back-control title. */
export interface LevelPlacement {
  readonly below: HTMLDialogElement;
  readonly belowTitle: string;
}

interface LevelState {
  readonly below: HTMLDialogElement;
  animations: readonly Animation[];
}

const levels = new WeakMap<HTMLDialogElement, LevelState>();

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

/** The sheet this one covers: its DOM ancestor. */
function coveredSheet(sheet: HTMLDialogElement): HTMLDialogElement | null {
  return sheet.parentElement ? enclosingSheet(sheet.parentElement) : null;
}

/** Lowest sheet of a level's chain. */
export function bottomSheet(sheet: HTMLDialogElement): HTMLDialogElement {
  let current = sheet;
  for (let below = coveredSheet(current); below; below = coveredSheet(current)) {
    current = below;
  }
  return current;
}

function setBackLabel(back: HTMLElement, text: string): void {
  const label = back.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.back_label}]`);
  if (label) label.textContent = text;
}

/** Shows back control naming sheet below. */
function showBackControl(level: HTMLDialogElement, belowTitle: string): void {
  const back = backControlOf(level);
  if (!back) return;
  back.hidden = false;
  back.setAttribute("aria-label", belowTitle ? `Back to ${belowTitle}` : "Back");
  setBackLabel(back, belowTitle || "Back");
}

function hideBackControl(level: HTMLDialogElement): void {
  const back = backControlOf(level);
  if (!back) return;
  back.hidden = true;
  back.removeAttribute("aria-label");
  setBackLabel(back, "");
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
  readonly level: readonly Keyframe[];
  /** Null: the sheet below stays put. */
  readonly below: readonly Keyframe[] | null;
  readonly scrim: readonly Keyframe[];
}

function reversed(frames: readonly Keyframe[]): Keyframe[] {
  return [...frames].reverse();
}

function inDirection(direction: Direction, frames: LevelFrames): LevelFrames {
  if (direction === "push") return frames;
  return {
    level: reversed(frames.level),
    below: frames.below && reversed(frames.below),
    scrim: reversed(frames.scrim),
  };
}

/** Level slides in; below shifts, darkens. */
function framesFor(direction: Direction): LevelFrames {
  return inDirection(direction, {
    level: [{ transform: "translateX(100%)" }, { transform: "translateX(0)" }],
    below: [{ transform: "translateX(0)" }, { transform: "translateX(-30%)" }],
    scrim: [{ opacity: 0 }, { opacity: BELOW_SCRIM }],
  });
}

/** Reduced motion: level fades. */
function crossfadeFor(direction: Direction): LevelFrames {
  return inDirection(direction, {
    level: [{ opacity: 0 }, { opacity: 1 }],
    below: null,
    scrim: [{ opacity: 0 }, { opacity: BELOW_SCRIM }],
  });
}

function timingFor(token: MotionToken): KeyframeAnimationOptions | null {
  const duration = motionDuration(token);
  if (duration === 0) return null;
  // No snap back before the settle.
  return { duration, easing: easingOf(), fill: "forwards" };
}

/** A failed animation drops motion, not the level. */
function animated(play: () => Animation[]): Animation[] {
  try {
    return play();
  } catch (error) {
    reportClientError("sheet-levels", `a level animation failed: ${String(error)}`, {
      toast: false,
    });
    return [];
  }
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
  const timing = timingFor(direction === "push" ? "slow" : "slow-exit");
  if (!timing) return [];
  const frames = prefersReducedMotion() ? crossfadeFor(direction) : framesFor(direction);
  return animated(() => {
    const animations = [
      levelPanel.animate([...frames.level], timing),
      belowPanel.animate([...frames.scrim], { ...timing, pseudoElement: "::after" }),
    ];
    if (frames.below) animations.push(belowPanel.animate([...frames.below], timing));
    return animations;
  });
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

/** Replaces a level's animations; true while current. */
function playing(level: HTMLDialogElement, animations: readonly Animation[]): () => boolean {
  const state = levels.get(level);
  if (state) {
    cancelAll(state.animations);
    state.animations = animations;
  }
  return () => levels.get(level)?.animations === animations;
}

/** Presents a level over the sheet below. */
export function pushLevel(level: HTMLDialogElement, placement: LevelPlacement): void {
  const { below, belowTitle } = placement;
  level.setAttribute(SHEET_ATTRIBUTES.level, "");
  showBackControl(level, belowTitle);
  levels.set(level, { below, animations: [] });
  const animations = playLevel(level, below, "push");
  const current = playing(level, animations);
  whenPlayed(animations, () => {
    // A pop or clear since owns the level.
    if (!current()) return;
    setPanelShown(below, false);
    cancelAll(animations);
  });
}

/** Holds a leave until its animations end. */
function holdLevel(level: HTMLDialogElement, animations: Animation[], done: () => void): CancelLeave {
  const current = playing(level, animations);
  let cancelled = false;
  whenPlayed(animations, () => {
    if (!cancelled && current()) done();
  });
  return () => {
    cancelled = true;
    cancelAll(animations);
  };
}

/** Slides a level out; then done. */
export function popLevel(
  level: HTMLDialogElement,
  below: HTMLDialogElement,
  done: () => void,
): CancelLeave {
  // Shown first, so the slide can run.
  setPanelShown(below, true);
  return holdLevel(level, playLevel(level, below, "pop"), done);
}

/** A whole chain closing: the level drops. */
export function dropLevel(level: HTMLDialogElement, done: () => void): CancelLeave {
  const panel = panelOf(level);
  const timing = timingFor("slow-exit");
  const frames: Keyframe[] = prefersReducedMotion()
    ? [{ opacity: 1 }, { opacity: 0 }]
    : [{ transform: "translateY(0)" }, { transform: "translateY(100%)" }];
  const animations =
    panel && timing && typeof panel.animate === "function"
      ? animated(() => [panel.animate(frames, timing)])
      : [];
  return holdLevel(level, animations, done);
}

/** Clears a level's marks. */
export function clearLevel(level: HTMLDialogElement): void {
  const state = levels.get(level);
  levels.delete(level);
  if (state) {
    cancelAll(state.animations);
    setPanelShown(state.below, true);
  }
  level.removeAttribute(SHEET_ATTRIBUTES.level);
  hideBackControl(level);
}
