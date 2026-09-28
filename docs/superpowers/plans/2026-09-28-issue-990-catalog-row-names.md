# Catalog Row Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Release row and Edition block in the Game form's Editions area names the value it holds now: on first render, on a refused re-render, in a cloned row, and after the browser restores a value.

**Architecture:** The server renders each name from the bound field's value (not the stored record) and stamps each named node with its sentence pattern (`data-catalog-name`), the value it follows (`data-catalog-name-of`), and an optional empty-value sentence (`data-catalog-name-empty`). `<catalog-editor>` fills those patterns from the row's current control value on every `input` event and once on connect. The mark's radio loses its `aria-label` so its label text names it.

**Tech Stack:** Django forms + htpy components (Python), TypeScript custom element, pytest / pytest-django, vitest + jsdom, Playwright (pytest-playwright).

**Spec:** `docs/superpowers/specs/2026-09-28-issue-990-catalog-row-names-design.md` — read it first. Issue: KucharczykL/timetracker#990.

## Global Constraints

- Sentences, verbatim: `Show the {} release in the library`, `Remove the {} release`, `{}` (Edition legend, empty → `Unnamed edition`), `Remove the {} edition` (empty → `Remove the unnamed edition`).
- The slot is `{}`. Python and TypeScript each state it once, as `NAME_SLOT`.
- A Release with no Platform, or with a key the select does not offer, is named by the field's `empty_label` (`Unspecified`). Never by a position.
- Edition names are trimmed on the server and in the element before the empty test.
- The page reads the Platform names once. Page query count must not grow with the number of rows (measured on `main`: 21 queries for 1 row and for 3 rows).
- The element never uses `innerHTML`/`replace` for names: text via `textContent`, attributes via `setAttribute`/`title`; substitution by `split(NAME_SLOT).join(value)`.
- The element holds no English words of any sentence.
- Run tests through `make`, inside the heavy-tests lock: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make …` (see the repo's CLAUDE.md).
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| File | Change |
|---|---|
| `common/components/choice_card.py` | Radio loses `aria-label`; `ChoiceCard(label_attributes=)`, `ChoiceCardGroup(legend_attributes=)` |
| `tests/test_choice_card.py` | Name-by-label-text and hook tests |
| `games/catalog_form.py` | `CatalogGraphForm.platform_names()` |
| `games/views/catalog_section.py` | Patterns, `_named`, `_filled`, bound-value names, trimmed Edition name, `platforms` threaded through |
| `tests/test_game_form_page.py` | Refused-page, whitespace, template-hook, first-render, query-count tests |
| `ts/elements/catalog-editor.ts` | `NAME_SLOT`, `filled()`, `input` listener, connect-time restatement |
| `ts/elements/catalog-editor.test.ts` | Name rewriting tests |
| `e2e/test_game_form_catalog_e2e.py` | Changed row, cloned row, cloned Edition |

---

### Task 1: The choice card names its mark by its label text, and takes name hooks

**Files:**
- Modify: `common/components/choice_card.py` (`ChoiceCardGroup.__init__/__getitem__/render`, `ChoiceCard.__init__/__getitem__/render`)
- Test: `tests/test_choice_card.py`

**Interfaces:**
- Produces: `ChoiceCardGroup(..., legend_attributes: Attributes | None = None)` — lands on the `<legend>`. `ChoiceCard(..., label_attributes: Attributes | None = None)` — lands on the label's `<span>`. The radio renders no `aria-label`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_choice_card.py`, add `import re` at the top, then replace `test_a_card_names_its_mark_for_a_screen_reader` with:

```python
def test_a_card_names_its_mark_by_its_label_text():
    """An aria-label would outrank the label, and hide a stale one."""
    rendered = str(
        ChoiceCard(name="in_library", value="row-0", label="Show the Wii release")[""]
    )

    assert "aria-label" not in rendered
    assert (
        rendered.index("<label")
        < rendered.index("Show the Wii release")
        < rendered.index("</label>")
    )


def test_a_card_hooks_its_label_text():
    rendered = str(
        ChoiceCard(
            name="in_library",
            value="row-0",
            label="Wii",
            label_attributes=[("data-x", "1")],
        )[""]
    )

    assert re.search(r'<span[^>]*data-x="1"[^>]*>Wii</span>', rendered)


def test_a_group_hooks_its_legend():
    rendered = str(
        ChoiceCardGroup(
            name="in_library", legend="Gold", legend_attributes=[("data-x", "1")]
        )[""]
    )

    assert re.search(r'<legend[^>]*data-x="1"[^>]*>Gold</legend>', rendered)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_choice_card.py"`
Expected: FAIL — `aria-label` present; `TypeError: ... unexpected keyword argument 'label_attributes'` / `'legend_attributes'`.

- [ ] **Step 3: Implement**

In `ChoiceCardGroup`: add the keyword `legend_attributes: Attributes | None = None` after `attributes`, store it as `self.legend_attributes`, pass `legend_attributes=self.legend_attributes` in `__getitem__`, and render:

```python
        )[Legend(self.legend_attributes, class_="sr-only")[self.legend], *self._children]
```

In `ChoiceCard`: add `label_attributes: Attributes | None = None` after `attributes`, store it as `self.label_attributes`, pass `label_attributes=self.label_attributes` in `__getitem__`, and replace the mark in `render`:

```python
        mark = Label(class_=_MARK_CLASS)[
            Radio(
                [(CHOICE_CARD_MARK_ATTRIBUTE, "")],
                name=self.name,
                value=self.value,
                checked=self.checked,
            ),
            # Names the radio at every width: seen narrow, sr-only wide.
            # An aria-label would outrank it.
            Span(self.label_attributes, class_="@2xl/edition:sr-only")[self.label],
        ]
```

Add one line to each class docstring: ``label_attributes`` / ``legend_attributes`` is the hook on the node that names it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_choice_card.py tests/test_game_form_page.py"`
Expected: PASS (the page tests do not assert the radio's `aria-label`).

- [ ] **Step 5: Commit**

```bash
git add common/components/choice_card.py tests/test_choice_card.py
git commit -m "fix: a choice card names its mark by its label text (#990)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The server names each row from its bound value, and stamps the patterns

**Files:**
- Modify: `games/catalog_form.py` (add `CatalogGraphForm.platform_names` after `blank_block`)
- Modify: `games/views/catalog_section.py` (`_remove_button`, `_platform_name`, `_release_card`, `_name_row`, `_edition_block`, `_templates`, `editions_area`; new constants and helpers)
- Test: `tests/test_game_form_page.py`

**Interfaces:**
- Consumes: Task 1's `label_attributes` / `legend_attributes`.
- Produces (DOM contract Task 3 and Task 4 rely on):
  - Release mark `<span data-catalog-name="Show the {} release in the library" data-catalog-name-of="platform">` (no `aria-label`, so the element sets its text).
  - Release bin `<button … aria-label=… title=… data-catalog-name="Remove the {} release" data-catalog-name-of="platform">`.
  - Edition `<legend data-catalog-name="{}" data-catalog-name-of="name" data-catalog-name-empty="Unnamed edition">`.
  - Edition bin `<button … aria-label=… title=… data-catalog-name="Remove the {} edition" data-catalog-name-of="name" data-catalog-name-empty="Remove the unnamed edition">`.
  - `CatalogGraphForm.platform_names() -> dict[str, str]`: `str(pk)` → option text.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_game_form_page.py` (add `import uuid` and `from django.db import connection` / `from django.test.utils import CaptureQueriesContext` at the top):

```python
def templates(body: str) -> str:
    """Only the blank rows the browser clones."""
    return body.split("<template data-catalog-template=", 1)[1]


def edit_url(game: Game) -> str:
    return reverse("games:edit_game", args=[game.pk])


def test_a_row_names_its_stored_platform(logged_in, owned_library, plain_game):
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    Release.objects.filter(edition__game=plain_game).update(platform=amiga)

    body = live(page(logged_in, plain_game))

    assert ">Show the Amiga release in the library</span>" in body
    assert 'aria-label="Remove the Amiga release"' in body


def test_a_refused_page_names_what_the_person_posted(
    logged_in, owned_library, plain_game
):
    """The stored Amiga is what the person just stopped the row being."""
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    dos = Platform.objects.create(library=owned_library, name="DOS")
    edition = Edition.objects.get(game=plain_game, is_default=True)
    release = edition.releases.get(is_default=True)
    Release.objects.filter(pk=release.pk).update(platform=amiga)

    response = logged_in.post(
        edit_url(plain_game),
        {
            "name": "Portal",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "1",
            "edition-0-edition_id": str(edition.pk),
            "edition-0-name": "Gold",
            "edition-0-releases-count": "2",
            "edition-0-release-0-release_id": str(release.pk),
            "edition-0-release-0-platform": str(dos.pk),
            # A key the library does not offer refuses the page.
            "edition-0-release-1-platform": str(uuid.uuid4()),
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    assert ">Show the DOS release in the library</span>" in body
    assert 'aria-label="Remove the DOS release"' in body
    assert "Amiga release" not in body
    assert ">Show the Unspecified release in the library</span>" in body
    assert ">Gold</legend>" in body
    assert 'aria-label="Remove the Gold edition"' in body


def test_a_blank_edition_name_is_unnamed(logged_in, plain_game):
    """Whitespace is no name; the form strips it on write too."""
    response = logged_in.post(
        edit_url(plain_game),
        {
            "name": "Portal",
            "status": "played",
            "reference_wikidata": "",
            "editions-count": "2",
            "edition-0-name": "   ",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": "",
            "edition-1-name": "",
            "edition-1-releases-count": "1",
            "edition-1-release-0-platform": "",
            "in_library": "edition-0-release-0",
        },
    )

    assert response.status_code == 200
    body = live(response.content.decode())
    assert body.count(">Unnamed edition</legend>") == 2
    assert body.count('aria-label="Remove the unnamed edition"') == 2
    assert "Remove the    " not in body


def test_the_cloned_rows_carry_their_name_patterns(logged_in, plain_game):
    blank = templates(page(logged_in, plain_game))

    assert 'data-catalog-name="Show the {} release in the library"' in blank
    assert 'data-catalog-name="Remove the {} release"' in blank
    assert 'data-catalog-name-of="platform"' in blank
    assert ">Show the Unspecified release in the library</span>" in blank
    assert 'data-catalog-name="Remove the {} edition"' in blank
    assert 'data-catalog-name-empty="Remove the unnamed edition"' in blank
    assert 'data-catalog-name-empty="Unnamed edition"' in blank
    assert 'data-catalog-name-of="name"' in blank
    assert ">Unnamed edition</legend>" in blank


def test_naming_the_rows_reads_no_more_per_row(logged_in, owned_library, plain_game):
    """One read of the Platforms serves every row on the page."""
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    edition = Edition.objects.get(game=plain_game, is_default=True)
    Release.objects.filter(edition=edition).update(platform=amiga)

    def queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            logged_in.get(edit_url(plain_game))
        return len(captured.captured_queries)

    one = queries()
    for year in (2011, 2012):
        Release.objects.create(
            edition=edition, platform=amiga, release_date=TemporalValue.from_year(year)
        )

    assert queries() == one
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_game_form_page.py"`
Expected: `test_a_row_names_its_stored_platform` and `test_naming_the_rows_reads_no_more_per_row` PASS already (guards). The other three FAIL: the refused page still names Amiga, the whitespace name renders `Remove the     edition`, the templates carry no `data-catalog-name`.

- [ ] **Step 3: Add `platform_names` to `CatalogGraphForm`**

In `games/catalog_form.py`, after `blank_block`:

```python
    def platform_names(self) -> dict[str, str]:
        """Each Platform a row offers, keyed and worded as its select is.

        One read for the whole page; each row looks its own name up.
        """
        field = cast(forms.ModelChoiceField, self.blank_row().fields["platform"])
        return {str(key): str(label) for key, label in field.choices if key != ""}
```

- [ ] **Step 4: Implement the names in `games/views/catalog_section.py`**

Imports: `from collections.abc import Mapping`, `from typing import Final, cast`, `from django import forms`.

After `_OUT_OF_SIGHT`, add:

```python
#: Where `<catalog-editor>` puts a row's current value. Mirrors
#: `NAME_SLOT` in `ts/elements/catalog-editor.ts`.
NAME_SLOT: Final[str] = "{}"

_MARK_NAME: Final[str] = "Show the {} release in the library"
_RELEASE_BIN_NAME: Final[str] = "Remove the {} release"
_EDITION_NAME: Final[str] = "{}"
_EDITION_NAME_EMPTY: Final[str] = "Unnamed edition"
_EDITION_BIN_NAME: Final[str] = "Remove the {} edition"
_EDITION_BIN_NAME_EMPTY: Final[str] = "Remove the unnamed edition"


def _named(
    pattern: str, follows: str, empty: str | None = None
) -> list[tuple[str, str]]:
    """The hooks `<catalog-editor>` restates a name through."""
    hooks = [("data-catalog-name", pattern), ("data-catalog-name-of", follows)]
    if empty is not None:
        hooks.append(("data-catalog-name-empty", empty))
    return hooks


def _filled(pattern: str, value: str, empty: str | None = None) -> str:
    """One name, as the element states it for ``value``."""
    if not value and empty is not None:
        return empty
    return pattern.replace(NAME_SLOT, value)
```

Replace `_remove_button`:

```python
def _remove_button(title: str, naming: list[tuple[str, str]]) -> Node:
    """Inert until `<catalog-editor>` picks it up."""
    return ControlButton(
        naming,
        color="red",
        variant="ghost",
        type="button",
        title=title,
        aria_label=title,
        data_catalog_remove="",
    )[Icon("delete", size=ICON_BUTTON_SIZE_CLASS)]
```

Replace `_platform_name` and add `_edition_name`:

```python
def _platform_name(row: ReleaseRowForm, platforms: Mapping[str, str]) -> str:
    """The option the row's select shows, worded as the select words it.

    The bound value, not the stored Release: a refused page shows what
    was posted. A key the select does not offer shows the empty option.
    """
    empty = cast(forms.ModelChoiceField, row.fields["platform"]).empty_label
    return platforms.get(str(row["platform"].value()), str(empty))


def _edition_name(block: EditionBlock) -> str:
    return str(block.form["name"].value() or "").strip()
```

Replace `_release_card`:

```python
def _release_card(
    row: ReleaseRowForm,
    *,
    index: RowIndex,
    value: str,
    chosen: bool,
    platforms: Mapping[str, str],
) -> Node:
    platform = _platform_name(row, platforms)
    return ChoiceCard(
        name=MARK_FIELD,
        value=value,
        label=_filled(_MARK_NAME, platform),
        label_attributes=_named(_MARK_NAME, "platform"),
        checked=chosen,
        columns=EDITION_COLUMNS,
        attributes=_row_hooks(row, "data-catalog-release", index),
    )[
        [
            *_hidden_fields(row),
            Div(class_=_BIN_CELL_CLASS)[
                _remove_button(
                    _filled(_RELEASE_BIN_NAME, platform),
                    _named(_RELEASE_BIN_NAME, "platform"),
                )
            ],
            _field_cell(row["platform"], _PLATFORM_PLACEMENT),
            _field_cell(row["release_date"], _DATE_PLACEMENT),
            *_hidden_errors(row),
            *_non_field_errors(row),
        ]
    ]
```

In `_name_row`, replace the `title` line and the bin:

```python
    title = _filled(_EDITION_BIN_NAME, _edition_name(block), _EDITION_BIN_NAME_EMPTY)
    ...
        Div(class_="flex min-h-control items-center")[
            _remove_button(
                title,
                _named(_EDITION_BIN_NAME, "name", _EDITION_BIN_NAME_EMPTY),
            )
        ],
```

`_edition_block` gains `platforms: Mapping[str, str]`, passes `platforms=platforms` to each `_release_card`, and names the group:

```python
    return ChoiceCardGroup(
        name=MARK_FIELD,
        legend=_filled(_EDITION_NAME, _edition_name(block), _EDITION_NAME_EMPTY),
        legend_attributes=_named(_EDITION_NAME, "name", _EDITION_NAME_EMPTY),
        class_=BLOCK_CLASS,
        attributes=_row_hooks(block.form, "data-catalog-edition", index),
    )[...]
```

`_templates(graph, platforms)` passes `platforms=platforms` to `_release_card` and `_edition_block`. `editions_area` reads `platforms = graph.platform_names()` once and passes it to every `_edition_block(...)` call and to `_templates(graph, platforms)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_game_form_page.py tests/test_choice_card.py tests/test_catalog_submit.py tests/test_rendered_pages.py"`
Expected: PASS. Then `make typecheck lint format-check` — PASS.

- [ ] **Step 6: Commit**

```bash
git add games/catalog_form.py games/views/catalog_section.py tests/test_game_form_page.py
git commit -m "fix: a catalog row names the value it was drawn with (#990)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `<catalog-editor>` restates names on input and on connect

**Files:**
- Modify: `ts/elements/catalog-editor.ts`
- Test: `ts/elements/catalog-editor.test.ts`

**Interfaces:**
- Consumes: Task 2's DOM contract (`data-catalog-name`, `data-catalog-name-of` ∈ {`platform`, `name`}, `data-catalog-name-empty`).
- Produces: `export function filled(pattern: string, value: string, empty?: string): string`.

- [ ] **Step 1: Write the failing tests**

In `ts/elements/catalog-editor.test.ts`, change the import to `import { filled, renumbered } from "./catalog-editor.js";` and append:

```ts
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

// One named Edition holding one Release on Amiga, hooks as the server
// stamps them.
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
      <select name="edition-0-release-0-platform">
        <option value="">Unspecified</option>
        <option value="a" selected>Amiga</option>
        <option value="d">DOS</option>
        <option value="p">PS$&amp;</option>
      </select>
    </div>
  </fieldset>
</catalog-editor>`;

describe("names", () => {
  beforeEach(() => {
    document.body.innerHTML = NAMED;
  });

  const release = '[data-catalog-release="0"]';
  const edition = '[data-catalog-edition="0"]';

  function choose(key: string): void {
    const select = document.querySelector<HTMLSelectElement>(`${release} select`)!;
    select.value = key;
    select.dispatchEvent(new Event("input", { bubbles: true }));
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

  it("names an edition by what is typed in it, and leaves its releases", () => {
    typeName("Silver");
    expect(document.querySelector(`${edition} > legend`)!.textContent).toBe("Silver");
    expect(bin(edition).getAttribute("aria-label")).toBe("Remove the Silver edition");
    expect(markText()).toBe("Show the Amiga release in the library");
  });

  it("names a blank edition as unnamed", () => {
    typeName("   ");
    expect(document.querySelector(`${edition} > legend`)!.textContent).toBe(
      "Unnamed edition",
    );
    expect(bin(edition).title).toBe("Remove the unnamed edition");
  });

  it("corrects a stale name on arrival", () => {
    // A browser that restores a changed select arrives with this page.
    document.body.innerHTML = NAMED.replace(
      '<option value="a" selected>Amiga</option>',
      '<option value="a">Amiga</option>',
    ).replace('<option value="d">DOS</option>', '<option value="d" selected>DOS</option>');
    expect(markText()).toBe("Show the DOS release in the library");
    expect(bin(release).getAttribute("aria-label")).toBe("Remove the DOS release");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-ts`
Expected: FAIL — `filled` is not exported; names stay Amiga.

- [ ] **Step 3: Implement**

In `ts/elements/catalog-editor.ts`, extend the module docblock with one paragraph:

```
 * A row's names follow its value. The server stamps each named node with
 * its sentence; the element fills the slot on input and on arrival, as
 * the server cannot know a cloned row's value or one the browser restores.
```

After `isGoing`, add:

```ts
// Where a name takes its row's value. Mirrors NAME_SLOT in
// games/views/catalog_section.py.
const NAME_SLOT = "{}";

/** A name with the row's value in its slot. Split, not `replace`,
 *  thus a `$` in the value stays literal. */
export function filled(pattern: string, value: string, empty?: string): string {
  if (value === "" && empty !== undefined) return empty;
  return pattern.split(NAME_SLOT).join(value);
}

// The control each kind of name follows, and the row it names.
const FOLLOWED = {
  platform: { control: 'select[name$="-platform"]', row: "[data-catalog-release]" },
  name: { control: 'input[name$="-name"]', row: "[data-catalog-edition]" },
} as const;

type Followed = keyof typeof FOLLOWED;

const KINDS = Object.keys(FOLLOWED) as Followed[];

/** What the control shows: an option's own text, or the typed value. */
function shown(control: HTMLInputElement | HTMLSelectElement): string {
  const text =
    control instanceof HTMLSelectElement
      ? (control.selectedOptions[0]?.textContent ?? "")
      : control.value;
  return text.trim();
}
```

In `connectedCallback`, after the click listener:

```ts
    // A select and a text field both fire `input`, a clone's too.
    this.addEventListener("input", this.onInput);
```

and before `this.restateMark();`:

```ts
    // The deferred script runs after the browser restores form values.
    this.restateNames();
```

Add to the class:

```ts
  private onInput = (event: Event): void => {
    const target = event.target as HTMLElement;
    for (const kind of KINDS) {
      if (!target.matches(FOLLOWED[kind].control)) continue;
      const row = target.closest<HTMLElement>(FOLLOWED[kind].row);
      if (row && this.contains(row)) this.restateRow(row, kind);
    }
  };

  /** Every row's names, from the values the page holds now. */
  private restateNames(): void {
    for (const kind of KINDS) {
      for (const row of this.querySelectorAll<HTMLElement>(FOLLOWED[kind].row)) {
        this.restateRow(row, kind);
      }
    }
  }

  /** One row's names of one kind. An Edition's `name` nodes are its
   *  own; its Releases' nodes follow `platform`. */
  private restateRow(row: HTMLElement, kind: Followed): void {
    const control = row.querySelector<HTMLInputElement | HTMLSelectElement>(
      FOLLOWED[kind].control,
    );
    if (!control) return;
    const value = shown(control);
    for (const node of row.querySelectorAll<HTMLElement>(
      `[data-catalog-name-of="${kind}"]`,
    )) {
      const name = filled(node.dataset.catalogName ?? "", value, node.dataset.catalogNameEmpty);
      if (node.hasAttribute("aria-label")) {
        node.setAttribute("aria-label", name);
        if (node.hasAttribute("title")) node.title = name;
      } else {
        node.textContent = name;
      }
    }
  }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-ts ts-check`
Expected: PASS, including the existing `renumbered` and mark tests.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/catalog-editor.ts ts/elements/catalog-editor.test.ts
git commit -m "fix: catalog-editor keeps a row's names on its value (#990)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Browser tests

**Files:**
- Test: `e2e/test_game_form_catalog_e2e.py`

**Interfaces:**
- Consumes: fixtures `signed_in`, `live_server`, `game` (Elite, one Release on Amiga, unnamed default Edition), `amiga`, `dos`; helpers `open_form`, `release_card`, `choose_platform`.

- [ ] **Step 1: Write the tests**

Append:

```python
def mark_text(card: Locator) -> Locator:
    """The label text that names a row's mark."""
    return card.locator("label [data-catalog-name-of='platform']")


def test_a_changed_row_names_its_new_platform(signed_in, live_server, game, dos):
    """Narrow, the name is visible text; wide, it names the radio."""
    page = signed_in
    page.set_viewport_size({"width": 390, "height": 900})
    open_form(page, live_server, game)
    card = release_card(page, 0, 0)

    choose_platform(card, "DOS")

    expect(mark_text(card)).to_be_visible()
    expect(mark_text(card)).to_have_text("Show the DOS release in the library")
    expect(
        card.get_by_role("button", name="Remove the DOS release", exact=True)
    ).to_be_visible()

    page.set_viewport_size({"width": 1200, "height": 900})

    expect(
        card.get_by_role(
            "radio", name="Show the DOS release in the library", exact=True
        )
    ).to_be_visible()


def test_a_cloned_row_names_the_platform_chosen_in_it(
    signed_in, live_server, game, dos
):
    page = signed_in
    open_form(page, live_server, game)
    page.click("[data-catalog-edition='0'] [data-catalog-add='release']")
    added = release_card(page, 0, 1)

    expect(
        added.get_by_role(
            "radio", name="Show the Unspecified release in the library", exact=True
        )
    ).to_be_visible()
    choose_platform(added, "DOS")

    expect(
        added.get_by_role(
            "radio", name="Show the DOS release in the library", exact=True
        )
    ).to_be_visible()
    expect(
        added.get_by_role("button", name="Remove the DOS release", exact=True)
    ).to_be_visible()
    expect(
        release_card(page, 0, 0).get_by_role(
            "radio", name="Show the Amiga release in the library", exact=True
        )
    ).to_be_visible()


def test_a_cloned_edition_names_what_is_typed_in_it(
    signed_in, live_server, game, amiga
):
    page = signed_in
    open_form(page, live_server, game)
    page.click("[data-catalog-add='edition']")
    block = page.locator("[data-catalog-edition='1']")

    expect(block).to_have_accessible_name("Unnamed edition")
    block.locator("input[name='edition-1-name']").fill("Gold")

    expect(block).to_have_accessible_name("Gold")
    expect(
        block.get_by_role("button", name="Remove the Gold edition", exact=True)
    ).to_be_visible()

    first = release_card(page, 1, 0)
    choose_platform(first, "Amiga")
    expect(
        first.get_by_role(
            "radio", name="Show the Amiga release in the library", exact=True
        )
    ).to_be_visible()
```

No test drives back/forward navigation; the vitest "corrects a stale name on arrival" case covers a restored value.

- [ ] **Step 2: Run the tests**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-e2e ARGS="e2e/test_game_form_catalog_e2e.py"`
Expected: PASS, the existing catalog browser tests included. If one of the new tests fails, the defect is in Task 2 or Task 3, not in the test: fix it there.

- [ ] **Step 3: Commit**

```bash
git add e2e/test_game_form_catalog_e2e.py
git commit -m "test: catalog rows name their value in a real browser (#990)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The full gate

- [ ] **Step 1: Run the full gate**

Run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
Expected: exit 0 (lint, format-check, mypy, vale, ts-check, check-icons, check-migrations, vitest, full pytest including `e2e/`).

- [ ] **Step 2: Fix and commit anything the gate reports**, one commit per cause, with the trailer. Do not weaken a test to pass.

- [ ] **Step 3: Check the acceptance list of #990** against the tests:
  - posted Platform named on re-render → `test_a_refused_page_names_what_the_person_posted`
  - cloned Release follows its Platform → `test_a_cloned_row_names_the_platform_chosen_in_it`
  - cloned Edition follows its name → `test_a_cloned_edition_names_what_is_typed_in_it`
  - restored value → vitest `corrects a stale name on arrival`
  - browser test + `make check` → Task 4, Task 5
