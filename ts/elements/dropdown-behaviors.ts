import { MenuController, MenuOptions } from "./menu-behavior.js";

/** A sheet's first focus inside its panel. */
export type SheetFocus = (menu: HTMLElement) => HTMLElement | null;

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
  sheetFocus?: SheetFocus;
  /** Holds the menu; default: the menu. */
  sheetLent?: (host: HTMLElement, toggle: HTMLElement, menu: HTMLElement) => HTMLElement;
  /** Focus return for an open stating none; wrapped into `defaultOpener`. */
  sheetOpener?: (host: HTMLElement) => HTMLElement | null;
}

const BEHAVIORS = new Map<string, DropdownBehavior>();

export function registerBehavior(name: string, behavior: DropdownBehavior): void {
  BEHAVIORS.set(name, behavior);
}

export function getBehavior(name: string): DropdownBehavior | undefined {
  return BEHAVIORS.get(name);
}
