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
add one. Base UI's open bug (the keyboard cannot return to the null row) is on
this design's test list.

## Three states

| State | Box shows | Hidden input | × |
|---|---|---|---|
| a value | its label | `name=<value>` | shown |
| none | `none_label` | `name=""`, marked `data-search-select-none` | hidden |
| nothing picked | the typed text, pencil cue | absent | shown while text is present |

Single mode marks no held row with `aria-selected`; the attribute follows the
highlight, and `clearHighlight` rewrites it. A held none follows the same
convention. The box text states the value to a screen reader.

- A field rendered with value `None` holds none. So does a value the resolver
  cannot resolve (a removed row): the box states what a save will post. Forms
  that keep a held removed row resolve it first, as `HistoricalPlaytimeForm`
  does; #1303 gives `SessionForm` the same. A picker with a `none_label`
  starts in none or a value, never in nothing picked.
- Picking the none row holds none.
- In a none picker, × always holds none, from a held value and from typed text
  alike, then emits `search-select:clear`. In a picker without `none_label`, ×
  behaves as #1287 states.
- The first keystroke into a held value or a held none drops to nothing
  picked, as it does today. The committed label is `none_label`, so focus
  selects it and a keystroke replaces it.
- Escape closes the panel and does not change the state.
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

The row carries its own hook, `data-search-select-none-option`, not
`data-search-select-modifier-option`. The Enter branch calls `setModifier` for any
highlighted row with the modifier attribute and is not limited to filter mode.
In form mode that would clone a `pill-modifier` template that does not exist and
raise. The click path finds no `[data-search-select-option]` and does nothing.
A separate hook keeps filter mode unchanged. The none row joins
`NAVIGABLE_ROWS`, and the click and Enter paths get a branch that holds none.
`filterRows` and `fetchFromServer` read only option rows, so they never hide or
remove it.

- **Highlight.** `autoHighlight` walks visible rows in order, and the none row
  comes first. With a query, it skips the none row, so "No" never highlights
  "No device" over a real device. With an empty query, it highlights as today.
- **Create row.** `loadedLabels` counts `none_label`. Typing the label exactly
  offers no Create row. Enter then picks none.
- **Panel.** A pinned row makes `hasVisibleContent` true, so the panel opens on
  focus. With a query that matches nothing, "No results" shows under the none
  row. That is correct: none stays reachable.

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
never carries `""`. The present listeners are safe. `add_purchase.ts` reads `values.length` and
`last.data`. `selection-fields.ts` reads pills. The filter builder, quick bar,
`filter-group` and `field-comparison-set` sit on pickers that take no
`none_label`. `time-zone-row.ts` returns on `last === null` and reads
`search-select:clear` as "use display zone". It must read `none` if it takes a
`none_label`, which is #1289's work. #1289 saves `null` on `none: true` and
ignores a drop with `none: false`.

A picker without `none_label` always emits `none: false`.

## Rules beside other features

Every reader of the hidden inputs must decide about the none input:

| Reader | Treatment of the none input |
|---|---|
| `currentValues` | skips it, so `values` never carries `""` |
| `getSelectedValues` | skips it, so `_searchSelectSetOptions` keeps a held none |
| `syncClearButton` | skips it, so × hides while none is held |
| `syncUncommitted` | counts it, so the pencil cue stays off (no change) |
| `commitTheSoleOption` | counts it, so none is held and never replaced (no change; a test pins it) |

`_searchSelectClear` empties pills, label and box. The ×,
`onDependencyChange`, `clearSelection()` and `_searchSelectSetOptions` call it.
A none picker gets `holdNone()`, which does the same and then writes the none
input and the label.

- **× (#1287).** The click calls `holdNone()` in a none picker and always emits
  the change with `none: true`, because the value was dropped or the typed text
  was.
- **`params` dependency (#1080).** A dependency change drops a held value,
  because the value belonged to the old parent. None belongs to no parent. In a
  none picker, the change calls `holdNone()` where a value was held, and does
  nothing where none was held.
- **`setSelected` / `setOptions`.** A programmatic set replaces none like a
  pick.
- **`_searchSelectRefetch`** reads `_searchSelectLabel`, which is `none_label`,
  so it works with none and needs no change.

## Refusals

`SearchSelect(none_label=…)` raises `ValueError` beside `multi_select=True`
(multi's none is "no pills") and beside `panel=True`. `FilterSelect` and
`PresetSelect` take no `none_label`. `SearchSelectWidget.render` raises
`ValueError` when `none_label` is set and `self.is_required` is true: a required
field has no "none". Django copies `required` to `widget.is_required` in
`Field.__init__`, so the refusal is reached on the first render; a form test
renders each consumer.

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

"No device" is the word the session and historical lists render for `NULL`.
No page renders a `NULL` `Purchase.platform`. "Unspecified" is the word the
catalog gives a game with no platform, and the Release row's empty choice uses it.

**Purchase platform autofill.** `add_purchase.ts` fills Platform from each game
pick. A person's own pick, a platform or "Unspecified", then stays. Autofill
writes only a Platform that is empty or that autofill wrote itself. This
matches the existing guard on `related_game` (`autofilledRelatedGameValue`).
Purchase `related_game` stays as it is: blank means "not an add-on" there, and
no word is needed.

Settings and the Library default Device use this through #1289, which adds the
live-settings reader.

## Testing

- **Python:** the none row renders first and pinned. A `None` value renders the
  empty marked input and the label in the box. Both refusals raise. The widget
  refuses `none_label` on a required field.
- **vitest:** pick none by click and by Enter (event, input, box). × on a held
  value and × on typed text both hold none and hide ×. A first keystroke into
  none emits `none: false`. The arrow keys reach the none row from both
  directions. A query never highlights the none row. Typing the none label
  offers no Create row. A server answer and `setOptions` keep the row and a
  held none. `commit_sole_option` does not replace a held none. A dependency
  change turns a held value into none and keeps a held none. A cloned
  prototype's none row works on its own. Filter mode's modifier rows are
  unchanged.
- **add_purchase vitest or e2e:** a game pick fills an empty Platform and
  replaces an autofilled one. It leaves a picked platform and "Unspecified"
  alone.
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
