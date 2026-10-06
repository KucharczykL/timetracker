# A form states the facts its opener knows

Issue #1516, part of #1485, after #1501, before #1385.

## Rule

A form page opened with a fact its opener knows does not offer that field.
It renders a **stated row** in the field's place: the field's label, the
value as text, and a hidden input that posts the value.

**A fact locks; a prefill stays editable.** Most tools prefill a
context-given value and keep it editable (Django admin, GitHub,
Salesforce, Dynamics, Jira). This mechanism locks, and a form declares a
field only where an editable one would contradict the opener (Kind beside
"Add-on of") or where the opener's own words already name the value ("Log
this game" on a game's page). Everything else stays a view's `initial`.
To change a locked fact, the person opens the page without it; the row
offers no "Change". An editable prefill from a link would need a carrier
of its own, never a flag on this one.

**Facts never reach an edit form.** An edit view passes no facts: a
stored row states its own values, and a stated kind on Edit game would
relabel the game.

## Carrier: the query string

An opener states a fact as a query parameter named after the form field's
html name (`form.add_prefix(name)`): `/session/add?game=<uuid>`,
`/game/add?kind=main`. The query is the same on a plain page and in a form
dialog. A form page has no `action` (`AddForm`), so its POST re-sends the
query, as `?origin=` already relies on; in a dialog `resolveUrls`
(`ts/elements/form-dialog/rewrite.ts`) sets `action` to the fetched URL,
query included. The fact is read on GET and on POST alike; the server
reads it from the query, and the hidden input exists for the client's
`FormData` readers alone (the run picker, the Release picker). Deleting
the query read because the input "already posts it" would let a tampered
body choose the value.

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
view and a test pass nothing). `opener_fields` names a field directly,
so each lock is visible where the form is declared. The form's own `__init__` calls
`self.state_opener_facts(facts)` once its fields and querysets are built
and before any `self[name]` access: a `BoundField` caches its initial, so
the mixin raises when the bound-field cache already holds a declared name.
The form then seeds inline from `self.stated_facts` (field name to cleaned
value). Only a declared field reads the query; `origin`, `filter`
and unknown parameters are ignored.

For each declared name present in the query:

1. **Malformed** — several values, an empty value, a choice word the
   field's `clean()` refuses, or, for a model choice, text `parse_uuidv7`
   refuses (`ModelChoiceField.clean` answers one `invalid_choice` for every
   failure, so it cannot tell shape from absence):
   the field stays editable and takes no initial from the fact (a
   declared default, such as Kind's Main game, still applies), and one
   WARNING on
   `games.opener_facts` names form, field and the value's `repr`, cut to 80
   characters. An opener that writes such a link is a defect.
2. **Absent row** — a parsed key the field's own queryset does not hold
   (`for_library()` for a session's game, `visible_to()` for Add to
   library's game; shared catalog rows count). On GET: `Http404` and the
   same WARNING, which keeps today's 404 for a foreign game and follows "a
   row library does not hold is absent, not refused"; the link is the
   defect. On POST the row may have gone after the page opened (removed,
   unshared): the field stays editable, logs nothing, and the posted value
   reaches the field's `clean()`, which answers `invalid_choice` on a
   visible picker and keeps every other typed value. A 404 there would
   lose the person's input, and inside a dialog it is not even a page.
3. Otherwise the value is **fixed**: `self.initial[name] = value`,
   `field.disabled = True`, and the field's name and statement join
   `self.stated_facts` and `self.statements`.

A refused fact (malformed, or absent on POST) joins
`self.refused_facts`; its row carries one sentence after the control:
"The link named a ⟨label⟩ this form cannot use. Pick one."

`disabled` governs cleaning alone: Django cleans the initial and ignores
the posted value, so a tampered body changes nothing. The control is not
rendered through Django: Django would stamp `disabled` on it, and a
disabled input does not post, which hides the value from `FormData`
readers. `FormFields` writes the hidden carrier itself (below). The
statement is `label_from_instance` for a model choice, the choice label
for a choice field.

A form fixes an **implied** fact with `self.fix_field(name, value)`: fixed
and posted, no statement, no row. Implications are imperative code in the
form's `__init__`, never read from the URL, and post so `clean()` sees one
consistent statement.

## Rendering: `FormFields`

`FormFields` reads `form.statements` (absent on a form without the mixin)
before its `is_hidden` branch, in the plain path and the grouped path,
where a stated row also counts toward a group's emptiness. The row is a
`data-field-row` `<dl>`: a `<dt>` with the label's class, a `<dd>` with the
statement, then the hidden input `FormFields` writes (`type="hidden"`,
`name=field.html_name`, `value=field.value()`, no `disabled`) and the
field's errors. A field fixed with no statement renders its hidden input
with the hidden fields; its errors join the non-field errors. A refused
fact's sentence renders after its control.

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
`addon` parameter holds text, else "Add New Game", on GET and on a refused
POST alike. `addon` is display text, never a field: control characters
become spaces, runs of space collapse, the text is stripped and cut to
`Game.name`'s 255.

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
value. The rewrite runs again on each connect, since `<form-dialog>`
inserts content anew. In Add game the field `name` is unique: edition rows are prefixed. `NEW_MAIN_GAME = DialogCreate(add_game,
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

| System | Carrier | Field | Override |
| --- | --- | --- | --- |
| Django admin add view | query into `initial`; `_popup`, `_to_field` | editable | yes |
| Rails, Phoenix nested resources | path | absent | no, 404 |
| GitHub new issue | query | editable | yes; 404 on a bad value |
| Airtable form | `prefill_X` query | editable | an unresolved link falls back to the picker |
| Salesforce Lightning | `defaultFieldValues` | editable | yes |
| Dynamics quick create | relationship mappings | editable | yes |
| Odoo | `default_*` context | `readonly` or `invisible` per view; `force_save` posts it | per view |
| Jira subtask, Linear sub-issue | in-app context | parent editable; context the editor opens with | yes |

- The query carrier and "path for the subject" follow Django admin, GitHub
  and Rails ("nest one level").
- The `opener_fields` allowlist follows the one admin parameter that is
  not editable: `_to_field`, gated by `to_field_allowed()`.
- Locking departs from the editable default; the lock rule above says when.
- Odoo's `force_save` shows the edge of a read-only value that must post:
  hence `disabled` for cleaning and a carrier written apart.
- A value the person cannot change reads as text, never a disabled or
  read-only control: Carbon, GOV.UK, USWDS, Cloudscape, Adrian Roselli.
- A bad prefill falls back to the field, as in Airtable.

Sources: docs.djangoproject.com (ModelAdmin.get_changeform_initial_data),
guides.rubyonrails.org/routing.html, docs.github.com (creating an issue),
developer.salesforce.com (navigate with default field values),
learn.microsoft.com (map table columns), odoo.com documentation (view
architectures), developer.atlassian.com (CreateIssueModal),
linear.app/docs/parent-and-sub-issues, carbondesignsystem.com (read-only
and disabled states), design-system.service.gov.uk (button),
designsystem.digital.gov (text input), cloudscape.design (disabled and
read-only states), adrianroselli.com (don't disable form controls).

## Limits

- "Submit & Add to library" in a picker's dialog continues to Add to
  library and selects nothing, as #1501 records.
- A picker + other than "Add-on of" carries no fact yet.

## Tests

- pytest, mechanism: fixed and stated; undeclared ignored; malformed
  (unknown word, empty, two values) renders the field, its sentence, and
  logs; absent row 404s on GET; absent row on POST renders the picker with
  `invalid_choice` and the typed values; tampered POST keeps the fact; no
  `disabled` on the hidden input; `<dl>` row in plain and grouped paths;
  implied fact; `action_url` with and without origin; `addon` cleaning.
- pytest, consumers: each page with and without its fact, the title, the
  played gate, the Release create rule, Cancel.
- vitest: the + query follows its field sources, and again after the
  element is re-inserted.
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
