// @vitest-environment jsdom
//
// The + link: a dialog's created row lands in the picker.
import { beforeEach, describe, expect, it } from "vitest";
import "./search-select.js"; // side effect: customElements.define
import { hosted } from "../test-setup/search-select-host.js";
import { FORM_DIALOG_CREATED } from "./form-dialog/events.js";
import type { SearchSelectChangeDetail } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

const OPTION = { value: "7", label: "Outer Wilds (PC)", data: { platform: "3" } };

function mount(): HTMLElement {
  const host = document.createElement("search-select");
  host.setAttribute("name", "game");
  host.setAttribute("multi", "false");
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search value="" />
    <a href="/game/add" data-form-dialog="">+</a>
    <div data-search-select-options hidden>
      <div data-search-select-no-results class="hidden">No results</div>
    </div>
    <template data-search-select-template="row"><div
      data-search-select-option role="option" aria-selected="false"
    ><span data-search-select-label></span></div></template>`;
  document.body.appendChild(hosted(host));
  return host;
}

function deliver(host: HTMLElement): CustomEvent {
  const event = new CustomEvent(FORM_DIALOG_CREATED, {
    bubbles: true,
    cancelable: true,
    detail: OPTION,
  });
  host.querySelector("a")!.dispatchEvent(event);
  return event;
}

describe("<search-select> created row", () => {
  beforeEach(() => document.body.replaceChildren());

  it("takes nothing when the row cannot land", () => {
    const host = mount();
    // insertBefore then names a node outside the panel.
    host.querySelector("[data-search-select-no-results]")!.remove();
    const errors: unknown[] = [];
    const onError = (event: ErrorEvent): void => {
      errors.push(event.error);
      event.preventDefault();
    };
    window.addEventListener("error", onError);
    const event = deliver(host);
    window.removeEventListener("error", onError);
    expect(errors).toHaveLength(1);
    expect(event.defaultPrevented).toBe(false);
  });

  it("selects the row, announces the change, and takes the event", () => {
    const host = mount();
    const changes: SearchSelectChangeDetail[] = [];
    host.addEventListener("search-select:change", (event) =>
      changes.push((event as CustomEvent<SearchSelectChangeDetail>).detail),
    );
    const event = deliver(host);
    expect(event.defaultPrevented).toBe(true);
    expect(host.querySelector<HTMLInputElement>('input[type="hidden"]')!.value).toBe("7");
    expect(host.querySelector<HTMLInputElement>("[data-search-select-search]")!.value).toBe(
      "Outer Wilds (PC)",
    );
    expect(changes).toHaveLength(1);
    expect(changes[0].values).toEqual(["7"]);
  });

  it("leaves a disabled picker alone", () => {
    const host = mount();
    host.querySelector<HTMLInputElement>("[data-search-select-search]")!.disabled = true;
    const event = deliver(host);
    expect(event.defaultPrevented).toBe(false);
    expect(host.querySelector('input[type="hidden"]')).toBeNull();
  });
});

/** A form whose + reads its name. */
function mountInForm(name: string): { form: HTMLFormElement; host: HTMLElement; field: HTMLInputElement } {
  const form = document.createElement("form");
  form.innerHTML = `<input name="name" value="${name}" />`;
  const host = document.createElement("search-select");
  host.setAttribute("name", "parent");
  host.setAttribute("multi", "false");
  host.setAttribute("dialog-create-params", JSON.stringify({ addon: { field: "name" } }));
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search value="" />
    <a href="/game/add?kind=main" data-search-select-dialog-create="" data-form-dialog="">+</a>
    <div data-search-select-options hidden>
      <div data-search-select-no-results class="hidden">No results</div>
    </div>
    <template data-search-select-template="row"><div
      data-search-select-option role="option" aria-selected="false"
    ><span data-search-select-label></span></div></template>`;
  form.appendChild(hosted(host));
  document.body.appendChild(form);
  return { form, host, field: form.querySelector<HTMLInputElement>('[name="name"]')! };
}

const plusHref = (host: HTMLElement): string =>
  host.querySelector("[data-search-select-dialog-create]")!.getAttribute("href")!;

function type(field: HTMLInputElement, value: string): void {
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("<search-select> + query", () => {
  beforeEach(() => document.body.replaceChildren());

  it("states the field's value on connect", () => {
    const { host } = mountInForm("Dawnguard");
    expect(plusHref(host)).toBe("/game/add?kind=main&addon=Dawnguard");
  });

  it("follows typing in the source field, on the same link", () => {
    const { host, field } = mountInForm("");
    const link = host.querySelector("[data-search-select-dialog-create]");
    type(field, "Hearthfire");
    expect(plusHref(host)).toBe("/game/add?kind=main&addon=Hearthfire");
    expect(host.querySelector("[data-search-select-dialog-create]")).toBe(link);
  });

  it("drops a blank source and keeps the literal", () => {
    const { host, field } = mountInForm("Dawnguard");
    type(field, "");
    expect(plusHref(host)).toBe("/game/add?kind=main");
  });

  it("ignores input in another field", () => {
    const { form, host } = mountInForm("Dawnguard");
    const other = document.createElement("input");
    other.name = "year";
    form.append(other);
    host.querySelector("[data-search-select-dialog-create]")!.setAttribute("href", "/x");
    type(other, "2012");
    expect(plusHref(host)).toBe("/x");
  });

  it("states the value again when inserted anew", () => {
    const { form, host, field } = mountInForm("Dawnguard");
    const hostElement = host.closest("drop-down")!;
    hostElement.remove();
    type(field, "Dragonborn");
    form.append(hostElement);
    expect(plusHref(host)).toBe("/game/add?kind=main&addon=Dragonborn");
  });
});
