# The release row's platform picker (#1222)

Part of #481. After #1080 and #1292.

## Outcome

`ReleaseRowForm.platform` renders a `SearchSelectWidget` over
`/api/platforms/search`. It offers two ways to make a platform the library
does not hold: the create row (`PostCreate("/api/platforms/")`, a typed
name) and a + that opens Add Platform in a form dialog
(`DialogCreate`, name plus references). Either way the new platform lands
in the picker and the person submits the Game once. After this no form on
any page renders a native `<select>`; `SettingWidget.MODEL` keeps its
plain path, and no setting uses it.

## Design

### The field

- `platform` stays a `ModelChoiceField`, `required=False`.
- `ReleaseRowForm` takes the stored Release at construction
  (`instance: Release | None = None`), no longer assigned after.
  `_blocks_from_post` resolves `_posted_release` before it builds the row.
  `EditionRowForm` keeps its assignment: nothing it builds reads it.
- Queryset: `visible_to(library)` or the stored release's platform, as
  `GameForm.parent` does. A removed stored platform resubmits; today the
  native select drops it to Unspecified and the save clears it.
- Widget: `search_url=PLATFORM_SEARCH_URL`, `create=PostCreate(
  PLATFORM_CREATE_URL)`, `dialog_create=NEW_PLATFORM`,
  `none_label=UNSPECIFIED_PLATFORM` (from `games/reads/releases.py`;
  `games/views/game.py` imports it instead of its copy),
  `revert_on_leave=True`, as every fixed-choice picker: a first keystroke
  drops the value, and leaving without a pick must not post nothing.
- `platform_options(values, *, library, stored)` joins `games/forms.py`
  beside `device_options`. It parses ids through `_parsed_ids`, reads the
  same visible-or-stored set, and labels a removed one `"<name> (removed)"`.
  Bound in `__init__`. It queries the scoped set, never an unscoped
  `pk__in`. A stored platform of another library cannot exist:
  `_refuse_foreign_platform` refuses it at the catalog write.
- `platform_option(platform)` (new) is the one row shape: the resolver,
  `POST /api/platforms/` and `add_platform` all build through it.
- `PLATFORM_SEARCH_URL`/`PLATFORM_CREATE_URL` join the device constants;
  `games/filters.py`'s three literals read the first.

### The + dialog

`NEW_PLATFORM = DialogCreate(reverse_lazy("games:add_platform"),
"New platform")`. `add_platform` answers `CreatedRedirect(..., option=
platform_option(platform))` after a write. Add and edit share
`_platform_form_page`; the created answer is gated on `platform is None`,
so edit keeps its plain redirect. `add_platform` is already
`ORIGIN_AWARE`. A dialog opened from Add Game, itself in a dialog, nests (#1499).

### The cloned row

The template renders the widget with the placeholders in its name, search
input `id`, clear button `aria-describedby`, and the + link. `renumbered()`
replaces every placeholder. Listbox, option and status ids are assigned at
init. `insertAdjacentHTML` connects the clone, which wires itself. The
create POST reads the hosting form's CSRF token.

### Names that follow the platform

The mark's label and the bin's name read "Show the DOS release…".

- Server: `CatalogGraphForm.platform_names()` reads every row's
  `value()` (bound or initial), parses ids, and resolves them in one query
  over visible-or-stored, labelled as the picker labels them. The `""`
  key reads `UNSPECIFIED_PLATFORM`, and `_platform_name` falls back to it
  for an unknown value, as today.
- Browser: `catalog-editor.ts` imports `search-select.js`.
  `FOLLOWED.platform.control` becomes `search-select[name$="-platform"]`;
  the select branch goes. The element listens for `search-select:change`
  beside `input`. `SearchSelectElement.heldLabel()` (new) answers the
  committed label, the none label for none, and `null` for nothing held or
  before init; it reads `_searchSelectLabel` and the held inputs
  directly, never `initializedPart`, which throws. The editor calls
  `customElements.upgrade` first, as `settingControlOf` does. `null`
  leaves the text as it stands, silently.
- Names follow emitted changes only. `setSelected`, `holdValue`,
  `holdNone`, `clearSelection` and the `revert_on_leave` restore emit
  nothing. A first keystroke emits a drop, `heldLabel()` answers `null`,
  the names keep the old platform, and the revert restores that same
  platform. A create row and a dialog's `created` both select with an
  emitted change.

### Back and forward

`test_a_restored_value_is_named_on_arrival` asserts a restored native
select. It is rewritten to assert that the names equal the label the
picker shows after back. If Chromium restores the hidden input but not the
label, that is a picker defect on every page: file it, and assert the
names agree with the picker.

### Tests that change

- `test_a_release_row_renders_a_plain_select_not_a_combobox` inverts: a
  `<search-select>` with the create URL and the + link, no `<select>`.
- `test_a_release_row_offers_unspecified_for_no_platform`: the none label.
  Its `own_platform.name in rendered` goes: a search picker draws no rows.
  New: a row bound to a foreign platform shows its name nowhere (picker,
  mark, bin).
- `test_form_relationship_querysets_are_explicitly_library_bound` keeps
  `{shared, own}`: no instance adds nothing.
- New: a stored removed platform renders `(removed)` and resubmits.
- New: `add_platform` in dialog mode answers `created` with the option.
- `test_html_validity`'s guard asserts no `<select>`; its comment goes.
- e2e: `choose_platform(card, platform)` picks by key inside the card's
  picker. New: create a platform from a cloned row's create row, submit
  once; create one through the +, submit once.
- vitest: the fixtures render a real `<search-select>` shell (the markup
  the `search-select.*.test.ts` files share); a real pick renames; a none
  pick names Unspecified; a keystroke keeps the name; the drift test keeps
  its `console.error`.

### Docs

CLAUDE.md's "but the release row's platform" clause, the field comment in
`games/catalog_form.py`, and the #1292 spec's line 68.

## Follow-up issues to file

None planned; the back/forward finding may add one.
