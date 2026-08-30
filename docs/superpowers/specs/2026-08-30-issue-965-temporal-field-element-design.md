# Expand date entry inline in the browser

A person who knows only a year must not answer a menu first. The `temporal-field`
element shows one field, and the field grows as the person types.

The behaviour goes in `ts/elements/temporal-field.ts`. The props go in
`common/components/custom_elements.py` through `register_element`, and
`manage.py gen_element_types` writes them into `ts/generated/props.ts`.

## It enhances; it does not replace

The server renders the native controls of #964. `connectedCallback` hides the
controls a person does not need yet, and binds the segments. Remove the script
and the form still works, because the element writes the same named inputs.

## The segments come from the existing core

`ts/elements/date-field-core.ts` owns segment order, digit entry, paste, and
hidden-input sync, behind `bindSegmentField()` and a `FieldCodec`. A temporal
codec joins `dateCodec`. It differs in two ways: it accepts a partial date, and
it writes the parts to the named inputs of #964 rather than one ISO string.

Segment order follows the account profile through `DateTimePresentation`, the way
`DatePicker` gets it.

## How the field grows

A person types a year. An empty month segment appears, and filling it reveals a
day. Clearing a coarser part clears every finer part, because `1984--12` states
no month.

Two toggles say approximate and uncertain, for the whole value. A range toggle
reveals the second endpoint, and copies the qualifiers to it. An unknown toggle
empties the value and leaves the parts unreachable.

Each visible state writes the hidden kind input, thus the server reads what the
person sees.

## No calendar

`date-picker` keeps its month grid. A temporal value may be coarser than a day,
and a grid states no decade, no open endpoint, and no unknown. A control that
cannot say what the value says would invite a fabricated exact date.

## Tests

vitest beside the module, at `ts/elements/temporal-field.test.ts`, covers the
codec, the growth rule, and the clearing rule. A browser test in `e2e/` proves a
round trip with the element, and the same form proves one with scripting off.

## Boundary

No form field; #964 owns the markup and the cleaning. No presenter; #963 owns the
reading. No new stored shape.
