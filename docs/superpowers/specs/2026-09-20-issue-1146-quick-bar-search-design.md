# The quick bar's search field

`search` is a criterion on all seven filters, reading several columns. The quick
bar renders it as one field at the start of the row.

## The field

`SegmentedField` joins a match-mode trigger to a text box. Position decides each
member's rounding; the row draws one border and one shadow, and a focused member
lifts above its neighbour.

The trigger shows a mark and a chevron; its accessible name states the mode
(`Match mode: excludes`). The wider menu shows each mark beside its words,
marking the current mode. A chosen mode closes the menu, which the shared radio
behaviour does not. The box has no label, so its placeholder names it.

A widget states its modifier on a `select`, read first, or on its root as
`data-modifier`; this field has only the second. A widget with neither is a
defect: it is reported, and reads includes.

## The modes

The six modes are includes, excludes, is, is not, matches regex, and not matches
regex. `IS_NULL` and `NOT_NULL` mean nothing across several columns. The field
states the same six as `search_q`, or it stops at import.

## The marks

An arc a bar crosses is `includes`. Two bars are `is`. `.*` is the regex. A
negative mark adds a diagonal, with a gap in the glyph where it crosses. The gap
is a stroke in the surface colour.

## What `search_q` reads

Each mode names a lookup. A negative mode negates its positive partner's whole
disjunction: "excludes Zelda" means no column holds it. The exact pair reads
without case; the regex pair does not. An empty value adds no constraint.
`search_q` reads the mode before the value: a refused mode carries none.

## The bar

`is_quick_editable` accepts a `search` holding text in one of the six modes, and
a facet whose mode its widget renders. Anything else degrades the bar to the
read-only pill, which holds no field. The field refuses a mode it cannot show,
because such a control widens the filter on the next apply.

A stated `search` naming no mode reads as is: `to_json` removes a default. A
bar with no `search` opens the field on includes.

The row reserves width for every child but the facets, and measures the overflow
host once, unhidden; the field is no facet, so the overflow never holds it.

Enter applies, and so does Apply. Clear removes the filter and the field.

## The builder

`field_metadata` includes `search`: the client registry keeps only the fields it
names, so the builder removed a filter's `search`. `search` has no column: no
choices, no `search_url`, never null.

A string or number widget offers only the modes its field states. No string
column here can be null, so none shows the presence pair: "is empty" is the
empty string under "is". A `count` is never null either; a `sum` and an `avg`
are, and keep the pair.

Each node applies its own `search`, at any depth: `to_q` ends with `_extra_q`.
