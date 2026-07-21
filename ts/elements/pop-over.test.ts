// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import "./pop-over.js"; // side effect: customElements.define

// jsdom has no layout engine, so the positioner's coordinates are meaningless
// here — these tests cover the show/hide state machine (the `hidden` attribute)
// driven by hover, focus, tap, and Escape.
function mount(options: { tap?: boolean } = {}): {
  host: HTMLElement;
  panel: HTMLElement;
  trigger: HTMLElement;
} {
  const tap = options.tap ?? false;
  const host = document.createElement("pop-over");
  host.setAttribute("tap", tap ? "true" : "false");
  const tag = tap ? "button" : "span";
  const triggerAttrs = tap ? 'type="button"' : 'tabindex="0"';
  host.innerHTML = `
    <${tag} data-pop-over-trigger aria-describedby="pid" ${triggerAttrs}>word</${tag}>
    <div data-pop-over-panel id="pid" role="tooltip" hidden>the full word<div data-pop-over-arrow></div></div>`;
  document.body.appendChild(host); // connectedCallback wires the listeners
  const panel = host.querySelector<HTMLElement>("[data-pop-over-panel]")!;
  const trigger = host.querySelector<HTMLElement>("[data-pop-over-trigger]")!;
  return { host, panel, trigger };
}

// jsdom ignores the `pointerType` init on PointerEvent, so build a MouseEvent and
// pin pointerType onto it — the element reads only that field.
function pointer(type: string, pointerType: string, init: EventInit = {}): Event {
  const event = new MouseEvent(type, { bubbles: true, ...init });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  return event;
}

describe("<pop-over> tooltip (hover/focus)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("shows on mouse hover and hides on leave", () => {
    const { host, panel } = mount();
    expect(panel.hidden).toBe(true);
    host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(panel.hidden).toBe(false);
    host.dispatchEvent(pointer("pointerleave", "mouse"));
    expect(panel.hidden).toBe(true);
  });

  it("ignores a touch pointerenter (no hover on touch)", () => {
    const { host, panel } = mount();
    host.dispatchEvent(pointer("pointerenter", "touch"));
    expect(panel.hidden).toBe(true);
  });

  it("pins the arrow to the panel edge facing the trigger on show", () => {
    const { host, panel } = mount();
    host.dispatchEvent(pointer("pointerenter", "mouse"));
    const arrow = panel.querySelector<HTMLElement>("[data-pop-over-arrow]")!;
    expect(arrow.style.top).toBe("-4px");
    expect(arrow.style.bottom).toBe("");
    expect(arrow.style.left).not.toBe("");
  });

  it("shows on focusin and hides on Escape", () => {
    const { host, panel } = mount();
    host.dispatchEvent(new FocusEvent("focusin"));
    expect(panel.hidden).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(panel.hidden).toBe(true);
  });

  it("hides when focus leaves the element entirely", () => {
    const { host, panel } = mount();
    host.dispatchEvent(new FocusEvent("focusin"));
    expect(panel.hidden).toBe(false);
    host.dispatchEvent(
      new FocusEvent("focusout", { relatedTarget: document.body, bubbles: true }),
    );
    expect(panel.hidden).toBe(true);
  });

  it("stays open when focus moves within the element", () => {
    const { host, panel, trigger } = mount();
    host.dispatchEvent(new FocusEvent("focusin"));
    expect(panel.hidden).toBe(false);
    host.dispatchEvent(
      new FocusEvent("focusout", { relatedTarget: trigger, bubbles: true }),
    );
    expect(panel.hidden).toBe(false);
  });
});

describe("<pop-over> tap mode (touch)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("toggles on tap, surviving the focus a tap gives the button", () => {
    const { panel, trigger } = mount({ tap: true });
    // A real tap: pointerdown, the button focuses (focusin), then click.
    trigger.dispatchEvent(pointer("pointerdown", "touch"));
    trigger.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    expect(panel.hidden).toBe(true); // focusin must NOT open on a touch tap
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false); // the click owns the toggle
    // Second tap closes.
    trigger.dispatchEvent(pointer("pointerdown", "touch"));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(true);
  });

  it("keeps mouse hover working and does not close on a mouse click", () => {
    const { host, panel, trigger } = mount({ tap: true });
    host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(panel.hidden).toBe(false);
    trigger.dispatchEvent(pointer("pointerdown", "mouse"));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false); // mouse owns hover; click is inert
  });

  it("opens on keyboard focus and toggles on keyboard activation", () => {
    const { host, panel, trigger } = mount({ tap: true });
    host.dispatchEvent(new FocusEvent("focusin")); // no preceding pointerdown
    expect(panel.hidden).toBe(false);
    // Enter/Space fire a click with no pointerType ("").
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(true);
  });

  it("dismisses on an outside press and on Escape", () => {
    const { panel, trigger } = mount({ tap: true });
    trigger.dispatchEvent(pointer("pointerdown", "touch"));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false);
    document.dispatchEvent(pointer("pointerdown", "touch")); // target = document
    expect(panel.hidden).toBe(true);

    trigger.dispatchEvent(pointer("pointerdown", "touch"));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(panel.hidden).toBe(true);
  });

  it("closes and unwires listeners on disconnect", () => {
    const { host, panel, trigger } = mount({ tap: true });
    trigger.dispatchEvent(pointer("pointerdown", "touch"));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false);
    host.remove(); // disconnectedCallback
    expect(panel.hidden).toBe(true);
    // The outside-press listener is gone: an Escape must not throw or reopen.
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(panel.hidden).toBe(true);
  });
});

describe("<pop-over> hover-only (tap=false)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("does not toggle on click", () => {
    const { panel, trigger } = mount({ tap: false });
    trigger.dispatchEvent(pointer("pointerdown", "touch"));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(true);
  });
});
