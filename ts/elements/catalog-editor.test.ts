// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { hosted } from "../test-setup/search-select-host.js";
import { filled, renumbered } from "./catalog-editor.js";
import "./catalog-editor.js";

Element.prototype.scrollIntoView = () => {};

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
      '<input type="radio" data-choice-card name="in_library" value="edition-__edition__-release-__release__">';
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
      <input type="radio" data-choice-card name="in_library" value="edition-0-release-0" checked>
      <input type="hidden" name="edition-0-release-0-removed">
      <button type="button" data-catalog-remove></button>
    </div>
    <button type="button" data-catalog-add="release">Add release</button>
  </fieldset>
  <button type="button" data-catalog-add="edition">Add edition</button>
  <template data-catalog-template="release">
    <div data-catalog-release="__release__">
      <input type="radio" data-choice-card name="in_library" value="edition-__edition__-release-__release__">
      <input type="hidden" name="edition-__edition__-release-__release__-removed">
      <button type="button" data-catalog-remove></button>
      <search-select name="edition-__edition__-release-__release__-platform">
        <input data-search-select-search id="id_edition-__edition__-release-__release__-platform">
      </search-select>
    </div>
  </template>
  <template data-catalog-template="edition">
    <fieldset data-catalog-edition="__edition__">
      <input type="hidden" name="edition-__edition__-removed">
      <input type="hidden" name="edition-__edition__-releases-count" value="1">
      <input name="edition-__edition__-name">
      <div data-catalog-release="0">
        <input type="radio" data-choice-card name="in_library" value="edition-__edition__-release-0">
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
  expect(document.querySelector('search-select[name="edition-0-release-1-platform"]')).not.toBeNull();
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
  expect(document.querySelector('search-select[name="edition-0-release-2-platform"]')).not.toBeNull();
});

it("gives each cloned picker its own id", () => {
  click('[data-catalog-add="release"]');
  click('[data-catalog-add="release"]');

  const ids = Array.from(
    document.querySelectorAll<HTMLInputElement>("[data-catalog-release] [data-search-select-search]"),
  ).map(input => input.id);
  expect(ids).toEqual([
    "id_edition-0-release-1-platform",
    "id_edition-0-release-2-platform",
  ]);
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

function marked(): string | null {
  const mark = document.querySelector<HTMLInputElement>("input[data-choice-card]:checked");
  return mark ? mark.value : null;
}

it("moves the mark off a binned release onto one that stays", () => {
  click('[data-catalog-add="release"]');
  click('[data-catalog-release="0"] [data-catalog-remove]');

  expect(marked()).toBe("edition-0-release-1");
});

it("moves the mark out of a binned edition into one that stays", () => {
  click('[data-catalog-add="edition"]');
  click("fieldset > [data-catalog-remove]");

  expect(marked()).toBe("edition-1-release-0");
});

it("gives the mark to an added row when every row before it is going", () => {
  click('[data-catalog-release="0"] [data-catalog-remove]');
  expect(marked()).toBe("edition-0-release-0");

  click('[data-catalog-add="release"]');

  expect(marked()).toBe("edition-0-release-1");
});

it("moves the mark off a row the server drew out of sight", () => {
  // A refused page comes back with the bin the person left, so the
  // element repairs the mark on arrival, before anyone clicks.
  document.body.innerHTML = PAGE.replace(
    '<div data-catalog-release="0">',
    '<div data-catalog-release="0" hidden style="display:none">',
  ).replace(
    '<button type="button" data-catalog-add="release">Add release</button>',
    '<div data-catalog-release="1">' +
      '<input type="radio" data-choice-card name="in_library" value="edition-0-release-1">' +
      "</div>",
  );

  expect(marked()).toBe("edition-0-release-1");
});

it("leaves the mark alone when the row it sits on stays", () => {
  click('[data-catalog-add="release"]');
  click('[data-catalog-release="1"] [data-catalog-remove]');

  expect(marked()).toBe("edition-0-release-0");
});

describe("filled", () => {
  it("puts the value in the slot", () => {
    expect(filled("Remove the {} release", "DOS")).toBe("Remove the DOS release");
  });

  it("keeps a dollar sign literal", () => {
    expect(filled("Remove the {} release", "PS$&")).toBe("Remove the PS$& release");
  });

  it("states the empty sentence for no value", () => {
    expect(filled("{}", "", "Unnamed edition")).toBe("Unnamed edition");
  });
});

// Hooks as the server stamps them.
const NAMED = `
<catalog-editor>
  <fieldset data-catalog-edition="0">
    <legend data-catalog-name="{}" data-catalog-name-of="name"
      data-catalog-name-empty="Unnamed edition">Gold</legend>
    <input name="edition-0-name" value="Gold">
    <button type="button" data-catalog-remove
      aria-label="Remove the Gold edition" title="Remove the Gold edition"
      data-catalog-name="Remove the {} edition" data-catalog-name-of="name"
      data-catalog-name-empty="Remove the unnamed edition"></button>
    <div data-catalog-release="0">
      <label>
        <input type="radio" data-choice-card name="in_library" value="edition-0-release-0" checked>
        <span data-catalog-name="Show the {} release in the library"
          data-catalog-name-of="platform">Show the Amiga release in the library</span>
      </label>
      <button type="button" data-catalog-remove
        aria-label="Remove the Amiga release" title="Remove the Amiga release"
        data-catalog-name="Remove the {} release" data-catalog-name-of="platform"></button>
      <input name="edition-0-release-0-release_date-year" value="1984">
      <span data-platform-picker></span>
    </div>
  </fieldset>
</catalog-editor>`;

const PLATFORMS: Record<string, string> = { a: "Amiga", d: "DOS", p: "PS$&" };

/** The platform picker, as the server draws it. */
function picker(held: string, name = "edition-0-release-0-platform"): HTMLElement {
  const element = document.createElement("search-select");
  element.setAttribute("name", name);
  element.setAttribute("multi", "false");
  element.setAttribute("none-label", "Unspecified");
  const rows = Object.entries(PLATFORMS)
    .map(
      ([key, label]) =>
        `<div data-search-select-option role="option" data-value="${key}"><span data-search-select-label></span></div>`,
    )
    .join("");
  const pill = held
    ? `<input type="hidden" name="${name}" value="${held}">`
    : `<input type="hidden" name="${name}" value="" data-search-select-none>`;
  element.innerHTML = `
    <div data-search-select-pills>${pill}</div>
    <input data-search-select-search>
    <div data-search-select-options hidden>
      <div role="option" data-search-select-none-option data-label="Unspecified"><span>Unspecified</span></div>
      ${rows}
      <div data-search-select-no-results class="hidden">No results</div>
    </div>`;
  element.querySelector<HTMLInputElement>("[data-search-select-search]")!.value = held
    ? PLATFORMS[held]
    : "Unspecified";
  for (const row of element.querySelectorAll<HTMLElement>("[data-search-select-option]")) {
    const label = PLATFORMS[row.dataset.value!];
    row.dataset.label = label;
    row.querySelector("span")!.textContent = label;
  }
  return hosted(element);
}

/** NAMED, its picker holding `held`. */
function mountNamed(held = "a", markup = NAMED): void {
  document.body.innerHTML = markup;
  document.querySelector("[data-platform-picker]")?.replaceWith(picker(held));
}

describe("names", () => {
  beforeEach(() => mountNamed());

  const release = '[data-catalog-release="0"]';
  const edition = '[data-catalog-edition="0"]';

  function platformBox(): HTMLInputElement {
    return document.querySelector<HTMLInputElement>(
      `${release} [data-search-select-search]`,
    )!;
  }

  function choose(key: string): void {
    platformBox().focus();
    const row = key
      ? `[data-search-select-option][data-value="${key}"]`
      : "[data-search-select-none-option]";
    document.querySelector<HTMLElement>(`${release} ${row}`)!.click();
  }

  function typePlatform(text: string): void {
    platformBox().value = text;
    platformBox().dispatchEvent(new Event("input", { bubbles: true }));
  }

  function typeName(name: string): void {
    const input = document.querySelector<HTMLInputElement>('input[name="edition-0-name"]')!;
    input.value = name;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function markText(): string {
    return document.querySelector(`${release} span[data-catalog-name]`)!.textContent!;
  }

  function bin(scope: string): HTMLElement {
    return document.querySelector<HTMLElement>(`${scope} > button[data-catalog-remove]`)!;
  }

  it("names a release by the platform chosen in it", () => {
    choose("d");
    expect(markText()).toBe("Show the DOS release in the library");
    expect(bin(release).getAttribute("aria-label")).toBe("Remove the DOS release");
    expect(bin(release).title).toBe("Remove the DOS release");
  });

  it("keeps a dollar sign in a platform literal", () => {
    choose("p");
    expect(markText()).toBe("Show the PS$& release in the library");
  });

  it("names a release with no platform as unspecified", () => {
    choose("");
    expect(markText()).toBe("Show the Unspecified release in the library");
  });

  it("keeps the name while a platform is being typed", () => {
    typePlatform("D");
    expect(markText()).toBe("Show the Amiga release in the library");
  });

  it("names an edition by what is typed in it, and leaves its releases", () => {
    typeName("Silver");
    expect(document.querySelector(`${edition} > legend`)!.textContent).toBe("Silver");
    expect(bin(edition).getAttribute("aria-label")).toBe("Remove the Silver edition");
    expect(bin(edition).title).toBe("Remove the Silver edition");
    expect(markText()).toBe("Show the Amiga release in the library");
  });

  it("names a blank edition as unnamed", () => {
    typeName("   ");
    expect(document.querySelector(`${edition} > legend`)!.textContent).toBe(
      "Unnamed edition",
    );
    expect(bin(edition).title).toBe("Remove the unnamed edition");
  });

  it("ignores input on a row's other fields", () => {
    const year = document.querySelector<HTMLInputElement>(
      'input[name="edition-0-release-0-release_date-year"]',
    )!;
    year.value = "Silver";
    year.dispatchEvent(new Event("input", { bubbles: true }));
    expect(markText()).toBe("Show the Amiga release in the library");
    expect(document.querySelector(`${edition} > legend`)!.textContent).toBe("Gold");
  });

  describe("drift", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    afterEach(() => error.mockClear());

    it("leaves a hook without a pattern alone, and says so", () => {
      mountNamed("a", NAMED.replace(' data-catalog-name="Remove the {} release"', ""));
      choose("d");
      expect(bin(release).getAttribute("aria-label")).toBe("Remove the Amiga release");
      expect(error).toHaveBeenCalled();
    });

    it("keeps the server's name while the picker is unwired", () => {
      document.body.innerHTML = NAMED.replace(
        "<span data-platform-picker></span>",
        '<search-select name="edition-0-release-0-platform"></search-select>',
      );
      error.mockClear();
      window.dispatchEvent(new Event("pageshow"));
      expect(markText()).toBe("Show the Amiga release in the library");
      expect(error).not.toHaveBeenCalledWith(
        expect.stringContaining("<catalog-editor>"),
        expect.anything(),
      );
    });

    it("says so when a named row has no control", () => {
      document.body.innerHTML = NAMED;
      expect(markText()).toBe("Show the Amiga release in the library");
      expect(error).toHaveBeenCalled();
    });
  });

  it("renames on pageshow", () => {
    const element = document.querySelector<HTMLElement & { holdValue(value: string): boolean }>(
      `${release} search-select`,
    )!;
    // A silent hold fires no change.
    element.holdValue("d");
    window.dispatchEvent(new Event("pageshow"));
    expect(markText()).toBe("Show the DOS release in the library");
  });

  it("stops listening for pageshow once removed", () => {
    const editor = document.querySelector("catalog-editor")!;
    const element = editor.querySelector<HTMLElement & { holdValue(value: string): boolean }>(
      `${release} search-select`,
    )!;
    editor.remove();
    element.holdValue("d");
    window.dispatchEvent(new Event("pageshow"));
    const mark = editor.querySelector(`${release} span[data-catalog-name]`)!;
    expect(mark.textContent).toBe("Show the Amiga release in the library");
  });
});
