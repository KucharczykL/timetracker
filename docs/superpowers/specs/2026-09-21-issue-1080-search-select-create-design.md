# The picker creates the row a person typed

A `<search-select>` whose query matches no option offers one more row,
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

`SearchSelect` takes `params` and `create_url`. Both reach `SearchSelectProps`,
thus `tsc` holds the element to them.

`params` maps a parameter name to its source. A source is a literal value or
the name of a sibling form field, read at the moment it is used. The search
query and the create POST read the one mapping: the run picker narrows on
`?game=<id>` and creates under the same key, and a second mechanism would let
the two disagree. A literal serves a form that states the value at render time
and offers no field to read.

`create_url` is the POST endpoint. Where it is set and the query matches no
visible option, the create row renders last in the panel and takes the
highlight, thus Enter commits it. A click commits it too.

The row POSTs `{name, ...params}` through `fetchWithHtmxTriggers`. A blank
query never creates.

`create_url` beside `filter_mode` or `free_text` raises at render. A filter
panel states a criterion and a free-text panel is the typed text itself;
neither holds a row to create.

## The answer, and the row that comes back

The route answers `{id, label}`.

The element upserts on the id: an id the panel already holds takes the new
label, and any other id is inserted. A creation may answer a key the panel
already lists, because a run picker adopts a placeholder (below), and an
element that always inserted would show one run twice.

The created option is then selected, and the query is replaced by its label.

A refusal keeps the query in the box and selects nothing. The sentence rides
the messages middleware as `HX-Trigger`, which `fetchWithHtmxTriggers` already
renders, so the toast is the one every other write shows. The success message
travels the same way.

## What a run creation states

`CreatePlaythrough` takes a `name`, and its build appends
`playthrough_name_changed` beside the creation, as it already appends
`playthrough_note_changed`. One build, thus a named run is one atom: a
creation that commits before a failed naming leaves a run nobody asked for.

The write path beside `record_run` adopts a **placeholder** alone. A
placeholder is the game's sole live ordinary run that states no start, no
completion, a blank name, and that no live session and no live record names.
That is the run tracking mints, and nothing else.

`record_run` adopts a wider set: any sole run that states neither act. From a
create row that rule is wrong. A person who types a name asks for the run they
named, and a run that already holds sessions would take the new label and carry
those sessions under it.

Never adopting is wrong too: a tracked game that states nothing keeps its blank
run beside the named one, which is the row `record_run` exists to avoid.

A game nothing tracks is tracked first. Tracking states a run, and that run is
a placeholder, thus the adopt rule names it and the game ends with one named
run.

## Three routes

`POST /api/playthrough/` answers `201 {id, label}` and `PlaythroughIn` states a
`name`. The route answers `204` and no body today, and nothing reads it.

`POST /api/devices/` and `POST /api/platforms/` take a name. Each runs the form
the add page runs — `DeviceForm`, `PlatformForm` — thus one set of rules
refuses on both paths. The device route states `type` as Unknown, which the
model's own default names and the person corrects on the device page. The
platform route states the library, so the created row is private: a shared row
is a fixture, not a thing a picker makes. `Platform.clean` and both unique
constraints refuse a name the library already holds.

Each answers 422 and the form's own sentence.

## The consumers

The device picker on the session form and on the historical playtime form.
Both read `/api/devices/search`, both state the same gap, and a create row on
one alone would read as an accident.

The run picker on the session form. `PlaythroughSelectWidget` renders a
`SearchSelect` over `/api/playthrough/`, with `params` naming the `game` field.
`<playthrough-select>` keeps two jobs: it searches again when the game changes,
and it hides its row while the list holds one option or none. The hide rule
stays there and never reaches `SearchSelect`, because a picker that states
where rows move must stay visible on a game that holds one run.

The platform picker on the purchase form.

The release row's platform on the game form is a plain `<select>` in a cloned
row, and it keeps that shape here. A follow-up issue converts it.

The game picker takes no create row. A game is a catalog graph, not a name.

## What proves it

Vitest covers the element: the row appears on a query no option matches and on
no other, Enter and a click both POST, the answer upserts on the id, a refusal
keeps the query, and a blank query creates nothing.

Pytest covers the three routes, and the adopt rule apart from them: a
placeholder is adopted and named, a run holding a session is not, an untracked
game ends with one named run.

`e2e/` records a session on a run created from the picker, in one submit, and
does the same for a device and for a platform.

## The order

Two members, as one `gh stack`.

1. The element, the three routes, and the device consumer. The contract #714
   reads, proved end to end on the picker that is already a `SearchSelect`.
2. The run picker's conversion, and the platform consumer.

## What this accepts

A creation is a side effect before the form submits, thus an abandoned form
leaves a run, a device or a platform that no session names. The row is visible
on its own page and removable, which is how every picker of this kind behaves.

A creation is its own request under its own correlation id. A batch that
creates a run and then moves sessions to it holds the move alone: an Undo moves
the sessions back and leaves the run standing.
