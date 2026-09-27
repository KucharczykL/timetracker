# A field that states "none" apart from "leave as it is"

Issue #1302. Consumer: bulk Edit on the session list (#1211, PR #1285), later
bulk status/mastered (#1270) and bulk record edits (#1150).

## Problem

A bulk form states three things per field:

| State | How it is stated | Posted |
|---|---|---|
| keep (leave as it is) | the field is empty; its placeholder names what is kept | field key empty or absent, no `<name>-unset` |
| a value | the field holds a value | field key with the value |
| none | ⊘ is pressed | `<name>-unset=1`, which wins over anything the field posts |

An empty field already means "keep", so "none" (no device, no note) needs its
own control. The picker's × (#1287) returns a picker to empty, which here is
"keep".

## Prior art

| System | Control | State |
|---|---|---|
| Stash bulk edit | a ban button beside each bulk text field | removes the value on every selected item |
| WAI-ARIA APG, toggle button | `aria-pressed` | the name stays the same in both states |

## Rejected: the picker's own none row

#1288 gives a picker `none_label`, whose wire already tells absent, `""` and a
value apart. A bulk picker could read none from that row. It is not used:

- With `none_label`, × holds none. Keep is then reachable only by typing into
  the box and emptying it again, never by one tap.
- A textarea has no none row, so the form would state none two ways.

`UnsetWidget` refuses an inner picker that pins a none row.

## The element

`<unset-field>` wraps one field and one ⊘ toggle, joined by `SegmentedField`
(field `start`, toggle `end`). It has a real checkbox,
`name="<name>-unset" value="1"`, which is the one source of the pressed state.

The element knows one thing about the field: its **control**, the first
`input:not([type=hidden])`, `textarea` or `select` in the field member. A
`SearchSelect` has one: its search box.

A press on ⊘:

1. Remembers the control's value and placeholder.
2. Empties the control and sets its placeholder to the none label ("No
   device").
3. Disables the control, unless the page already did. A `SearchSelect`
   keeps its hidden value input enabled, so it still posts its value; the
   server lets ⊘ win. Its × hides through `peer-disabled`.
4. Checks the checkbox, sets `aria-pressed="true"`.
5. Dispatches `unset-field:change` with `{ name, unset: true }`, bubbling.

A second press reverses each step: value and placeholder back, the control
re-enabled if the press disabled it, checkbox off, `aria-pressed="false"`, event
with `unset: false`.

At connect, a checked checkbox applies the pressed state without an event. The
checkbox has `autocomplete="off"`, so a reload does not restore a stale press.
A reconnect after a DOM move binds nothing twice.

`unset-field:change` is not a native `change`. A disabled control leaves
`FormData`, so a ⊘ field is not a picker's `params` source.

## Layout

The element is `block`; the joined row is `w-full`. The field member is
`flex-1 min-w-0 focus-within:z-10`, so a focused box's ring lies over the
toggle's shared border. The toggle stretches to the field's height, a
textarea's included.

## Accessibility

The toggle is a `ControlButton`, `variant="segmented"`, `color="gray"`, with an
icon only. Its `aria-label` and `title` are the none label; its
`aria-describedby` is the field label, as the picker × does. Orca reads "No
device, toggle button, not pressed, Device". The pressed look is the brand
fill that the current page tab uses. `dark:aria-pressed:solid-brand` repeats
it, because the gray look's `dark:hover:` and `dark:focus:` text outrank a bare
`aria-pressed:` fill.

## Scripting off

The element is undefined. `[unset-field:not(:defined)_&]` hides the toggle
and `[unset-field:defined_&]` hides the checkbox's label. So without
scripting the end member is the checkbox, labelled with the none label, in
the segmented look. The server lets a checked box win over a value left in
the field.

## Server side

`UnsetWidget(widget, *, none_label)` in `games/forms.py` wraps a widget:

- `render` draws `UnsetField` around the inner widget. It renders the inner
  widget at the shape its place gives it, with the wrapper's own `attrs`
  (Django writes `maxlength` there) merged in.
- Only a single-value `SearchSelect` adapter and a text, number, textarea or
  select control are joined. A picker with `params` or `commit_sole_option`
  is refused: search-select rewrites such a picker's value while its box is
  disabled.
- A write to an attribute the inner widget holds (`placeholder`,
  `options_resolver`) raises `AttributeError`, because the wrapper would keep
  it and the inner widget would never see it. Callers write to `.widget`.
  The names Django writes onto a field's widget stay the wrapper's.
- `value_from_datadict`: a posted `<name>-unset` returns `None`, so the field
  cleans to its own empty value and a value left in the field is never
  validated. Otherwise the inner widget answers.
- `value_omitted_from_data`: both keys absent.
- `id_for_label`, `choices` and `needs_multipart_form` go to the inner widget.
  `__deepcopy__` copies the inner widget.
- Refused with `ValueError` at render: a required field, where empty cannot
  mean keep, and an inner picker that pins a none row. A fixed-choice picker
  pins one from a `""` choice, so the check reads the inner widget at render,
  after the wrapper hands its `is_required` down.

`UnsetFieldsForm`, a `forms.Form`, reads `<prefix>-<name>-unset` at
construction, so a bound form shown again renders ⊘ pressed. Its `clean()`
skips a field with errors and gives every other ⊘ field one of three values:

| Posted | `cleaned_data[name]` |
|---|---|
| `<name>-unset` | the field's empty value: `None` for a model choice, `""` for text |
| an empty field | `KEEP` |
| a value | the cleaned value |

`KEEP` is the one member of `Keep`. `type Kept[T] = T | Keep` names a field's
cleaned type. A `clean_<name>` method still sees the field's own empty value
for both keep and none.

## The shape

- `SearchSelect` takes `shape: ButtonShape = "full"`. The box takes
  `SHAPE_CLASSES[shape]` where it had `rounded-base`. The default output does
  not change. `_SearchSelectAdapter` carries `shape` to it.
- The native classes split into a look without corners and
  `native_control_class(widget, shape)`. `apply_primitive_widget_classes`
  skips an `UnsetWidget`, which stamps its inner native control at render.

## Media

A widget renders to text, so a component's `Media` does not bubble. A widget
can now declare `component_media`; `FormFields` attaches it to the control.
The row and the embedded path both attach it. `UnsetWidget` declares
`dist/elements/unset-field.js`. A widget can also name `requires_form`;
`FormFields` raises `ValueError` for a form that is not one, so an
`UnsetWidget` outside `UnsetFieldsForm`, where keep and none would clean
alike, fails at render. A form drawn without `FormFields` is not checked.

The picker adapters do not declare media yet; their pages thread the scripts.
A follow-up issue moves them and drops the threading.

## The icon

`no-symbol` (⊘), added to `games/templates/icons/` and generated by
`make gen-icons`.

## Tests

- vitest: a press, a second press that restores, controls already disabled
  stay disabled, the event, a checked box at connect, a reconnect.
- pytest: the component markup, the three cleaned states for a model choice
  and a text field, ⊘ over a left value and over an invalid value, a bound
  form shown again, the refusals, the attribute guard, `choices` forwarding,
  the deep copy, the shaped classes, the media and the missing-base refusal.
- e2e, synthetic page: ⊘ on a picker and on a textarea posts none; a second
  press posts the value; an empty field posts keep.
- Orca: the pressed state, by the owner.

## Out of scope

- Wiring the bulk Edit form: PR #1285, after this lands.
- Moving the picker adapters onto `component_media`: follow-up issue.
