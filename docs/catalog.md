# A private Game's catalog graph

A library writes its own catalog. One Game holds many Editions, and one Edition
holds many Releases. The service that writes them is `games/catalog_writes.py`,
and it is the only place either row is created or changed.

- A **Game** is the work.
- An **Edition** is the shape of that work a person bought: a base game, a
  Game of the Year cut, a remaster.
- A **Release** is that Edition on one Platform, on one date.

One call writes all of it. `state_catalog_graph()` takes one Game's whole
desired graph, and there is no second writer and no per-row verb.

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

A removal is a stamp. `state_catalog_graph` calls `remove()` from
`games/removal.py`; nothing in the service destroys a row.

- **The last Edition of a Game stays.** A Game with no Edition has nowhere to
  hold a Release. An Edition nobody mentioned counts: the rule is about what
  the Game is left holding.
- **The last Release of an Edition goes**, and the default mark goes with it.
  An Edition holding no Release is an ordinary state.

The three rules that used to guard the default mark are gone. A statement says
which row is default and which row leaves at the same time, so a mark a
removal would have stranded is a question the caller already answered.

## Permission

A private Game belongs to one library, and that library writes its graph. The
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

A private Game's page carries one control, and the page writes nothing. The
`Editions` section gains an Actions column holding a single `Edit` link, drawn
once per row and pointing at Edit Game. The plain shape carries no control row
at all: its two header rows read, and the same `Edit Game` button above the page
states them.

The graph is written in one place. Add Game and Edit Game host the same area,
holding every Edition and every Release, and one Submit states the whole set in
one transaction, so neither page needs a per-row Add, Edit or Remove. Nothing
hides a button to dodge a 409 either: a refusal the service states comes back on
the row that caused it, in the form, where the value that caused it still is.
Promoting a sibling is how the mark moves; see [The default](#the-default).

On Add Game there is no Game to hang the graph from yet, and the area starts as
one blank Edition holding one blank marked row. `games/catalog_submit.py` saves
the Game's own columns first and hands the graph form the Game it made, so one
statement writes the whole graph. There is no second creator and nothing to
claim. The Game, its wikidata reference, its graph and the flat columns are one
transaction, so a refused row leaves no Game behind for a second submit to
collide with.

A shared Game's graph is shown, and the control is not. The page says
nothing about who may change it, because the page offers nothing either way.
What sharing means is unsettled until the IGDB wave (#783, #784, #785) lands,
and a mark written now would state a rule that does not exist yet.

## What a form refuses that the service does not

A second Edition must state a name. Two unnamed siblings both present as the
Game's own name, so the page would show one work twice with no way to tell the
rows apart. `CatalogGraphForm` refuses it; the service does not.

Two surviving Releases of one Edition may not state the same platform and date.
The page would show a person two rows nothing tells apart. `CatalogGraphForm`
refuses it; the service does not, because #782 needs two regions on one date to
be two rows. The rule is about the surviving set, so binning a row and adding
another that states its platform and date is fine, and is written.

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

## Stating a graph

`state_catalog_graph()` takes one Game's whole desired graph and writes it in
one transaction. Identity is the row the caller names and nothing else: a state
naming an Edition or a Release is that row, and a state naming none is a new
row. A name is a name, not an identity.

A row the caller does not mention is left alone. Removal is stated by a mark on
the row, so a writer that knows about two Editions can state those two without
taking the three somebody added by hand. Absence meaning removal would let one
importer defect take a whole catalog.

Every refusal is checked against the desired end state, before anything is
written, and each carries the caller's own name for the row that caused it, so
a sentence reaches the row a person typed into.

A named row is read again under the Game's lock. The Edition or Release a
caller passes is identity only: the verb resolves each after
`select_for_update()` and refuses one that is removed, or that hangs from
another Game or Edition. Every caller reads its rows before the lock, so no
caller can act on a stale one.

## What a constraint says

No pre-check wins a race. The mirror reads with a SELECT and writes with an
UPDATE, the wikidata reference has the same shape, and the two default marks
are set with no pre-check at all. So `games/catalog_submit.py` catches the
`IntegrityError` outside the transaction, reads the constraint the database
named, and looks it up in `CONSTRAINT_ANSWERS`. A constraint that is not in
that mapping rises as itself: a wrong sentence is worse than none. A guard test
fails unless every unique constraint on Game, Edition, Release and
ExternalReference is either mapped or named as out of reach, with a reason.

## The flat columns follow the graph

`Game.platform`, `Game.year_released` and `Game.original_year_released` are the
three columns the graph replaced. Nothing renders a Game from them any more, but
filters, the API and the sample fixture still read them, so they are kept true.

`mirror_legacy_columns()` in `games/catalog_compat.py` writes them from the
default Edition's default Release: its Platform, and the year of its date where
the date states one. A decade and a range state no year, so there the column
goes null. `write_and_mirror(game, write)` wraps every catalog write in one
transaction — the statement, then the mirror — so the columns can never lag the
graph they shadow.

The mirror checks before it writes. `(library, name, platform, year)` still
carries a unique constraint, so a Release edit can walk one Game onto another
Game's identity. The check raises `LEGACY_IDENTITY_TAKEN` and the whole
transaction goes back, rather than letting the database refuse a write the form
had already reported as saved. The check loses a race, and the constraint
answers the one it loses; see [What a constraint says](#what-a-constraint-says).

The Game form itself no longer states a Platform or a year. It states the work's
`original_release_date` as a temporal value, and the Editions area beneath it
states every Release. There is nothing left to reconcile: the form and the
column speak the same grammar, which [Temporal](temporal.md) sets out.

#889 retires this path.
