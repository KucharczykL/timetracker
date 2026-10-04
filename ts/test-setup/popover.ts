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

export function isPopoverOpen(element: HTMLElement): boolean {
  return openPopovers.has(element);
}

if (typeof HTMLElement !== "undefined" && !("showPopover" in HTMLElement.prototype)) {
  Object.assign(HTMLElement.prototype, { showPopover, hidePopover });
}
