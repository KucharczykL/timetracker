// @vitest-environment jsdom
//
// Below sm: the face and the lent widget.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "./search-select.js";
import type { SearchSelectElement } from "./search-select.js";
import type { DropdownElement } from "./drop-down.js";
import { resetModalLayerForTests } from "./modal-layer.js";
import { resetSurfacesForTests } from "./surface-stack.js";
import { setNarrow, sheetHosted } from "../test-setup/search-select-host.js";
import { FORM_DIALOG_CREATED } from "./form-dialog/events.js";

Element.prototype.scrollIntoView = () => {};

interface MountOptions {
  held?: { value: string; label: string };
  multi?: boolean;
  noneLabel?: string;
  revertOnLeave?: boolean;
  narrow?: boolean;
  create?: boolean;
  //: Widget attributes beyond these.
  attributes?: Record<string, string>;
  pills?: string;
  rows?: string;
  label?: boolean;
  //: Runs before the host connects.
  tweak?: (host: HTMLElement) => void;
}

const ROWS = `
  <div data-search-select-option data-value="1" data-label="Deck" role="option"><span data-search-select-label>Deck</span></div>
  <div data-search-select-option data-value="2" data-label="Switch" role="option"><span data-search-select-label>Switch</span></div>`;

interface Mounted {
  host: DropdownElement;
  widget: SearchSelectElement;
  box: HTMLInputElement;
  open: HTMLButtonElement;
  value: HTMLElement;
  faceClear: HTMLButtonElement;
  dialog: HTMLDialogElement;
}

function mount({
  held,
  multi = false,
  noneLabel,
  revertOnLeave = false,
  narrow = true,
  create = false,
  attributes = {},
  pills: pillMarkup,
  rows = ROWS,
  label = true,
  tweak,
}: MountOptions = {}): Mounted {
  document.body.replaceChildren();
  const widget = document.createElement("search-select") as SearchSelectElement;
  widget.setAttribute("name", "platform");
  widget.setAttribute("multi", String(multi));
  if (noneLabel) widget.setAttribute("none-label", noneLabel);
  if (revertOnLeave) widget.setAttribute("revert-on-leave", "true");
  if (create) widget.setAttribute("dialog-create-params", '{"platform": {"field": "platform_hint"}}');
  for (const [attribute, value] of Object.entries(attributes)) widget.setAttribute(attribute, value);
  const pills = pillMarkup ?? (held
    ? (multi
        ? `<span data-pill data-value="${held.value}"><span data-search-select-label>${held.label}</span></span>`
        : "") + `<input type="hidden" name="platform" value="${held.value}">`
    : "");
  widget.innerHTML = `
    <div data-search-select-pills>${pills}</div>
    <input data-search-select-search id="pick" placeholder="Pick one" value="${multi ? "" : (held?.label ?? "")}" />
    <button type="button" data-search-select-clear${held ? "" : " hidden"}>×</button>
    ${create ? '<a href="/new" data-search-select-dialog-create>+</a>' : ""}
    <div data-search-select-panel>
      <div data-search-select-options>
        ${noneLabel ? `<div data-search-select-none-option data-label="${noneLabel}" role="option">${noneLabel}</div>` : ""}
        ${rows}
        <div data-search-select-no-results class="hidden">No results</div>
        <div data-search-select-create hidden><span data-label></span></div>
      </div>
    </div>
    <template data-search-select-template="row"><div data-search-select-option role="option"><span data-search-select-label></span></div></template>
    <template data-search-select-template="pill"><span data-pill><span data-search-select-label></span><button type="button" data-pill-remove>×</button></span></template>`;
  const host = sheetHosted(widget, { create }) as DropdownElement;
  const form = document.createElement("form");
  form.innerHTML = `${label ? '<label for="pick">Platform</label>' : ""}<input name="platform_hint" value="3">`;
  tweak?.(host);
  form.append(host);
  document.body.append(form);
  setNarrow(host, narrow);
  return {
    host,
    widget,
    box: widget.querySelector<HTMLInputElement>("[data-search-select-search]")!,
    open: host.querySelector<HTMLButtonElement>("[data-search-select-face-open]")!,
    value: host.querySelector<HTMLElement>("[data-search-select-face-value]")!,
    faceClear: host.querySelector<HTMLButtonElement>("[data-search-select-face-clear]")!,
    dialog: host.querySelector<HTMLDialogElement>("dialog")!,
  };
}

const row = (widget: HTMLElement, value: string) =>
  widget.querySelector<HTMLElement>(`[data-search-select-option][data-value="${value}"]`)!;

function type(box: HTMLInputElement, text: string): void {
  box.value = text;
  box.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["requestAnimationFrame", "cancelAnimationFrame", "setTimeout", "clearTimeout"],
  });
  // Reduced motion: a close finishes at once.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
  vi.stubGlobal("scrollTo", vi.fn());
});

afterEach(() => {
  document.body.replaceChildren();
  resetSurfacesForTests();
  resetModalLayerForTests();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the face", () => {
  it("names the field and shows the held label", () => {
    const { host, value } = mount({ held: { value: "1", label: "Deck" } });
    expect(value.textContent).toBe("Deck");
    expect(value.hasAttribute("data-placeholder")).toBe(false);
    expect(host.querySelector("[data-search-select-face-name]")!.textContent).toBe("Platform, ");
    expect(host.querySelector("[data-dropdown-sheet-title]")!.textContent).toBe("Platform");
  });

  it("shows the placeholder when nothing is held, none when none is", () => {
    expect(mount().value.textContent).toBe("Pick one");
    expect(mount().value.hasAttribute("data-placeholder")).toBe(true);
    const { widget, value } = mount({ noneLabel: "No platform" });
    widget.holdNone();
    expect(value.textContent).toBe("No platform");
  });

  it("follows a code commit and a silent clear", () => {
    const { widget, value, faceClear } = mount();
    widget.setSelected("2", "Switch");
    expect(value.textContent).toBe("Switch");
    expect(faceClear.hidden).toBe(false);
    widget.clearSelection();
    expect(value.textContent).toBe("Pick one");
    expect(faceClear.hidden).toBe(true);
  });

  it("shows a typed draft as a draft, with its ×", () => {
    const { box, open, value, faceClear } = mount();
    open.click();
    type(box, "Sw");
    expect(value.textContent).toBe("Sw");
    expect(value.hasAttribute("data-draft")).toBe(true);
    expect(value.hasAttribute("data-placeholder")).toBe(false);
    expect(faceClear.hidden).toBe(false);
    row(box.closest("search-select")!, "2").click();
    expect(value.textContent).toBe("Switch");
    expect(value.hasAttribute("data-draft")).toBe(false);
  });

  it("joins a multi-select's labels", () => {
    const { widget, value } = mount({ multi: true, held: { value: "1", label: "Deck" } });
    widget.setSelected("2", "Switch");
    expect(value.textContent).toBe("Deck, Switch");
  });

  it("clears through its × and keeps focus on the face", () => {
    const { widget, open, value, faceClear } = mount({ held: { value: "1", label: "Deck" } });
    const cleared = vi.fn();
    widget.addEventListener("search-select:clear", cleared);
    faceClear.focus();
    faceClear.click();
    expect(cleared).toHaveBeenCalledOnce();
    expect(value.textContent).toBe("Pick one");
    expect(faceClear.hidden).toBe(true);
    expect(document.activeElement).toBe(open);
  });

  it("leaves focus alone on a press", () => {
    const { faceClear } = mount({ held: { value: "1", label: "Deck" } });
    const elsewhere = document.createElement("input");
    document.body.append(elsewhere);
    elsewhere.focus();
    const press = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    faceClear.dispatchEvent(press);
    faceClear.click();
    expect(press.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(elsewhere);
  });

  it("hands a created row from its + to the widget", () => {
    const { host, widget, value } = mount({ create: true });
    const link = host.querySelector("[data-search-select-face-create]")!;
    const event = new CustomEvent(FORM_DIALOG_CREATED, {
      bubbles: true,
      cancelable: true,
      detail: { value: "9", label: "Steam Deck", data: {} },
    });
    link.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(widget.heldLabel()).toBe("Steam Deck");
    expect(value.textContent).toBe("Steam Deck");
  });

  it("follows the +'s source fields", () => {
    const { host } = mount({ create: true });
    const link = host.querySelector("[data-search-select-face-create]")!;
    expect(link.getAttribute("href")).toBe("/new?platform=3");
  });

  it("mirrors the box's disabled and invalid state", async () => {
    const { box, open } = mount();
    box.disabled = true;
    box.setAttribute("aria-invalid", "true");
    await Promise.resolve();
    expect(open.disabled).toBe(true);
    expect(open.getAttribute("aria-invalid")).toBe("true");
    box.disabled = false;
    await Promise.resolve();
    expect(open.disabled).toBe(false);
  });
});

describe("the lent widget", () => {
  it("opens in the sheet with the box focused", () => {
    const { host, widget, box, open, dialog } = mount();
    open.click();
    expect(dialog.open).toBe(true);
    expect(widget.parentElement).toBe(dialog.querySelector("[data-sheet-body]"));
    expect(widget.getAttribute("data-dropdown-host")).toBe("sheet");
    expect(document.activeElement).toBe(box);
    expect(box.getAttribute("aria-expanded")).toBe("true");
    expect(open.getAttribute("aria-expanded")).toBe("true");
    expect(host.isOpen()).toBe(true);
  });

  it("closes on a person's pick and returns focus to the face", () => {
    const { host, widget, open, value, dialog } = mount();
    open.click();
    row(widget, "2").click();
    expect(dialog.open).toBe(false);
    expect(widget.parentElement).toBe(host);
    expect(widget.hasAttribute("data-dropdown-host")).toBe(false);
    expect(value.textContent).toBe("Switch");
    expect(document.activeElement).toBe(open);
    expect(open.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes on Enter over a highlighted row", () => {
    const { widget, box, open, dialog } = mount();
    open.click();
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    const highlighted = widget.querySelector("[data-search-select-highlighted]")!;
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    expect(dialog.open).toBe(false);
    expect(widget.heldLabel()).toBe(highlighted.getAttribute("data-label"));
  });

  it("closes on the none row", () => {
    const { widget, open, value, dialog } = mount({ noneLabel: "No platform" });
    open.click();
    widget.querySelector<HTMLElement>("[data-search-select-none-option]")!.click();
    expect(dialog.open).toBe(false);
    expect(value.textContent).toBe("No platform");
  });

  it("stays open over a code commit", () => {
    const { widget, open, dialog } = mount();
    open.click();
    widget.setSelected("1", "Deck");
    expect(dialog.open).toBe(true);
  });

  it("stays open over a multi-select pick", () => {
    const { widget, open, value, dialog } = mount({ multi: true });
    open.click();
    row(widget, "1").click();
    expect(dialog.open).toBe(true);
    expect(value.textContent).toBe("Deck");
  });

  it("does its leave work once the sheet hides", () => {
    const { host, widget, box, open } = mount({
      held: { value: "1", label: "Deck" },
      revertOnLeave: true,
    });
    open.click();
    type(box, "Sw");
    box.blur();
    expect(widget.heldLabel()).toBeNull();
    host.close();
    expect(widget.heldLabel()).toBe("Deck");
    expect(box.value).toBe("Deck");
  });

  it("opens from its label below sm only", () => {
    const narrow = mount();
    document.querySelector<HTMLLabelElement>("label")!.click();
    expect(narrow.dialog.open).toBe(true);

    const wide = mount({ narrow: false });
    document.querySelector<HTMLLabelElement>("label")!.click();
    expect(wide.dialog.open).toBe(false);
  });

  it("opens anchored when wide, nothing lent", () => {
    const { host, widget, box, dialog } = mount({ narrow: false });
    box.focus();
    expect(host.isOpen()).toBe(true);
    expect(dialog.open).toBe(false);
    expect(widget.parentElement).toBe(host);
  });
});

//: Lets fetch answers land.
async function settle(): Promise<void> {
  for (let step = 0; step < 6; step += 1) await Promise.resolve();
}

function answering(rows: { value: string; label: string }[]): ReturnType<typeof vi.fn> {
  const fetchStub = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(rows.map((row) => ({ ...row, data: {} }))),
    }),
  );
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

const REMOTE = { "search-url": "/api/runs", prefetch: "10" };

describe("the face, more", () => {
  it("rewrites both + links from their source field", () => {
    const { host } = mount({ create: true });
    const links = [...host.querySelectorAll("a[data-search-select-dialog-create]")];
    expect(links).toHaveLength(2);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/new?platform=3",
      "/new?platform=3",
    ]);
    const hint = document.querySelector<HTMLInputElement>('input[name="platform_hint"]')!;
    hint.value = "7";
    hint.dispatchEvent(new Event("input", { bubbles: true }));
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/new?platform=7",
      "/new?platform=7",
    ]);
  });

  it("names a filter's modifier, includes and excludes, never a draft", () => {
    const { box, value } = mount({
      multi: true,
      attributes: { "filter-mode": "true" },
      pills: `
        <span data-pill data-search-select-modifier="NOT_NULL"><span data-search-select-label>(Any)</span></span>
        <span data-pill data-search-select-type="include" data-value="1" data-label="PC"><span data-search-select-label>PC</span></span>
        <span data-pill data-search-select-type="exclude" data-value="2" data-label="Switch"><span data-search-select-label>Switch</span></span>`,
    });
    expect(value.textContent).toBe("(Any), PC, not Switch");
    type(box, "x");
    expect(value.textContent).toBe("(Any), PC, not Switch");
  });

  it("is named by the box's aria-label, else its placeholder", () => {
    const named = mount({ label: false, tweak: (host) =>
      host.querySelector("[data-search-select-search]")!.setAttribute("aria-label", "Console") });
    expect(named.host.querySelector("[data-search-select-face-name]")!.textContent).toBe("Console, ");
    const placeheld = mount({ label: false });
    expect(placeheld.host.querySelector("[data-dropdown-sheet-title]")!.textContent).toBe("Pick one");
  });

  it("mirrors aria-describedby", async () => {
    const { box, open } = mount();
    box.setAttribute("aria-describedby", "help");
    await Promise.resolve();
    expect(open.getAttribute("aria-describedby")).toBe("help");
  });

  it("opens nothing while disabled, by button or label", async () => {
    const { box, open, dialog } = mount();
    box.disabled = true;
    await Promise.resolve();
    open.click();
    document.querySelector("label")!.click();
    expect(dialog.open).toBe(false);
  });

  it("reports a face with no open button, or a × the box lacks", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mount({ tweak: (host) => host.querySelector("[data-search-select-face-open]")!.remove() });
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("no open button"));
    mount({ tweak: (host) => host.querySelector("[data-search-select-clear]")!.remove() });
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("a × the box lacks"));
  });

  it("reports a sheet nothing names", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mount({
      label: false,
      tweak: (host) => host.querySelector("[data-search-select-search]")!.setAttribute("placeholder", ""),
    });
    expect(logged).toHaveBeenCalledWith(expect.stringContaining("no label names its sheet"));
  });
});

describe("the lent widget, more", () => {
  it("closes on a typed create row", () => {
    const { widget, box, open, value, dialog } = mount({ attributes: { create: "select" } });
    open.click();
    type(box, "Wii");
    widget.querySelector<HTMLElement>("[data-search-select-create]")!.click();
    expect(dialog.open).toBe(false);
    expect(value.textContent).toBe("Wii");
  });

  it("commits a late create answer without reopening", async () => {
    let answer: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetchWithEvents",
      vi.fn(() => new Promise<Response>((resolve) => (answer = resolve))),
    );
    const { host, widget, box, open, dialog } = mount({
      attributes: { create: "post", "create-url": "/api/platforms/" },
    });
    open.click();
    type(box, "Wii");
    widget.querySelector<HTMLElement>("[data-search-select-create]")!.click();
    host.close();
    answer(new Response(JSON.stringify({ value: "9", label: "Wii" }), { status: 201 }));
    await settle();
    expect(widget.heldLabel()).toBe("Wii");
    expect(dialog.open).toBe(false);
  });

  it("keeps the draft and the focus across a widening", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const { host, widget, box, open } = mount({
      held: { value: "1", label: "Deck" },
      revertOnLeave: true,
    });
    open.click();
    type(box, "Sw");
    setNarrow(host, false);
    window.dispatchEvent(new Event("resize"));
    vi.runAllTimers();
    expect(host.isOpen()).toBe(true);
    expect(widget.parentElement).toBe(host);
    expect(widget.heldLabel()).toBeNull();
    expect(box.value).toBe("Sw");
    expect(document.activeElement).toBe(box);
  });

  it("drops a pending search when the sheet hides", async () => {
    const fetchStub = answering([{ value: "1", label: "Deck" }]);
    const { host, box, open } = mount({ attributes: REMOTE, rows: "" });
    open.click();
    await settle();
    const asked = fetchStub.mock.calls.length;
    type(box, "x");
    host.close();
    vi.advanceTimersByTime(1000);
    expect(fetchStub.mock.calls.length).toBe(asked);
  });

  it("keeps the sheet open over a sole-option commit", async () => {
    answering([{ value: "4", label: "Run 1" }]);
    const { widget, open, dialog } = mount({
      attributes: { ...REMOTE, "commit-sole-option": "true" },
      rows: "",
    });
    open.click();
    await settle();
    expect(widget.heldLabel()).toBe("Run 1");
    expect(dialog.open).toBe(true);
  });
});
