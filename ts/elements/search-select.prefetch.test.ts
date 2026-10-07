// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js";

vi.mock("../client-errors.js", () => ({ reportClientError: vi.fn(() => "error-id") }));
import { hosted } from "../test-setup/search-select-host.js";

Element.prototype.scrollIntoView = () => {};

interface Answer {
  ok: boolean;
  items: { value: string; label: string; data: Record<string, unknown> }[];
}

/** A fetch answering each call from a queue; null hangs until aborted. */
function queuedFetch(answers: (Answer | null)[]) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void input;
    const answer = answers.shift() ?? null;
    if (answer === null) {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError"))
        );
      });
    }
    return Promise.resolve({
      ok: answer.ok,
      status: answer.ok ? 200 : 500,
      json: () => Promise.resolve(answer.items),
    } as Response);
  });
}

function mountPicker(): { box: HTMLInputElement; outside: HTMLInputElement } {
  const picker = document.createElement("search-select");
  picker.setAttribute("name", "game");
  picker.setAttribute("search-url", "/api/games/search");
  picker.setAttribute("prefetch", "20");
  picker.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options>
      <div data-search-select-no-results class="hidden">No results</div>
    </div>
    <template data-search-select-template="row"><div
      data-search-select-option role="option" aria-selected="false"
    ><span data-label></span></div></template>
  `;
  const outside = document.createElement("input");
  document.body.append(hosted(picker), outside);
  return {
    box: picker.querySelector<HTMLInputElement>("[data-search-select-search]")!,
    outside,
  };
}

const rowLabels = (): string[] =>
  Array.from(document.querySelectorAll<HTMLElement>("[data-search-select-option]"))
    .filter(row => row.style.display !== "none")
    .map(row => row.dataset.label ?? "");

const ROWS: Answer = {
  ok: true,
  items: [
    { value: "g1", label: "Hades", data: {} },
    { value: "g2", label: "Celeste", data: {} },
  ],
};

describe("<search-select> prefetch that never landed", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  it("fetches the window again after a blur aborts it", async () => {
    const fetchMock = queuedFetch([null, ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { box, outside } = mountPicker();

    box.focus();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    outside.focus();
    box.focus();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades", "Celeste"]));
  });

  it("fetches the window again after a failed answer", async () => {
    const fetchMock = queuedFetch([{ ok: false, items: [] }, ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { box, outside } = mountPicker();

    box.focus();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await new Promise(resolve => setTimeout(resolve, 0));
    outside.focus();
    box.focus();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades", "Celeste"]));
  });

  it("does not fetch again once the window landed", async () => {
    const fetchMock = queuedFetch([ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { box, outside } = mountPicker();

    box.focus();
    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades", "Celeste"]));
    outside.focus();
    box.focus();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
