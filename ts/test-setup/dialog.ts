// Stands in for jsdom's missing dialog methods.
const modalDialogs = new WeakSet<HTMLDialogElement>();

/** Removal ends the modal, as browsers do. */
export function isDialogModal(dialog: HTMLDialogElement): boolean {
  return dialog.isConnected && modalDialogs.has(dialog);
}

function showModal(this: HTMLDialogElement): void {
  if (this.open && isDialogModal(this)) return;
  if (this.open) {
    throw new DOMException("Dialog is open but not modal", "InvalidStateError");
  }
  if (!this.isConnected) {
    throw new DOMException("Dialog is not connected", "InvalidStateError");
  }
  this.open = true;
  modalDialogs.add(this);
}

function close(this: HTMLDialogElement): void {
  modalDialogs.delete(this);
  if (!this.open) return;
  this.open = false;
  // Browsers queue the event as a task.
  setTimeout(() => this.dispatchEvent(new Event("close")), 0);
}

if (
  typeof HTMLDialogElement !== "undefined" &&
  !("showModal" in HTMLDialogElement.prototype)
) {
  Object.assign(HTMLDialogElement.prototype, { showModal, close });
  // jsdom does not parse :modal.
  const matches = Element.prototype.matches;
  function matchesModal(this: Element, selector: string): boolean {
    if (selector !== ":modal") return matches.call(this, selector);
    return this instanceof HTMLDialogElement && isDialogModal(this);
  }
  Object.assign(Element.prototype, { matches: matchesModal });
}
