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
  _searchSelectSetSelected?: (value: string, label?: string) => void;
  _searchSelectClear?: () => void;
}

function mountSingle(
  committed: CommittedSeed | null,
  { statusSpan = false, multi = false, filterMode = false } = {},
): StatefulHost {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as StatefulHost;
  host.setAttribute("name", "device");
  host.setAttribute("multi", String(multi));
  if (filterMode) host.setAttribute("filter-mode", "true");
  const hidden = committed
    ? `<input type="hidden" name="device" value="${committed.value}">`
    : "";
  // statusSpan reproduces the committed_marker=True server markup (#450); the
  // span's presence is the JS's opt-in signal for the uncommitted cue.
  const status = statusSpan
    ? '<span data-search-select-status role="status" class="sr-only"></span>'
    : "";
  host.innerHTML = `
    <div data-search-select-pills>${hidden}</div>
    <input data-search-select-search value="${committed?.label ?? ""}" />
    ${status}
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

describe("uncommitted cue (#450, committed_marker widgets)", () => {
  const statusOf = (host: HTMLElement): HTMLElement =>
    host.querySelector<HTMLElement>("[data-search-select-status]")!;

  it("first edit of a committed value sets the attribute and status text", () => {
    const host = mountSingle({ value: "7", label: "Game A" }, { statusSpan: true });
    expect(host.hasAttribute("data-uncommitted")).toBe(false);
    expect(statusOf(host).textContent).toBe("");

    typeIntoBox(host, "Game A"); // re-typing the committed label commits nothing

    expect(host.hasAttribute("data-uncommitted")).toBe(true);
    expect(statusOf(host).textContent).toBe("No option selected");
  });

  it("later keystrokes cause no further status-span mutations", () => {
    const host = mountSingle({ value: "7", label: "Game A" }, { statusSpan: true });
    typeIntoBox(host, "Game X");

    const observer = new MutationObserver(() => {});
    observer.observe(statusOf(host), {
      childList: true,
      characterData: true,
      subtree: true,
    });
    typeIntoBox(host, "Game XY");
    typeIntoBox(host, "Game XYZ");

    expect(observer.takeRecords()).toHaveLength(0);
    observer.disconnect();
    expect(host.hasAttribute("data-uncommitted")).toBe(true);
  });

  it("typing into a never-committed field sets the cue too", () => {
    const host = mountSingle(null, { statusSpan: true });

    typeIntoBox(host, "G");

    expect(host.hasAttribute("data-uncommitted")).toBe(true);
    expect(statusOf(host).textContent).toBe("No option selected");
  });

  it("a pick clears the cue and empties the status text", () => {
    const host = mountSingle({ value: "7", label: "Game A" }, { statusSpan: true });
    typeIntoBox(host, "Game B");
    expect(host.hasAttribute("data-uncommitted")).toBe(true);

    host._searchSelectSetSelected!("8", "Game B");

    expect(host.hasAttribute("data-uncommitted")).toBe(false);
    expect(statusOf(host).textContent).toBe("");
  });

  it("clearSelection removes the cue with the text", () => {
    const host = mountSingle({ value: "7", label: "Game A" }, { statusSpan: true });
    typeIntoBox(host, "Game B");

    host._searchSelectClear!();

    expect(host.hasAttribute("data-uncommitted")).toBe(false);
    expect(statusOf(host).textContent).toBe("");
  });

  it("an empty box at rest carries no cue", () => {
    const host = mountSingle(null, { statusSpan: true });
    expect(host.hasAttribute("data-uncommitted")).toBe(false);
  });

  it("no status span (no committed_marker) → no attribute ever", () => {
    const host = mountSingle({ value: "7", label: "Game A" });

    typeIntoBox(host, "Game X");

    expect(host.hasAttribute("data-uncommitted")).toBe(false);
  });

  it("multi/filter modes never get the attribute even with a span", () => {
    const multiHost = mountSingle(null, { statusSpan: true, multi: true });
    typeIntoBox(multiHost, "Game X");
    expect(multiHost.hasAttribute("data-uncommitted")).toBe(false);

    const filterHost = mountSingle(null, { statusSpan: true, filterMode: true });
    typeIntoBox(filterHost, "Game X");
    expect(filterHost.hasAttribute("data-uncommitted")).toBe(false);
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
