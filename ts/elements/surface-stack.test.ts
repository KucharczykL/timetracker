// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import {
  hideFromTopLayer,
  openSurfacesForTests,
  pushSurface,
  removeSurface,
  resetSurfacesForTests,
  showInTopLayer,
  type Surface,
  type SurfaceKind,
} from "./surface-stack.js";

const closed: string[] = [];

afterEach(() => {
  resetSurfacesForTests();
  document.body.innerHTML = "";
  closed.length = 0;
});

function host(parent: HTMLElement = document.body): HTMLElement {
  const element = document.createElement("div");
  parent.append(element);
  return element;
}

function surface(name: string, element: HTMLElement, kind: SurfaceKind = "panel"): Surface {
  const result: Surface = {
    host: element,
    kind,
    close: () => {
      closed.push(name);
      removeSurface(result);
    },
  };
  return result;
}

function pressEscape(init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key: "Escape",
    bubbles: true,
    cancelable: true,
    ...init,
  });
  document.body.dispatchEvent(event);
  return event;
}

function pointer(type: string, target: EventTarget, init: PointerEventInit = {}): void {
  target.dispatchEvent(
    new PointerEvent(type, {
      bubbles: true,
      composed: true,
      isPrimary: true,
      button: 0,
      pointerId: 1,
      ...init,
    }),
  );
}

describe("single open", () => {
  it("closes an unrelated panel", () => {
    pushSurface(surface("unrelated", host()));
    const panel = surface("panel", host());
    pushSurface(panel);
    expect(closed).toEqual(["unrelated"]);
    expect(openSurfacesForTests()).toEqual([panel]);
  });

  it("keeps the panel whose host holds the new one", () => {
    const outer = host();
    const ancestor = surface("ancestor", outer);
    const nested = surface("nested", host(outer));
    pushSurface(ancestor);
    pushSurface(nested);
    expect(closed).toEqual([]);
    expect(openSurfacesForTests()).toEqual([ancestor, nested]);
  });

  it("lets a hint close nothing", () => {
    const panel = surface("panel", host());
    pushSurface(panel);
    pushSurface(surface("hint", host(), "hint"));
    expect(closed).toEqual([]);
    expect(openSurfacesForTests()).toHaveLength(2);
  });

  it("closes an unrelated hint when a panel opens", () => {
    pushSurface(surface("hint", host(), "hint"));
    pushSurface(surface("panel", host()));
    expect(closed).toEqual(["hint"]);
  });

  it("closes panels outside a modal", () => {
    const dialog = host();
    pushSurface(surface("outside", host()));
    const modal = surface("modal", dialog, "modal");
    pushSurface(modal);
    pushSurface(surface("inside", host(dialog)));
    expect(closed).toEqual(["outside"]);
    expect(openSurfacesForTests()[0]).toBe(modal);
  });

  it("moves nothing on a second push", () => {
    const first = surface("first", host());
    pushSurface(first);
    pushSurface(first);
    expect(openSurfacesForTests()).toEqual([first]);
  });
});

describe("removal", () => {
  it("closes nested surfaces first, topmost first", () => {
    const parentHost = host();
    const childHost = host(parentHost);
    const parent = surface("parent", parentHost);
    pushSurface(parent);
    pushSurface(surface("child", childHost));
    pushSurface(surface("grandchild", host(childHost)));
    parent.close();
    expect(closed).toEqual(["parent", "grandchild", "child"]);
    expect(openSurfacesForTests()).toEqual([]);
  });

  it("is idempotent", () => {
    const panel = surface("panel", host());
    pushSurface(panel);
    removeSurface(panel);
    removeSurface(panel);
    expect(openSurfacesForTests()).toEqual([]);
  });
});

describe("Escape", () => {
  it("closes only the topmost and marks the key spent", () => {
    const outer = host();
    pushSurface(surface("outer", outer));
    pushSurface(surface("inner", host(outer)));
    const event = pressEscape();
    expect(closed).toEqual(["inner"]);
    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves the key unspent with nothing open", () => {
    expect(pressEscape().defaultPrevented).toBe(false);
  });

  it.each([{ isComposing: true }, { repeat: true }])("ignores %o", (init) => {
    pushSurface(surface("panel", host()));
    expect(pressEscape(init).defaultPrevented).toBe(false);
    expect(closed).toEqual([]);
  });

  it("closes a panel over a modal and spends the key", () => {
    const dialog = host();
    pushSurface(surface("modal", dialog, "modal"));
    pushSurface(surface("panel", host(dialog)));
    expect(pressEscape().defaultPrevented).toBe(true);
    expect(closed).toEqual(["panel"]);
  });

  it("leaves a modal on top to its own cancel", () => {
    pushSurface(surface("modal", host(), "modal"));
    expect(pressEscape().defaultPrevented).toBe(false);
    expect(closed).toEqual([]);
  });

  it("restores focus before the surface closes", () => {
    const panelHost = host();
    const input = document.createElement("input");
    panelHost.append(input);
    input.focus();
    const order: string[] = [];
    const panel: Surface = {
      host: panelHost,
      kind: "panel",
      close: () => order.push("close"),
      restoreFocus: () => order.push(`focus inside: ${panelHost.contains(document.activeElement)}`),
    };
    pushSurface(panel);
    pressEscape();
    expect(order).toEqual(["focus inside: true", "close"]);
  });
});

describe("outside press", () => {
  it("closes only the surfaces above the pressed one", () => {
    const outer = host();
    const innerHost = host(outer);
    pushSurface(surface("outer", outer));
    pushSurface(surface("inner", innerHost));
    pushSurface(surface("innermost", host(innerHost)));
    pointer("pointerdown", innerHost);
    pointer("pointerup", innerHost);
    expect(closed).toEqual(["innermost"]);
  });

  it("closes every surface on a press outside all", () => {
    pushSurface(surface("panel", host()));
    pushSurface(surface("hint", host(), "hint"));
    const outside = host();
    pointer("pointerdown", outside);
    pointer("pointerup", outside);
    expect(closed).toEqual(["hint", "panel"]);
  });

  it("closes nothing on pointerdown alone", () => {
    pushSurface(surface("panel", host()));
    pointer("pointerdown", document.body);
    expect(closed).toEqual([]);
  });

  it("discards a press the browser cancels", () => {
    pushSurface(surface("panel", host()));
    pointer("pointerdown", document.body);
    pointer("pointercancel", document.body);
    pointer("pointerup", document.body);
    expect(closed).toEqual([]);
  });

  it("ignores a pointerup of another pointer", () => {
    pushSurface(surface("panel", host()));
    pointer("pointerdown", document.body);
    pointer("pointerup", document.body, { pointerId: 2 });
    expect(closed).toEqual([]);
  });

  it("ignores a secondary button", () => {
    pushSurface(surface("panel", host()));
    pointer("pointerdown", document.body, { button: 2 });
    pointer("pointerup", document.body, { button: 2 });
    expect(closed).toEqual([]);
  });

  it("counts a target detached by its own handler as inside", () => {
    const panelHost = host();
    const item = document.createElement("button");
    panelHost.append(item);
    pushSurface(surface("panel", panelHost));
    pointer("pointerdown", item);
    item.remove();
    pointer("pointerup", document.body);
    expect(closed).toEqual([]);
  });

  it("closes the panels above a pressed modal and keeps it", () => {
    const dialog = host();
    pushSurface(surface("modal", dialog, "modal"));
    pushSurface(surface("panel", host(dialog)));
    pointer("pointerdown", dialog);
    pointer("pointerup", dialog);
    expect(closed).toEqual(["panel"]);
    expect(openSurfacesForTests().map((open) => open.kind)).toEqual(["modal"]);
  });

  it("never closes a modal", () => {
    pushSurface(surface("modal", host(), "modal"));
    pointer("pointerdown", document.body);
    pointer("pointerup", document.body);
    expect(closed).toEqual([]);
  });

  it("lets a pressed hint shield no panel beneath it", () => {
    pushSurface(surface("panel", host()));
    const hintHost = host();
    pushSurface(surface("hint", hintHost, "hint"));
    pointer("pointerdown", hintHost);
    pointer("pointerup", hintHost);
    expect(closed).toEqual(["panel"]);
    expect(openSurfacesForTests().map((open) => open.kind)).toEqual(["hint"]);
  });

  it("ignores a press that is not the primary pointer", () => {
    pushSurface(surface("panel", host()));
    pointer("pointerdown", document.body, { isPrimary: false });
    pointer("pointerup", document.body, { isPrimary: false });
    expect(closed).toEqual([]);
  });
});

describe("a close that throws", () => {
  it("still leaves the stack", () => {
    const broken: Surface = {
      host: host(),
      kind: "panel",
      close: () => {
        throw new Error("broken");
      },
    };
    pushSurface(broken);
    const next = surface("next", host());
    expect(() => pushSurface(next)).toThrow("broken");
    expect(openSurfacesForTests()).toEqual([next]);
  });
});

describe("top layer helpers", () => {
  function panel(parent: HTMLElement | null = document.body): HTMLElement {
    const element = document.createElement("div");
    element.setAttribute("popover", "manual");
    element.hidden = true;
    parent?.append(element);
    return element;
  }

  it("shows a connected panel and clears hidden", () => {
    const element = panel();
    expect(showInTopLayer(element)).toBe(true);
    expect(element.hidden).toBe(false);
    hideFromTopLayer(element);
    expect(element.hidden).toBe(true);
  });

  it("refuses a disconnected panel and keeps it hidden", () => {
    const element = panel(null);
    expect(showInTopLayer(element)).toBe(false);
    expect(element.hidden).toBe(true);
  });

  it("hides a panel the browser already hid", () => {
    const element = panel();
    showInTopLayer(element);
    element.remove();
    hideFromTopLayer(element);
    expect(element.hidden).toBe(true);
  });

  it("throws for a panel missing its popover attribute", () => {
    const element = panel();
    element.removeAttribute("popover");
    expect(() => showInTopLayer(element)).toThrow();
  });
});
