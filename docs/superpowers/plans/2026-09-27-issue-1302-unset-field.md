# Plan: the ⊘ unset field (#1302)

Spec: [A field that states "none" apart from "leave as it is"](../specs/2026-09-27-issue-1302-unset-field-design.md).
Inline, test first per task. `make check-fast` while iterating; one full
`make check` (under the heavy-tests lock) before the PR.

## 1. Shape reaches the controls

- `common/components/search_select.py`: `SearchSelect(shape: ButtonShape =
  "full")`; `_BOX_CLASS` keeps its order with the corner as a slot.
- `games/forms.py`: `_SearchSelectAdapter.shape` (default `"full"`), passed in
  `_render`. Native classes split: `_INPUT_LOOK`, `_SELECT_LOOK`,
  `_TEXTAREA_LOOK` + `native_control_class(widget, shape)`; the three public
  constants stay, equal to the `full` shape.
- Tests: `tests/test_components.py` (a `start` box has `rounded-s-base`, no
  `rounded-base`; default markup unchanged); `native_control_class` per widget
  kind.

## 2. The icon

- `games/templates/icons/no-symbol.html` (⊘, `currentColor`, same frame as
  `x-mark.html`), `make gen-icons`.

## 3. The component

- `common/components/custom_elements.py`: `UnsetFieldProps(name, none_label)`,
  `register_element("unset-field", "UnsetField", …)`, `make
  gen-element-types`.
- `common/components/unset_field.py`: `UnsetField(*, name, none_label, field:
  ShapedMember, unset: bool, describedby: str | None)`. The field member is a
  `flex-1 min-w-0 focus-within:z-10` wrapper with `data-unset-field-member`.
  The end member holds the toggle (`ControlButton`, segmented gray,
  `data-unset-field-toggle`, `aria-pressed`, hidden while undefined) and the
  checkbox label (`data-unset-field-state` on the input, hidden once defined).
  Export from `common/components/__init__.py`.
- Tests: `tests/test_unset_field.py` — names, `-unset` checkbox, `checked` and
  `aria-pressed` follow `unset`, `:defined` classes, shapes, media.

## 4. The element

- `ts/elements/unset-field.ts`: as the spec's press list. State in a
  `Pressed` record (value, placeholder, controls it disabled). Guard
  reconnects.
- `ts/elements/unset-field.test.ts` (jsdom): textarea press/restore,
  SearchSelect-like markup (hidden input + search box + ×), pre-disabled
  control stays disabled, event detail both ways, checked-at-connect applies
  without event, reconnect binds once.

## 5. Widget, mixin, FormFields

- `games/forms.py`: `Keep`/`KEEP`, `type Kept[T]`, `UnsetWidget`,
  `UnsetFieldsForm`; `apply_primitive_widget_classes` skips the wrapper,
  which stamps its inner native control at render.
- `common/components/primitives.py` `_form_field_row`: attach
  `widget.component_media` when present. `FormFields` refuses an
  `UnsetWidget` in a form that is not an `UnsetFieldsForm` — the check
  imports nothing from `games`: the widget names `requires_form`.
- Tests (`tests/test_unset_field.py`): three states × `ModelChoiceField`
  (`Device`) and `CharField` textarea; ⊘ beats a left value and an invalid
  pk; required and a none row refused at render; attribute guard;
  `ChoiceField` choices reach the inner widget; two form instances do not
  share the inner widget; `id_for_label`; FormFields media + refusal.

## 6. e2e

- `e2e/test_unset_field_e2e.py`, synthetic urlconf as
  `e2e/test_choice_search_select_e2e.py`: a `ChoiceSearchSelectWidget` field
  and a textarea, both initial values. Cases: ⊘ posts none on each; ⊘ twice
  posts the value; emptied field posts keep; the pressed toggle reads
  `aria-pressed=true` and the control is disabled with the none placeholder.
  No console errors.
- Screenshot the harness in the Browser pane, light and dark, both states.

## 7. Docs

- CLAUDE.md: `unset_field.py` beside `search_select.py`; `component_media` in
  the widget-media note.
- Follow-up issue: move the picker/temporal adapters onto `component_media`
  and drop the threaded scripts.
- Comment on #1211 / PR #1285: how to wire Device and Note.

## Gotchas

- `make lint-fix` for import order; `make format` before each commit.
- `make ts` before e2e so `dist/` holds the element.
- Never run e2e beside `make dev`.
