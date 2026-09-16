# CLEAN-03: Remove legacy Session storage

**Date:** 2026-09-16
**Issue:** https://github.com/KucharczykL/timetracker/issues/772
**Parent phase:** #601, in the
[Session delivery wave](2026-09-12-session-wave-design.md)
**Precedent:** [CLEAN-02](2026-09-11-clean-02-legacy-table-removal.md)
**Follow-up:** #1081, squash step two
**Status:** Done

## Problem

Every session write is a command. Every session read is the `PlayerSession`
projection. Migration `0004` converted each legacy `Session` row into events.
Migration `0005` seeded one calendar per library. The deployment applied both.
The legacy table was inert. 3,200 lines of one-time machinery stood around
it, and the sample fixture held 2,807 legacy rows.

## Design

**The table goes.** `0004` and `0005` are `RunPython.noop`: a database with
rows has applied them, and a fresh one has nothing for them to do. `0006`
counts, in raw SQL, the `games_session` rows with no
`library.playersession.created` event at their own id, refuses when the count
is not zero, then drops the model. The conversion appended that event under
each row's own pk, and each row it did not convert aborted `0004`, so the
guard cannot fire on a converted deployment.

**The history is squashed** with `squashmigrations`, output as written plus
ruff's formatting: 74 operations become 71, the three `RunPython`s elided. The
four `RunSQL` operations in `0001` are optimizer barriers, so a fresh install
still creates and drops the `Session` table. The six replaced files stay until
the deployment has recorded the squash. #1081 removes them.

**One-time machinery leaves:** `games/backfill/`, `games/preflight/`, the
legacy playtime source, the parity harness and its command, the import guard,
`games/fixtures/data.yaml`, a 2024 streak script, and `library_scope`. The
playtime package becomes `games/reads/playtime.py`; each import is unchanged.

**The sample fixture carries session events**, regenerated from a fresh
dump of the deployment. The anonymizer reads the vocabulary: `aggregate_id_keys`
and `dated_keys` walk each payload's annotations for the `ReferenceId`,
`InstantText` and `DayText` aliases. A dated field moves in wall-clock days in
its `day_zone`. An end follows its start by the original elapsed time. An
undated event takes the day of its aggregate's latest dated one, so a removal
never precedes its creation. A payload reference is re-captured through its
kind's model. `source_metadata` is written empty. The calendar's aggregate is
the library, so it travels as the owner marker and the loader substitutes the
target library.

**Two readers of the reverse accessor changed**, which the import guard never
matched: the Remove-device confirmation counts `library_sessions()`, and the
comparable-column test asserts a `PlayerGame` reverse column. A `Game` preset
comparing a `sessions__*` column is refused with the "has no field" sentence.

## Verification

Measured on the 2026-09-15 post-deploy dump, 2,810 legacy rows:

- Full `make check` green on each commit, `e2e/` included.
- `make loadsample` into an empty database: 2,810 sessions, 874 runs, one
  calendar keyed on the library; replay parity and identity audit clean; a
  second load refused with a sentence.
- `make verify-dump` green. `make verify-baseline ARGS="--migrate"` green,
  seven catalogs identical. `--migrate` is new: it carries the copy over as
  the deployment's startup will. The fresh build's round trip through pg_dump
  and pg_restore is new too: a CHECK's deparsed text is not a fixed point under
  re-parse, and the deployment's copy took that trip.
- `make render-pages` before and after: 6 of 1,702 files differ, all
  filter-builder pages, which lost the 56 legacy `session`-rooted columns.

## Rollback

Not reversible after `0006` applies: the events are the only copy. Before
that, `git revert`; after, the rehearsed dump.
