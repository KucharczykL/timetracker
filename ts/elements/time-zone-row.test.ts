// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "./time-zone-row.js";

const REAL_DATE_TIME_FORMAT = Intl.DateTimeFormat;

function stubBrowserZone(timeZone: string): void {
  vi.spyOn(Intl, "DateTimeFormat").mockImplementation((...formatArguments) => {
    const formatter = new REAL_DATE_TIME_FORMAT(...formatArguments);
    const realResolvedOptions = formatter.resolvedOptions.bind(formatter);
    formatter.resolvedOptions = () => ({ ...realResolvedOptions(), timeZone });
    return formatter;
  });
}

function mount({
  storedZone = "",
  displayZone = "Europe/Prague",
  captureDefault = true,
}: { storedZone?: string; displayZone?: string; captureDefault?: boolean } = {}): HTMLElement {
  document.body.innerHTML = `
    <time-zone-row field-name="timestamp_start_timezone"
        stored-zone="${storedZone}" display-zone="${displayZone}"
        capture-default="${captureDefault}" class="block">
      <input type="hidden" name="timestamp_start_timezone"
          value="${storedZone}" data-time-zone-value="">
      <div class="mt-1">
        <button type="button" aria-haspopup="dialog">Start time zone: ${
          storedZone || `${displayZone} (display zone)`
        }<svg></svg></button>
      </div>
    </time-zone-row>`;
  return document.querySelector("time-zone-row")!;
}

function valueInput(host: HTMLElement): HTMLInputElement {
  return host.querySelector<HTMLInputElement>("[data-time-zone-value]")!;
}

function trigger(host: HTMLElement): HTMLButtonElement {
  return host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
}

beforeEach(() => {
  document.body.replaceChildren();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("time-zone-row", () => {
  it("captures the browser zone into an empty input on a new record", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ captureDefault: true });
    expect(valueInput(host).value).toBe("Asia/Tokyo");
  });

  it("leaves an existing record's empty value untouched (NULL stays NULL)", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ captureDefault: false });
    expect(valueInput(host).value).toBe("");
  });

  it("emphasises the trigger when the effective zone disagrees with the browser zone", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(true);
  });

  it("leaves the trigger unemphasised when the zones agree", () => {
    stubBrowserZone("Europe/Prague");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(false);
  });

  it("never opens the panel by itself", () => {
    // Auto-opening a dialog on load steals focus and interrupts a screen
    // reader; the emphasis class is the whole mismatch signal.
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).getAttribute("aria-expanded")).not.toBe("true");
  });

  it("compares NULL against the display zone", () => {
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "", displayZone: "Europe/Prague", captureDefault: false });
    expect(trigger(host).classList.contains("font-semibold")).toBe(true);
  });

  it("mirrors a picker selection into the value and the trigger label", () => {
    stubBrowserZone("Europe/Prague");
    const host = mount({ storedZone: "Europe/Prague", captureDefault: false });
    host.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: {
          name: "timestamp_start_timezone_picker",
          values: ["Asia/Tokyo"],
          last: { value: "Asia/Tokyo", label: "Asia/Tokyo", data: {} },
        },
      }),
    );
    expect(valueInput(host).value).toBe("Asia/Tokyo");
    expect(trigger(host).textContent).toContain("Start time zone: Asia/Tokyo");
  });

  it("treats the pinned empty option as a clear back to NULL", () => {
    // The API's browse-all response pins {value: ""}; it is the only route
    // back to NULL once a zone has been captured.
    stubBrowserZone("Asia/Tokyo");
    const host = mount({ storedZone: "Asia/Tokyo", captureDefault: false });
    host.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: {
          name: "timestamp_start_timezone_picker",
          values: [""],
          last: { value: "", label: "Use account display zone", data: {} },
        },
      }),
    );
    expect(valueInput(host).value).toBe("");
    expect(trigger(host).textContent).toContain(
      "Start time zone: Europe/Prague (display zone)",
    );
  });
});
