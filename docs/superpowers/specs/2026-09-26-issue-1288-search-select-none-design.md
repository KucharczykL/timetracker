# A SearchSelect that holds "none"

Issue #1288, parent epic #481. Builds on #1287 (the ×) and #1295 (one row
builder).

## Outcome

A single-select `SearchSelect` can hold **none** as a value: a pinned row the
caller labels ("No device", "Unspecified", "Use site default (UTC)"). Picking
it is a committed act, told apart from **nothing picked**, the transient state
a person is in while typing into a held value.

The two post the same `null` to a two-state form. They differ for a form that
saves on change (#1289): a pick of none is a reset to save, a first keystroke is
not. Today a first keystroke into a held value emits `search-select:change`
with `values: []` (`ts/elements/search-select.ts`, the `input` listener), which
a live setting cannot tell from a reset.

## Prior art

| System | "None" | Held and shown |
|---|---|---|
| Native `<select>` | `<option value="">` | its label |
| MUI Material Select | `<MenuItem value="">None</MenuItem>`, `displayEmpty` | "None" |
| Base UI Select | an item with `value: null` | its label replaces the placeholder |
| Linear | "No assignee" row in the assign menu | "No assignee" |
| Radix Select | `""` is reserved for "nothing picked"; callers add a `"none"` item and map it to `null` | the item's label |
| React Aria Select | placeholder and `null` only | — |

"None" is a row that is held once picked. Systems without that row make callers
add one. Base UI's open bugs (the null row is not marked selected, and the
keyboard cannot return to it) are this design's test list.

## Three states

| State | Box shows | Hidden input | Row `aria-selected` | × |
|---|---|---|---|---|
| a value | its label | `name=<value>` | the value's row | shown |
| none | `none_label` | `name=""`, marked `data-search-select-none` | the none row | hidden |
| nothing picked | the typed text, pencil cue | absent | none | shown while text is present |

- A field rendered with value `None` holds none. A picker with a `none_label`
  starts in none or a value, never in nothing picked.
- Picking the none row holds none.
- × on a held value holds none, then emits `search-select:clear`. In a picker
  without `none_label`, × behaves as #1287 states.
- The first keystroke into a held value or a held none drops to nothing
  picked, as it does today. The committed label is `none_label`, so focus
  selects it and a keystroke replaces it.
- Blur does not change the state. A person who types and tabs away is still in
  nothing picked, and the pencil cue shows it. A two-state form posts `null`
  for it, which is the same fact as none.

## The row

`_option_row(option, RowKind.MODIFIER)` with `{value: "", label: none_label}`,
rendered first in the options panel. It is pinned: the text filter never hides
it, and a server answer replaces only `[data-search-select-option]` rows, so the
none row survives every fetch. It is navigable (`NAVIGABLE_ROWS` already includes
modifier rows). The row renders no `id`, so a cloned prototype carries it
(#1222, #991).

Filter mode already reads modifier rows for `(Any)`/`(None)`. The form-mode
click and Enter paths get their own branch for the none row, so filter mode is
unchanged.

## The wire

- none: an empty hidden input, so the key is present with `""`.
- nothing picked: no hidden input, so the key is absent.

`SearchSelectWidget.value_from_datadict` stays `data.get(name)`. Django reads
both as `None`, so each form that adopts `none_label` keeps its `clean`. The wire
still separates them. A three-state bulk form (#1302) can later read `""` as none
and a missing key as "leave as it is". This issue does not change bulk forms.

## The event

`SearchSelectChangeDetail` gains `none: boolean`.

| Act | `values` | `last` | `none` |
|---|---|---|---|
| pick a value | `[value]` | the option | `false` |
| pick the none row | `[]` | `null` | `true` |
| × on a held value (none picker) | `[]` | `null` | `true` |
| first keystroke into a held value or none | `[]` | `null` | `false` |

`currentValues()` skips the input marked `data-search-select-none`, so `values`
never carries `""`. Every present listener reads `values` and needs no change.
#1289 saves `null` on `none: true` and ignores a drop with `none: false`.

A picker without `none_label` always emits `none: false`.

## Rules beside other features

- **`commit_sole_option` (#1080).** None is held. `commitTheSoleOption` already
  returns when a hidden input exists, so the none input blocks it with no new
  code; a test pins it.
- **`params` dependency (#1080).** A dependency change drops a held value,
  because the value belonged to the old parent. None belongs to no parent, so it
  survives, and no event fires.
- **× visibility.** `syncClearButton` counts hidden inputs; it skips the none
  input, so × hides while none is held.
- **Uncommitted cue.** A held none has a hidden input, so the cue stays off.

## Refusals

`SearchSelect(none_label=…)` raises `ValueError` beside `multi_select=True`
(multi's none is "no pills") and beside `panel=True`. `FilterSelect` and
`PresetSelect` take no `none_label`. `SearchSelectWidget.render` raises
`ValueError` when `none_label` is set and `self.is_required` is true: a required
field has no "none".

## Django adapter

`SearchSelectWidget(none_label: str | None = None)` passes the label through.
`clearable` is unchanged.

The two-state rule for #1301: a `ChoiceField`'s empty choice `("", label)` is
`none_label` in a two-state form. In a bulk form it is the placeholder that
names "leave as it is". #1301 gets a comment that states this rule. This issue
does not implement it.

## Consumers

Three optional pickers that store `NULL` for none and show a blank box today:

| Form | Field | `none_label` |
|---|---|---|
| `SessionForm` | `device` | `No device` |
| `HistoricalPlaytimeForm` | `device` | `No device` |
| `PurchaseForm` | `platform` | `Unspecified` |

The labels are the ones list and detail pages already render for `NULL`.
Purchase `related_game` stays as it is: blank means "not an add-on" there, and
no word is needed.

Settings and the Library default Device use this through #1289, which adds the
live-settings reader.

## Testing

- **Python:** the none row renders first and pinned. A `None` value renders the
  empty marked input and the label in the box. Both refusals raise. The widget
  refuses `none_label` on a required field.
- **vitest:** pick none (event, input, box, `aria-selected`). × on a held value
  holds none and hides ×. A first keystroke into none emits `none: false`. The
  arrow keys reach the none row from both directions. A server answer keeps the
  row. `commit_sole_option` does not replace a held none. A dependency change
  keeps none. A cloned prototype's none row works independently.
- **e2e:** on Edit Session, pick "No device" and save, and the row stores
  `NULL`. Press × on a held device and save, with the same result.
- **Accessibility:** a screen reader reads the held none as the field's value
  ("No device, Device, combo box").

## Out of scope

- The live-settings reader, the settings conversions and the Library default
  Device: #1289.
- The ⊘ toggle in bulk forms: #1302.
- The fixed-choice adapter: #1301.
- Scripting off: #1290. If #1290 enhances a native select, none maps to its
  `<option value="">`.
