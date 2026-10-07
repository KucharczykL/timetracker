# The catalog graph reads its rows once

Issue: #993. Contract: [Catalog](../../catalog.md).

## Rule

`state_catalog_graph()` reads a fixed number of rows under the Game's lock.
The number does not grow with the statement. A statement without removals
runs three `SELECT`s: the Game lock, the Editions, the Releases. A statement
that names a new Platform runs a fourth: the Platform lock.

## The reads

`GraphRows.of()` reads the stored graph of one Game:

- every Edition of the Game, removed ones included, keyed by pk;
- every Release of those Editions, removed ones included, keyed by pk, with
  its Platform. The save of a Release that keeps the mark validates it.

Each Edition holds the locked Game as `game`. Each Release holds its map
Edition as `edition`. Thus `Release.clean()` reads no row. The write stamps
and saves these same instances.

The verb reads removed rows too. `REMOVED_EDITION` and `REMOVED_RELEASE` read
their mark. A live-only read would answer `FOREIGN_ROW`.

## Resolve

- A stated Edition that the map does not hold is `FOREIGN_ROW`.
- A stated Release is `FOREIGN_ROW` when its parent is new, when the map does
  not hold it, or when its Edition is not the stated parent.
- The refusals keep their order and their keys.

## Platforms

One read locks the live Platforms that the statement newly names, in pk order.
A Platform is newly named when its row is not stated removed, its Edition is
not stated removed, it is saved, and the stored Release of the row does not
already name it. The read locks only the shared Platforms and the Platforms of
this library. `PlatformLocks` keeps the Platforms the statement named and the
Platforms the read locked. A refusal asks it about a named Platform only; any
other Platform is a defect, and `holds()` raises. The platform refusal stays in
the per-Edition loop of `_refuse_the_set`. An unsaved Platform is
`REMOVED_PLATFORM`.

The pk order gives two writers on different Games one lock order. A refusal
rolls back the transaction and releases the locks.

## The mark

The standing defaults are map rows, read before the defaults step down.
`remove()` writes `removed_at` on the instance it stamps, and every stated
stored row is a map instance. Thus the kept check reads `removed_at` on the
instance. The fallback is the live map row of the lowest pk. It runs only
when nothing was written at that level.

## What stays per row

- A write stays one statement per row: `Release.save()` calls `clean()`, and a
  bulk write skips it.
- `remove()` reads the previous mark of each row it stamps.

## Tests

`tests/test_state_catalog_graph.py` counts the `SELECT`s of a restatement of
one Edition with one Release and of three Editions with three Releases each,
on the stored Platform (three reads) and on a new Platform (four reads), and
checks what the restatement wrote. Other tests remove a standing default with
no stated mark. The live sibling of the lowest pk takes the mark. A removed
row and a row of another Edition never take it.
