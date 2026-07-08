// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import "./pop-over.js"; // side effect: customElements.define

// The <pop-over> hover/focus tooltip (issue #303) replaces the Flowbite popover.
// jsdom has no layout engine, so positionPanel's coordinates are meaningless
// here — these tests cover the show/hide state machine (the `hidden` attribute)
// driven by hover, focus, and Escape.
function mount(): { host: HTMLElement; panel: HTMLElement } {
  const host = document.createElement("pop-over");
  host.innerHTML = `
    <span data-pop-over-trigger aria-describedby="pid" tabindex="0">word</span>
    <div data-pop-over-panel id="pid" role="tooltip" hidden>the full word</div>`;
  document.body.appendChild(host); // connectedCallback wires the listeners
  const panel = host.querySelector<HTMLElement>("[data-pop-over-panel]")!;
  return { host, panel };
}

describe("<pop-over> tooltip (#303)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("shows on hover and hides on leave", () => {
    const { host, panel } = mount();
    expect(panel.hidden).toBe(true);
    host.dispatchEvent(new MouseEvent("mouseenter"));
    expect(panel.hidden).toBe(false);
    host.dispatchEvent(new MouseEvent("mouseleave"));
    expect(panel.hidden).toBe(true);
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
    const { host, panel } = mount();
    host.dispatchEvent(new FocusEvent("focusin"));
    expect(panel.hidden).toBe(false);
    // relatedTarget is a descendant of the host -> onFocusOut must NOT hide.
    const inner = host.querySelector<HTMLElement>("[data-pop-over-trigger]")!;
    host.dispatchEvent(
      new FocusEvent("focusout", { relatedTarget: inner, bubbles: true }),
    );
    expect(panel.hidden).toBe(false);
  });
});
