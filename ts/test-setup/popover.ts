// Stands in for jsdom's missing Popover API.
const openPopovers = new WeakSet<HTMLElement>();

function requirePopover(element: HTMLElement): void {
  if (!element.hasAttribute("popover")) {
    throw new DOMException("Element has no popover attribute", "NotSupportedError");
  }
}

function showPopover(this: HTMLElement): void {
  requirePopover(this);
  if (!this.isConnected) {
    throw new DOMException("Element is not connected", "InvalidStateError");
  }
  openPopovers.add(this);
}

function hidePopover(this: HTMLElement): void {
  requirePopover(this);
  openPopovers.delete(this);
}

/** Removal hides it, as browsers do. */
export function isPopoverOpen(element: HTMLElement): boolean {
  return element.isConnected && openPopovers.has(element);
}

if (typeof HTMLElement !== "undefined" && !("showPopover" in HTMLElement.prototype)) {
  Object.assign(HTMLElement.prototype, { showPopover, hidePopover });
  // jsdom does not parse :popover-open.
  const matches = Element.prototype.matches;
  function matchesPopoverOpen(this: Element, selector: string): boolean {
    if (selector !== ":popover-open") return matches.call(this, selector);
    return this instanceof HTMLElement && isPopoverOpen(this);
  }
  Object.assign(Element.prototype, { matches: matchesPopoverOpen });
}
