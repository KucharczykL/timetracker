// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";

const reportClientError = vi.hoisted(() => vi.fn(() => "id"));
vi.mock("../client-errors.js", () => ({ reportClientError }));

import "./tri-state-checkbox.js";

beforeEach(() => {
  document.body.innerHTML = "";
  reportClientError.mockClear();
});

const HINT = {
  "hint-mixed": "Keep: mixed",
  "hint-kept": "Keep",
  "hint-changed": "Will change",
};

function mount({
  held,
  box = held === "checked",
  posted = "",
  checkedWord = "True",
  uncheckedWord = "False",
}: {
  held: "checked" | "unchecked" | "mixed";
  box?: boolean;
  posted?: string;
  checkedWord?: string;
  uncheckedWord?: string;
}): void {
  document.body.innerHTML = markup({ held, box, posted, checkedWord, uncheckedWord });
}

/** Server markup; the box starts disabled. */
function markup({
  held,
  box = held === "checked",
  posted = "",
  checkedWord = "True",
  uncheckedWord = "False",
}: {
  held: "checked" | "unchecked" | "mixed";
  box?: boolean;
  posted?: string;
  checkedWord?: string;
  uncheckedWord?: string;
}): string {
  const hintText = { checked: "Keep", unchecked: "Keep", mixed: "Keep: mixed" }[held];
  return `
    <tri-state-checkbox name="mastered" held="${held}" checked-word="${checkedWord}"
      unchecked-word="${uncheckedWord}" hint-mixed="${HINT["hint-mixed"]}"
      hint-kept="${HINT["hint-kept"]}" hint-changed="${HINT["hint-changed"]}">
      <span data-tri-state-hint id="box-hint">${hintText}</span>
      <input type="checkbox" id="box" data-tri-state-box aria-describedby="box-hint" disabled ${
        box ? "checked" : ""
      }>
      <input type="hidden" name="mastered" value="${posted}" data-tri-state-value>
    </tri-state-checkbox>`;
}

const box = () => document.querySelector<HTMLInputElement>("[data-tri-state-box]")!;
const hidden = () => document.querySelector<HTMLInputElement>("[data-tri-state-value]")!;
const hint = () => document.querySelector<HTMLElement>("[data-tri-state-hint]")!;

it("an agreeing held checked toggles checked and unchecked", () => {
  mount({ held: "checked", box: true });
  box().click();
  expect(box().checked).toBe(false);
  expect(box().indeterminate).toBe(false);
  expect(hidden().value).toBe("False");
  expect(hint().textContent).toBe("Will change");

  box().click();
  expect(box().checked).toBe(true);
  expect(hidden().value).toBe("");
  expect(hint().textContent).toBe("Keep");
});

it("an agreeing held unchecked never offers mixed", () => {
  mount({ held: "unchecked" });
  box().click();
  expect(box().indeterminate).toBe(false);
  expect(hidden().value).toBe("True");
  box().click();
  expect(hidden().value).toBe("");
  expect(box().indeterminate).toBe(false);
});

it("a held mixed cycles mixed, checked, unchecked, mixed", () => {
  mount({ held: "mixed" });
  expect(box().indeterminate).toBe(true);
  expect(hint().textContent).toBe("Keep: mixed");

  box().click();
  expect(box().checked).toBe(true);
  expect(box().indeterminate).toBe(false);
  expect(hidden().value).toBe("True");
  expect(hint().textContent).toBe("Will change");

  box().click();
  expect(box().checked).toBe(false);
  expect(hidden().value).toBe("False");

  box().click();
  expect(box().indeterminate).toBe(true);
  expect(box().checked).toBe(false);
  expect(hidden().value).toBe("");
  expect(hint().textContent).toBe("Keep: mixed");
});

it("a restored hidden value sets the state on connect", () => {
  mount({ held: "mixed", box: false, posted: "True" });
  expect(box().checked).toBe(true);
  expect(box().indeterminate).toBe(false);
  expect(hidden().value).toBe("True");
  expect(hint().textContent).toBe("Will change");
});

it("a restored word that equals held is held", () => {
  mount({ held: "checked", box: true, posted: "" });
  expect(box().checked).toBe(true);
  expect(hint().textContent).toBe("Keep");
});

it("a held mixed box shows indeterminate on connect, not checked", () => {
  mount({ held: "mixed" });
  expect(box().checked).toBe(false);
  expect(box().indeterminate).toBe(true);
});

it("binds once across a DOM move", () => {
  mount({ held: "unchecked" });
  const element = document.querySelector("tri-state-checkbox")!;
  const host = document.createElement("div");
  document.body.append(host);
  host.append(element);
  box().click();
  expect(hidden().value).toBe("True");
  expect(reportClientError).not.toHaveBeenCalled();
});

it("the box stays disabled until it binds", () => {
  const host = document.createElement("div");
  host.innerHTML = markup({ held: "unchecked" });
  expect(host.querySelector<HTMLInputElement>("[data-tri-state-box]")!.disabled).toBe(true);

  document.body.append(host);
  expect(box().disabled).toBe(false);
});

it("a restored word that is not one of its two is held and reported", () => {
  mount({ held: "mixed", posted: "garbage" });
  expect(box().indeterminate).toBe(true);
  expect(box().checked).toBe(false);
  expect(hidden().value).toBe("");
  expect(hint().textContent).toBe("Keep: mixed");
  expect(reportClientError).toHaveBeenCalledWith(
    "tri-state-checkbox",
    "mastered: unknown posted value garbage",
  );
});

it("a restored False over held checked is unchecked", () => {
  mount({ held: "checked", box: true, posted: "False" });
  expect(box().checked).toBe(false);
  expect(box().indeterminate).toBe(false);
  expect(hidden().value).toBe("False");
  expect(hint().textContent).toBe("Will change");
  expect(reportClientError).not.toHaveBeenCalled();
});

it("reports the missing parts by name and stays disabled", () => {
  document.body.innerHTML = `<tri-state-checkbox name="mastered" held="mixed"
    checked-word="True" unchecked-word="False" hint-mixed="m" hint-kept="k"
    hint-changed="c"><input type="checkbox" data-tri-state-box disabled>
    </tri-state-checkbox>`;
  expect(reportClientError).toHaveBeenCalledWith(
    "tri-state-checkbox",
    "mastered: missing value, hint",
  );
  expect(box().disabled).toBe(true);
});

it("an empty or equal word reports and stays disabled", () => {
  mount({ held: "mixed", checkedWord: "", uncheckedWord: "False" });
  expect(reportClientError).toHaveBeenCalledWith(
    "tri-state-checkbox",
    "mastered: words must be non-empty and differ",
  );
  expect(box().disabled).toBe(true);

  reportClientError.mockClear();
  mount({ held: "mixed", checkedWord: "True", uncheckedWord: "True" });
  expect(reportClientError).toHaveBeenCalledWith(
    "tri-state-checkbox",
    "mastered: words must be non-empty and differ",
  );
  expect(box().disabled).toBe(true);
});
