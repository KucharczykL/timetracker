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
