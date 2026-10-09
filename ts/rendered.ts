/** Whether the engine renders an element, so focus can land on it. */
export function isRendered(element: Element): boolean {
  if (!element.isConnected) return false;
  if (typeof element.checkVisibility === "function") {
    return element.checkVisibility();
  }
  return !element.closest("[hidden]");
}
