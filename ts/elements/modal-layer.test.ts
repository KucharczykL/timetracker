// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  attachModal,
  isModalOpen,
  MODAL_CHANGE,
  type Modal,
  type ModalOptions,
  topModal,
} from "./modal-layer.js";
import { openSurfaces, pushSurface, removeSurface, type Surface } from "./surface-stack.js";

let changes = 0;
const countChange = (): void => {
  changes += 1;
};

beforeEach(() => {
  changes = 0;
  window.addEventListener(MODAL_CHANGE, countChange);
});

afterEach(() => {
  window.removeEventListener(MODAL_CHANGE, countChange);
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  document.body.removeAttribute("style");
  document.documentElement.removeAttribute("style");
});

function mountDialog(parent: HTMLElement = document.body): HTMLDialogElement {
  const dialog = document.createElement("dialog");
  dialog.setAttribute("data-modal", "");
  dialog.innerHTML = `
    <div data-panel>
      <button data-first>First</button>
      <button data-last data-modal-dismiss>Close</button>
    </div>
  `;
  parent.append(dialog);
  return dialog;
}

function mountOpener(parent: HTMLElement = document.body): HTMLButtonElement {
  const button = document.createElement("button");
  button.textContent = "Open";
  parent.append(button);
  return button;
}

function first(dialog: HTMLDialogElement): HTMLButtonElement {
  return dialog.querySelector<HTMLButtonElement>("[data-first]")!;
}

function dismissControl(dialog: HTMLDialogElement): HTMLButtonElement {
  return dialog.querySelector<HTMLButtonElement>("[data-modal-dismiss]")!;
}

function modalOn(dialog: HTMLDialogElement, options: ModalOptions = {}): Modal {
  return attachModal(dialog, options);
}

function pointer(type: string, target: EventTarget, pointerId = 1): void {
  target.dispatchEvent(
    new PointerEvent(type, { bubbles: true, isPrimary: true, button: 0, pointerId }),
  );
}

function pressTab(target: HTMLElement, shiftKey = false): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key: "Tab",
    shiftKey,
    bubbles: true,
    cancelable: true,
  });
  target.dispatchEvent(event);
  return event;
}

function cancel(dialog: HTMLDialogElement): Event {
  const event = new Event("cancel", { cancelable: true });
  dialog.dispatchEvent(event);
  return event;
}

describe("attachModal", () => {
  it("refuses a dialog without data-modal", () => {
    const dialog = document.createElement("dialog");
    document.body.append(dialog);
    expect(() => attachModal(dialog)).toThrow(TypeError);
  });
});

describe("open", () => {
  it("shows the dialog as the top modal and pushes a modal surface", () => {
    const opener = mountOpener();
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    expect(modal.open(opener)).toBe(true);
    expect(dialog.matches(":modal")).toBe(true);
    expect(modal.isOpen()).toBe(true);
    expect(isModalOpen()).toBe(true);
    expect(topModal()).toBe(dialog);
    expect(openSurfaces().map((surface) => surface.kind)).toEqual(["modal"]);
    expect(changes).toBe(1);
  });

  it("focuses initialFocus, else [data-modal-initial-focus]", () => {
    const dialog = mountDialog();
    dismissControl(dialog).setAttribute("data-modal-initial-focus", "");
    modalOn(dialog).open();
    expect(document.activeElement).toBe(dismissControl(dialog));

    const other = mountDialog();
    modalOn(other, { initialFocus: () => first(other) }).open();
    expect(document.activeElement).toBe(first(other));
  });

  it("answers false for a disconnected host", () => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("data-modal", "");
    expect(modalOn(dialog).open()).toBe(false);
    expect(isModalOpen()).toBe(false);
  });

  it("reports a refused showModal and leaves nothing locked", () => {
    const dialog = mountDialog();
    dialog.setAttribute("open", "");
    const modal = modalOn(dialog);
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(modal.open()).toBe(false);
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("modal-layer: showModal"));
    logged.mockRestore();
    expect(isModalOpen()).toBe(false);
    expect(document.body.style.position).toBe("");
    expect(openSurfaces()).toEqual([]);
  });

  it("does nothing on an open modal", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    expect(modal.open()).toBe(true);
    expect(changes).toBe(1);
  });
});

describe("nesting", () => {
  it("nests a dialog placed inside another", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    modalOn(lower).open();
    modalOn(upper).open();
    expect(topModal()).toBe(upper);
    expect(lower.matches(":modal")).toBe(true);
    expect(openSurfaces().map((surface) => surface.kind)).toEqual(["modal", "modal"]);
  });

  it("nests a dialog placed beside another", () => {
    const lower = mountDialog();
    const upper = mountDialog();
    modalOn(lower).open();
    modalOn(upper).open();
    expect(topModal()).toBe(upper);
    expect(lower.open).toBe(true);
  });

  it("closes the modals above a closing one, topmost first", () => {
    const closed: string[] = [];
    const bottom = modalOn(mountDialog(), { onClosed: () => closed.push("bottom") });
    const middle = modalOn(mountDialog(), { onClosed: () => closed.push("middle") });
    const top = mountDialog();
    bottom.open();
    middle.open();
    modalOn(top, { onClosed: () => closed.push("top") }).open();
    middle.close();
    expect(closed).toEqual(["top", "middle"]);
    expect(top.open).toBe(false);
    expect(bottom.isOpen()).toBe(true);
  });

  it("closes a modal opened above a closing one before it leaves", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower);
    const lowerModal = modalOn(lower, { leave: () => {} });
    lowerModal.open();
    modalOn(upper).open();
    lowerModal.close();
    expect(upper.open).toBe(false);
    expect(document.querySelectorAll(":modal")).toHaveLength(0);
  });
});

describe("scroll lock", () => {
  it("is one lock for the stack", () => {
    const lower = modalOn(mountDialog());
    const upper = modalOn(mountDialog());
    lower.open();
    expect(document.body.style.position).toBe("fixed");
    upper.open();
    upper.close();
    expect(document.body.style.position).toBe("fixed");
    lower.close();
    expect(document.body.style.position).toBe("");
  });

  it("holds through a leave", () => {
    let finish = (): void => {};
    const modal = modalOn(mountDialog(), {
      leave: (done) => {
        finish = done;
      },
    });
    modal.open();
    modal.close();
    expect(document.body.style.position).toBe("fixed");
    finish();
    expect(document.body.style.position).toBe("");
  });
});

describe("focus return", () => {
  it("returns focus to the opener", () => {
    const opener = mountOpener();
    const modal = modalOn(mountDialog());
    modal.open(opener);
    modal.close();
    expect(document.activeElement).toBe(opener);
  });

  it("defaults the opener to the focused element", () => {
    const opener = mountOpener();
    opener.focus();
    const modal = modalOn(mountDialog());
    modal.open();
    modal.close();
    expect(document.activeElement).toBe(opener);
  });

  it("returns no focus to a hidden opener", () => {
    const wrapper = document.createElement("div");
    document.body.append(wrapper);
    const opener = mountOpener(wrapper);
    const modal = modalOn(mountDialog());
    modal.open(opener);
    wrapper.hidden = true;
    modal.close();
    expect(document.activeElement).not.toBe(opener);
  });

  it("falls back to the toggle of an enclosing drop-down", () => {
    document.body.innerHTML = `
      <drop-down>
        <button data-toggle>Menu</button>
        <div data-menu hidden><button data-item>Item</button></div>
      </drop-down>
    `;
    const item = document.querySelector<HTMLElement>("[data-item]")!;
    const modal = modalOn(mountDialog());
    modal.open(item);
    modal.close();
    expect(document.activeElement).toBe(document.querySelector("[data-toggle]"));
  });

  it("skips a nested drop-down's hidden toggle for the outer one", () => {
    document.body.innerHTML = `
      <drop-down id="outer">
        <button data-toggle id="outer-toggle">Outer</button>
        <div data-menu>
          <drop-down>
            <button data-toggle hidden>Inner</button>
            <div data-menu hidden><button data-item>Item</button></div>
          </drop-down>
        </div>
      </drop-down>
    `;
    const modal = modalOn(mountDialog());
    modal.open(document.querySelector<HTMLElement>("[data-item]")!);
    modal.close();
    expect(document.activeElement?.id).toBe("outer-toggle");
  });

  it("focuses the remaining modal when the opener sits outside it", () => {
    const opener = mountOpener();
    const lower = mountDialog();
    modalOn(lower, { initialFocus: () => first(lower) }).open();
    const upper = modalOn(mountDialog());
    upper.open(opener);
    upper.close();
    expect(document.activeElement).toBe(first(lower));
  });

  it("returns focus inside the remaining modal to the opener there", () => {
    const lower = mountDialog();
    modalOn(lower).open();
    const upper = modalOn(mountDialog());
    upper.open(dismissControl(lower));
    upper.close();
    expect(document.activeElement).toBe(dismissControl(lower));
  });

  it("lets onClosed move focus last", () => {
    const opener = mountOpener();
    const elsewhere = mountOpener();
    const modal = modalOn(mountDialog(), { onClosed: () => elsewhere.focus() });
    modal.open(opener);
    modal.close();
    expect(document.activeElement).toBe(elsewhere);
  });
});

describe("dismissal", () => {
  it("prevents cancel and dismisses", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    expect(cancel(dialog).defaultPrevented).toBe(true);
    expect(modal.isOpen()).toBe(false);
  });

  it("lets dismiss veto a cancel", () => {
    const dialog = mountDialog();
    const dismiss = vi.fn();
    const modal = modalOn(dialog, { dismiss });
    modal.open();
    cancel(dialog);
    expect(dismiss).toHaveBeenCalledOnce();
    expect(modal.isOpen()).toBe(true);
  });

  it("dismisses on a press that starts and ends on the backdrop", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    pointer("pointerdown", dialog);
    pointer("pointerup", dialog);
    expect(modal.isOpen()).toBe(false);
  });

  it("keeps the modal on a press that starts inside the panel", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    pointer("pointerdown", first(dialog));
    pointer("pointerup", dialog);
    expect(modal.isOpen()).toBe(true);
  });

  it("keeps the modal when the browser cancels the press", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    pointer("pointerdown", dialog);
    pointer("pointercancel", dialog);
    pointer("pointerup", dialog);
    expect(modal.isOpen()).toBe(true);
  });

  it("keeps the modal on another pointer's release", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    pointer("pointerdown", dialog, 1);
    pointer("pointerup", dialog, 2);
    expect(modal.isOpen()).toBe(true);
  });

  it("dismisses on a click on [data-modal-dismiss]", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    dismissControl(dialog).click();
    expect(modal.isOpen()).toBe(false);
  });

  it("leaves a nested dialog's dismiss control to it", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    const lowerModal = modalOn(lower);
    const upperModal = modalOn(upper);
    lowerModal.open();
    upperModal.open();
    dismissControl(upper).click();
    expect(upperModal.isOpen()).toBe(false);
    expect(lowerModal.isOpen()).toBe(true);
  });
});

describe("Tab boundary", () => {
  it("wraps among the top modal's own tabbables", () => {
    const dialog = mountDialog();
    modalOn(dialog).open();
    dismissControl(dialog).focus();
    expect(pressTab(dismissControl(dialog)).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(first(dialog));
    pressTab(first(dialog), true);
    expect(document.activeElement).toBe(dismissControl(dialog));
  });

  it("skips tabbables of a nested dialog", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    modalOn(lower).open();
    modalOn(upper).open();
    dismissControl(upper).focus();
    pressTab(dismissControl(upper));
    expect(document.activeElement).toBe(first(upper));
  });

  it("does nothing in a modal that is not the top one", () => {
    const lower = mountDialog();
    modalOn(lower).open();
    modalOn(mountDialog()).open();
    dismissControl(lower).focus();
    expect(pressTab(dismissControl(lower)).defaultPrevented).toBe(false);
  });
});

describe("leave", () => {
  it("keeps the dialog shown until finish", () => {
    let finish = (): void => {};
    const dialog = mountDialog();
    const onClosed = vi.fn();
    const modal = modalOn(dialog, {
      leave: (done) => {
        finish = done;
      },
      onClosed,
    });
    modal.open();
    modal.close();
    expect(dialog.open).toBe(true);
    expect(modal.isOpen()).toBe(false);
    expect(isModalOpen()).toBe(false);
    expect(openSurfaces()).toEqual([]);
    expect(onClosed).not.toHaveBeenCalled();
    finish();
    expect(dialog.open).toBe(false);
    expect(onClosed).toHaveBeenCalledOnce();
  });

  it("finishes at once when leave calls finish at once", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog, { leave: (done) => done() });
    modal.open();
    modal.close();
    expect(dialog.open).toBe(false);
  });

  it("ignores close during a leave", () => {
    const leave = vi.fn();
    const dialog = mountDialog();
    const modal = modalOn(dialog, { leave });
    modal.open();
    modal.close();
    modal.close();
    expect(leave).toHaveBeenCalledOnce();
    expect(dialog.open).toBe(true);
  });

  it("finishes a leave when the host is gone", () => {
    const dialog = mountDialog();
    const modal = modalOn(dialog, { leave: () => {} });
    modal.open();
    modal.close();
    dialog.remove();
    modal.close();
    expect(dialog.open).toBe(false);
    expect(document.body.style.position).toBe("");
  });

  it("skips leave for a disconnected host", () => {
    const leave = vi.fn();
    const dialog = mountDialog();
    const modal = modalOn(dialog, { leave });
    modal.open();
    dialog.remove();
    modal.close();
    expect(leave).not.toHaveBeenCalled();
    expect(dialog.open).toBe(false);
  });

  it("refuses to open while a modal leaves", () => {
    const leaving = modalOn(mountDialog(), { leave: () => {} });
    leaving.open();
    leaving.close();
    expect(modalOn(mountDialog()).open()).toBe(false);
  });

  it("ignores a late finish after a reopen", () => {
    let finish = (): void => {};
    const dialog = mountDialog();
    const modal = modalOn(dialog, {
      leave: (done) => {
        finish = done;
      },
    });
    modal.open();
    modal.close();
    const stale = finish;
    stale();
    modal.open();
    stale();
    expect(modal.isOpen()).toBe(true);
    expect(dialog.open).toBe(true);
  });
});

describe("native close", () => {
  it("finishes on a close the dialog fires itself", () => {
    vi.useFakeTimers();
    const opener = mountOpener();
    const dialog = mountDialog();
    const onClosed = vi.fn();
    const modal = modalOn(dialog, { onClosed });
    modal.open(opener);
    dialog.close();
    vi.runAllTimers();
    expect(modal.isOpen()).toBe(false);
    expect(onClosed).toHaveBeenCalledOnce();
    expect(document.body.style.position).toBe("");
  });

  it("ignores a stale close event after a reopen", () => {
    vi.useFakeTimers();
    const dialog = mountDialog();
    const modal = modalOn(dialog);
    modal.open();
    modal.close();
    modal.open();
    vi.runAllTimers();
    expect(modal.isOpen()).toBe(true);
  });

  it("closes the modals above too", () => {
    vi.useFakeTimers();
    const lower = mountDialog();
    const upper = mountDialog();
    modalOn(lower).open();
    const upperModal = modalOn(upper);
    upperModal.open();
    lower.close();
    vi.runAllTimers();
    expect(upperModal.isOpen()).toBe(false);
    expect(isModalOpen()).toBe(false);
  });
});

describe("removal", () => {
  it("finishes a modal whose dialog leaves the document", async () => {
    const dialog = mountDialog();
    const onClosed = vi.fn();
    const modal = modalOn(dialog, { onClosed });
    modal.open();
    dialog.remove();
    await Promise.resolve();
    expect(modal.isOpen()).toBe(false);
    expect(onClosed).toHaveBeenCalledOnce();
    expect(document.body.style.position).toBe("");
  });
});

describe("backdrops", () => {
  it("covers every shown dialog but the topmost one", () => {
    let finish = (): void => {};
    const lower = mountDialog();
    const upper = mountDialog();
    const lowerModal = modalOn(lower);
    const upperModal = modalOn(upper, {
      leave: (done) => {
        finish = done;
      },
    });
    lowerModal.open();
    expect(lower.hasAttribute("data-modal-covered")).toBe(false);
    expect(lower.hasAttribute("data-modal-over")).toBe(false);
    upperModal.open();
    expect(lower.hasAttribute("data-modal-covered")).toBe(true);
    expect(upper.hasAttribute("data-modal-covered")).toBe(false);
    expect(upper.hasAttribute("data-modal-over")).toBe(true);
    upperModal.close();
    // The leaving one still dims.
    expect(lower.hasAttribute("data-modal-covered")).toBe(true);
    finish();
    expect(lower.hasAttribute("data-modal-covered")).toBe(false);
    expect(upper.hasAttribute("data-modal-over")).toBe(false);
  });
});

describe("change events", () => {
  it("fires when the top modal changes", () => {
    const lower = modalOn(mountDialog());
    const upper = modalOn(mountDialog());
    lower.open();
    upper.open();
    expect(changes).toBe(2);
    upper.close();
    expect(changes).toBe(3);
    lower.close();
    expect(changes).toBe(4);
  });

  it("fires at the start of a leave, not again at finish", () => {
    let finish = (): void => {};
    const modal = modalOn(mountDialog(), {
      leave: (done) => {
        finish = done;
      },
    });
    modal.open();
    modal.close();
    expect(changes).toBe(2);
    finish();
    expect(changes).toBe(2);
  });
});

describe("surface stack", () => {
  it("closes a panel inside the modal before a leave", () => {
    const dialog = mountDialog();
    const closePanel = vi.fn();
    const panel: Surface = {
      host: first(dialog),
      kind: "panel",
      close: () => {
        closePanel();
        removeSurface(panel);
      },
    };
    const modal = modalOn(dialog, { leave: () => {} });
    modal.open();
    pushSurface(panel);
    modal.close();
    expect(closePanel).toHaveBeenCalledOnce();
  });
});

function silenceReports(): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(console, "error").mockImplementation(() => {});
}

describe("failure paths", () => {
  it("reports and finishes a leave that throws", () => {
    const logged = silenceReports();
    const modal = modalOn(mountDialog(), {
      leave: () => {
        throw new Error("broken slide");
      },
    });
    modal.open();
    modal.close();
    expect(modal.state()).toBe("closed");
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("leave threw"));
    expect(modalOn(mountDialog()).open()).toBe(true);
  });

  it("finishes a leave that never calls finish", () => {
    vi.useFakeTimers();
    const logged = silenceReports();
    const dialog = mountDialog();
    const modal = modalOn(dialog, { leave: () => {} });
    modal.open();
    modal.close();
    expect(dialog.open).toBe(true);
    vi.advanceTimersByTime(1_000);
    expect(modal.state()).toBe("closed");
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("never called finish"));
  });

  it("refuses a showModal that leaves the dialog closed", () => {
    const logged = silenceReports();
    const dialog = mountDialog();
    vi.spyOn(dialog, "showModal").mockImplementation(() => {});
    const modal = modalOn(dialog);
    expect(modal.open()).toBe(false);
    expect(modal.state()).toBe("closed");
    expect(document.body.style.position).toBe("");
    expect(openSurfaces()).toEqual([]);
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("left the dialog closed"));
  });

  it("rethrows a showModal error that is no refusal", () => {
    const dialog = mountDialog();
    vi.spyOn(dialog, "showModal").mockImplementation(() => {
      throw new TypeError("defect");
    });
    expect(() => modalOn(dialog).open()).toThrow(TypeError);
    expect(document.body.style.position).toBe("");
  });

  it("keeps the page lock when a nested open is refused", () => {
    silenceReports();
    const lower = modalOn(mountDialog());
    lower.open();
    const refused = mountDialog();
    refused.setAttribute("open", "");
    expect(modalOn(refused).open()).toBe(false);
    expect(document.body.style.position).toBe("fixed");
    expect(lower.isOpen()).toBe(true);
  });

  it("closes the rest when an onClosed throws", () => {
    const logged = silenceReports();
    const lower = modalOn(mountDialog());
    const upper = modalOn(mountDialog(), {
      onClosed: () => {
        throw new Error("broken hook");
      },
    });
    lower.open();
    upper.open();
    lower.close();
    expect(upper.state()).toBe("closed");
    expect(lower.state()).toBe("closed");
    expect(document.body.style.position).toBe("");
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("onClosed threw"));
  });

  it("finishes on a cancel the browser will not let it veto", () => {
    vi.useFakeTimers();
    const dialog = mountDialog();
    const dismiss = vi.fn();
    const onClosed = vi.fn();
    const modal = modalOn(dialog, { dismiss, onClosed });
    modal.open();
    dialog.dispatchEvent(new Event("cancel", { cancelable: false }));
    // The browser then closes the dialog.
    dialog.close();
    vi.runAllTimers();
    expect(dismiss).toHaveBeenCalledOnce();
    expect(modal.state()).toBe("closed");
    expect(onClosed).toHaveBeenCalledOnce();
  });
});

describe("removal of a stack", () => {
  it("finishes a lower dialog and the one inside it, topmost first", async () => {
    const closed: string[] = [];
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    modalOn(lower, { onClosed: () => closed.push("lower") }).open();
    modalOn(upper, { onClosed: () => closed.push("upper") }).open();
    lower.remove();
    await Promise.resolve();
    expect(closed).toEqual(["upper", "lower"]);
    expect(isModalOpen()).toBe(false);
    expect(document.body.style.position).toBe("");
  });

  it("closes a modal beside a removed lower one", async () => {
    const lower = mountDialog();
    const upper = modalOn(mountDialog());
    modalOn(lower).open();
    upper.open();
    lower.remove();
    await Promise.resolve();
    expect(upper.state()).toBe("closed");
    expect(document.querySelectorAll(":modal")).toHaveLength(0);
  });

  it("closes nothing on another change to the document", async () => {
    const modal = modalOn(mountDialog());
    modal.open();
    document.body.append(document.createElement("div"));
    await Promise.resolve();
    expect(modal.isOpen()).toBe(true);
  });
});

describe("more focus and dismissal", () => {
  it("focuses the remaining modal's first tabbable without initial focus", () => {
    const opener = mountOpener();
    const lower = mountDialog();
    modalOn(lower).open();
    opener.focus();
    const upper = modalOn(mountDialog());
    upper.open(opener);
    upper.close();
    expect(document.activeElement).toBe(first(lower));
  });

  it("keeps the lower modal on a backdrop press of a nested one", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    const lowerModal = modalOn(lower);
    const upperModal = modalOn(upper);
    lowerModal.open();
    upperModal.open();
    pointer("pointerdown", upper);
    pointer("pointerup", upper);
    expect(upperModal.isOpen()).toBe(false);
    expect(lowerModal.isOpen()).toBe(true);
  });

  it("refuses a second attach to one dialog", () => {
    const dialog = mountDialog();
    modalOn(dialog);
    expect(() => modalOn(dialog)).toThrow(TypeError);
  });

  it("wraps Tab back in when focus sits outside", () => {
    const opener = mountOpener();
    const dialog = mountDialog();
    modalOn(dialog).open();
    opener.focus();
    expect(pressTab(dialog).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(first(dialog));
  });

  it("marks a middle modal both covered and over", () => {
    const dialogs = [mountDialog(), mountDialog(), mountDialog()];
    for (const dialog of dialogs) modalOn(dialog).open();
    const marks = dialogs.map((dialog) => [
      dialog.hasAttribute("data-modal-covered"),
      dialog.hasAttribute("data-modal-over"),
    ]);
    expect(marks).toEqual([
      [true, false],
      [true, true],
      [false, true],
    ]);
  });

  it("reports its state through a leave", () => {
    let finish = (): void => {};
    const modal = modalOn(mountDialog(), {
      leave: (done) => {
        finish = done;
      },
    });
    expect(modal.state()).toBe("closed");
    modal.open();
    expect(modal.state()).toBe("open");
    modal.close();
    expect(modal.state()).toBe("leaving");
    finish();
    expect(modal.state()).toBe("closed");
  });
});
