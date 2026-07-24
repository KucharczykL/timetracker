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

function mountDisabledControl(): {
  host: HTMLElement;
  panel: HTMLElement;
  trigger: HTMLElement;
  control: HTMLButtonElement;
} {
  const host = document.createElement("pop-over");
  host.setAttribute("tap", "true");
  host.innerHTML = `
    <span data-pop-over-trigger role="button" aria-disabled="true" tabindex="0" aria-describedby="pid">
      <button type="button" data-pop-over-control disabled aria-hidden="true" class="pointer-events-none">word</button>
    </span>
    <div data-pop-over-panel id="pid" role="tooltip" hidden>why unavailable<div data-pop-over-arrow></div></div>`;
  document.body.appendChild(host);
  return {
    host,
    panel: host.querySelector<HTMLElement>("[data-pop-over-panel]")!,
    trigger: host.querySelector<HTMLElement>("[data-pop-over-trigger]")!,
    control: host.querySelector<HTMLButtonElement>("[data-pop-over-control]")!,
  };
}

// jsdom ignores the `pointerType` init on PointerEvent, so build a MouseEvent and
// pin pointerType onto it — the element reads only that field.
function pointer(type: string, pointerType: string, init: EventInit = {}): Event {
  const event = new MouseEvent(type, { bubbles: true, ...init });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  return event;
}

function setRect(
  element: HTMLElement,
  { x, y = 100, width, height = 24 }: Partial<DOMRect> & {
    x: number;
    width: number;
  },
): void {
  element.getBoundingClientRect = () =>
    ({
      x,
      y,
      width,
      height,
      top: y,
      right: x + width,
      bottom: y + height,
      left: x,
      toJSON: () => ({}),
    }) as DOMRect;
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

  it("continues to use the host as its positioning anchor by default", () => {
    const { host, panel, trigger } = mount();
    setRect(host, { x: 200, width: 100 });
    setRect(trigger, { x: 20, width: 20 });
    setRect(panel, { x: 0, y: 0, width: 100, height: 40 });
    Object.defineProperties(panel, {
      offsetWidth: { configurable: true, value: 100 },
      offsetHeight: { configurable: true, value: 40 },
      scrollHeight: { configurable: true, value: 40 },
    });

    host.dispatchEvent(pointer("pointerenter", "mouse"));

    expect(panel.style.left).toBe("200px");
  });

  it("shows on focusin and hides on Escape", () => {
    const { host, panel } = mount();
    host.dispatchEvent(new FocusEvent("focusin"));
    expect(panel.hidden).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(panel.hidden).toBe(true);
  });

  it("explains a disabled control through its separate hover/focus trigger", () => {
    const { host, panel, trigger, control } = mountDisabledControl();

    expect(control.disabled).toBe(true);
    expect(trigger.tabIndex).toBe(0);
    host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(panel.hidden).toBe(false);
    host.dispatchEvent(pointer("pointerleave", "mouse"));
    expect(panel.hidden).toBe(true);
    trigger.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    expect(panel.hidden).toBe(false);
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

  it("explains a disabled control on a touch tap via its wrapper trigger", () => {
    const { panel, trigger } = mountDisabledControl();
    // Browsers never dispatch `click` on a disabled button, so the button
    // carries `pointer-events-none` and the wrapper span is the tap target —
    // the same sequence a real tap produces on the wrapper.
    trigger.dispatchEvent(pointer("pointerdown", "touch"));
    trigger.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    expect(panel.hidden).toBe(true); // focusin must NOT open on a touch tap
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false);
  });

  it("keeps mouse hover working and does not close on a mouse click", () => {
    const { host, panel, trigger } = mount({ tap: true });
    host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(panel.hidden).toBe(false);
    trigger.dispatchEvent(pointer("pointerdown", "mouse"));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false); // mouse owns hover; click is inert
  });

  it("reopens when a hovered trigger is re-enabled without pointer movement", async () => {
    const { host, panel, trigger } = mount({ tap: true });
    host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(panel.hidden).toBe(false);

    trigger.setAttribute("disabled", "");
    await Promise.resolve();
    expect(panel.hidden).toBe(true);

    trigger.removeAttribute("disabled");
    await Promise.resolve();
    expect(panel.hidden).toBe(false);
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
