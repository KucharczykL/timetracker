// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  attachModal,
  closeTogether,
  focusReturnTarget,
  isModalLeaving,
  isModalOpen,
  isReachable,
  MODAL_CHANGE,
  openModals,
  resetModalLayerForTests,
  topModal,
  whenSettled,
  type FinishLeave,
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
    const modal = attachModal(dialog);
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
    attachModal(dialog).open();
    expect(document.activeElement).toBe(dismissControl(dialog));

    const other = mountDialog();
    attachModal(other, { initialFocus: () => first(other) }).open();
    expect(document.activeElement).toBe(first(other));
  });

  it("reports and refuses a disconnected host", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const dialog = document.createElement("dialog");
    dialog.setAttribute("data-modal", "");
    expect(attachModal(dialog).open()).toBe(false);
    expect(isModalOpen()).toBe(false);
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("detached"));
  });

  it("reports a refused showModal and leaves nothing locked", () => {
    const dialog = mountDialog();
    dialog.setAttribute("open", "");
    const modal = attachModal(dialog);
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
    const modal = attachModal(dialog);
    modal.open();
    expect(modal.open()).toBe(true);
    expect(changes).toBe(1);
  });
});

describe("nesting", () => {
  it("lists open modals in opening order, leaving ones excluded", () => {
    const lower = mountDialog();
    const upper = mountDialog();
    attachModal(lower).open();
    const upperModal = attachModal(upper, { leave: () => {} });
    upperModal.open();
    expect(openModals()).toEqual([lower, upper]);
    upperModal.close();
    expect(openModals()).toEqual([lower]);
  });

  it("nests a dialog placed inside another", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    attachModal(lower).open();
    attachModal(upper).open();
    expect(topModal()).toBe(upper);
    expect(lower.matches(":modal")).toBe(true);
    expect(openSurfaces().map((surface) => surface.kind)).toEqual(["modal", "modal"]);
  });

  it("nests a dialog placed beside another", () => {
    const lower = mountDialog();
    const upper = mountDialog();
    attachModal(lower).open();
    attachModal(upper).open();
    expect(topModal()).toBe(upper);
    expect(lower.open).toBe(true);
  });

  it("closes the modals above a closing one, topmost first", () => {
    const closed: string[] = [];
    const bottom = attachModal(mountDialog(), { onClosed: () => closed.push("bottom") });
    const middle = attachModal(mountDialog(), { onClosed: () => closed.push("middle") });
    const top = mountDialog();
    bottom.open();
    middle.open();
    attachModal(top, { onClosed: () => closed.push("top") }).open();
    middle.close();
    expect(closed).toEqual(["top", "middle"]);
    expect(top.open).toBe(false);
    expect(bottom.isOpen()).toBe(true);
  });

  it("closes a modal opened above a closing one before it leaves", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower);
    const lowerModal = attachModal(lower, { leave: () => {} });
    lowerModal.open();
    attachModal(upper).open();
    lowerModal.close();
    expect(upper.open).toBe(false);
    expect(document.querySelectorAll(":modal")).toHaveLength(0);
  });
});

describe("scroll lock", () => {
  it("is one lock for the stack", () => {
    const lower = attachModal(mountDialog());
    const upper = attachModal(mountDialog());
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
    const modal = attachModal(mountDialog(), {
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
  it("names the drop-down toggle of an unreachable opener", () => {
    document.body.innerHTML = `
      <drop-down><button data-toggle>Menu</button>
        <div hidden><a href="/edit">Edit</a></div></drop-down>`;
    const item = document.querySelector<HTMLElement>("a")!;
    expect(focusReturnTarget(item)).toBe(document.querySelector("[data-toggle]"));
    expect(focusReturnTarget(null)).toBeNull();
  });

  it("returns focus to the opener", () => {
    const opener = mountOpener();
    const modal = attachModal(mountDialog());
    modal.open(opener);
    modal.close();
    expect(document.activeElement).toBe(opener);
  });

  it("defaults the opener to the focused element", () => {
    const opener = mountOpener();
    opener.focus();
    const modal = attachModal(mountDialog());
    modal.open();
    modal.close();
    expect(document.activeElement).toBe(opener);
  });

  it("returns no focus to a hidden opener", () => {
    const wrapper = document.createElement("div");
    document.body.append(wrapper);
    const opener = mountOpener(wrapper);
    const modal = attachModal(mountDialog());
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
    const modal = attachModal(mountDialog());
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
    const modal = attachModal(mountDialog());
    modal.open(document.querySelector<HTMLElement>("[data-item]")!);
    modal.close();
    expect(document.activeElement?.id).toBe("outer-toggle");
  });

  it("focuses the remaining modal when the opener sits outside it", () => {
    const opener = mountOpener();
    const lower = mountDialog();
    attachModal(lower, { initialFocus: () => first(lower) }).open();
    const upper = attachModal(mountDialog());
    upper.open(opener);
    upper.close();
    expect(document.activeElement).toBe(first(lower));
  });

  it("returns focus inside the remaining modal to the opener there", () => {
    const lower = mountDialog();
    attachModal(lower).open();
    const upper = attachModal(mountDialog());
    upper.open(dismissControl(lower));
    upper.close();
    expect(document.activeElement).toBe(dismissControl(lower));
  });

  it("lets onClosed move focus last", () => {
    const opener = mountOpener();
    const elsewhere = mountOpener();
    const modal = attachModal(mountDialog(), { onClosed: () => elsewhere.focus() });
    modal.open(opener);
    modal.close();
    expect(document.activeElement).toBe(elsewhere);
  });
});

describe("dismissal", () => {
  it("prevents cancel and dismisses", () => {
    const dialog = mountDialog();
    const modal = attachModal(dialog);
    modal.open();
    expect(cancel(dialog).defaultPrevented).toBe(true);
    expect(modal.isOpen()).toBe(false);
  });

  it("lets dismiss veto a cancel", () => {
    const dialog = mountDialog();
    const dismiss = vi.fn();
    const modal = attachModal(dialog, { dismiss });
    modal.open();
    cancel(dialog);
    expect(dismiss).toHaveBeenCalledOnce();
    expect(modal.isOpen()).toBe(true);
  });

  it("dismisses on a press that starts and ends on the backdrop", () => {
    const dialog = mountDialog();
    const modal = attachModal(dialog);
    modal.open();
    pointer("pointerdown", dialog);
    pointer("pointerup", dialog);
    expect(modal.isOpen()).toBe(false);
  });

  it("keeps the modal on a press that starts inside the panel", () => {
    const dialog = mountDialog();
    const modal = attachModal(dialog);
    modal.open();
    pointer("pointerdown", first(dialog));
    pointer("pointerup", dialog);
    expect(modal.isOpen()).toBe(true);
  });

  it("keeps the modal when the browser cancels the press", () => {
    const dialog = mountDialog();
    const modal = attachModal(dialog);
    modal.open();
    pointer("pointerdown", dialog);
    pointer("pointercancel", dialog);
    pointer("pointerup", dialog);
    expect(modal.isOpen()).toBe(true);
  });

  it("keeps the modal on another pointer's release", () => {
    const dialog = mountDialog();
    const modal = attachModal(dialog);
    modal.open();
    pointer("pointerdown", dialog, 1);
    pointer("pointerup", dialog, 2);
    expect(modal.isOpen()).toBe(true);
  });

  it("dismisses on a click on [data-modal-dismiss]", () => {
    const dialog = mountDialog();
    const modal = attachModal(dialog);
    modal.open();
    dismissControl(dialog).click();
    expect(modal.isOpen()).toBe(false);
  });

  it("leaves a nested dialog's dismiss control to it", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    const lowerModal = attachModal(lower);
    const upperModal = attachModal(upper);
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
    attachModal(dialog).open();
    dismissControl(dialog).focus();
    expect(pressTab(dismissControl(dialog)).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(first(dialog));
    pressTab(first(dialog), true);
    expect(document.activeElement).toBe(dismissControl(dialog));
  });

  it("skips tabbables of a nested dialog", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    attachModal(lower).open();
    attachModal(upper).open();
    dismissControl(upper).focus();
    pressTab(dismissControl(upper));
    expect(document.activeElement).toBe(first(upper));
  });

  it("does nothing in a modal that is not the top one", () => {
    const lower = mountDialog();
    attachModal(lower).open();
    attachModal(mountDialog()).open();
    dismissControl(lower).focus();
    expect(pressTab(dismissControl(lower)).defaultPrevented).toBe(false);
  });
});

describe("leave", () => {
  it("keeps the dialog shown until finish", () => {
    let finish = (): void => {};
    const dialog = mountDialog();
    const onClosed = vi.fn();
    const modal = attachModal(dialog, {
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
    const modal = attachModal(dialog, { leave: (done) => done() });
    modal.open();
    modal.close();
    expect(dialog.open).toBe(false);
  });

  it("ignores close during a leave", () => {
    const leave = vi.fn();
    const dialog = mountDialog();
    const modal = attachModal(dialog, { leave });
    modal.open();
    modal.close();
    modal.close();
    expect(leave).toHaveBeenCalledOnce();
    expect(dialog.open).toBe(true);
  });

  it("finishes a leave when the host is gone", () => {
    const dialog = mountDialog();
    const modal = attachModal(dialog, { leave: () => {} });
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
    const modal = attachModal(dialog, { leave });
    modal.open();
    dialog.remove();
    modal.close();
    expect(leave).not.toHaveBeenCalled();
    expect(dialog.open).toBe(false);
  });

  it("refuses to open while a modal leaves", () => {
    const leaving = attachModal(mountDialog(), { leave: () => {} });
    leaving.open();
    leaving.close();
    expect(attachModal(mountDialog()).open()).toBe(false);
  });

  it("ignores a late finish after a reopen", () => {
    let finish = (): void => {};
    const dialog = mountDialog();
    const modal = attachModal(dialog, {
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
    const modal = attachModal(dialog, { onClosed });
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
    const modal = attachModal(dialog);
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
    attachModal(lower).open();
    const upperModal = attachModal(upper);
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
    const modal = attachModal(dialog, { onClosed });
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
    const lowerModal = attachModal(lower);
    const upperModal = attachModal(upper, {
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
    const lower = attachModal(mountDialog());
    const upper = attachModal(mountDialog());
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
    const modal = attachModal(mountDialog(), {
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
    const modal = attachModal(dialog, { leave: () => {} });
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
    const modal = attachModal(mountDialog(), {
      leave: () => {
        throw new Error("broken slide");
      },
    });
    modal.open();
    modal.close();
    expect(modal.state()).toBe("closed");
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("leave threw"));
    expect(attachModal(mountDialog()).open()).toBe(true);
  });

  it("finishes a leave that never calls finish", () => {
    vi.useFakeTimers();
    const logged = silenceReports();
    const dialog = mountDialog();
    const modal = attachModal(dialog, { leave: () => {} });
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
    const modal = attachModal(dialog);
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
    expect(() => attachModal(dialog).open()).toThrow(TypeError);
    expect(document.body.style.position).toBe("");
  });

  it("keeps the page lock when a nested open is refused", () => {
    silenceReports();
    const lower = attachModal(mountDialog());
    lower.open();
    const refused = mountDialog();
    refused.setAttribute("open", "");
    expect(attachModal(refused).open()).toBe(false);
    expect(document.body.style.position).toBe("fixed");
    expect(lower.isOpen()).toBe(true);
  });

  it("closes the rest when an onClosed throws", () => {
    const logged = silenceReports();
    const lower = attachModal(mountDialog());
    const upper = attachModal(mountDialog(), {
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

  it("skips dismiss on a cancel it cannot veto", () => {
    vi.useFakeTimers();
    const dialog = mountDialog();
    const dismiss = vi.fn();
    const onClosed = vi.fn();
    const modal = attachModal(dialog, { dismiss, onClosed });
    modal.open();
    dialog.dispatchEvent(new Event("cancel", { cancelable: false }));
    // The browser then closes the dialog.
    dialog.close();
    vi.runAllTimers();
    expect(dismiss).not.toHaveBeenCalled();
    expect(modal.state()).toBe("closed");
    expect(onClosed).toHaveBeenCalledOnce();
  });
});

describe("removal of a stack", () => {
  it("finishes a lower dialog and the one inside it, topmost first", async () => {
    const closed: string[] = [];
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    attachModal(lower, { onClosed: () => closed.push("lower") }).open();
    attachModal(upper, { onClosed: () => closed.push("upper") }).open();
    lower.remove();
    await Promise.resolve();
    expect(closed).toEqual(["upper", "lower"]);
    expect(isModalOpen()).toBe(false);
    expect(document.body.style.position).toBe("");
  });

  it("closes a modal beside a removed lower one", async () => {
    const lower = mountDialog();
    const upper = attachModal(mountDialog());
    attachModal(lower).open();
    upper.open();
    lower.remove();
    await Promise.resolve();
    expect(upper.state()).toBe("closed");
    expect(document.querySelectorAll(":modal")).toHaveLength(0);
  });

  it("closes nothing on another change to the document", async () => {
    const modal = attachModal(mountDialog());
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
    attachModal(lower).open();
    opener.focus();
    const upper = attachModal(mountDialog());
    upper.open(opener);
    upper.close();
    expect(document.activeElement).toBe(first(lower));
  });

  it("keeps the lower modal on a backdrop press of a nested one", () => {
    const lower = mountDialog();
    const upper = mountDialog(lower.querySelector<HTMLElement>("[data-panel]")!);
    const lowerModal = attachModal(lower);
    const upperModal = attachModal(upper);
    lowerModal.open();
    upperModal.open();
    pointer("pointerdown", upper);
    pointer("pointerup", upper);
    expect(upperModal.isOpen()).toBe(false);
    expect(lowerModal.isOpen()).toBe(true);
  });

  it("refuses a second attach to one dialog", () => {
    const dialog = mountDialog();
    attachModal(dialog);
    expect(() => attachModal(dialog)).toThrow(TypeError);
  });

  it("wraps Tab back in when focus sits outside", () => {
    const opener = mountOpener();
    const dialog = mountDialog();
    attachModal(dialog).open();
    opener.focus();
    expect(pressTab(dialog).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(first(dialog));
  });

  it("marks a middle modal both covered and over", () => {
    const dialogs = [mountDialog(), mountDialog(), mountDialog()];
    for (const dialog of dialogs) attachModal(dialog).open();
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
    const modal = attachModal(mountDialog(), {
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

describe("caller hooks", () => {
  it("routes the backdrop and the dismiss control through dismiss", () => {
    const dialog = mountDialog();
    const dismiss = vi.fn();
    const modal = attachModal(dialog, { dismiss });
    modal.open();
    pointer("pointerdown", dialog);
    pointer("pointerup", dialog);
    dismissControl(dialog).click();
    expect(dismiss).toHaveBeenCalledTimes(2);
    expect(modal.isOpen()).toBe(true);
  });

  it("calls no dismiss during a leave", () => {
    const dialog = mountDialog();
    const dismiss = vi.fn();
    const modal = attachModal(dialog, { dismiss, leave: () => {} });
    modal.open();
    modal.close();
    dismissControl(dialog).click();
    expect(dismiss).not.toHaveBeenCalled();
  });

  it("reports a throwing dismiss and closes anyway", () => {
    const logged = silenceReports();
    const dialog = mountDialog();
    const modal = attachModal(dialog, {
      dismiss: () => {
        throw new Error("broken veto");
      },
    });
    modal.open();
    cancel(dialog);
    expect(modal.state()).toBe("closed");
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("dismiss threw"));
  });

  it("reports a throwing initialFocus and keeps the open whole", () => {
    const logged = silenceReports();
    const dialog = mountDialog();
    dismissControl(dialog).setAttribute("data-modal-initial-focus", "");
    const modal = attachModal(dialog, {
      initialFocus: () => {
        throw new Error("broken focus");
      },
    });
    expect(modal.open()).toBe(true);
    expect(changes).toBe(1);
    expect(document.activeElement).toBe(dismissControl(dialog));
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("initialFocus threw"));
  });

  it("refuses a host that does not hold the dialog", () => {
    const dialog = mountDialog();
    expect(() => attachModal(dialog, { host: mountOpener() })).toThrow(TypeError);
  });
});

describe("reachability", () => {
  it("skips an opener inside a closed dialog", () => {
    const closed = document.createElement("dialog");
    const toggle = document.createElement("button");
    toggle.setAttribute("data-toggle", "");
    const dropdown = document.createElement("drop-down");
    const opener = mountOpener(closed);
    dropdown.append(toggle, closed);
    document.body.append(dropdown);
    const modal = attachModal(mountDialog());
    modal.open(opener);
    modal.close();
    expect(isReachable(opener)).toBe(false);
    expect(document.activeElement).toBe(toggle);
  });

  it("wraps Tab past hidden, disabled and untabbable edges", () => {
    const dialog = mountDialog();
    const panel = dialog.querySelector<HTMLElement>("[data-panel]")!;
    panel.insertAdjacentHTML("afterbegin", '<input disabled><button tabindex="-1">x</button>');
    panel.insertAdjacentHTML("beforeend", "<button hidden>y</button>");
    attachModal(dialog).open();
    dismissControl(dialog).focus();
    pressTab(dismissControl(dialog));
    expect(document.activeElement).toBe(first(dialog));
    pressTab(first(dialog), true);
    expect(document.activeElement).toBe(dismissControl(dialog));
  });

  it("leaves Tab alone in a dialog with nothing to tab to", () => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("data-modal", "");
    dialog.innerHTML = "<p>Text only</p>";
    document.body.append(dialog);
    attachModal(dialog).open();
    expect(pressTab(dialog).defaultPrevented).toBe(false);
  });
});

describe("scrollbar", () => {
  it("pads the body by the scrollbar it hides", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1000);
    vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(985);
    document.body.style.paddingRight = "5px";
    attachModal(mountDialog()).open();
    expect(document.body.style.paddingRight).toBe("20px");
  });
});

describe("whenSettled", () => {
  let finishes: (() => void)[] = [];

  function leavingModal(): { open: () => void; close: () => void } {
    const dialog = mountDialog();
    const modal = attachModal(dialog, { leave: (finish) => finishes.push(finish) });
    return { open: () => modal.open(), close: () => modal.close() };
  }

  beforeEach(() => {
    finishes = [];
  });

  afterEach(() => {
    resetModalLayerForTests();
  });

  it("runs at once when no modal leaves", () => {
    const callback = vi.fn();
    whenSettled(callback);
    expect(callback).toHaveBeenCalledOnce();
  });

  it("waits for every leaving modal", () => {
    const first = leavingModal();
    const second = leavingModal();
    first.open();
    second.open();
    second.close();
    const callback = vi.fn();
    whenSettled(callback);
    first.close();
    finishes[0]();
    expect(callback).not.toHaveBeenCalled();
    finishes[1]();
    expect(callback).toHaveBeenCalledOnce();
  });

  it("reports a callback that throws and runs the rest", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const modal = leavingModal();
    modal.open();
    modal.close();
    const later = vi.fn();
    whenSettled(() => {
      throw new Error("broken");
    });
    whenSettled(later);
    finishes[0]();
    expect(later).toHaveBeenCalledOnce();
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("a settle callback threw"));
  });

  it("cancels a queued callback", () => {
    const modal = leavingModal();
    modal.open();
    modal.close();
    const callback = vi.fn();
    const cancel = whenSettled(callback);
    cancel();
    finishes[0]();
    expect(callback).not.toHaveBeenCalled();
  });

  it("waits for the outermost close, not a modal it closes above", () => {
    const lower = leavingModal();
    const upper = leavingModal();
    lower.open();
    upper.open();
    upper.close();
    const callback = vi.fn(() => expect(openModals()).toEqual([]));
    whenSettled(callback);
    //: Closing the lower one finishes the upper first.
    lower.close();
    expect(callback).not.toHaveBeenCalled();
    finishes.at(-1)!();
    expect(callback).toHaveBeenCalledOnce();
  });

  it("forgets its queue on a test reset", () => {
    const modal = leavingModal();
    modal.open();
    modal.close();
    const callback = vi.fn();
    whenSettled(callback);
    resetModalLayerForTests();
    whenSettled(vi.fn());
    expect(callback).not.toHaveBeenCalled();
  });
});

describe("default leave", () => {
  it("holds a centred modal's close until its fade ends", async () => {
    document.documentElement.style.setProperty("--duration-medium-exit", "160ms");
    const dialog = mountDialog();
    let finishFade: () => void = () => undefined;
    const fade = new Promise<void>((resolve) => {
      finishFade = resolve;
    });
    Object.defineProperty(dialog, "getAnimations", {
      configurable: true,
      value: () => [{ finished: fade }],
    });
    const modal = attachModal(dialog);
    modal.open();

    modal.close();

    expect(dialog.open).toBe(true);
    expect(modal.state()).toBe("leaving");
    expect(dialog.getAttribute("data-motion")).toBe("leaving");

    finishFade();
    await vi.waitFor(() => expect(dialog.open).toBe(false));
    expect(modal.state()).toBe("closed");
    expect(dialog.hasAttribute("data-motion")).toBe(false);
  });
});

describe("cancel", () => {
  it("routes native cancel apart from the backdrop and the dismiss control", () => {
    const dialog = mountDialog();
    const cancelAction = vi.fn();
    const dismiss = vi.fn();
    const modal = attachModal(dialog, { cancel: cancelAction, dismiss });
    modal.open();
    cancel(dialog);
    expect(cancelAction).toHaveBeenCalledOnce();
    expect(dismiss).not.toHaveBeenCalled();
    expect(modal.isOpen()).toBe(true);
    pointer("pointerdown", dialog);
    pointer("pointerup", dialog);
    dismissControl(dialog).click();
    expect(dismiss).toHaveBeenCalledTimes(2);
    expect(cancelAction).toHaveBeenCalledOnce();
  });
});

describe("closeTogether", () => {
  it("runs only the top's leave, finishes top first, and focuses the lowest opener once", () => {
    const leaves: string[] = [];
    const closed: string[] = [];
    let finishTop: FinishLeave = () => {};
    const bottomOpener = mountOpener();
    const middleOpener = mountOpener();
    const topOpener = mountOpener();
    const bottomDialog = mountDialog();
    const middleDialog = mountDialog();
    const bottom = attachModal(bottomDialog, {
      leave: () => leaves.push("bottom"),
      onClosed: () => closed.push("bottom"),
    });
    const middle = attachModal(middleDialog, {
      leave: () => leaves.push("middle"),
      onClosed: () => closed.push("middle"),
    });
    const top = attachModal(mountDialog(), {
      leave: (done) => {
        leaves.push("top");
        finishTop = done;
      },
      onClosed: () => closed.push("top"),
    });
    bottom.open(bottomOpener);
    middle.open(middleOpener);
    top.open(topOpener);
    const bottomFocus = vi.spyOn(bottomOpener, "focus");
    const middleFocus = vi.spyOn(middleOpener, "focus");
    const topFocus = vi.spyOn(topOpener, "focus");
    closeTogether(bottomDialog);
    let settledWith: string[] | null = null;
    whenSettled(() => {
      settledWith = [...closed];
    });
    expect(leaves).toEqual(["top"]);
    expect(isModalLeaving()).toBe(true);
    expect(bottomDialog.open && middleDialog.open).toBe(true);
    expect(settledWith).toBeNull();

    finishTop();
    expect(closed).toEqual(["top", "middle", "bottom"]);
    expect(openModals()).toEqual([]);
    expect(isModalLeaving()).toBe(false);
    expect(bottomFocus).toHaveBeenCalledOnce();
    expect(middleFocus).not.toHaveBeenCalled();
    expect(topFocus).not.toHaveBeenCalled();
    expect(settledWith).toEqual(["top", "middle", "bottom"]);
  });
});

describe("closeAbove focus", () => {
  it("returns no focus to an upper modal closed by a lower one", () => {
    const lower = mountDialog();
    const upper = mountDialog();
    const upperOpener = mountOpener();
    const lowerModal = attachModal(lower);
    const upperModal = attachModal(upper);
    lowerModal.open();
    upperModal.open(upperOpener);
    const focus = vi.spyOn(upperOpener, "focus");
    lowerModal.close();
    expect(upperModal.isOpen()).toBe(false);
    expect(upper.open).toBe(false);
    expect(focus).not.toHaveBeenCalled();
  });
});

describe("sheet levels", () => {
  it("keeps the dim on the dialog below a level", () => {
    const sheet = mountDialog();
    const level = mountDialog();
    level.setAttribute("data-sheet-level", "");
    attachModal(sheet).open();
    attachModal(level).open();
    expect(sheet.hasAttribute("data-modal-covered")).toBe(false);
    expect(level.hasAttribute("data-modal-covered")).toBe(false);
  });

  it("covers a level and the sheet under it when a form sits above", () => {
    const sheet = mountDialog();
    const level = mountDialog();
    level.setAttribute("data-sheet-level", "");
    const form = mountDialog();
    attachModal(sheet).open();
    attachModal(level).open();
    attachModal(form).open();
    expect(sheet.hasAttribute("data-modal-covered")).toBe(true);
    expect(level.hasAttribute("data-modal-covered")).toBe(true);
    expect(form.hasAttribute("data-modal-covered")).toBe(false);
  });

  it("dims a lone level", () => {
    const level = mountDialog();
    level.setAttribute("data-sheet-level", "");
    attachModal(level).open();
    expect(level.hasAttribute("data-modal-covered")).toBe(false);
  });
});
