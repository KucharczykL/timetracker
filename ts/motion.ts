// Motion durations come from the computed root style; no number lives here.

export type MotionToken = "fast" | "fast-exit" | "medium" | "medium-exit" | "slow" | "slow-exit" | "reduced";

export type CancelLeave = () => void;

const MOTION_ATTRIBUTE = "data-motion";
const LEAVING = "leaving";
const ENTERING = "entering";
// Past the animation, a missed event still finishes the leave.
const CAP_SLACK_MS = 100;

export function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Parses a CSS time such as "150ms" or "0.15s" into milliseconds. */
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

/** Holds an element in its leave until its animations end or the cap passes. */
export function holdLeave(
  element: Element,
  token: MotionToken,
  finish: () => void,
): CancelLeave {
  element.setAttribute(MOTION_ATTRIBUTE, LEAVING);
  const duration = motionDuration(token);
  if (typeof element.getAnimations !== "function" || duration === 0) {
    element.removeAttribute(MOTION_ATTRIBUTE);
    finish();
    return () => {};
  }
  let settled = false;
  const settle = (): void => {
    if (settled) return;
    settled = true;
    window.clearTimeout(timer);
    if (element.getAttribute(MOTION_ATTRIBUTE) === LEAVING) {
      element.removeAttribute(MOTION_ATTRIBUTE);
    }
    finish();
  };
  const timer = window.setTimeout(settle, duration + CAP_SLACK_MS);
  // One style read starts any transition the stamp caused.
  void getComputedStyle(element).opacity;
  const animations = element.getAnimations({ subtree: true });
  void Promise.allSettled(animations.map((animation) => animation.finished)).then(settle);
  return () => {
    if (settled) return;
    settled = true;
    window.clearTimeout(timer);
    if (element.getAttribute(MOTION_ATTRIBUTE) === LEAVING) {
      element.removeAttribute(MOTION_ATTRIBUTE);
    }
  };
}

/** True while an element holds its leave. */
export function isLeaving(element: Element): boolean {
  return element.getAttribute(MOTION_ATTRIBUTE) === LEAVING;
}

/** Drops the entering stamp once the entry has started. */
export function settleEntry(element: Element): void {
  void getComputedStyle(element).opacity;
  if (element.getAttribute(MOTION_ATTRIBUTE) === ENTERING) {
    element.removeAttribute(MOTION_ATTRIBUTE);
  }
}
