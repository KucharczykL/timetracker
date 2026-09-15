// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./playthrough-select.js";

function mount(options: string, selected = ""): HTMLSelectElement {
  document.body.innerHTML = `
    <form>
      <div data-field-row>
        <playthrough-select game-field="game" api-url="/api/playthrough/" selected="${selected}">
          <select name="playthrough">${options}</select>
        </playthrough-select>
      </div>
    </form>`;
  return document.querySelector("select")!;
}

function changeGame(gameId: string): void {
  document.querySelector("form")!.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: { name: "game", values: gameId ? [gameId] : [], last: null },
    }),
  );
}

async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("stays hidden while the game holds one run", () => {
  mount('<option value="r1" selected>Playthrough 1</option>');
  expect(document.querySelector<HTMLElement>("[data-field-row]")!.hidden).toBe(true);
});

it("shows itself for a game with two runs", () => {
  mount('<option value="r1">Playthrough 1</option><option value="r2">Second</option>');
  expect(document.querySelector<HTMLElement>("[data-field-row]")!.hidden).toBe(false);
});

it("refills from the API when the game changes and keeps the selected run", async () => {
  const select = mount("", "r2");
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [
      { id: "r1", display_name: "Playthrough 1" },
      { id: "r2", display_name: "Second run" },
    ],
  });
  vi.stubGlobal("fetch", fetchMock);

  changeGame("g1");
  await settle();

  expect(fetchMock).toHaveBeenCalledWith("/api/playthrough/?game=g1&limit=0", expect.anything());
  expect([...select.options].map((option) => option.textContent)).toEqual([
    "Playthrough 1",
    "Second run",
  ]);
  expect(select.value).toBe("r2");
  expect(document.querySelector<HTMLElement>("[data-field-row]")!.hidden).toBe(false);
});

it("selects the only run and hides when the new game holds one", async () => {
  const select = mount('<option value="r1">Playthrough 1</option><option value="r2">Second</option>');
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ id: "r9", display_name: "Playthrough 1" }],
    }),
  );

  changeGame("g2");
  await settle();

  expect(select.value).toBe("r9");
  expect(document.querySelector<HTMLElement>("[data-field-row]")!.hidden).toBe(true);
});

it("empties and hides when the game is cleared", async () => {
  const select = mount('<option value="r1">Playthrough 1</option><option value="r2">Second</option>');

  changeGame("");
  await settle();

  expect(select.options.length).toBe(0);
  expect(document.querySelector<HTMLElement>("[data-field-row]")!.hidden).toBe(true);
});
