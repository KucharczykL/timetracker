# The quick bar's search field

`search` is a criterion on all seven filters, and it reads several columns at
once. The quick filter bar renders it as one field at the start of the row.

## The field

`SegmentedField` joins a match-mode trigger to a text box. Position decides the
rounding of each member, because a member does not know its own. The row draws
one border line and one shadow. A focused member goes above its neighbour, or
the neighbour cuts its focus ring. A member can wrap its control, so the rules
also reach a button in a member.

The trigger shows a mark and a chevron, and its accessible name states the mode
(`Match mode: excludes`). Each row of the wider menu shows a mark and its mode
in words. The menu marks the current mode.

The field is not a facet. The overflow never holds it.

A widget states its modifier on a `select`, or on its root as `data-modifier`.
The reader takes the `select` first. This field has none.

## The modes

There are six modes: includes, excludes, is, is not, matches regex, and not
matches regex. `IS_NULL` and `NOT_NULL` are not available, because "is null"
across several columns has no meaning.

## The marks

An arc that a bar crosses is `includes`. Two bars are `is`. `.*` is the regex.

A negative mark adds a diagonal from the top left to the bottom right, and the
glyph has a gap where it crosses. The gap is part of the path: a stroke in the
colour of the surface makes a halo when the surface changes. The regex marks
keep the dot low and the asterisk high, so the diagonal cuts neither.

## What `search_q` reads

Each mode names a lookup. A negative mode makes the same disjunction and negates
all of it: "excludes Zelda" means that no column holds the text. The exact pair
reads without case, because all other modes ignore case. An empty value adds no
constraint. `search_q` refuses a mode that is not one of the six.

## The bar

`is_quick_editable` accepts a top-level `search` in one of the six modes. Any
other mode degrades the bar to the read-only pill, which holds no field: the bar
must not show a control for a filter it would rewrite.

The row reserves width for each child that is not a facet, and measures the
overflow host once, unhidden.

Enter applies the filter, and so does Apply. Clear removes the filter and the
field together. There is no live apply, because each apply loads a page.

## The builder

`field_metadata` includes `search`. The client registry keeps only the fields it
names, so the builder removed a `search` from a filter it read. `search` has no
column: no choices, no `search_url`, never null.

Each node applies its own `search`, at any depth. `to_q` ends with `_extra_q`,
and `_apply_operators` composes each sub-filter with `to_q`.
