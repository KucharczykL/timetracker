// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js";
import { hosted } from "../test-setup/search-select-host.js";

const reportClientError = vi.hoisted(() => vi.fn(() => "error-id"));
vi.mock("../client-errors.js", () => ({ reportClientError }));

Element.prototype.scrollIntoView = () => {};

interface Answer {
  ok: boolean;
  items: { value: string; label: string; data: Record<string, unknown> }[];
}

interface RefetchingPicker extends HTMLElement {
  refetchOptions(): void;
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

interface MountedPicker {
  picker: RefetchingPicker;
  box: HTMLInputElement;
  clearButton: HTMLButtonElement;
  outside: HTMLInputElement;
}

function mountPicker(): MountedPicker {
  const picker = document.createElement("search-select") as RefetchingPicker;
  picker.setAttribute("name", "game");
  picker.setAttribute("search-url", "/api/games/search");
  picker.setAttribute("prefetch", "20");
  picker.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <button type="button" data-search-select-clear aria-label="Clear">×</button>
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
    picker,
    box: picker.querySelector<HTMLInputElement>("[data-search-select-search]")!,
    clearButton: picker.querySelector<HTMLButtonElement>("[data-search-select-clear]")!,
    outside,
  };
}

const rowLabels = (): string[] =>
  Array.from(document.querySelectorAll<HTMLElement>("[data-search-select-option]"))
    .filter(row => row.style.display !== "none")
    .map(row => row.dataset.label ?? "");

const queries = (fetchMock: ReturnType<typeof queuedFetch>): (string | null)[] =>
  fetchMock.mock.calls.map(([input]) => new URL(String(input)).searchParams.get("q"));

const ROWS: Answer = {
  ok: true,
  items: [
    { value: "g1", label: "Hades", data: {} },
    { value: "g2", label: "Celeste", data: {} },
  ],
};
const FAILED: Answer = { ok: false, items: [] };

describe("<search-select> rows that never landed", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    reportClientError.mockClear();
  });
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

  it("fetches the window again after the × takes focus", async () => {
    const fetchMock = queuedFetch([null, ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { box, clearButton } = mountPicker();

    box.focus();
    clearButton.focus();
    box.focus();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades", "Celeste"]));
  });

  it("fetches the window again after a failed answer", async () => {
    const fetchMock = queuedFetch([FAILED, ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { box, outside } = mountPicker();

    box.focus();
    await vi.waitFor(() => expect(reportClientError).toHaveBeenCalledOnce());
    outside.focus();
    box.focus();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades", "Celeste"]));
  });

  it("says the search failed rather than that nothing matched", async () => {
    vi.stubGlobal("fetch", queuedFetch([FAILED]));
    const { picker, box } = mountPicker();

    box.focus();
    await vi.waitFor(() => expect(reportClientError).toHaveBeenCalledOnce());

    const noResults = picker.querySelector<HTMLElement>("[data-search-select-no-results]")!;
    expect(noResults.textContent).toBe("Could not load results");
    expect(noResults.classList.contains("hidden")).toBe(false);
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

  it("asks once when a focus follows a refetch in flight", () => {
    const fetchMock = queuedFetch([null]);
    vi.stubGlobal("fetch", fetchMock);
    const { picker, box } = mountPicker();

    picker.refetchOptions();
    box.focus();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ignores the failure of a superseded request", async () => {
    const fetchMock = queuedFetch([FAILED, ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { picker } = mountPicker();

    picker.refetchOptions();
    picker.refetchOptions();

    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades", "Celeste"]));
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("asks the typed query again when its search was cut short", async () => {
    const fetchMock = queuedFetch([ROWS, null, ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { box, outside } = mountPicker();

    box.focus();
    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades", "Celeste"]));
    box.value = "zel";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    outside.focus();
    box.focus();

    expect(queries(fetchMock)).toEqual(["", "zel", "zel"]);
  });

  it("asks for the window when the shown rows answer a typed query", async () => {
    const fetchMock = queuedFetch([ROWS, ROWS, ROWS]);
    vi.stubGlobal("fetch", fetchMock);
    const { box, outside } = mountPicker();

    box.focus();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    box.value = "Ha";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(rowLabels()).toEqual(["Hades"]));
    box.value = "";
    outside.focus();
    box.focus();

    expect(queries(fetchMock)).toEqual(["", "Ha", ""]);
  });
});
