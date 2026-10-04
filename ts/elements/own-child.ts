/** First match not inside a nested <drop-down>. */
export function ownChild(host: HTMLElement, selector: string): HTMLElement | null {
  for (const match of host.querySelectorAll<HTMLElement>(selector)) {
    if (match.closest("drop-down") === host) return match;
  }
  return null;
}
