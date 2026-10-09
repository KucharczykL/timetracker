// Durations come from computed root style.
import { reportClientError } from "./client-errors.js";

export type MotionToken = "fast" | "fast-exit" | "medium" | "medium-exit" | "slow" | "slow-exit" | "reduced";

/** Idempotent; never calls finish. */
export type CancelLeave = () => void;

const MOTION_ATTRIBUTE = "data-motion";
const LEAVING = "leaving";
const ENTERING = "entering";
// Cap finishes a leave no animation ends.
const CAP_SLACK_MS = 100;

export function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Parses a CSS time into milliseconds. */
function parseMilliseconds(value: string): number {
  const trimmed = value.trim();
  const amount = Number.parseFloat(trimmed);
  if (Number.isNaN(amount)) return 0;
  if (trimmed.endsWith("ms")) return amount;
  if (trimmed.endsWith("s")) return amount * 1000;
  return 0;
}

function durationOf(token: MotionToken): number {
  const value = getComputedStyle(document.documentElement).getPropertyValue(
    `--duration-${token}`,
  );
  return parseMilliseconds(value);
}

export function motionDuration(token: MotionToken): number {
  if (token !== "reduced" && prefersReducedMotion()) return durationOf("reduced");
  return durationOf(token);
}

/** Stamps an anchored entry's start values. */
export function markEntering(element: Element): void {
  element.setAttribute(MOTION_ATTRIBUTE, ENTERING);
}

export function markLeaving(element: Element): void {
  element.setAttribute(MOTION_ATTRIBUTE, LEAVING);
}

export function clearLeaving(element: Element): void {
  if (isLeaving(element)) element.removeAttribute(MOTION_ATTRIBUTE);
}

/** An infinite animation never ends a leave. */
function endsOnItsOwn(animation: Animation): boolean {
  return animation.effect?.getTiming().iterations !== Number.POSITIVE_INFINITY;
}

function runFinish(finish: () => void): void {
  try {
    finish();
  } catch (error) {
    reportClientError("motion", `a leave's finish threw: ${String(error)}`, { toast: false });
  }
}

/** Holds a leave; null when finished at once. */
export function holdLeave(
  element: Element,
  token: MotionToken,
  finish: () => void,
): CancelLeave | null {
  markLeaving(element);
  const duration = motionDuration(token);
  if (typeof element.getAnimations !== "function" || duration === 0) {
    clearLeaving(element);
    runFinish(finish);
    return null;
  }
  let settled = false;
  const stop = (): boolean => {
    if (settled) return false;
    settled = true;
    window.clearTimeout(timer);
    clearLeaving(element);
    return true;
  };
  const settle = (): void => {
    if (stop()) runFinish(finish);
  };
  const timer = window.setTimeout(settle, duration + CAP_SLACK_MS);
  // Style read starts the stamped transition.
  void getComputedStyle(element).opacity;
  const animations = element.getAnimations({ subtree: true }).filter(endsOnItsOwn);
  void Promise.allSettled(animations.map((animation) => animation.finished)).then(settle);
  return () => {
    stop();
  };
}

/** True while an element holds its leave. */
export function isLeaving(element: Element): boolean {
  return element.getAttribute(MOTION_ATTRIBUTE) === LEAVING;
}

/** Drops the entering stamp; entry runs. */
export function settleEntry(element: Element): void {
  void getComputedStyle(element).opacity;
  if (element.getAttribute(MOTION_ATTRIBUTE) === ENTERING) {
    element.removeAttribute(MOTION_ATTRIBUTE);
  }
}
