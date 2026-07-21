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
}

const BEHAVIORS = new Map<string, DropdownBehavior>();

export function registerBehavior(name: string, behavior: DropdownBehavior): void {
  BEHAVIORS.set(name, behavior);
}

export function getBehavior(name: string): DropdownBehavior | undefined {
  return BEHAVIORS.get(name);
}
