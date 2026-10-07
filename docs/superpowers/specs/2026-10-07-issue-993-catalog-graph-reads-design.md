# The catalog graph reads its rows once

Issue: #993. Contract it serves: [Catalog](../../catalog.md).

## Problem

`state_catalog_graph()` locks the Game, then reads row by row:

- `_resolved_edition()` and `_resolved_release()` each run one `SELECT`;
- the standing default Release, one `SELECT` per stated stored Edition;
- `_refuse_platform()`, one locking `SELECT` per Release that names a new
  Platform;
- `Release.save()` calls `clean()`, which lazy-loads what the row was read
  without: `edition` and `edition.game` on a stated stored Release, those and
  `platform` on the row the mark falls to;
- the kept checks and fallbacks of the mark choice, one per level.

The Release default clear writes one `UPDATE` per stated stored Edition. The
round trips grow with the statement, all inside the Game's lock.

## Design

The verb reads the Game's graph once, after it takes the Game lock, into a
`GraphRows` value:

- one `SELECT` of every Edition of the Game, removed ones included, keyed by
  pk; each gets `game = owner`;
- one `SELECT` of every Release of those Editions, removed ones included,
  `select_related("platform")`, keyed by pk; each gets `edition` set to the
  map's own Edition instance;
- one locking `SELECT` (`select_for_update(no_key=True)`, ordered by pk) of the
  Platforms the statement newly names. "Newly" is today's rule, exactly: a
  Release row not stated removed, under an Edition not stated removed, whose
  platform is not `None`, is this library's or shared, and either has no
  stored row or differs from that row's own stored `platform_id`. A foreign Platform is never locked.

Every resolve, refusal, default read and mark choice reads `GraphRows`.

- A stated Edition whose pk the map lacks is `FOREIGN_ROW`: a row of another
  Game and a row that does not exist both fail the lookup.
- A stated Release under a new Edition is `FOREIGN_ROW`, as today. Otherwise
  it is `FOREIGN_ROW` unless the map holds it and its `edition_id` is the
  stated parent's pk.
- Refusals keep their order and keys. Resolves run every Edition, then every
  Release, then `REPEATED_ROW`, then `_refuse_the_set`. The platform refusal
  stays inside `_refuse_the_set`'s per-Edition loop, after that Edition's
  `TWO_DEFAULT_RELEASES`; only the locking read moves earlier, ahead of
  every set refusal. A refusal rolls back, so the earlier locks go with it.
  The read filters `removed_at__isnull=True`; a Platform it does not return
  is `REMOVED_PLATFORM`.
- `untouched` is the map's live Editions the statement does not name; a
  removed Edition's name claims no slot.
- The standing defaults are map instances that are live and `is_default`,
  taken before step 1. `remove()` sets `removed_at` on the instance it
  stamps, and every stated stored row is a map instance, so the kept check
  `removed_at is None` sees each removal step 2 makes.
- The fallback "first live row by pk" is the minimum pk among the map's live
  rows of that parent. It runs only when nothing was written at that level,
  so no new row is missing from the map. Python's `UUID` order matches
  PostgreSQL's.
- The Release default clear is one `UPDATE` over every stated surviving
  stored Edition.

A queryset `UPDATE` leaves map instances stale (step 1 clears, step 3 names).
That is harmless: every stated surviving row is rewritten by `save()`, `is_default` is
read only before step 1, and a stale unmentioned default is re-saved `True`
only when it wins.

## Decisions

- **Read removed rows too.** `REMOVED_EDITION` and `REMOVED_RELEASE` need the
  mark; a live-only map would answer `FOREIGN_ROW`.
- **Batch the Platform lock, ordered by pk.** Same round-trip shape in the
  same lock. Two writers on different Games then lock shared Platforms in one
  order. That order is not tested; a two-connection deadlock test costs more
  than it proves.
- **Writes stay per row.** A bulk write skips `save()` and `clean()`.
- **`remove()` keeps its own read.** It reads the previous mark per row; a
  statement that removes rows still pays one `SELECT` each.
- **Returned rows hold the mark.** A stated standing default is now the same
  instance the `WrittenGraph` returns, so it reads `is_default=True` in
  memory. No caller reads it.

## Tests

- Statement size does not change the number of `SELECT`s: one Edition with
  one platformed Release against three Editions with three platformed Releases
  each, on stored graphs, no removals. Count `SELECT`s only, and assert the
  exact number: Game lock, Editions, Releases, and the Platform lock when a
  Release names a new Platform.
- A standing default Release the statement removes, with no stated mark and a
  live unmentioned sibling: the sibling takes the mark. The same at the
  Edition level.
- The refusal tests in `tests/test_state_catalog_graph.py` pin keys and
  sentences, and run unchanged.

## Follow-up issues to file

None.
