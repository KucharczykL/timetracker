# A SearchSelect that clears

Every `SearchSelect` shows a trailing × when it holds a value or a typed
query. One press empties the query and the value. This applies to single and
multi mode, and to required and optional fields. A press never restores the
value that the page rendered. `clearable=False` removes the button.

## Prior art

| System | Name | What × clears | Signal |
|---|---|---|---|
| PatternFly Select typeahead | "Clear input value" | query and selection | consumer handler |
| MUI Autocomplete | "Clear" | query and value | reason `clear` |
| Carbon ComboBox, MultiSelect | "Clear selected item(s)" | selection | `onClearSelection` |
| Web Awesome, Shoelace | generic | value | `wa-clear`, `sl-clear` |
| React Aria SearchField | "Clear search" | query | `onClear` |

No system clears in two stages. No system puts the field name in the button
name.

## The button

The button is a `<button type="button">` with the name "Clear". Its
`aria-describedby` points to the field label. A screen reader reads "Clear,
push button, Device".

The button is in the field box, after the search input. Every combobox
personality draws its field with the same box, `[data-search-select-box]`. The
button is 32px square: this is more than the 24px touch minimum. A disabled
search input hides the button through `peer-disabled:hidden`.

The button is a Tab stop. When it gets focus, the panel closes and the pending
search stops. A late answer must not open the panel again.

## A press

A press stops the pending search and empties the box. It shows all rows again.
It blocks the automatic commit of a sole option until the next pick. Without
this block, the next search puts the cleared value back.

A pointer press does not move focus. Thus a phone tap does not open the
keyboard. A press from the focused button moves focus to the search input.

## The events

A press sends `search-select:change` with `values: []` only when it removed a
value. Then it always sends `search-select:clear` with `{ name }`. The time
zone row reads the clear event as its "use display zone" option.

## The options surface

`_OptionsSurface` declares each options list together with its row class. On
the unpadded field list, rows fill the width. On the padded dialog surface,
rows are inset and rounded, as other dialog items are.
