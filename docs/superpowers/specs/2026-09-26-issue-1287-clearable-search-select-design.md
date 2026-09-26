# A SearchSelect that clears

Issue #1287, first item of the shared component work in epic #481.

A `SearchSelect` can only be emptied by selecting the box text and deleting it.
Nobody finds that, and a phone user must open the field and summon the keyboard
to do it. Every select #481 still converts is optional, so converting one today
makes its value permanent. A clearable `SearchSelect` shows a trailing × that
empties the field in one press, from any state, without the box being focused.

## Where this departs from #481 and the issue

Three rules of the filed text are reversed. Each follows the prior art below.

1. **One press clears everything.** The epic asked for two stages: × first
   clears a typed query and keeps the committed selection, a second × clears
   the selection. No surveyed system does this. In single mode it protects
   nothing either: the first keystroke already abandons the committed value
   (`search-select.ts`, the `input` listener). So × resets query and value
   together, in both flavours.
2. **The button is named "Clear", not "Clear Device".** No surveyed system puts
   the field in the name. The field reaches assistive technology as the
   button's description instead (below).
3. **Every press is announced.** The issue had a query-only press emit nothing.
   A dedicated clear event is common prior art, and a consumer can use it to
   tell a reset gesture from a pick.

| System | Name | What × clears | Signal |
|---|---|---|---|
| PatternFly Select typeahead | "Clear input value" | query and selection | consumer handler |
| MUI Autocomplete | "Clear" | query and value | `onInputChange`/`onChange` with reason `clear` |
| Carbon ComboBox, MultiSelect | "Clear selected item(s)" | selection | `onClearSelection` |
| Web Awesome, Shoelace | generic | value | `wa-clear`, `sl-clear` |
| React Aria SearchField | "Clear search" | query | `onClear` |

## The button

`SearchSelect(clearable=True)` renders a `<button type="button">` inside the
field, after the search box and before the #450 committed marker. It carries
`aria-label="Clear"`, `title="Clear"` and a `data-search-select-clear` hook.

The button shows when the widget holds a committed value (a single label or at
least one pill) or the box holds a typed query. Otherwise it carries `hidden`.
The server renders it hidden when no option is selected. One function in the
element, `syncClearButton()`, decides visibility. Every path that changes the
value or the box text calls it: a pick, a pill ×, an input, `setSelected`,
`_searchSelectClear`, `setOptions`, the create row, a dependency change and the
× itself. The button is also hidden while the search box is `disabled`. Nothing
disables a `SearchSelect` at runtime today, so no observer watches for it.

The field's name reaches the button as a description. At init the element finds
the field's `<label>`, the same lookup `fieldLabel` performs, assigns it an id
if it has none, and points the button's `aria-describedby` at it. Orca then
reads "Clear, push button, Device". A field without a `<label>` gets no
description. The id is assigned at init, not rendered, because the filter
builder clones whole `<search-select>` prototypes.

## A press

A press clears the pills or hidden inputs, the label and the box text. Then it
marks the box as a typed query that is empty. That mark keeps
`commitTheSoleOption` from committing the one option the next fetch answers.
Without it, a field whose search states one option would put back the value the
person just removed. A later pick, or a dependency change, lifts the mark as it
does today.

Focus follows the input method:

- **Pointer or touch.** The button takes no focus: its `mousedown` is
  prevented, as the pill × already is. Focus stays where it was. A phone tap
  clears the field without opening the keyboard or the panel.
- **Keyboard.** Enter or Space produces a click whose `detail` is 0. Focus
  moves to the search box, because the button hides under it and focus would
  otherwise fall to `<body>`.

## The events

A press dispatches, in order:

1. `search-select:change` with `values: []` and `last: null`, only when the
   press removed a committed value. A press that emptied a query alone does not
   change the value, so it does not claim one.
2. `search-select:clear`, always, bubbling, with detail `{ name }`. Its type,
   `SearchSelectClearDetail`, sits beside `SearchSelectChangeDetail` in
   `ts/elements/search-select.ts`, which consumers import and never redefine.

No consumer listens to the clear event yet. The bulk Edit of #1211 is the
likely first one: its × means "leave as it is" and its ⊘ toggle means "none",
and the two stay different facts.

## Who gets the button

The component takes `clearable: bool = False`. It knows nothing of forms, so it
has no notion of required.

`SearchSelectWidget` takes `clearable: bool | None = None`. `None` resolves at
render to `not self.is_required`, which Django sets from the field. `True` or
`False` at the call site overrides it. Every optional form picker offers ×
without being told. A required one does not offer an emptiness the form would
refuse, unless its call site asks.

`FilterSelect` and `PresetSelect` do not take the parameter. The quick filter
bar has its own Clear, and the builder's rows belong to #481's third
workstream.

## The contract

`clearable` reaches the element as a prop registered through
`register_element`. `make gen-element-types` regenerates `ts/generated/props.ts`.

## Tests

- **pytest, component.** A clearable widget renders the button hidden with no
  selection and shown with one, in both flavours. The attributes are as stated.
  A non-clearable widget renders no button. `SearchSelectWidget` resolves
  `None` from `is_required` both ways and honours both overrides.
- **vitest.** Visibility follows every path `syncClearButton()` names. A press
  with a committed value emits change, then clear. A query-only press emits
  clear and no change. A press on a `commit_sole_option` field whose next fetch
  answers one option leaves it empty. `aria-describedby` points at the label,
  and at nothing when there is no label.
- **e2e, one per flavour.** A keyboard press empties the field, moves focus to
  the box, and the form posts no value. A pointer press empties it and leaves
  focus where it was.
