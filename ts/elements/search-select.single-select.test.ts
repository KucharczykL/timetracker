// @vitest-environment jsdom
//
// The single-select text/value contract: a value is committed only by an
// explicit pick; the first edit of a committed field clears it; focus keeps
// the box text (selecting a committed label, caret-at-end for a retained
// query). Blur is covered e2e (jsdom focus semantics are too loose for it).
import { describe, it, expect } from "vitest";
import "./search-select.js"; // side effect: customElements.define
import type { SearchSelectChangeDetail } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface CommittedSeed {
  value: string;
  label: string;
}

interface StatefulHost extends HTMLElement {
  _searchSelectDirty?: boolean;
}

function mountSingle(committed: CommittedSeed | null): StatefulHost {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as StatefulHost;
  host.setAttribute("name", "device");
  host.setAttribute("multi", "false");
  const hidden = committed
    ? `<input type="hidden" name="device" value="${committed.value}">`
    : "";
  host.innerHTML = `
    <div data-search-select-pills>${hidden}</div>
    <input data-search-select-search value="${committed?.label ?? ""}" />
    <div data-search-select-options></div>
  `;
  document.body.appendChild(host); // connectedCallback → initWidget
  return host;
}

function searchBox(host: HTMLElement): HTMLInputElement {
  return host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
}

function committedHidden(host: HTMLElement): HTMLInputElement | null {
  return host.querySelector<HTMLInputElement>(
    '[data-search-select-pills] input[type="hidden"]',
  );
}

function collectChanges(host: HTMLElement): SearchSelectChangeDetail[] {
  const details: SearchSelectChangeDetail[] = [];
  host.addEventListener("search-select:change", (event) =>
    details.push((event as CustomEvent<SearchSelectChangeDetail>).detail),
  );
  return details;
}

function typeIntoBox(host: HTMLElement, text: string): void {
  const search = searchBox(host);
  search.value = text;
  search.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("single-select first edit clears a committed value", () => {
  it("removes the hidden input and emits one empty change", () => {
    const host = mountSingle({ value: "7", label: "Game A" });
    const details = collectChanges(host);

    typeIntoBox(host, "Game X");

    expect(committedHidden(host)).toBeNull();
    expect(details).toHaveLength(1);
    expect(details[0].values).toEqual([]);
    expect(details[0].last).toBeNull();
  });

  it("later keystrokes are plain query edits without further events", () => {
    const host = mountSingle({ value: "7", label: "Game A" });
    const details = collectChanges(host);

    typeIntoBox(host, "Game X");
    typeIntoBox(host, "Game XY");

    expect(details).toHaveLength(1);
  });

  it("editing an uncommitted field emits no change event", () => {
    const host = mountSingle(null);
    const details = collectChanges(host);

    typeIntoBox(host, "G");

    expect(details).toHaveLength(0);
    expect(host._searchSelectDirty).toBe(true);
  });
});

describe("single-select focus keeps the box text", () => {
  it("a retained query stays dirty with the caret at the end", () => {
    const host = mountSingle(null);
    const search = searchBox(host);
    search.value = "Gam"; // retained from an earlier unpicked edit

    search.dispatchEvent(new Event("focus"));

    expect(host._searchSelectDirty).toBe(true);
    expect(search.selectionStart).toBe(search.value.length);
    expect(search.selectionEnd).toBe(search.value.length);
  });

  it("a committed label is selected whole so a keystroke replaces it", () => {
    const host = mountSingle({ value: "7", label: "Game A" });
    const search = searchBox(host);

    search.dispatchEvent(new Event("focus"));

    expect(host._searchSelectDirty).toBe(false);
    expect(search.selectionStart).toBe(0);
    expect(search.selectionEnd).toBe(search.value.length);
  });
});
