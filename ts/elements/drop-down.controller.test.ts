// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { registerBehavior } from "./dropdown-behaviors.js";
import type { MenuController } from "./menu-behavior.js";
import "./drop-down.js";

interface DropdownHost extends HTMLElement {
  open(): void;
  close(): void;
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("<drop-down> behavior-owned controller seam", () => {
  it("uses one custom controller across disconnect/reconnect", () => {
    const open = vi.fn();
    const close = vi.fn();
    const focusFirst = vi.fn();
    const unbind = vi.fn();
    const bindDocument = vi.fn(() => unbind);
    const controller: MenuController = {
      open,
      close,
      isOpen: () => false,
      focusFirst,
      bindDocument,
    };
    const createController = vi.fn(() => controller);
    const wire = vi.fn();
    registerBehavior("test-controller", { createController, wire });

    const host = document.createElement("drop-down") as DropdownHost;
    host.setAttribute("behavior", "test-controller");
    host.setAttribute("placement", "bottom-start");
    host.setAttribute("submenu", "false");
    host.innerHTML = `
      <button data-toggle aria-expanded="false">Open</button>
      <div data-menu hidden>Panel</div>`;

    document.body.appendChild(host);
    host.open();
    host.close();

    expect(createController).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalledTimes(1);
    expect(bindDocument).toHaveBeenCalledTimes(1);
    expect(wire).toHaveBeenCalledWith(
      expect.objectContaining({ host, controller }),
    );

    host.remove();
    expect(close).toHaveBeenCalledTimes(2);
    expect(unbind).toHaveBeenCalledTimes(1);

    document.body.appendChild(host);
    expect(createController).toHaveBeenCalledTimes(1);
    expect(bindDocument).toHaveBeenCalledTimes(2);
  });
});
