/** A composite field a ⊘ can empty and restore. */
export interface UnsetTarget {
  /** Keep the value, empty it, disable controls. */
  unsetValue(): void;
  /** Re-enable, then set the kept value. */
  restoreValue(): void;
}

export function isUnsetTarget(element: Element): element is HTMLElement & UnsetTarget {
  const candidate = element as Partial<UnsetTarget>;
  return typeof candidate.unsetValue === "function" && typeof candidate.restoreValue === "function";
}

const FREEZABLE = "input, select, textarea, button";

/** Disable enabled controls; return the undo. */
export function freezeControls(root: HTMLElement): () => void {
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
