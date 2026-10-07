import { MenuController, MenuOptions } from "./menu-behavior.js";

export interface BehaviorCtx {
  host: HTMLElement;
  toggle: HTMLElement;
  menu: HTMLElement;
  controller: MenuController;
}

export interface DropdownBehavior {
  menuOptions?: (host: HTMLElement) => Partial<MenuOptions>;
  // Most dropdowns use attachMenu. A presentation that shares the generic
  // trigger/panel shell but is not an anchored ARIA menu (the modal sheet) may
  // supply the same controller contract without adding branches to attachMenu.
  createController?: (
    host: HTMLElement,
    toggle: HTMLElement,
    menu: HTMLElement,
  ) => MenuController;
  wire?: (ctx: BehaviorCtx) => (() => void) | void;
  /** First focus when the panel is a sheet. */
  sheetFocus?: (menu: HTMLElement) => HTMLElement | null;
  /** The node the sheet holds; default the menu. */
  sheetLent?: (host: HTMLElement, toggle: HTMLElement, menu: HTMLElement) => HTMLElement;
  /** Focus return for an open stating none. */
  sheetOpener?: (host: HTMLElement) => HTMLElement | null;
}

const BEHAVIORS = new Map<string, DropdownBehavior>();

export function registerBehavior(name: string, behavior: DropdownBehavior): void {
  BEHAVIORS.set(name, behavior);
}

export function getBehavior(name: string): DropdownBehavior | undefined {
  return BEHAVIORS.get(name);
}
