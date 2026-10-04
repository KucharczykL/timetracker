// jsdom lacks the Popover API; this stands in.
const openPopovers = new WeakSet<HTMLElement>();

function showPopover(this: HTMLElement): void {
  if (!this.hasAttribute("popover")) {
    throw new DOMException("Element has no popover attribute", "NotSupportedError");
  }
  if (!this.isConnected) {
    throw new DOMException("Element is not connected", "InvalidStateError");
  }
  openPopovers.add(this);
}

function hidePopover(this: HTMLElement): void {
  openPopovers.delete(this);
}

export function isPopoverOpen(element: HTMLElement): boolean {
  return openPopovers.has(element);
}

if (typeof HTMLElement !== "undefined" && !("showPopover" in HTMLElement.prototype)) {
  Object.assign(HTMLElement.prototype, { showPopover, hidePopover });
}
