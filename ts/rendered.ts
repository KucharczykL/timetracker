/** Whether the engine renders the element. */
export function isRendered(element: Element): boolean {
  if (!element.isConnected) return false;
  if (typeof element.checkVisibility === "function") {
    return element.checkVisibility();
  }
  return !element.closest("[hidden]");
}
