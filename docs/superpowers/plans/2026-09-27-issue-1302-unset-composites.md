# Plan: ⊘ on composite fields (#1302, part 2)

Spec: "Composite fields" in [the unset field](../specs/2026-09-27-issue-1302-unset-field-design.md).

## 1. Python

- `games/forms.py`: widen `_UNSET_NATIVE` to `forms.Input` minus checkbox,
  hidden, file; add `_UNSET_BESIDE = (HoursMinutesWidget, DatePickerWidget,
  DateTimeFieldWidget, TemporalWidget)`; `render` passes `joined=False` for
  those and renders the inner widget unshaped.
- `common/components/unset_field.py`: `UnsetField(joined=True)`; beside layout
  is `flex items-start gap-2`, toggle and fallback label at `full`.
- Tests: `EmailInput` joins; each composite renders beside; `RadioSelect`,
  `ClearableFileInput`, `TimeZoneRowWidget` refused; a composite field cleans
  none, keep and value.

## 2. TS

- `ts/elements/unset-target.ts`: `UnsetTarget`, `isUnsetTarget`,
  `freezeControls`.
- `unset-field.ts`: target-or-native; connect waits on `whenDefined` of the
  field's custom elements before applying a checked box.
- `date-picker.ts`, `date-time-field.ts`, `temporal-field.ts`: implement the
  two methods (commit `""` / `setValue("")` / `adoptDraft(empty)`).
- vitest: `freezeControls` keeps pre-disabled controls; native multi-input;
  a fake target gets both calls; each composite's own test file: unset
  empties and disables, restore brings the value back.

## 3. e2e

- Harness gains a date picker, an hours+minutes and a temporal field: ⊘
  posts none, ⊘ twice posts the value.
- Screenshot the beside layout.

## Gotchas

- `make gen-element-types`, `make ts`, `make css` before e2e.
