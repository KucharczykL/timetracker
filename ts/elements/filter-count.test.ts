// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  COUNTING_TEXT,
  UNAVAILABLE_TEXT,
  countEndpointUrl,
  totalText,
} from "./filter-count.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";
// Importing the module defines both <filter-count> and (transitively) <filter-group>.
import "./filter-count.js";

const ENDPOINT = "/api/filter/count";

describe("pure label helpers", () => {
  it("renders the plural noun for counts other than 1", () => {
    expect(totalText(0, "game", "games")).toBe("≈ 0 games");
    expect(totalText(2, "game", "games")).toBe("≈ 2 games");
    expect(totalText(142, "game", "games")).toBe("≈ 142 games");
  });

  it("renders the singular noun for exactly 1", () => {
    expect(totalText(1, "game", "games")).toBe("≈ 1 game");
  });

  it("url-encodes model and filter", () => {
    const url = countEndpointUrl(ENDPOINT, "game", '{"a":"x&y"}');
    expect(url).toBe(
      `${ENDPOINT}?model=game&filter=${encodeURIComponent('{"a":"x&y"}')}`,
    );
  });
});

// A <filter-group> whose serializeForQuery is stubbed, mounted so events bubble
// to `document` where <filter-count> listens.
function mountGroup(query: Record<string, unknown> = { AND: [] }): FilterGroupElement {
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", "{}");
  // Override before insertion so the shadowed method survives connectedCallback.
  group.serializeForQuery = () => query;
  document.body.appendChild(group);
  return group;
}

function mountBadge(): HTMLElement {
  const badge = document.createElement("filter-count");
  badge.setAttribute("model", "game");
  badge.setAttribute("noun-singular", "game");
  badge.setAttribute("noun-plural", "games");
  badge.setAttribute("endpoint", ENDPOINT);
  document.body.appendChild(badge);
  return badge;
}

function label(badge: HTMLElement): string {
  return badge.querySelector("span")?.textContent ?? "";
}

function jsonResponse(count: number): Response {
  return { ok: true, json: async () => ({ count }) } as unknown as Response;
}

describe("<filter-count> behavior", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.replaceChildren();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("debounces rapid edits into a single request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(7));
    vi.stubGlobal("fetch", fetchMock);
    const group = mountGroup();
    const badge = mountBadge();

    for (let index = 0; index < 5; index++) {
      group.dispatchEvent(
        new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }),
      );
    }
    expect(label(badge)).toBe(COUNTING_TEXT);

    await vi.advanceTimersByTimeAsync(300);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(label(badge)).toBe("≈ 7 games");
  });

  it("renders 'count unavailable' on a non-200 response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 400 } as Response),
    );
    const group = mountGroup();
    const badge = mountBadge();

    group.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }));
    await vi.advanceTimersByTimeAsync(300);
    expect(label(badge)).toBe(UNAVAILABLE_TEXT);
  });

  it("ignores an AbortError without showing unavailable", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));
    const group = mountGroup();
    const badge = mountBadge();

    group.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }));
    await vi.advanceTimersByTimeAsync(300);
    expect(label(badge)).toBe(COUNTING_TEXT); // stayed in the counting state
  });

  it("discards a stale earlier response so the newer count wins", async () => {
    // First fetch resolves only after the second is issued and settled.
    let resolveFirst!: (value: Response) => void;
    const firstPending = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(firstPending)
      .mockResolvedValueOnce(jsonResponse(2));
    vi.stubGlobal("fetch", fetchMock);
    const group = mountGroup();
    const badge = mountBadge();

    // First settled edit -> debounce fires -> request #1 in flight (unresolved).
    group.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }));
    await vi.advanceTimersByTimeAsync(300);
    // Second settled edit -> request #2 -> resolves to 2.
    group.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }));
    await vi.advanceTimersByTimeAsync(300);
    expect(label(badge)).toBe("≈ 2 games");

    // Now the stale first request finally resolves — it must NOT overwrite "2".
    resolveFirst(jsonResponse(999));
    await vi.advanceTimersByTimeAsync(0);
    expect(label(badge)).toBe("≈ 2 games");
  });

  it("renders 'count unavailable' on a non-Abort network rejection", async () => {
    // fetch rejecting with a TypeError is the offline/DNS case — a different
    // branch from a resolved non-200 response.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    const group = mountGroup();
    const badge = mountBadge();

    group.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }));
    await vi.advanceTimersByTimeAsync(300);
    expect(label(badge)).toBe(UNAVAILABLE_TEXT);
  });

  it("stops listening and cancels pending work once disconnected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(5));
    vi.stubGlobal("fetch", fetchMock);
    const group = mountGroup();
    const badge = mountBadge();

    // Arm the debounce timer, then remove the badge before it fires.
    group.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }));
    badge.remove(); // disconnectedCallback: clears timer, aborts, removes listener

    await vi.advanceTimersByTimeAsync(300);
    // The cleared timer never fired, so no request was issued.
    expect(fetchMock).not.toHaveBeenCalled();

    // A later change must not reach the detached badge (listener was removed).
    group.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true }));
    await vi.advanceTimersByTimeAsync(300);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
