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

## The button

The button is a `<button type="button">` with the name "Clear". In a form, its
`aria-describedby` points to the field label. A screen reader reads "Clear,
push button, Device".

The button follows the search input in the field box. It is 32px square, more
than the 24px touch minimum. A disabled search input hides
the button through `peer-disabled:hidden`.

The button is a Tab stop. When it gets focus, the panel closes and the pending
search stops. A late answer must not open the panel again.

## A press

A press stops the pending search and the pending create. It empties the box.
A picker that searches a server drops the loaded rows and asks for the full
list again. A press blocks the automatic commit of a sole option until the next
pick or a change to a field that the picker depends on. Without this block, the
next search puts the cleared value back.

A pointer press keeps focus, so a phone tap opens no keyboard. A press from the
focused button moves focus to the search input.

## The events

A press sends `search-select:change` with `values: []` only when it removed a
value. Then it always sends `search-select:clear` with `{ name }`.

The time zone row reads the clear event as "use display zone". Its picker also
holds a captured browser zone, so the picker shows what the row submits.

The filter builder reads `last: null` from its field picker as "no field". It
replaces only the value cell, so text that a person types in the picker stays.

## The layout

`_ComboboxLayout` declares where a combobox lives: standalone, in a drop-down,
or in a dialog. It sets the list, the rows, the pills and the drop-down hook. `SearchSelect`, `FilterSelect` and
`PresetSelect` take one layout each.

- Every personality draws its field with one box, `[data-search-select-box]`.
- In a field, the pills are in the box and the rows fill the width.
- In a dialog, the pills are above the box and the rows are inset and rounded,
  as other dialog items are.
- A dialog shows the held label in the box when it opens.
