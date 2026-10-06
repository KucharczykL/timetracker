/** One accessor over a single-choice picker. */
// Defines <search-select> before any read.
import { reportClientError } from "../client-errors.js";
import {
  heldValue,
  SearchSelectElement,
  type SearchSelectChangeDetail,
  type SearchSelectOptionGroup,
} from "./search-select.js";

//: A host `data-*` attribute naming the control, e.g. "data-fc-op".
export type ChoiceMarker = string;

export interface ChoiceControl {
  readonly element: HTMLElement;
  //: `null`: nothing held, or mid-edit.
  read(): string | null;
  //: Silent; false when no row offers `value`.
  write(value: string): boolean;
  //: Wired pickers only.
  setChoices(groups: SearchSelectOptionGroup[]): void;
  setDisabled(disabled: boolean): void;
}

const PILLS = "[data-search-select-pills]";
const SEARCH = "[data-search-select-search]";

// Template clones stay un-upgraded until connected.
function wired(element: HTMLElement): element is SearchSelectElement {
  return element instanceof SearchSelectElement && element.wired;
}

function escapeValue(value: string): string {
  return value.replace(/["\\]/g, (character) => `\\${character}`);
}

class SearchSelectChoice implements ChoiceControl {
  constructor(readonly element: HTMLElement) {}

  private partless(): boolean {
    if (this.element.querySelector(PILLS) && this.element.querySelector(SEARCH)) return false;
    reportClientError("choice-control", `${this.name()}: a picker without its parts`, {
      toast: false,
    });
    return true;
  }

  private name(): string {
    return this.element.getAttribute("name") ?? "";
  }

  read(): string | null {
    if (this.partless()) return null;
    const value = heldValue(this.element);
    return value ? value : null;
  }

  write(value: string): boolean {
    if (this.partless()) return false;
    const element = this.element;
    if (wired(element)) return element.offers(value) && element.holdValue(value);
    const row = element.querySelector<HTMLElement>(
      `[data-search-select-option][data-value="${escapeValue(value)}"]`,
    );
    if (!row) return false;
    // initWidget adopts this hidden input and the box text.
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = this.name();
    hidden.value = value;
    element.querySelector(PILLS)!.replaceChildren(hidden);
    const search = element.querySelector<HTMLInputElement>(SEARCH)!;
    const label = row.getAttribute("data-label") ?? value;
    search.setAttribute("value", label);
    search.value = label;
    return true;
  }

  setChoices(groups: SearchSelectOptionGroup[]): void {
    const element = this.element;
    if (!wired(element)) throw new Error(`search-select[${this.name()}]: not initialised`);
    element.setOptionGroups(groups);
  }

  setDisabled(disabled: boolean): void {
    const search = this.element.querySelector<HTMLInputElement>(SEARCH);
    if (search) search.disabled = disabled;
  }
}

/** The accessor over one picker. */
export function choiceOf(picker: HTMLElement): ChoiceControl {
  return new SearchSelectChoice(picker);
}

/** The picker carrying, or inside, `marker`. */
export function choiceControl(root: ParentNode, marker: ChoiceMarker): ChoiceControl | null {
  const picker = root.querySelector<HTMLElement>(
    `search-select[${marker}], [${marker}] search-select`,
  );
  return picker ? choiceOf(picker) : null;
}

/** A person picked a row in a `marker` picker. */
export function isChoicePick(event: Event, marker: ChoiceMarker): boolean {
  if (event.type !== "search-select:change") return false;
  const target = event.target;
  if (!(target instanceof Element)) return false;
  if (!target.matches(`search-select[${marker}], [${marker}] search-select`)) return false;
  return (event as CustomEvent<SearchSelectChangeDetail>).detail?.last != null;
}
