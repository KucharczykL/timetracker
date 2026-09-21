# The picker creates the row a person typed

A `<search-select>` whose query names no option offers one more row,
`Create “…”`. The row POSTs the typed name, takes back `{id, label}`, and holds
it.

The row appears when the trimmed query is not blank and no loaded label equals
it, case ignored. Equality, not the substring the panel filters with:
`PlayStation` beside `PlayStation 4` matches that filter, and a rule built on
the filter refuses every name a longer name holds. It appears after the answer
decides, because the loaded window is partial; a name beyond it is refused by
the route, which reads the whole table.

The element upserts the answer on its id. A creation can answer a key the panel
already lists, because a run creation adopts a placeholder, and an element that
always inserts shows one run two times.

## The parameters a request rides

`params` is one JSON object, carried as an attribute, because the codegen maps
a prop to `int`, `float`, `str` or `bool` alone.

Each key names a request parameter, and its value is a literal or the name of a
sibling field. The search query and the create POST read the one mapping, thus
the run picker narrows on the game and creates under the same key; two
mechanisms let the two disagree. A field source is also a dependency, so the
element searches again when that field changes.

## What a run creation states

`RecordPlaythroughByName` reads the game's runs in its build, under the stream
head's lock. A game that already holds a live ordinary run of that name answers
`Unchanged`, read ahead of every other rule: that run is the one the person
named.

A placeholder is the game's sole live ordinary run that states no start, no
completion and a blank name, and that no live session and no live record names.
The command names it, or mints a key. `record_run` adopts a wider set — any
sole run that states neither act — which is wrong from a create row, because a
run holding sessions would take the new label and carry them under it. Never
adopting is wrong too: the blank run stays beside the named one.

The label is read from the game's numbered runs, and the row is picked in
Python. A number counts over a partition, so a queryset narrowed to one key
counts over one row, and every blank name reads as `Playthrough 1`.

The search route is declared ahead of the keyed route. Ninja matches `search`
as a key otherwise, and answers 422.

## One typed name, one set of rules

`POST /api/devices/` and `POST /api/platforms/` run the forms the add pages
run. A device takes the Unknown its default names. A platform states the
library, so the row is private: a shared row is a fixture. Each answers 422 and
one sentence, flattened from `form.errors` with the `__all__` errors
`Platform.clean` states; a command refusal keeps its 409. The element reads the
CSRF token from the hosting form, so no form constructor takes a request.

## The run field is required

A native select commits its first option, and a `SearchSelect` holds a value
only through a pick. `commit_sole_option` holds the one option an answer
states, where nothing is held and the box is untouched. A box someone typed in
holds their name: an answer landing mid-word would put a label where the name
stands, and the create row that name was typed for could never be offered
again. Landing in a box somebody stands in, the commit selects the label, as
focus on a committed field does. The page seeds the same rule, so a game
holding more than one run is a choice.

## What this accepts

A creation is a side effect before the form submits, thus an abandoned form
leaves a row nothing names. That row is visible on its own page and removable.

A creation is its own request under its own correlation id. A batch that
creates a run and moves sessions to it holds the move alone.

A name is the only fact the row states. A device is Unknown until somebody says
otherwise, and a platform holds no group and no icon.
