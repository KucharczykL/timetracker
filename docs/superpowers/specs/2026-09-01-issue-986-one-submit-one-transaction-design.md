# One submit, one statement

Issue [#986](https://github.com/KucharczykL/timetracker/issues/986). Add Game
and Edit Game each present one page and one Submit. One submit is one
transaction and one service call.

## The verb

`games/catalog_writes.py` has one public verb.

```text
state_catalog_graph(*, game, library, editions) -> WrittenGraph
```

`editions` is the whole desired graph of one Game, in the order it reads. Each
`EditionState` holds a key, an optional stored row, two marks, a name, and its
`ReleaseState` rows. A `ReleaseState` states a Platform and a date in place of
the name. `WrittenGraph` hands each written row back under its key.

Identity is the row the caller names. A state that names none is a new row. A
name is not an identity.

A row the caller does not mention stays as it is. A removal is stated by a mark
on the row. Absence is not a removal, because one partial writer must not take
a catalog somebody built by hand.

## What the verb refuses

The verb refuses a shared Game, a Game of another library, and a removed Game.
It refuses a named row that is removed, or that hangs from another Game or
Edition, and a Platform of another library. It refuses two surviving Editions
that state one name, two surviving rows that state one mark, and a statement
that leaves the Game no Edition.

Each refusal is checked against the desired end state, before the first write.
Each carries the key of the row that caused it. The key is opaque here: it is
the caller's own name for that row.

A named row is read again under the Game lock. The row the caller passes is
identity only.

If no surviving row states the mark, the first row takes it, at both levels.

## One submit

`games/catalog_submit.py` writes one submit of the Game form. One transaction
holds the Game's own columns, its wikidata reference, the graph, and the flat
mirror. The mirror is last, because it reads the default Release and the Game's
final name.

The PlayerGame command stays outside the transaction. `run_in_transaction`
opens the transaction it retries, and refuses to nest.

A refusal goes to the Game field that caused it, else to the row that stated
it, else it rises.

## What a constraint says

No pre-check wins a race. The module catches `IntegrityError` outside the
transaction, reads the constraint name the database gave, and looks that name
up in `CONSTRAINT_ANSWERS`. An unmapped constraint rises as itself. A guard
test fails unless each unique constraint on Game, Edition, Release and
ExternalReference is mapped, or named as out of reach.

## What the form also refuses

`CatalogGraphForm` refuses a second unnamed Edition. It also refuses two
surviving Releases of one Edition that state one platform and one date. The
service permits the second: #782 needs two regions on one date to be two rows.

## Boundary

Region on a Release: #782 decides it. A refused PlayerGame command leaves the
committed graph written. #889 removes the mirror, `games/catalog_compat.py`
and `LEGACY_IDENTITY_TAKEN`.
