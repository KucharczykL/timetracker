import { MenuController, MenuOptions } from "./menu-behavior.js";

export interface BehaviorCtx {
  host: HTMLElement;
  toggle: HTMLElement;
  menu: HTMLElement;
  controller: MenuController;
}

export interface DropdownBehavior {
  menuOptions?: (host: HTMLElement) => Partial<MenuOptions>;
  wire?: (ctx: BehaviorCtx) => (() => void) | void;
}

const BEHAVIORS = new Map<string, DropdownBehavior>();

export function registerBehavior(name: string, behavior: DropdownBehavior): void {
  BEHAVIORS.set(name, behavior);
}

export function getBehavior(name: string): DropdownBehavior | undefined {
  return BEHAVIORS.get(name);
}
