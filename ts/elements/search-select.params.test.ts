// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface SearchSelectLike extends HTMLElement {
  setSelected(value: string, label?: string): void;
}

function answersNothing() {
  return vi.fn((input: RequestInfo | URL) => {
    void input;
    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response);
  });
}

/** A form holding a game field and a run picker that depends on it. */
function mountDependentPicker(params: string): {
  picker: SearchSelectLike;
  gameField: HTMLInputElement;
  fetchMock: ReturnType<typeof answersNothing>;
} {
  document.body.replaceChildren();
  const fetchMock = answersNothing();
  vi.stubGlobal("fetch", fetchMock);
  const form = document.createElement("form");
  form.innerHTML = '<input type="hidden" name="game" value="g1" />';
  const picker = document.createElement("search-select") as SearchSelectLike;
  picker.setAttribute("name", "playthrough");
  picker.setAttribute("search-url", "/api/playthrough/search");
  picker.setAttribute("prefetch", "20");
  picker.setAttribute("params", params);
  picker.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options></div>
  `;
  form.appendChild(picker);
  document.body.appendChild(form);
  return {
    picker,
    gameField: form.querySelector<HTMLInputElement>('[name="game"]')!,
    fetchMock,
  };
}

function urlsRequested(fetchMock: ReturnType<typeof answersNothing>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input));
}

describe("<search-select> params (#1080)", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  it("rides a literal value on the search URL", async () => {
    const { picker, fetchMock } = mountDependentPicker(
      JSON.stringify({ game: { value: "fixed-key" } })
    );
    picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(urlsRequested(fetchMock)[0]).toContain("game=fixed-key");
  });

  it("reads a field param's current value from the form", async () => {
    const { picker, fetchMock } = mountDependentPicker(
      JSON.stringify({ game: { field: "game" } })
    );
    picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(urlsRequested(fetchMock)[0]).toContain("game=g1");
  });

  it("searches again when a depended-on field changes", async () => {
    const { picker, gameField, fetchMock } = mountDependentPicker(
      JSON.stringify({ game: { field: "game" } })
    );
    picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    gameField.value = "g2";
    gameField.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() =>
      expect(urlsRequested(fetchMock).some(url => url.includes("game=g2"))).toBe(true)
    );
  });

  it("drops the held selection when a depended-on field changes", async () => {
    const { picker, gameField, fetchMock } = mountDependentPicker(
      JSON.stringify({ game: { field: "game" } })
    );
    picker.setSelected("r1", "Playthrough 1");
    expect(
      picker.querySelector<HTMLInputElement>(
        '[data-search-select-pills] input[type="hidden"]'
      )?.value
    ).toBe("r1");

    gameField.value = "g2";
    gameField.dispatchEvent(new Event("change", { bubbles: true }));

    await vi.waitFor(() =>
      expect(
        picker.querySelector<HTMLInputElement>(
          '[data-search-select-pills] input[type="hidden"]'
        )
      ).toBeNull()
    );
    expect(fetchMock).toHaveBeenCalled();
  });

  it("holds the one option a search answers where nothing is held", async () => {
    document.body.replaceChildren();
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve([{ value: "r1", label: "Playthrough 1", data: {} }]),
      } as Response)
    );
    vi.stubGlobal("fetch", fetchMock);
    const picker = document.createElement("search-select") as SearchSelectLike;
    picker.setAttribute("name", "playthrough");
    picker.setAttribute("search-url", "/api/playthrough/search");
    picker.setAttribute("prefetch", "20");
    picker.setAttribute("commit-sole-option", "true");
    picker.innerHTML = `
      <div data-search-select-pills></div>
      <input data-search-select-search />
      <div data-search-select-options></div>
      <template data-search-select-template="row"><div
        data-search-select-option role="option" aria-selected="false"
      ><span data-search-select-label></span></div></template>
    `;
    document.body.appendChild(picker);

    picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();

    await vi.waitFor(() =>
      expect(
        picker.querySelector<HTMLInputElement>(
          '[data-search-select-pills] input[type="hidden"]'
        )?.value
      ).toBe("r1")
    );
  });

  it("selects the label it commits into a focused box", async () => {
    document.body.replaceChildren();
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve([{ value: "r1", label: "Playthrough 1", data: {} }]),
      } as Response)
    );
    vi.stubGlobal("fetch", fetchMock);
    const picker = document.createElement("search-select") as SearchSelectLike;
    picker.setAttribute("name", "playthrough");
    picker.setAttribute("search-url", "/api/playthrough/search");
    picker.setAttribute("prefetch", "20");
    picker.setAttribute("commit-sole-option", "true");
    picker.innerHTML = `
      <div data-search-select-pills></div>
      <input data-search-select-search />
      <div data-search-select-options></div>
      <template data-search-select-template="row"><div
        data-search-select-option role="option" aria-selected="false"
      ><span data-search-select-label></span></div></template>
    `;
    document.body.appendChild(picker);

    const search = picker.querySelector<HTMLInputElement>(
      "[data-search-select-search]"
    )!;
    search.focus();

    await vi.waitFor(() => expect(search.value).toBe("Playthrough 1"));
    //: A keystroke replaces the label, never appends to it.
    expect(search.selectionStart).toBe(0);
    expect(search.selectionEnd).toBe("Playthrough 1".length);
  });

  it("leaves a name being typed alone", async () => {
    document.body.replaceChildren();
    let answer: (rows: unknown[]) => void = () => {};
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>(resolve => {
          answer = rows =>
            resolve({ ok: true, json: () => Promise.resolve(rows) } as Response);
        })
    );
    vi.stubGlobal("fetch", fetchMock);
    const picker = document.createElement("search-select") as SearchSelectLike;
    picker.setAttribute("name", "playthrough");
    picker.setAttribute("search-url", "/api/playthrough/search");
    picker.setAttribute("prefetch", "20");
    picker.setAttribute("commit-sole-option", "true");
    picker.innerHTML = `
      <div data-search-select-pills></div>
      <input data-search-select-search />
      <div data-search-select-options></div>
      <template data-search-select-template="row"><div
        data-search-select-option role="option" aria-selected="false"
      ><span data-search-select-label></span></div></template>
    `;
    document.body.appendChild(picker);

    const search = picker.querySelector<HTMLInputElement>(
      "[data-search-select-search]"
    )!;
    search.focus();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    //: The name is typed while the first answer is still on its way.
    search.value = "New Game Plus";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    answer([{ value: "r1", label: "Playthrough 1", data: {} }]);
    await vi.waitFor(() =>
      expect(picker.querySelectorAll("[data-search-select-option]")).toHaveLength(1)
    );

    expect(search.value).toBe("New Game Plus");
    expect(
      picker.querySelector('[data-search-select-pills] input[type="hidden"]')
    ).toBeNull();
  });

  it("searches without params when the attribute cannot be parsed", async () => {
    const { picker, fetchMock } = mountDependentPicker("{not json");
    picker.querySelector<HTMLInputElement>("[data-search-select-search]")!.focus();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const searches = urlsRequested(fetchMock).filter(url =>
      url.includes("/api/playthrough/search")
    );
    expect(searches).toHaveLength(1);
    expect(searches[0]).not.toContain("game=");
  });
});
