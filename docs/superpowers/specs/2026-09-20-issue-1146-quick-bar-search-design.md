# The quick bar's search field

`search` is a criterion on all six filters and the only one with no control.
It reaches the database through `search_q`, it survives in a saved preset, and
a person can state it only by hand-editing `?filter=` or by opening the nested
builder. The flat bar that used to render it went with #315. This gives it a
control again, and states the match mode it never expressed.

## The field shell

`search_select.py` holds a container that impersonates a native input: a
bordered row that wraps, a bare input inside it that states no padding and no
ring of its own, a slot at the right edge, and the focus ring expressed on the
wrapper. Three comboboxes share it and nothing else can.

The shell moves to `primitives.py` as its own component, with a leading slot, a
field slot and a trailing slot. It keeps `relative`, because the combobox's
options panel is positioned against it. It keeps the disabled fade, which reads
the control inside rather than the wrapper, because a wrapper holds no disabled
state.

`SearchSelect`, `FilterSelect` and `PresetSelect` are built on the moved shell
and state the same markup as before. That equality is the gate on the move: the
three render byte for byte what they rendered, so nothing in this member can
change a page.

The search field is the fourth consumer and the first that is not a combobox.
It states no listbox, no options and no combobox role.

## The field

One field holds a match-mode trigger and a text input, joined as segments: the
trigger rounds its leading edge, the input rounds its trailing edge, the two
share one shadow and one border line, and the input lifts above its neighbour
while focused so its ring is whole.

The trigger is an icon and a chevron. Its accessible name states the mode it
holds, so a reader who cannot see the icon hears `Match mode: Excludes` rather
than a button with no value. Its title says the same.

The menu is wider than the trigger. Each row is the icon beside the mode in
words, so a person who opens it once has read what each icon means. The mode
the field holds is marked.

The trigger is an icon alone because the row is one line that the facets
compete for. A trigger that spells its mode costs about four times the width,
and that width is taken from the facets that stay in the row rather than moving
into the overflow menu.

## The modes

Six: includes, excludes, is, is not, matches regex, not matches regex.

`IS_NULL` and `NOT_NULL` are refused. `search` reads several columns at once,
and "is null" across an OR of them states nothing a person could mean.

## What `search_q` states

`search_q` reads one criterion and several column names. It ORs the columns and
negates the whole disjunction on `EXCLUDES`. Every other modifier reaches it as
`icontains`, so a filter built in the nested builder that states `matches regex`
is answered today as though it stated `includes`.

It is generalized: the positive form of the modifier builds the disjunction, and
a negative modifier negates the disjunction whole. Negation wraps the OR and
never each column, because "excludes Zelda" means no column holds it, not that
each column separately does not.

The criterion layer needs nothing. `StringCriterion.to_q` already states every
modifier, and `from_json` already validates a regex against PostgreSQL before
any query runs, so a pattern that is invalid or pathological is refused as a
filter error rather than reaching a worker. `search` is a `StringCriterion` and
parses through that path, so it inherits both.

## The icons

Six icons, three shapes and one rule for the negative of each.

An arc enclosing a bar is `includes`. Two bars are `is`. `.*` is the regex,
which is the mark a person has already met in an editor's search field.

A negative is its positive with a diagonal from the upper left to the lower
right. That is the direction the icon sets draw — Lucide's `eye-off` is one
stroke from corner to corner — and it is the direction that misses both marks
of `.*`, whose dot sits low and left.

Where the diagonal crosses the glyph, the glyph states a gap. The gap is drawn
into the path rather than painted over it, because a stroke in the surface
colour is a halo as soon as the trigger is hovered and the surface beneath it
is another colour.

The mark is stated as an icon snippet and reaches the page through the icon
codegen, as every other icon does.

## The bar

The field leads the row, before the facets. It is not a facet: the overflow
menu never holds it, at any width.

The row reserves width for what cannot move. That reserve reads the siblings
after the overflow host, so a field placed before the facets is not counted and
the facets claim room that is taken. The measurement is corrected to read the
row's children that are not facets, wherever they stand.

Enter in the field applies, as Enter in a facet does. Apply applies. Clear
clears the field with everything else, because Clear states the empty filter.

A live apply is refused. Each apply is a page the browser loads, so a filter
that applied while a person typed would take the focus and the scroll position
with every pause.

## The bar's predicate

`is_quick_editable` admits a top-level `search` key that holds a criterion. A
filter of facets and a search stays editable, and the bar's own output still
round-trips, because the serializer states facets and `search` and nothing
else.

The serializer needs no case of its own. It reads each flat widget by its
declared kind and path, so the field is read as the string widget it is.

The degraded state holds no field. It is links and no element, it loads no
script of the bar's, and a search box there would need the typed text to reach
the filter through a second path on the server. A person whose filter has an
operator or a relation states a search in the builder, which the state already
links to.

## What stays

`?search_string=` does not return. Free-text search lives in `?filter=`.

The per-mode `name` facets stay. A facet narrows one column; `search` reads
several, and the two answer different questions.

## The stack

Three members, merged as one.

1. The shell moves to `primitives.py`; the three comboboxes state the same
   markup.
2. `search_q` states every modifier; the icons are drawn.
3. The field is built and the bar holds it.

## Verification

The move is verified by rendering the three comboboxes before and after and
comparing the markup. The generalization is verified per modifier, with one
case for negation across several columns and one for a regex that PostgreSQL
refuses. The field is verified as markup, as a round-trip through the
serializer, and in a browser: the row at 390 pixels, the menu by keyboard, the
name the trigger speaks, and the field with no scripting.
