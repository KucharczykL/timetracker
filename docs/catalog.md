# A private Game's catalog graph

A library writes its own catalog. One Game holds many Editions, and one Edition
holds many Releases. The service that writes them is `games/catalog_writes.py`,
and it is the only place either row is created or changed.

- A **Game** is the work.
- An **Edition** is the shape of that work a person bought: a base game, a
  Game of the Year cut, a remaster.
- A **Release** is that Edition on one Platform, on one date.

`save_private_game()` still writes the one default graph a legacy Game form
states. The six verbs below write the rest of it.

## The name

`Edition.name` is text, and empty is allowed. Most Editions carry no name: a
Game a person owns one way holds one Edition, and naming it would say nothing.

An Edition with no name presents as the Game's own name. That is
`Edition.display_name`, and a screen reads it rather than testing the column.

A name is unique among one Game's live Editions, ignoring case and surrounding
space. Two Games may each hold an Edition of the same name. No name is not a
name, thus two unnamed Editions of one Game may stand, and the constraint
`unique_live_edition_name_per_game` excludes them.

## The default

A Game holds at least one live Edition, and exactly one of them is the default.
An Edition may hold no Release; when it holds any, exactly one of them is the
default. A reader that wants one row of each reads the default.

The first live child a Game or an Edition gets becomes the default. Setting a
new default clears the old one in the same transaction, and the old one steps
down before the new one stands: the constraint is a partial unique index, and
the database checks it per statement.

A removed row holds no slot. Thus the default mark of a removed Edition is free
for the next write, which is the rule
[Retaining a referenced row](event-retention.md) states for every conditional
constraint here.

## What a removal refuses

A removal is a stamp. `remove_edition` and `remove_release` call
`remove()` from `games/removal.py`; nothing in the service destroys a row.

- **The last Edition of a Game stays.** A Game with no Edition has nowhere to
  hold a Release.
- **A default Edition stays while a live sibling exists.** A sibling can take
  the mark, and the writer says which. With the last-Edition rule, this means a
  default Edition is never the one that goes: promote a sibling first.
- **The last Release of an Edition goes**, and the default mark goes with it.
  An Edition holding no Release is an ordinary state.
- **A default Release stays while a live sibling exists**, for the same reason
  a default Edition does.

## Permission

A private Game belongs to one library, and that library writes its graph. Every
verb resolves the owning Game under `select_for_update()` and refuses:

- a **shared Game** — `library IS NULL` — and its Editions and Releases, which
  are read-only for everyone;
- a Game, Edition or Release of **another library**;
- a **removed** Game, Edition or Release, which goes back first;
- a **Platform of another library**. A shared Platform is fine.

Each refusal is a `ValidationError` carrying one sentence a person can read.
The sentences are module constants, so a screen and a test name the same words.
Nothing scopes the row away and reports success: a write a library may not make
raises, and the transaction leaves the graph as it was.

An unset Platform and an unknown date stay unset. Neither is inferred from the
Game, from a sibling Release, or from a display default.

## Repeating a write

`add_edition` and `add_release` state a whole row, and a repeat gives back the
row already there rather than a second one. An Edition is matched by its name
under one Game; a Release by its Platform and its date under one Edition, which
is the pair that tells two Releases apart.

An unnamed Edition matches nothing, and each unnamed add makes one. A Game the
legacy form wrote already holds an unnamed Edition, so matching on the empty
name would answer every unnamed add with that one and add nothing.

`update_edition` and `update_release` take every field, not a patch. A partial
update would need a sentinel to tell "leave this" from "make this empty", and
an empty name and an unknown date are both things a writer states on purpose.

Neither one writes a row its add verb could not have added: a name a live
sibling holds, or a Platform and date pair a live sibling holds, is refused.
A row that states its own name or its own pair again is fine.

## The legacy Game form

`games/catalog_compat.py` adapts the one-year Game form onto the graph. The
form knows a bare year and nothing richer, so it writes a temporal value only
where it owns one: where the stored value is absent, or is the bare year the
persisted integer column already states.

Anything richer — a month, a day, a decade, a range, a qualifier — stays as it
is, and the integer column is written from it where it states a year. A decade
and a range state none, so there the stored integer stands: a form that does
not own the value does not own the column beside it either.

The comparison is against the *persisted* integer, never the posted one.
Against the posted one, an ordinary year edit would read as a disagreement and
undo itself.

#889 retires this path.
