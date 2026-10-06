# Fixed choices leave the native select (#1292)

Parent: #481. Decision by the person, 2026-10-06: every fixed-choice
field converts to `SearchSelect`, small or not. The epic's acceptance
("No production user-facing native `<select>` remains") stays as written.

## Why convert, not radio or native

- Bulk Edit already edits `status`, game and purchase `kind`, entry
  `access` and the end `way` through `ChoiceSearchSelectWidget` (#1301).
  The single-row forms for the same facts render a native select. One
  fact, two controls.
- Settings convert every SELECT setting, THEME's three words included
  (#1289). Option count was not the rule there.
- #1290 closed: scripting off is not supported. A native select's one
  advantage (posts without JS) is no requirement.
- `RadioListWidget` stays where it already is (price, refund, format,
  provenance). Those are not selects; each option reveals other rows
  through `group-has-[[value=…]:checked]` CSS, which a radio states and a
  picker does not.

## The rule

A fixed-choice field renders `ChoiceSearchSelectWidget`. The form
framework states this, not each declaration:
`apply_primitive_widget_classes` (`games/forms.py`) already replaces a
`BooleanField`'s widget with `PrimitiveCheckboxWidget`. It now also
replaces a plain `forms.Select` on a fixed-choice field through
`host_choices`, so a field declared with Django's default widget renders
the picker.

- The type checks run first, `host_choices` second: `host_choices`
  raises on a `ModelChoiceField`, and three of them hold a plain `Select`
  when the mixin runs (`default_device`, the release row's platform, the
  settings `MODEL` path).
- "Plain" is `type(widget) is forms.Select`. `SelectMultiple`,
  `NullBooleanSelect` and any subclass are left alone.
- A `ModelChoiceField` is left alone: its picker needs a search URL, and
  `host_choices` refuses it. The one such field still native is the
  release row's platform (below).
- An `UnsetWidget` wrapping a native select is left alone (it is the
  wrapper, not a `forms.Select`).
- The replacement keeps the field's `required`, through `host_choices`.
  A later `field.choices = …` reaches the new widget: Django's choices
  setter writes `widget.choices`.
- The replacement states two options a native select implies:
  - `clearable` only where the choices hold `""` and the field is
    optional, the case where `render` pins a none row. A native select
    without an empty choice cannot be emptied. A × there would leave
    "Choose…" over a value the save then states silently (game kind
    cleans to main, edition kind keeps), or refuse a required field.
  - `revert_on_leave=True`. A first keystroke drops the held value and
    emits `search-select:change` with nothing (`search-select.ts`, the
    `input` handler). Leaving without a pick restores it, silently.
- A form that sets `field.required` after `super().__init__()` must call
  `host_choices` again: the widget's `is_required` decides the none row,
  and Django copies it only at build. No form does this today.
- A field the form replaces later (the session form's two zone fields,
  replaced by `TimeZoneRowWidget`) is swapped first and replaced second.
  The cost is one `normalize_choices` per build; accepted.
- A required field's picker says so. `SearchSelect` gains `required`,
  written as `aria-required="true"` on its search box, and `_render`
  forwards the adapter's `is_required`. The native select's `required`
  also blocked the submit in the browser; that block is gone, and the
  server's refusal is the only one.
- The replacement carries the old widget's `attrs`. `_render` refuses an
  attribute a `SearchSelect` has no home for, so a forgotten one fails
  loudly rather than vanishing.

## Fields that change

| Form | Field | Choices | None row |
|---|---|---|---|
| `GameForm` | `status` | `PlayerGameStatus` | no (required) |
| `GameForm` | `kind` | `GameKind` | no, no ×; a POST without it cleans to main |
| `EditionRowForm` (catalog) | `kind` | `EditionKind` | no, no ×; a POST without it keeps |
| Purchase add/edit | `kind` | `PurchaseKind` | no (required) |
| `DeviceForm` | `type` | `Device.DEVICE_TYPES` | no (required) |
| `DeviceForm` | `access` | `ACCESS_CHOICES` | `Held` |
| `EntryAddForm`, `EntryEditForm` | `access` | `EntryAccess` | no (required) |
| `EntryEndForm` | `way` | `WAY_CHOICES` | no (required); seeds `unstated` |
| `EntryEndEditForm` | `way` | `WAY_CHOICES` | no (required) |
| `BulkAccessEndForm` | `way` | the act's `ways` | no (required) |

`EntryEndForm` states no initial `way`. A native select posted its first
choice, `unstated` ("Not said"); a picker holds nothing. The form seeds
`way` with `EndWay.UNSTATED`, as `BulkAccessEndForm` does.
`BulkAccessEndForm`'s `_NO_WAY_CHOSEN` (`("", "Choose…")`, inserted when
`unstated` is not offered) goes: a required picker drops a `""` row, and
the placeholder already says "Choose…". The `unstated`-first sort stays.

Test harness forms on the same path convert by the same rule:
`KitForm` (`tests/test_settings_ui_kit.py`), `KitHarnessForm`
(`e2e/test_settings_ui_kit_e2e.py`), and the `DEBUG`-only settings kit
preview form. The preview's hand-built `Select` in
`_preview_standard_field` is no form field and stays; the page is
`DEBUG` only.

## Readers that change

- `<game-addon>` (`ts/elements/game-addon.ts`) reads
  `select[name=kind]` and listens for `change`. It reads
  `search-select[name=kind]` instead: the server-rendered held hidden
  input at connect, and a `search-select:change` carrying a value for a
  pick. A change carrying nothing is a typing drop, not a pick: it moves
  nothing, so the chosen parent survives a keystroke into Kind. It
  listens on the kind `<search-select>` itself: the parent picker's own
  events bubble through the same form.
- The catalog editor clones an edition row from a `<template>` by
  replacing `__edition__`/`__release__` in the whole markup
  (`renumbered`). A picker's id sits on its search box and its listbox
  ids are minted at init, so the clone is numbered like every other
  control and wires on connect. The `ReleaseRowForm.platform` comment
  and `test_a_release_row_renders_a_plain_select_not_a_combobox` claim a
  clone cannot rewrite a composite's id; that is false, and #1222, which
  converts the platform, removes both. The edition kind picker in the
  same template is this issue's proof that it is.
- `ts/setting-control.ts` reads a native `HTMLSelectElement` at four
  sites (the `NativeElement` union, `resolvedSnapshot`'s blank branch,
  `editable()`'s read-only guard, `settingControlOf`). Once the kit
  harnesses convert, no live setting renders one; all four go.
  `NativeSettingControl` keeps checkbox, number and text. The fixtures
  in `setting-control.test.ts`, `live-setting-fields.test.ts` and
  `theme-setting.test.ts` that mount a `<select>` mount a
  `<search-select>` instead.

## The temporal shape select

`common/components/temporal_field.py` renders the shape select itself,
inside `[data-temporal-native]`. Two cases:

- Segments can hold the value: the group is wrapped in
  `<temporal-field>`, which hides the native set and derives the shape.
  The shape control is never visible. It becomes
  `<input type="hidden" data-temporal-input="kind">`;
  `temporal-field.ts` already reads and writes its `.value`.
- Segments cannot hold it (the server echoes text a segment cannot
  hold): the group is returned bare, no element runs, and the native set
  is the control. The shape becomes a `SearchSelect` over
  `TEMPORAL_DRAFT_KIND_LABELS`, a refused shape echoed as one more row,
  `clearable=False`, `revert_on_leave=True`, `required` from the field.
  `TemporalWidget.component_media` adds `search-select.js` and
  `drop-down.js`: a widget's media does not bubble. A picker holding nothing
  posts no kind, and `TemporalWidget.value_omitted_from_data` then reads
  the whole field as omitted; these two options keep a value held.

The row label's `for` names `input_id`, which stays on the kind control
in both cases: the picker's search box, or the hidden input. Today it
names a select the element hides, so the wrapped case focuses nothing
either way; the group's `aria-labelledby` names the field.

The module docstring of `temporal_field.py` ("Nothing here needs a
script", "Every posted control is shown") and `docs/temporal.md` change
with it.

## Out of scope

- The release row's platform: a `ModelChoiceField`, #1222.
- The filter builder's and quick bar's selects: #1291.
- `_preview_standard_field`'s hand-built select (`DEBUG` only).

## Tests

Existing tests that pin a native select are rewritten, not deleted.
`test_stamping_applies_the_shared_control_classes_by_widget_type`
(`tests/test_settings_forms.py`) is the mixin's own contract and states
the new one. The preview tests' `_named_tag(body, "select",
"destination")` match the converted form field. Also:
`<option … selected>` pins in the game, edition, device, entry-end and
temporal tests; `select_option` calls in the library tab, library
section, device access end, dialog create and catalog e2e files; the kit
harness asserts; `ts/elements/game-addon.test.ts`.

New:

- `apply_primitive_widget_classes` replaces a plain `Select` on
  `ChoiceField` and `TypedChoiceField`, keeps `required`, keeps a later
  `choices` assignment, leaves `ModelChoiceField`, `SelectMultiple`,
  `NullBooleanSelect` and `UnsetWidget` alone.
- Each form above renders `search-select[name=…]` and no `<select`.
- `EntryEndForm` holds `unstated` unbound.
- A required field's picker carries `aria-required="true"`.
- A swapped field shows × only with a none row.
- vitest: `<game-addon>` ignores a typing drop and ignores the parent
  picker's events.
- e2e: two cloned editions' kind pickers hold distinct listbox ids and
  save their kinds; a refused temporal value renders a shape picker and
  saves a picked shape.

## Follow-up issues

None new. #1222 owns the last form select; #1291 the builder's.
