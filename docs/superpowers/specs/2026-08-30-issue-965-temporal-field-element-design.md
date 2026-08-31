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

A widget renders to text, so the node tree stops at `TemporalWidget.render()`
and this element's `Media` never reaches `collect_media()`. A page that hosts
the field threads `scripts=ModuleScript("dist/elements/temporal-field.js")`
itself, the way the purchase and play-event pages do for the date picker.

## The segments come from the existing core

`ts/elements/date-field-core.ts` owns segment order, digit entry, paste, and
hidden-input sync, behind `bindSegmentField()` and a `FieldCodec`. A temporal
codec joins `dateCodec`, and differs in one way: it accepts a partial date.

A codec reaches one hidden input, so it cannot address the several named inputs
of #964. Its value goes to an unnamed scratch input instead. The element's
`onCommit` reads the segment buffers back and writes the named inputs itself.

Segment order follows the account profile through `DateTimePresentation`, the way
`DatePicker` gets it.

## How the field grows

A person types a year, then a month, then a day, in one box. All three segments
stand there from the start: a segment that appeared only once the coarser one
was whole would move under the cursor mid-keystroke. Clearing a coarser part
clears every finer part, because `1984--12` states no month.

Everything else waits behind one disclosure, "I don't know the exact date",
which folds both ways. It takes itself away while the controls behind it hold
something the plain box could not state, so closing it strands no answer.

Behind it: approximate and uncertain, one pair per endpoint, because the grammar
qualifies each end on its own; a whole-decade box, which snaps the year down to
its ten and reads `1980s` in one cell; "No known start"; and how the value ends.

How it ends is one question with one answer — nothing more, ends on a date, or
still going — so it is a radio group, not boxes that reach into each other. Two
boxes could say "ends on a date" and "still going" at once, and the grammar has
no shape for that. An open start only disables the group, because an until does
end on a date.

Each visible state writes the hidden kind input, thus the server reads what the
person sees. Nothing states unknown: an empty field already does.

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
