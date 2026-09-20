# The quick bar's search field

`search` is a criterion on all seven filters and the only one with no control.
It reaches the database through `search_q` and it survives in a saved preset.
The flat bar that used to render it went with #315. This gives it a control
again, states the match mode it never expressed, and repairs the two paths that
answer a stated mode with something else.

## What a person can state today

Two paths reach `search`: a hand-edited `?filter=`, and a preset posted to the
preset API, which validates through the same parsers and accepts every string
modifier.

The nested builder is not a third. `field_metadata` refuses `search` as a
pickable field, so the client registry never holds it, and the client keeps
only the keys its registry names. A filter that carries a search therefore
loses it when the builder reads it, and Apply writes the filter back without
it. The filter widens and nothing says so. That is a defect of its own and this
work repairs it.

`search_q` is the second such path. It ORs the columns as `icontains` and reads
one modifier, `EXCLUDES`, which negates the disjunction. A stated `matches
regex` is answered as a substring match.

## The field

One field holds a match-mode trigger and a text input, joined as segments: the
trigger rounds its leading edge, the input rounds its trailing edge, the two
share one border line and one shadow, and the input lifts above its neighbour
while focused so its ring is whole.

`INPUT_CLASS` states `rounded-base`, and a caller that appends a different
rounding wins by stylesheet order rather than by intent. So the segmented field
is a component that owns the rounding of each member and the line they share.
It states a leading slot, the field, and a trailing slot; a member it does not
hold costs no markup. It keeps the one control height.

The combobox container in `search_select.py` is not extracted for this. It
wraps a bare input in a bordered row, which is the other shape, and a third
sibling of it — `FIELD_CONTAINER_CLASS`, already extracted for the pickers —
shows what a second one costs. The field here is segments, not a wrapper.

## The trigger and the menu

The trigger is an icon and a chevron. Its accessible name states the mode it
holds, so a reader who cannot see the icon hears `Match mode: Excludes` rather
than a button with no value. Its title says the same.

The menu is wider than the trigger. Each row is the icon beside the mode in
words, so a person who opens it once has read what each icon means. The mode
the field holds is marked.

The trigger is an icon alone because the row is one line that the facets
compete for. A trigger that spells its mode costs about four times the width,
taken from the facets that stay in the row rather than move into the overflow
menu.

## The modes

Six: includes, excludes, is, is not, matches regex, not matches regex.

`IS_NULL` and `NOT_NULL` are refused. `search` reads several columns at once,
and "is null" across an OR of them states nothing a person could mean.

## What `search_q` states

The positive form of the modifier builds the disjunction, and a negative
modifier negates the disjunction whole. Negation wraps the OR and never each
column, because "excludes Zelda" means no column holds it, not that each column
separately does not.

An empty value states no constraint, as it does now.

The exact pair reads case-insensitively. Every other mode ignores case, and a
field that matches `zelda` for `includes` and refuses it for `is` reads as
broken. This is the one place the reader does not take the criterion's own
lookup.

A modifier the field cannot state reaches `search_q` only from a stored filter.
It is answered as the filter error it is, rather than silently as a substring
match.

The criterion layer needs nothing. `StringCriterion.to_q` states every
modifier, and `from_json` validates a regex against PostgreSQL under a timeout
before any query runs, so a pattern that is invalid or pathological is refused
as a filter error. `search` is a `StringCriterion` and parses through that path
on every filter.

## How the mode reaches the server

The bar's serializer reads each flat widget by its declared kind and path, and
the string reader takes the modifier from the modifier `select`. This field
states its mode in a menu and holds no such `select`.

The string reader is generalized: a widget states its modifier on its root, and
the `select` is one way to state it. A field that holds no `select` is then read
correctly rather than read as the default mode.

The bar also wires the modifier toggles, which reach for an ancestor by a layout
class to disable a value input. The segmented field is not that layout and must
not be reached by that walk.

## The icons

Six icons, three shapes and one rule for the negative of each.

An arc enclosing a bar is `includes`. Two bars are `is`. `.*` is the regex,
which is the mark a person has already met in an editor's search field.

A negative is its positive with a diagonal from the upper left to the lower
right. That is the direction the icon sets draw, and it is the direction that
misses both marks of `.*`, whose dot sits low and left.

Where the diagonal crosses the glyph, the glyph states a gap. The gap is drawn
into the path rather than painted over it, because a stroke in the surface
colour is a halo as soon as the trigger is hovered and the surface beneath it is
another colour.

Each mark is an icon snippet and reaches the page through the icon codegen,
whose slugs it shares with the platform marks.

## The bar

The field leads the row, before the facets. It is not a facet: the overflow menu
never holds it, at any width.

The row reserves width for what cannot move, and that reserve reads the siblings
after the overflow host. A field before the facets is not counted, the facets
claim room that is taken, and because the row wraps, the bar states a second
line instead of moving a facet into the overflow. The measurement is corrected
to read every child that is not a facet, counting the overflow host once.

Enter in the field applies, as Enter in a facet does. Apply applies. Clear
clears the field with everything else, because Clear states the empty filter.

A live apply is refused. Each apply is a page the browser loads, so a filter
that applied while a person typed would take the focus and the scroll position
with every pause.

The field is a component that carries its own script, so a page that holds one
loads it without the view naming it. The synthetic pages that state their own
scripts name it too, or the field is inert there.

## The bar's predicate

`is_quick_editable` admits a top-level `search` that holds one of the six modes.
A stored search in any other mode degrades the bar to the read-only pill, as
every other key the bar cannot state does. The bar never shows a control for a
filter it would rewrite.

A filter of facets and a search stays editable, and the bar's own output still
round-trips, because the serializer states facets and `search` and nothing else.

The degraded state holds no field. It is links and no element, it loads no
script of the bar's, and a search box there would need the typed text to reach
the filter through a second path on the server.

## What stays

`?search_string=` does not return. Free-text search lives in `?filter=`.

The per-mode `name` facets stay. A facet narrows one column; `search` reads
several, and the two answer different questions. Which columns a mode reads
differs per list, and the field says so where a person can read it.

## The stack

Four members, merged as one.

1. The segmented field: one component for a field built of joined members.
2. `search_q` states every modifier, with the exact pair read case-insensitively.
3. The builder holds `search`, so reading a filter no longer takes it away.
4. The icons are drawn, the string reader is generalized, and the bar holds the
   field.

Members 2 and 3 each repair a defect a person can reach today and stand without
member 4.

## Verification

Member 2 is verified per modifier, with one case for negation across several
columns, one for case, one for the empty value, and one for a regex PostgreSQL
refuses. Member 3 is verified by reading a filter that carries a search into the
builder and writing it back unchanged.

The field is verified as markup, as a round-trip through the serializer, and in
a browser: the row at 390 pixels, the menu by keyboard, the name the trigger
speaks, and the field with no scripting. The pinned reserve arithmetic and the
existing statement that a search degrades the bar are both restated by this
work, and the page and row scans for height, colour and type cover the new
markup.
