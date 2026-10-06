// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import {
  attachModal,
  refreshModalStack,
  type FinishLeave,
  type Modal,
} from "./modal-layer.js";

afterEach(() => {
  document.body.innerHTML = "";
});

interface Layout {
  /** The panel's layout top, transforms ignored. */
  top?: number;
  /** The header's height. */
  header?: number;
}

interface Mount {
  parent?: HTMLElement;
  role?: "dialog" | "alertdialog";
  leave?: (finish: FinishLeave) => void;
}

interface Stacked {
  dialog: HTMLDialogElement;
  panel: HTMLElement;
  trail: HTMLElement;
  title: HTMLElement;
  modal: Modal;
}

let mounted = 0;

function stub(element: HTMLElement, name: "offsetTop" | "offsetHeight", value: number): void {
  Object.defineProperty(element, name, { configurable: true, get: () => value });
}

function mountStacked(
  name: string,
  { top = 0, header = 44 }: Layout = {},
  { parent = document.body, role = "dialog", leave }: Mount = {},
): Stacked {
  mounted += 1;
  const titleId = `title-${mounted}`;
  const dialog = document.createElement("dialog");
  dialog.setAttribute("data-modal", "");
  dialog.setAttribute("aria-labelledby", titleId);
  if (role === "alertdialog") dialog.setAttribute("role", role);
  dialog.innerHTML = `
    <div data-modal-panel>
      <div data-modal-header>
        <div><p data-modal-trail hidden></p><h2 id="${titleId}">${name}</h2></div>
      </div>
      <div data-body></div>
    </div>
  `;
  parent.append(dialog);
  const panel = dialog.querySelector<HTMLElement>("[data-modal-panel]")!;
  stub(panel, "offsetTop", top);
  stub(dialog.querySelector<HTMLElement>("[data-modal-header]")!, "offsetHeight", header);
  return {
    dialog,
    panel,
    trail: dialog.querySelector<HTMLElement>("[data-modal-trail]")!,
    title: dialog.querySelector<HTMLElement>("h2")!,
    modal: attachModal(dialog, { leave }),
  };
}

function property(panel: HTMLElement, name: string): string {
  return panel.style.getPropertyValue(name);
}

describe("depth", () => {
  it("stamps open modals above on each covered panel", () => {
    const lower = mountStacked("Lower");
    const middle = mountStacked("Middle");
    const top = mountStacked("Top");
    for (const stacked of [lower, middle, top]) stacked.modal.open();
    expect(lower.panel.getAttribute("data-modal-depth")).toBe("2");
    expect(middle.panel.getAttribute("data-modal-depth")).toBe("1");
    expect(top.panel.hasAttribute("data-modal-depth")).toBe(false);
    expect(property(lower.panel, "--modal-depth")).toBe("2");
    expect(property(top.panel, "--modal-depth")).toBe("0");
  });

  it("clears the stamp when the modal above closes", () => {
    const lower = mountStacked("Lower");
    const upper = mountStacked("Upper");
    lower.modal.open();
    upper.modal.open();
    upper.modal.close();
    expect(lower.panel.hasAttribute("data-modal-depth")).toBe(false);
    expect(property(lower.panel, "--modal-shift")).toBe("0px");
  });

  it("steps the lower one forward while the top leaves", () => {
    const lower = mountStacked("Lower");
    const upper = mountStacked("Upper", {}, { leave: () => {} });
    lower.modal.open();
    upper.modal.open();
    upper.modal.close();
    expect(upper.modal.state()).toBe("leaving");
    expect(lower.panel.hasAttribute("data-modal-depth")).toBe(false);
    expect(upper.trail.textContent).toBe("Lower");
  });

  it("clears every value from a closed modal", () => {
    const lower = mountStacked("Lower");
    const upper = mountStacked("Upper");
    lower.modal.open();
    upper.modal.open();
    lower.modal.close();
    for (const stacked of [lower, upper]) {
      expect(stacked.panel.hasAttribute("data-modal-depth")).toBe(false);
      expect(property(stacked.panel, "--modal-shift")).toBe("");
      expect(property(stacked.panel, "--modal-reserve")).toBe("");
      expect(property(stacked.panel, "--modal-depth")).toBe("");
    }
  });
});

describe("geometry", () => {
  it("reserves the scaled strips below each panel", () => {
    const lower = mountStacked("Lower", { header: 40 });
    const middle = mountStacked("Middle", { header: 40 });
    const top = mountStacked("Top", { header: 40 });
    for (const stacked of [lower, middle, top]) stacked.modal.open();
    expect(property(lower.panel, "--modal-reserve")).toBe("0px");
    // depth 2 scales .9: 36px.
    expect(property(middle.panel, "--modal-reserve")).toBe("36px");
    // plus depth 1 at .95: 38px.
    expect(property(top.panel, "--modal-reserve")).toBe("74px");
  });

  it("lifts each covered panel by its scaled strip above the next", () => {
    const lower = mountStacked("Lower", { top: 200, header: 40 });
    const top = mountStacked("Top", { top: 100, header: 40 });
    lower.modal.open();
    top.modal.open();
    expect(property(top.panel, "--modal-shift")).toBe("0px");
    // 100 - 38 = 62; 62 - 200 = -138.
    expect(property(lower.panel, "--modal-shift")).toBe("-138px");
  });

  it("never lowers a panel and follows where it lands", () => {
    const lower = mountStacked("Lower", { top: 300, header: 40 });
    const middle = mountStacked("Middle", { top: 20, header: 40 });
    const top = mountStacked("Top", { top: 100, header: 40 });
    for (const stacked of [lower, middle, top]) stacked.modal.open();
    expect(property(middle.panel, "--modal-shift")).toBe("0px");
    // Middle lands at 20; lower aims 16.
    expect(property(lower.panel, "--modal-shift")).toBe("-316px");
  });

  it("ignores a panel nested in another dialog's DOM", () => {
    const outer = mountStacked("Outer");
    const inner = mountStacked("Inner", {}, {
      parent: outer.dialog.querySelector<HTMLElement>("[data-body]")!,
    });
    outer.modal.open();
    inner.modal.open();
    expect(outer.panel.getAttribute("data-modal-depth")).toBe("1");
    expect(inner.panel.hasAttribute("data-modal-depth")).toBe(false);
    expect(outer.trail.hidden).toBe(true);
    expect(inner.trail.textContent).toBe("Outer");
  });

  it("leaves a dialog without parts alone", () => {
    const bare = document.createElement("dialog");
    bare.setAttribute("data-modal", "");
    document.body.append(bare);
    const plain = attachModal(bare);
    const upper = mountStacked("Upper");
    expect(plain.open()).toBe(true);
    expect(upper.modal.open()).toBe(true);
    expect(upper.trail.hidden).toBe(true);
    upper.modal.close();
    plain.close();
  });
});

describe("trail", () => {
  it("names the modals below on the top one, bottom first", () => {
    const lower = mountStacked("Lower");
    const middle = mountStacked("Middle");
    const top = mountStacked("Top");
    for (const stacked of [lower, middle, top]) stacked.modal.open();
    expect(top.trail.hidden).toBe(false);
    expect(top.trail.textContent).toBe("Lower › , Middle");
    const glyphs = top.trail.querySelectorAll("[aria-hidden='true']");
    expect(Array.from(glyphs, (glyph) => glyph.textContent)).toEqual([" › "]);
    expect(top.trail.querySelector(".sr-only")?.textContent).toBe(", ");
    for (const covered of [lower, middle]) {
      expect(covered.trail.hidden).toBe(true);
      expect(covered.trail.textContent).toBe("");
    }
  });

  it("leads the description of a dialog", () => {
    const lower = mountStacked("Lower");
    const top = mountStacked("Top");
    top.dialog.setAttribute("aria-describedby", "note");
    lower.modal.open();
    top.modal.open();
    const tokens = top.dialog.getAttribute("aria-describedby")!.split(" ");
    expect(tokens).toEqual([top.trail.id, "note"]);
    expect(top.trail.id).not.toBe("");
  });

  it("follows the message of an alertdialog", () => {
    const lower = mountStacked("Lower");
    const warning = mountStacked("Warning", {}, { role: "alertdialog" });
    warning.dialog.setAttribute("aria-describedby", "message");
    lower.modal.open();
    warning.modal.open();
    expect(warning.dialog.getAttribute("aria-describedby")).toBe(
      `message ${warning.trail.id}`,
    );
  });

  it("drops its token when it hides", () => {
    const lower = mountStacked("Lower");
    const middle = mountStacked("Middle");
    const top = mountStacked("Top");
    middle.dialog.setAttribute("aria-describedby", "note");
    lower.modal.open();
    middle.modal.open();
    top.modal.open();
    expect(middle.dialog.getAttribute("aria-describedby")).toBe("note");
    top.modal.close();
    expect(middle.trail.textContent).toBe("Lower");
    lower.modal.close();
    expect(middle.dialog.getAttribute("aria-describedby")).toBe("note");
    expect(top.dialog.hasAttribute("aria-describedby")).toBe(false);
  });

  it("falls back to aria-label and skips a nameless modal", () => {
    const labelled = mountStacked("ignored");
    labelled.dialog.removeAttribute("aria-labelledby");
    labelled.dialog.setAttribute("aria-label", "Bare");
    const nameless = mountStacked("ignored");
    nameless.dialog.removeAttribute("aria-labelledby");
    const top = mountStacked("Top");
    for (const stacked of [labelled, nameless, top]) stacked.modal.open();
    expect(top.trail.textContent).toBe("Bare");
  });

  it("stays hidden on a lone modal", () => {
    const lone = mountStacked("Lone");
    lone.modal.open();
    expect(lone.trail.hidden).toBe(true);
    expect(lone.dialog.hasAttribute("aria-describedby")).toBe(false);
  });

  it("is rebuilt for a new top", () => {
    const lower = mountStacked("Lower");
    const first = mountStacked("First");
    const second = mountStacked("Second");
    lower.modal.open();
    first.modal.open();
    first.modal.close();
    second.modal.open();
    expect(second.trail.textContent).toBe("Lower");
    expect(first.trail.textContent).toBe("");
  });

  it("picks up a renamed title on refresh", () => {
    const lower = mountStacked("Lower");
    const top = mountStacked("Top");
    lower.modal.open();
    top.modal.open();
    lower.title.textContent = "  Renamed ";
    refreshModalStack();
    expect(top.trail.textContent).toBe("Renamed");
  });

  it("refreshes nothing with no modal shown", () => {
    expect(() => refreshModalStack()).not.toThrow();
  });
});
