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

## What Game detail shows

Game detail reads the graph through `game_hierarchy()` in
`games/reads/catalog_hierarchy.py`: the Editions one library may see under one
Game, each with its Releases, in two queries. Nothing on the page reads a
reverse accessor, because a shared Game's accessors reach every library that
ever wrote under it.

Most Games hold one unnamed Edition and one Release. That shape says everything
in two header rows — the Platform, and the date through the presenter — and the
page adds no heading above them. Three things break the shape and bring the
`Releases` section: a second Edition, a second Release, or a name on the only
Edition. The section carries one block per Edition, each a Platform and Released
table, or the words `No releases yet.` where an Edition holds none.

A block is headed by `display_name` where the name tells one Edition from
another: where two Editions meet, and where a lone Edition states a name of its
own. A lone unnamed Edition is not headed, because `display_name` falls back to
the Game and the heading would print the Game's own name above the Game's own
page.

A Release with no Platform reads as `Unspecified`. Nothing is inferred from the
Game, from a sibling Release, or from a display default.

A private Game carries controls. The plain shape gains one row under its two
header rows: `Edit release` where the Edition holds one, `Add release` where it
holds none, and `Add edition`. The `Releases` section gains an Actions column
per Release, a control row per Edition — `Add release`, `Edit edition`, and
`Remove edition` where a removal is allowed — and one `Add edition` under the
last block.

Two rules hide a button, because the service would refuse the write and a
person should not meet a 409 they could not have avoided. No `Remove edition`
on the last Edition, or on a default Edition while a live sibling could take the
mark. No `Remove release` on a default Release while a live sibling stands.
Promoting a sibling is how the mark moves; see [The default](#the-default).

A shared Game's graph is shown, and none of the controls are. The page says
nothing about who may change it, because the page offers nothing either way.
What sharing means is unsettled until the IGDB wave (#783, #784, #785) lands,
and a mark written now would state a rule that does not exist yet.

## What a form refuses that the service does not

A second Edition must state a name. Two unnamed siblings both present as the
Game's own name, so the page would show one work twice with no way to tell the
rows apart. `EditionForm` refuses it; `add_edition` does not.

The service stays permissive on purpose. #782's importer normalizes IGDB and
writes unnamed Editions in bulk, and a rule in the service would stop it. The
rule moves down to the service if a second writer ever needs it.

## The section is a placeholder

The `Releases` section states that it is under construction, on the page, where
a reader sees it.

`Edition` and `Release` are the words the schema needs. #782 normalizes IGDB
into these two levels, and IGDB has them. They are not words a reader wants.
Nothing a person makes names either one: a Purchase, a Session, a PlayEvent and
a PlayerGame each name a Game, and the only foreign keys to an Edition or a
Release come from `ExternalReference`. On 858 real Games the split has never
once carried a fact — one Game, one Edition, one Release, 858 times.

The section worth having states what a person did with each edition, not what
the catalog holds. That needs a Session that names a Release, which #690 adds.
This shape is replaced then, and the notice goes with it.

The Game's own `original_release_date` stays on the Game, because it is a fact
of the work rather than of one Release. The flattened Platform row and the
flattened release year left with this reading; #889 takes the columns.

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

## The flat columns follow the graph

`Game.platform`, `Game.year_released` and `Game.original_year_released` are the
three columns the graph replaced. Nothing renders a Game from them any more, but
filters, the API and the sample fixture still read them, so they are kept true.

`mirror_legacy_columns()` in `games/catalog_compat.py` writes them from the
default Edition's default Release: its Platform, and the year of its date where
the date states one. A decade and a range state no year, so there the column
goes null. `write_and_mirror(game, write)` wraps every catalog write in one
transaction — the verb, then the mirror — so the columns can never lag the graph
they shadow.

The mirror checks before it writes. `(library, name, platform, year)` still
carries a unique constraint, so a Release edit can walk one Game onto another
Game's identity. The check raises `LEGACY_IDENTITY_TAKEN` and the whole
transaction goes back, rather than letting the database refuse a write the form
had already reported as saved.

The Game form itself no longer states a Platform or a year. It states the work's
`original_release_date` as a temporal value, and the Add form states one inline
Release beside it. There is nothing left to reconcile: the form and the column
speak the same grammar, which [Temporal](temporal.md) sets out.

#889 retires this path.
