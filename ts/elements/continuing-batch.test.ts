// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import "./continuing-batch.js";

const page = `
  <continuing-batch>
    <form method="post" action="/bulk/session.reclassify/" data-continuing-batch-form>
      <input type="hidden" name="submission" value="0199-token">
      <button type="submit">Continue</button>
      <button type="submit" name="stop" value="1" data-continuing-batch-stop>Stop</button>
    </form>
  </continuing-batch>`;

let requestSubmit: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  document.body.innerHTML = "";
  requestSubmit = vi
    .spyOn(HTMLFormElement.prototype, "requestSubmit")
    .mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Parse the children first, so connecting sees the whole form. */
function mount(markup = page): HTMLElement {
  const holder = document.createElement("div");
  holder.innerHTML = markup;
  const host = holder.firstElementChild as HTMLElement;
  document.body.append(host);
  return host;
}

it("posts the next chunk as soon as it is connected", () => {
  mount();
  expect(requestSubmit).toHaveBeenCalledTimes(1);
});

it("carries on by itself when the page is swapped in again", () => {
  mount();
  document.body.innerHTML = "";
  mount();
  expect(requestSubmit).toHaveBeenCalledTimes(2);
});

it("leaves the Stop press to the button that was pressed", () => {
  const host = mount();
  requestSubmit.mockClear();
  host.querySelector<HTMLButtonElement>("[data-continuing-batch-stop]")!.click();
  expect(requestSubmit).not.toHaveBeenCalled();
});

it("does not carry on after Stop, even if it is connected again", () => {
  const host = mount();
  host.querySelector<HTMLButtonElement>("[data-continuing-batch-stop]")!.click();
  requestSubmit.mockClear();
  host.remove();
  document.body.append(host);
  expect(requestSubmit).not.toHaveBeenCalled();
});

it("waits for the rest of the page while the parser is still reading it", () => {
  const readyState = vi.spyOn(document, "readyState", "get").mockReturnValue("loading");
  mount();
  expect(requestSubmit).not.toHaveBeenCalled();
  readyState.mockReturnValue("interactive");
  document.dispatchEvent(new Event("DOMContentLoaded"));
  expect(requestSubmit).toHaveBeenCalledTimes(1);
});

it("states nothing without a form to post", () => {
  mount("<continuing-batch><p>0 of 3 done.</p></continuing-batch>");
  expect(requestSubmit).not.toHaveBeenCalled();
});
