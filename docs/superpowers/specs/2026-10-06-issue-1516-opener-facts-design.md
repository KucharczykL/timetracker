# A form states the facts its opener knows

Issue #1516, part of #1485, after #1501, before #1385.

## Rule

A form page opened with a fact its opener knows does not offer that field.
It renders a **stated row** in the field's place: the field's label, the
value as text, and a hidden input that posts the value.

## Carrier: the query string

An opener states a fact as a query parameter named after the form field's
html name (`form.add_prefix(name)`): `/session/add?game=<uuid>`,
`/game/add?kind=main`. The query is the same on a plain page and in a form
dialog. A form page has no `action` (`AddForm`), so its POST re-sends the
query, as `?origin=` already relies on; in a dialog `resolveUrls`
(`ts/elements/form-dialog/rewrite.ts`) sets `action` to the fetched URL,
query included. The fact is read on GET and on POST alike.

`action_url(name, *args, origin=..., facts=...)` writes `facts` (field name
to text) beside `origin`, also where `origin` is `None`.

**A path stays for a route's subject.** A path argument names the row a
page is about and has no field: Add historical playtime's game, Add
purchase's entry. Those keep their paths and titles. A path that only
prefills a field the same page otherwise asks for becomes a fact.

## Declaration: the form

A form opts in with `OpenerFactsMixin` (`common/opener_facts.py`), a
class-level `opener_fields: tuple[FieldName, ...]`, and an optional
`facts=` keyword (default `None`; an add view passes `request.GET`, an edit
view and a test pass nothing). The form's own `__init__` calls
`self.state_opener_facts(facts)` once its fields and querysets are built
and before any `self[name]` access: a `BoundField` caches its initial, so
the mixin raises when the bound-field cache already holds a declared name.
The form then seeds inline from `self.stated_facts` (field name to cleaned
value). `edit_game` passes no facts, so a stated kind never relabels a
stored game. Only a declared field reads the query; `origin`, `filter`
and unknown parameters are ignored.

For each declared name present in the query:

1. **Malformed** — several values, an empty value, a choice word the
   field's `clean()` refuses, or, for a model choice, text `parse_uuidv7`
   refuses (`ModelChoiceField.clean` answers one `invalid_choice` for every
   failure, so it cannot tell shape from absence):
   the field stays as today, with no initial, and one WARNING on
   `games.opener_facts` names form, field and the value's `repr`, cut to 80
   characters. An opener that writes such a link is a defect.
2. **Absent row** — a parsed key that `queryset.filter(pk=key).first()`
   does not find (the queryset is `for_library()`): `Http404` and the same WARNING. This keeps today's
   404 for a foreign game on the chained pages and follows "a row library
   does not hold is absent, not refused".
3. Otherwise the value is **fixed**: `self.initial[name] = value`,
   `field.disabled = True`, `field.widget = StatedFactWidget(statement)`.

`disabled` makes Django clean the initial and ignore the posted value, so a
tampered hidden input changes nothing. Django renders `disabled` on a
disabled field's input, and a disabled input does not post, which would
hide the value from `FormData` readers (the run picker's `{"field":
"game"}`). `StatedFactWidget` is a `HiddenInput` that drops `disabled`
(scratch repro). Its statement is `label_from_instance` for a model choice,
the choice label for a choice field.

A form fixes an **implied** fact with `self.fix_field(name, value)`: fixed
and posted, no statement, no row.

## Rendering: `FormFields`

`FormFields` tests for a `StatedFactWidget` before its `is_hidden` branch,
in the plain path and the grouped path, where a stated row also counts
toward a group's emptiness. The row is a `data-field-row` `Div`: a `<p>`
with the label's class and an id, a `<p>` with the statement, the hidden
input, and the field's errors. A field fixed with no statement renders with
the hidden fields; its errors join the non-field errors.

## Consumers

| Page | Opener | Facts |
| --- | --- | --- |
| Add game | "Add-on of" + | `kind=main`, implied `parent`; title from `addon` |
| Add session | Game detail "Log this game" | `game` |
| Add playthrough | Game detail, both links | `game` |
| Add to library | Game detail card, Add game's "Submit & Add to library" | `game` |

**Add game.** `GameForm.opener_fields = ("kind",)`. A stated kind that is
not an add-on kind fixes `parent` to none. The view skips `GameAddon` when
`kind` is stated, because its element needs the kind select. The page's
title is "Add the main game of ⟨addon⟩" when `kind` is stated main and the
`addon` parameter holds text (cut to `Game.name`'s 255), else "Add New
Game", on GET and on a refused POST alike. `addon` is display text, never a field.

The + carries the DLC's unsaved name, so `DialogCreate` takes
`params: ParamSources | None = None`, the pickers' shape, as its last
field. `_dialog_create_link` joins each literal source to the href at
render. The field sources reach the element as a registered prop,
`dialog_create_params` on `SearchSelectProps`, parsed by `parseParams`.
`<search-select>` rewrites the +'s query on connect and on each `input` and
`change` whose target names a source field (one form-level listener): it
parses the href with `new URL`, sets each resolved source, deletes a blank
one, keeps every other parameter, and writes the attribute of the same
`<a>`, because `<form-dialog>` hands the created row only to a connected
opener. A click, a middle click and a copied link all carry the current
value. In Add game the field `name` is unique: edition rows are prefixed. `NEW_MAIN_GAME = DialogCreate(add_game,
"New main game", params={"kind": {"value": "main"}, "addon": {"field":
"name"}})` is the + on "Add-on of", on Add and Edit game. The url stays a
plain `reverse_lazy`.

**The chained routes go.** `add_session_for_game`,
`add_playthrough_for_game` and `add_library_entry` become `add_session`,
`add_playthrough` and `add_to_library` with `?game=`; every caller and the
route classification follow. Seeds move into the forms:

- `SessionForm`: the sole ordinary run as the run's initial, and autofocus
  on the device field.
- `PlaythroughForm`: the seeded run dates while unbound, and the
  `also_mark_played` gate
  that `offered_game` drove; `offered_game` goes.
- `EntryAddForm`: one `game` field always; the Release picker reads
  `{"field": "game"}`, offers its create row only for a stated game the
  library owns, and takes the default Release as initial. `game=` and
  `self.game` go; Cancel and the success target read the stated game.
  Its title loses "- ⟨game⟩"; the row states it.

The Game detail "Played N times" button gains its game.

## Prior art

From documentation known to the author, not re-checked here:

- Django admin's add view reads GET parameters named after model fields
  into `initial`; popups add `_popup` and `_to_field`. Fields stay
  editable. We take the carrier, not the editability.
- GitHub's new-issue URL prefills editable fields from `title`, `labels`,
  `projects`.
- Linear and Jira show a sub-issue's parent as fixed context, not a field.
- Carbon and GOV.UK advise against disabled inputs for data the person
  cannot change: show it as text.

## Limits

- "Submit & Add to library" in a picker's dialog continues to Add to
  library and selects nothing, as #1501 records.
- A picker + other than "Add-on of" carries no fact yet.

## Tests

- pytest, mechanism: fixed and stated; undeclared ignored; malformed
  (unknown word, empty, two values) renders the field and logs; absent row
  404s; tampered POST keeps the fact; no `disabled` on the hidden input;
  plain and grouped rows; implied fact; `action_url` with and without
  origin.
- pytest, consumers: each page with and without its fact, the title, the
  played gate, the Release create rule, Cancel.
- vitest: the + query follows its field sources.
- Changed pins: the + href and label in `tests/test_dialog_create_pages.py`
  and `e2e/test_dialog_create_e2e.py`; the 404 test in
  `tests/test_library_page_isolation.py` moves to `?game=`.
- e2e: Add game, type a DLC name, pick Kind DLC, press the + on "Add-on
  of"; the stacked
  form is titled for the DLC and has no Kind field; save; the main game is
  selected below and the DLC saves.

## Follow-up issues to file

- Field-sourced facts on the other game pickers' + (e.g. the platform).
- "Add add-on" on Game detail's Add-ons section, stating `kind` and
  `parent`.
