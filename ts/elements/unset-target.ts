/** A composite field a ⊘ can empty and restore. */
export interface UnsetTarget {
  /** Keep, empty, freeze; no-op while unset. */
  unsetValue(): void;
  /** Re-enable what unset froze, then restore. */
  restoreValue(): void;
}

export function isUnsetTarget(element: Element): element is HTMLElement & UnsetTarget {
  const candidate = element as Partial<UnsetTarget>;
  return typeof candidate.unsetValue === "function" && typeof candidate.restoreValue === "function";
}

/** Undoes exactly one freeze. */
export type Thaw = () => void;

const FREEZABLE = "input, select, textarea, button";

/** Disable, make inert; return the undo. */
export function freezeControls(root: HTMLElement): Thaw {
  const frozen = Array.from(
    root.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | HTMLButtonElement>(
      FREEZABLE,
    ),
  ).filter((control) => !control.disabled);
  const wasInert = root.hasAttribute("inert");
  frozen.forEach((control) => (control.disabled = true));
  // Holds controls a script re-enables.
  root.toggleAttribute("inert", true);
  return () => {
    root.toggleAttribute("inert", wasInert);
    frozen.forEach((control) => (control.disabled = false));
  };
}

/** One composite's kept value while unset. */
export class UnsetHold<Value> {
  private kept: { value: Value; thaw: Thaw } | null = null;

  get held(): boolean {
    return this.kept !== null;
  }

  /**
   * Keep `read()`, run `empty`, freeze `root`.
   *
   * Empty runs before the hold, so guards see it.
   */
  hold(root: HTMLElement, read: () => Value, empty: () => void): void {
    if (this.kept) return;
    const value = read();
    empty();
    this.kept = { value, thaw: freezeControls(root) };
  }

  /** Thaw, then hand back the kept value. */
  release(write: (value: Value) => void): void {
    const kept = this.kept;
    if (!kept) return;
    this.kept = null;
    kept.thaw();
    write(kept.value);
  }
}
