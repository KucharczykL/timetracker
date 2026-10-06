// Single-select picker markup, as the server renders it.

export interface ChoiceRow {
  value: string;
  label: string;
}

export interface ChoiceRowGroup {
  label: string;
  rows: ChoiceRow[];
}

export interface ChoicePickerMarkup {
  name: string;
  //: A host `data-*` attribute, e.g. "data-fc-op".
  marker?: string;
  rows?: ChoiceRow[];
  groups?: ChoiceRowGroup[];
  held?: string;
  placeholder?: string;
}

const escape = (text: string): string =>
  text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

function row({ value, label }: ChoiceRow): string {
  return (
    `<div role="option" aria-selected="false" data-search-select-option="" ` +
    `data-value="${escape(value)}" data-label="${escape(label)}">` +
    `<span data-search-select-label="">${escape(label)}</span>` +
    `<span data-search-select-hint="" hidden></span></div>`
  );
}

function header(label: string): string {
  return `<div data-search-select-group-header="" role="presentation">${escape(label)}</div>`;
}

/** One `<drop-down>` hosting one picker. */
export function choicePickerHtml(markup: ChoicePickerMarkup): string {
  const groups = markup.groups ?? [{ label: "", rows: markup.rows ?? [] }];
  const all = groups.flatMap((group) => group.rows);
  const held = all.find((candidate) => candidate.value === markup.held);
  const marker = markup.marker ? ` ${markup.marker}=""` : "";
  const hidden = held
    ? `<input type="hidden" name="${escape(markup.name)}" value="${escape(held.value)}">`
    : "";
  const boxValue = held ? ` value="${escape(held.label)}"` : "";
  const rows = groups
    .map((group) => (group.label ? header(group.label) : "") + group.rows.map(row).join(""))
    .join("");
  return (
    `<drop-down placement="bottom-start" submenu="false" behavior="inline-combobox">` +
    `<search-select data-toggle=""${marker} name="${escape(markup.name)}" multi="false" create="" ` +
    `filter-mode="false" free-text="false" always-visible="false" revert-on-leave="true">` +
    `<div data-search-select-box=""><div data-search-select-pills="">${hidden}</div>` +
    `<input data-search-select-search="" placeholder="${escape(markup.placeholder ?? "Choose…")}" ` +
    `autocomplete="off" role="combobox" aria-expanded="false" type="text"${boxValue}>` +
    `<span data-search-select-status="" role="status"></span></div>` +
    `<div data-search-select-panel="" data-menu="" hidden="" popover="manual">` +
    `<div data-search-select-options="" role="listbox" data-menu-scroll="">${rows}` +
    `<div data-search-select-no-results="" role="presentation">No results</div></div></div>` +
    `<template data-search-select-template="row">${row({ value: "", label: "" })}</template>` +
    `<template data-search-select-template="header">${header("")}</template>` +
    `</search-select></drop-down>`
  );
}

/** The picker element out of `choicePickerHtml`. */
export function choicePicker(markup: ChoicePickerMarkup): HTMLElement {
  const holder = document.createElement("div");
  holder.innerHTML = choicePickerHtml(markup);
  return holder.firstElementChild as HTMLElement;
}
