// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import "./truncated-text.js";

let resizeCallback: ResizeObserverCallback | null = null;

class FakeResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback;
  }
  observe(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver = FakeResizeObserver as unknown as typeof ResizeObserver;

function pointer(type: string, pointerType: string): Event {
  const event = new MouseEvent(type, { bubbles: true });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  return event;
}

function mount(options: {
  clientWidth?: number;
  scrollWidth?: number;
  linked?: boolean;
  reveal?: "auto" | "always";
} = {}): {
  host: HTMLElement;
  clip: HTMLElement;
  panel: HTMLElement;
  setWidths(clientWidth: number, scrollWidth: number): void;
} {
  let clientWidth = options.clientWidth ?? 100;
  let scrollWidth = options.scrollWidth ?? 100;
  const host = document.createElement("truncated-text");
  host.setAttribute("tap", "true");
  host.setAttribute("reveal", options.reveal ?? "auto");
  const visible = options.linked
    ? '<a href="/game"><span data-truncated-clip>name</span></a>'
    : "<span data-truncated-clip>name</span>";
  host.innerHTML = `${visible}
    <button type="button" data-truncated-reveal></button>
    <div data-pop-over-panel hidden>
      <div data-pop-over-content>full name</div>
      <div data-pop-over-arrow></div>
    </div>`;
  const clip = host.querySelector<HTMLElement>("[data-truncated-clip]")!;
  Object.defineProperties(clip, {
    clientWidth: { configurable: true, get: () => clientWidth },
    scrollWidth: { configurable: true, get: () => scrollWidth },
  });
  document.body.appendChild(host);
  return {
    host,
    clip,
    panel: host.querySelector<HTMLElement>("[data-pop-over-panel]")!,
    setWidths(nextClientWidth: number, nextScrollWidth: number): void {
      clientWidth = nextClientWidth;
      scrollWidth = nextScrollWidth;
    },
  };
}

describe("<truncated-text>", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    resizeCallback = null;
  });

  it("uses a one-pixel epsilon and toggles overflow on resize", () => {
    const mounted = mount({ clientWidth: 100, scrollWidth: 101 });
    expect(mounted.host.hasAttribute("data-overflowing")).toBe(false);

    mounted.setWidths(100, 102);
    resizeCallback?.([], {} as ResizeObserver);
    expect(mounted.host.hasAttribute("data-overflowing")).toBe(true);
  });

  it("gates opening and closes an open panel when text fits again", () => {
    const mounted = mount({ clientWidth: 100, scrollWidth: 100 });
    mounted.host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(mounted.panel.hidden).toBe(true);

    mounted.setWidths(100, 130);
    resizeCallback?.([], {} as ResizeObserver);
    mounted.host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(mounted.panel.hidden).toBe(false);

    mounted.setWidths(140, 140);
    resizeCallback?.([], {} as ResizeObserver);
    expect(mounted.panel.hidden).toBe(true);
    expect(mounted.host.hasAttribute("data-overflowing")).toBe(false);
  });

  it("adds a tab stop only to overflowing unlinked auto text", () => {
    const mounted = mount({ clientWidth: 100, scrollWidth: 130 });
    expect(mounted.clip.getAttribute("tabindex")).toBe("0");

    mounted.setWidths(130, 130);
    resizeCallback?.([], {} as ResizeObserver);
    expect(mounted.clip.hasAttribute("tabindex")).toBe(false);
  });

  it("does not add a managed tab stop when the text has a link", () => {
    const mounted = mount({ clientWidth: 100, scrollWidth: 130, linked: true });
    expect(mounted.clip.hasAttribute("tabindex")).toBe(false);
  });

  it("keeps an always-reveal tooltip active when its text fits", () => {
    const mounted = mount({ reveal: "always" });
    mounted.host.dispatchEvent(pointer("pointerenter", "mouse"));
    expect(mounted.panel.hidden).toBe(false);
  });

  it("remeasures after fonts become ready without a resize", async () => {
    let resolveFonts!: () => void;
    const ready = new Promise<void>((resolve) => {
      resolveFonts = resolve;
    });
    const fontSet = {
      ready,
      addEventListener: (): void => {},
      removeEventListener: (): void => {},
    } as unknown as FontFaceSet;
    Object.defineProperty(document, "fonts", { configurable: true, value: fontSet });

    const mounted = mount({ clientWidth: 100, scrollWidth: 100 });
    mounted.setWidths(100, 130);
    resolveFonts();
    await ready;
    await Promise.resolve();
    expect(mounted.host.hasAttribute("data-overflowing")).toBe(true);
  });
});
