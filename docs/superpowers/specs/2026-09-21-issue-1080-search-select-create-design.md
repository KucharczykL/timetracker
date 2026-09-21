# The picker creates the row a person typed

A `<search-select>` whose query names no option offers one more row,
`Create “…”`. The row POSTs the typed name, takes back the new row, selects it,
and says so. One code path serves every form that picks a row a person may not
hold yet.

Three pickers show the gap. The add-session form hides the run picker while a
game holds one run, and the link that starts a second run lives on the page the
person just left. The device beside it, and the platform on the purchase form,
each send a person to another page to add a row and back again.

[#714](https://github.com/KucharczykL/timetracker/issues/714) reads this
contract: its move confirmation hosts a `SearchSelect` with `create_url`, so by
submit time the target is always an existing run key.

## Two props

`SearchSelect` takes `params` and `create_url`.

`params` is one JSON object, carried as text. Props are attributes, and the
codegen maps a prop to `int`, `float`, `str` or `bool` alone, thus a mapping
travels the way `FilterJson` and `SelectionScope` travel: as a string the
element parses. `tsc` holds the attribute, and vitest holds the parsed shape.

Each key names a request parameter. Its value is a literal, or the name of a
sibling form field read at the moment it is used. The search query and the
create POST read the one mapping: the run picker narrows on `?game=<id>` and
creates under the same key, and a second mechanism would let the two disagree.
A literal serves a form that states the value at render time and offers no
field to read, which is the shape #714 renders.

A field-sourced parameter is also a dependency. The element searches again when
that field changes, and drops a selection the new value does not hold.

`create_url` is the POST endpoint. `FilterSelect` and `PresetSelect` take no
such argument, and the element ignores the attribute while `filter-mode` or
`free-text` is true: a filter panel states a criterion, a free-text panel is
the typed text itself, and neither holds a row to create.

## The create row

The row is its own kind, `data-search-select-create`. Modifier rows are the
precedent: a kind of its own is read by `getVisibleOptions`,
`hasVisibleContent`, the Enter branch and the click branch, and it survives the
`renderRows` sweep that empties the panel on every answer.

It renders after the no-results node, and it replaces that node rather than
standing beside it.

It appears when the query, trimmed, is not blank and no loaded option's label
equals it, case ignored. Equality, not the substring test the panel filters
with: `PlayStation` beside `PlayStation 4` matches that filter, and a rule
built on the filter would refuse to create any name that a longer name holds.

It appears only after the answer decides, which is the rule the no-results node
already follows. A row judged on the loaded window alone flashes on every
keystroke.

The judgement reads the loaded window. A name the library holds beyond that
window is refused by the route, which reads the whole table.

The row takes the highlight, thus Enter commits it. A click commits it too. It
is disabled while its own POST is in flight, so a second Enter creates no
second row.

## The answer, and the row that comes back

The route answers `{id, label}`.

The element upserts on the id: an id the panel already holds takes the new
label, and any other id is inserted. A creation may answer a key the panel
already lists, because a run creation adopts a placeholder (below), and an
element that always inserted would show one run twice.

The created option is then selected, and the query is replaced by its label.

A refusal keeps the query in the box and selects nothing.

Both answers carry their sentence as a queued message, which the middleware
puts on `HX-Trigger` and `fetchWithHtmxTriggers` renders. The middleware reads
no request header, thus a plain POST from the element is enough. A route that
queues nothing shows nothing, so each route queues one sentence, on the refusal
as well as on the creation.

The element reads the CSRF token out of the hosting form's own hidden input, so
no form constructor takes a request. A prop overrides it, for a create row that
stands outside a form.

## What a run creation states

`RecordPlaythroughByName` is one command. Its build reads the game's runs and
answers one of two event sequences: the name alone, against the placeholder it
adopts, or a creation and the name, against a key it mints.

A game already holding a live ordinary run of that name answers `Unchanged`,
which is read before the placeholder. That run is the one the person named, and
a second of that name would leave the picker showing one label twice. The rule
also makes a repeated POST record one row, which no key absorbs.

The read is in the build because the build runs under the stream head's lock.
`record_run` reads `run_to_adopt` outside the lock and names the race in its
own docstring. Here the race is the harm: a session recorded between the read
and the append would be carried under a name nobody gave it.

A placeholder is the game's sole live ordinary run that states no start, no
completion, and a blank name, and that no live session and no live record
names. `blocking_referrer` reads those two referrers today, scoped on the
library, and this rule reads them the same way.

`record_run` adopts a wider set: any sole run that states neither act. From a
create row that rule is wrong. A person who types a name asks for the run they
named, and a run that already holds sessions would take the new label and carry
those sessions under it.

Never adopting is wrong too: a tracked game that states nothing keeps its blank
run beside the named one, which is the row `record_run` exists to avoid.

A game nothing tracks is tracked first, as `record_run` tracks it. Tracking
states a run, and that run is a placeholder, thus the adopt rule names it and
the game ends with one named run.

`CreatePlaythrough` also takes a `name`, and its build appends
`playthrough_name_changed` beside the creation, as it already appends
`playthrough_note_changed`. One build, thus a named run is one atom. The new
field changes the command's canonical input, which is harmless: every dispatch
mints its own key, and no test pins the field set.

## Three routes

`GET /api/playthrough/search` answers `{value, label, data}` rows for a game,
narrowed by `q`. It names the game `game_id`, as the creation body names it: the
picker reads one mapping for its query and for its POST. The list route answers `PlaythroughOut`, which states
`display_name` and no `value`, and reads no `q`; a picker cannot read it. The
device and platform search routes are the shape, and this is the third.

`POST /api/playthrough/` states a `name` and answers `201 {id, label}`. It
answers `204` and no body today. No application code reads that, and three
tests pin it.

The label is read from the game's numbered runs, and the row is picked out in
Python. A number is counted over a partition, so narrowing that queryset to one
key leaves the count running over one row and every blank name reads as
`Playthrough 1`. The picker's options resolver reads the same way, and compares
its wanted keys as text: a posted value is a string where the column holds a
UUID, which the resolvers beside it only survive because `pk__in` coerces.

`POST /api/devices/` and `POST /api/platforms/` take a name. Each runs the form
the add page runs — `DeviceForm`, `PlatformForm` — thus one set of rules
refuses on both paths. The device route states `type` as Unknown, which the
model's own default names and the person corrects on the device page. The
platform route states the library, so the created row is private: a shared row
is a fixture, not a thing a picker makes.

A platform whose name and group a *shared* row already holds is refused by
`Platform.clean`; one the *library* already holds is refused by the private
unique constraint, which the form validates through
`_LibraryBoundConstraintValidationMixin`. Both reach the answer the same way.

Each form route answers 422 and one sentence, flattened from `form.errors`.
Field errors and `__all__` errors alike reach it, because `Platform.clean`
states a non-field error and a sentence that named no field would say nothing.
A command refusal keeps its own status, which is 409.

## The consumers

The device picker on the session form and on the historical playtime form.
Both read `/api/devices/search`, both state the same gap, and a create row on
one alone would read as an accident.

The run picker on the session form. `PlaythroughSelectWidget` renders a
`SearchSelect` over `/api/playthrough/search`, with `params` naming the `game`
field, and an options resolver that gives a held run its label on a bound
render. `<playthrough-select>` is then removed: the element searches again on
the game it depends on, which was that element's remaining job.

The picker is always visible. It hides its row today while the list holds one
option or none, and that is the very game this issue is about: nobody types
into a hidden control. The sole run is committed as the selection, thus the
field reads as a filled one and the form posts what it posted before.

That commit is a prop on the element, stated by the run picker alone, because
the run field is required where every other picker is not. It holds the one
option an answer states, only where nothing is held and the box is untouched:
an answer that lands while a name is being typed would put a label where the
name stands, and the create row that name was typed for could never be
offered again.

#714 renders `SearchSelect` directly, with a literal game key and no hide rule
to undo.

The platform picker on the purchase form. The issue names "Add Game's
platform", and no such field exists: the platform moved to the release row,
which is a plain `<select>` in a cloned block. The purchase form holds the
platform picker that is a `SearchSelect`, and it states the same gap.

The release row keeps its plain `<select>` here. The comment that calls a
composite widget impossible there is stale — the element assigns its own ids at
init, because the filter builder clones whole prototypes — so the follow-up
issue is scope, not a blocked path.

The game picker takes no create row. A game is a catalog graph, not a name.

## What proves it

Vitest covers the element: the row appears on a query no label equals and on no
other, a substring of a longer label still offers it, Enter and a click both
POST, a second Enter posts nothing while the first is in flight, the answer
upserts on the id, a refusal keeps the query, a blank query creates nothing,
and a change to a depended-on field searches again.

Pytest covers the four routes, and the adopt rule apart from them: a
placeholder is adopted and named, a run holding a session is not, a run holding
a record is not, and an untracked game ends with one named run.

`e2e/` records a session on a run created from the picker, in one submit, and
does the same for a device and for a platform.

## The order

Two members, as one `gh stack`.

1. The element, the four routes, and the device consumer. The contract #714
   reads, proved end to end on the picker that is already a `SearchSelect`.
2. The run picker's conversion, and the platform consumer.

## What this accepts

A creation is a side effect before the form submits, thus an abandoned form
leaves a run, a device or a platform that no session names. The row is visible
on its own page and removable, which is how every picker of this kind behaves.

A creation is its own request under its own correlation id. A batch that
creates a run and then moves sessions to it holds the move alone: an Undo moves
the sessions back and leaves the run standing.

A name is the only fact the row states. A device created this way is Unknown
until someone says otherwise, and a platform holds no group and no icon.
