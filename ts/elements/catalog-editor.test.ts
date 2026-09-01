// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { renumbered } from "./catalog-editor.js";
import "./catalog-editor.js";

describe("renumbered", () => {
  it("rewrites the edition index in every posted name", () => {
    const markup = '<input name="edition-__edition__-name">';
    expect(renumbered(markup, { edition: 3 })).toContain('name="edition-3-name"');
  });

  it("rewrites the release index a temporal control carries", () => {
    const markup = '<input name="edition-__edition__-release-__release__-release_date-year">';
    expect(renumbered(markup, { edition: 0, release: 2 })).toContain(
      'name="edition-0-release-2-release_date-year"',
    );
  });

  it("rewrites the id and the label that points at it", () => {
    const markup =
      '<label for="id_edition-__edition__-name"></label>' +
      '<input id="id_edition-__edition__-name">';
    const result = renumbered(markup, { edition: 1 });
    expect(result).toContain('for="id_edition-1-name"');
    expect(result).toContain('id="id_edition-1-name"');
  });

  it("rewrites the mark's value so the new row can be chosen", () => {
    const markup =
      '<input type="radio" name="in_library" value="edition-__edition__-release-__release__">';
    expect(renumbered(markup, { edition: 2, release: 0 })).toContain(
      'value="edition-2-release-0"',
    );
  });

  it("leaves a row that names no placeholder alone", () => {
    const markup = '<input name="editions-count" value="2">';
    expect(renumbered(markup, { edition: 9 })).toBe(markup);
  });
});

// One Edition holding one Release, plus the two templates the server ships.
// Trimmed to the hooks the element reads: the classes and the labels are the
// server's business.
const PAGE = `
<catalog-editor>
  <input type="hidden" name="editions-count" value="1">
  <fieldset data-catalog-edition="0">
    <input type="hidden" name="edition-0-removed">
    <input type="hidden" name="edition-0-releases-count" value="1">
    <button type="button" data-catalog-remove></button>
    <div data-catalog-release="0">
      <input type="radio" name="in_library" value="edition-0-release-0" checked>
      <input type="hidden" name="edition-0-release-0-removed">
      <button type="button" data-catalog-remove></button>
    </div>
    <button type="button" data-catalog-add="release">Add release</button>
  </fieldset>
  <button type="button" data-catalog-add="edition">Add edition</button>
  <template data-catalog-template="release">
    <div data-catalog-release="__release__">
      <input type="radio" name="in_library" value="edition-__edition__-release-__release__">
      <input type="hidden" name="edition-__edition__-release-__release__-removed">
      <select name="edition-__edition__-release-__release__-platform"></select>
    </div>
  </template>
  <template data-catalog-template="edition">
    <fieldset data-catalog-edition="__edition__">
      <input type="hidden" name="edition-__edition__-removed">
      <input type="hidden" name="edition-__edition__-releases-count" value="1">
      <input name="edition-__edition__-name">
      <div data-catalog-release="0">
        <input type="radio" name="in_library" value="edition-__edition__-release-0">
      </div>
    </fieldset>
  </template>
</catalog-editor>`;

function click(selector: string): void {
  document.querySelector<HTMLElement>(selector)!.click();
}

function value(name: string): string {
  return document.querySelector<HTMLInputElement>(`input[name="${name}"]`)!.value;
}

beforeEach(() => {
  document.body.innerHTML = PAGE;
});

it("appends a release row and bumps that edition's count", () => {
  click('[data-catalog-add="release"]');

  const rows = document.querySelectorAll("[data-catalog-edition] [data-catalog-release]");
  expect(rows.length).toBe(2);
  expect(value("edition-0-releases-count")).toBe("2");
  expect(document.querySelector('select[name="edition-0-release-1-platform"]')).not.toBeNull();
  // The mark is one group over the whole game, so the new row can take it.
  expect(
    document.querySelector<HTMLInputElement>('input[value="edition-0-release-1"]')!.name,
  ).toBe("in_library");
});

it("appends an edition block whose one row is row zero", () => {
  click('[data-catalog-add="edition"]');

  expect(document.querySelectorAll("[data-catalog-edition]").length).toBe(2);
  expect(value("editions-count")).toBe("2");
  expect(value("edition-1-releases-count")).toBe("1");
  expect(document.querySelector('input[name="edition-1-name"]')).not.toBeNull();
  expect(document.querySelector('input[value="edition-1-release-0"]')).not.toBeNull();
});

it("numbers a second added row after the first", () => {
  click('[data-catalog-add="release"]');
  click('[data-catalog-add="release"]');

  expect(value("edition-0-releases-count")).toBe("3");
  expect(document.querySelector('select[name="edition-0-release-2-platform"]')).not.toBeNull();
});

it("states a removed release rather than detaching it", () => {
  click('[data-catalog-release="0"] [data-catalog-remove]');

  const row = document.querySelector<HTMLElement>('[data-catalog-release="0"]')!;
  expect(row.isConnected).toBe(true);
  expect(row.hidden).toBe(true);
  expect(value("edition-0-release-0-removed")).toBe("on");
  // Removal never renumbers: the count still states what the form posts.
  expect(value("edition-0-releases-count")).toBe("1");
});

it("states a removed edition without touching its releases", () => {
  click("fieldset > [data-catalog-remove]");

  expect(value("edition-0-removed")).toBe("on");
  expect(value("edition-0-release-0-removed")).toBe("");
  expect(document.querySelector<HTMLElement>("[data-catalog-edition]")!.hidden).toBe(true);
});
