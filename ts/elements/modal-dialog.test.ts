// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import "./modal-dialog.js"; // side effect: customElements.define

// The <modal-dialog> confirm-overlay element (issue #303) gives the portaled
// delete/refund/split confirm modals the shared dismiss contract they lacked:
// Escape, a backdrop click, and a [data-modal-dismiss] control. Dismissing
// removes the overlay. data-manage="false" keeps it inert (session-actions
// owns the session-reset overlay).
function mount(manage = "true"): HTMLElement {
  const host = document.createElement("modal-dialog");
  host.setAttribute("data-manage", manage);
  host.innerHTML = `
    <div data-modal-panel>
      <button data-modal-dismiss>Cancel</button>
      <button data-keep>Keep</button>
    </div>`;
  document.body.appendChild(host); // connectedCallback wires the dismiss
  return host;
}

describe("<modal-dialog> dismiss contract (#303)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("removes itself on Escape", () => {
    const host = mount();
    expect(host.isConnected).toBe(true);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(host.isConnected).toBe(false);
  });

  it("removes itself on a backdrop press (outside the panel)", () => {
    const host = mount();
    host.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(host.isConnected).toBe(false);
  });

  it("stays open on a press inside the panel", () => {
    const host = mount();
    const panel = host.querySelector<HTMLElement>("[data-modal-panel]")!;
    panel.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(host.isConnected).toBe(true);
  });

  it("removes itself when a [data-modal-dismiss] control is clicked", () => {
    const host = mount();
    host
      .querySelector<HTMLElement>("[data-modal-dismiss]")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(host.isConnected).toBe(false);
  });

  it("data-manage=false is inert (session-actions owns the overlay)", () => {
    const host = mount("false");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    host.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(host.isConnected).toBe(true);
  });
});
