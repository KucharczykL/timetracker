# CLEAN-03: Remove legacy Session storage

**Date:** 2026-09-16
**Issue:** https://github.com/KucharczykL/timetracker/issues/772
**Parent phase:** #601, in the
[Session delivery wave](2026-09-12-session-wave-design.md)
**Precedent:** [CLEAN-02](2026-09-11-clean-02-legacy-table-removal.md)
**Follow-up:** #1081, squash step two
**Status:** Done

## Problem

Every session write is a command and every read is the `PlayerSession`
projection. Migration `0004` converted each legacy `Session` row into events,
`0005` seeded one calendar per library, and the deployment applied both. The
legacy table was inert, and 3,200 lines of one-time machinery stood around it:
the conversion, the calendar seed, the census, the legacy playtime source,
the parity harness, an import guard, and a sample fixture that still carried
2,807 legacy rows.

## Design

**The table goes.** `0004` and `0005` are `RunPython.noop`: a database that
holds rows has applied them, and a fresh database has nothing for them to do.
`0006` refuses, in raw SQL, any `games_session` row with no
`library.playersession.created` event at its own id, then drops the model.
`convert_row` appended that event under the row's own pk for live and removed
rows alike, and every row it did not convert aborted `0004`, so the guard
cannot fire on a correctly converted deployment. It fires on a copy seeded with
one unconverted row; measured.

**The history is squashed** with `squashmigrations`, output as written plus
ruff's formatting: 74 operations to 71, the three `RunPython`s elided. The four
`RunSQL` operations in `0001` are optimizer barriers, so a fresh install still
creates and drops the `Session` table and the `playtime` column. The six
replaced files stay until the deployment has run once with both present and
recorded the squash; #1081 takes them out.

**Everything one-time leaves:** `games/backfill/`, `games/preflight/`, the
legacy playtime source, both parity modules and their command, the import
guard, `games/fixtures/data.yaml`, a 2024 streak exploration script, and
`library_scope`. The playtime package collapses to `games/reads/playtime.py`;
every caller's import is unchanged.

**The sample fixture carries session events.** It is regenerated from a
fresh dump of the deployment. The anonymizer reads the vocabulary rather than
special-casing event types: `aggregate_id_keys` and `dated_keys` on the
registry walk each payload's annotations for the `ReferenceId`, `InstantText`
and `DayText` aliases. A dated field moves in wall-clock days in its
`day_zone`, an end follows its start by the original elapsed time, and an
undated event takes the day of its aggregate's latest dated one, so a removal
never precedes its creation. A payload reference is re-captured through its
kind's model. `source_metadata` is written empty. The calendar's aggregate is
the library, so it travels as the owner marker and the loader substitutes the
target library, which the `id = library` check on `LibraryCalendar` requires.

**Two readers of the reverse accessor** that the import guard never matched
changed: the Remove-device confirmation counts `library_sessions()`, and the
comparable-column test asserts a `PlayerGame` reverse column. A `Game` preset
comparing a `sessions__*` column is refused with the "has no field" sentence;
accepted.

## Verification

Measured on the 2026-09-15 post-deploy dump, 2,810 legacy rows:

- Full `make check` green on every commit, `e2e/` included.
- `make loadsample` into an empty database: 2,810 sessions, 874 runs, one
  calendar keyed on the library; replay parity and the identity audit clean;
  a second load refused with a sentence.
- `make verify-dump` green. `make verify-baseline ARGS="--migrate"` green,
  seven catalogs identical. The `--migrate` flag is new: it carries the copy
  over as the deployment's startup will. So is the round trip of the fresh
  build through pg_dump and pg_restore, because a CHECK's deparsed text is
  not a fixed point under re-parse and the deployment's copy took that trip.
- `make render-pages` at `bb41e358` and at the branch head: 6 of 1,702 files
  differ, all six the filter-builder pages, which lost the 56 legacy
  `session`-rooted comparable columns and gained none.

## Rollback

Not reversible on the deployment once `0006` applies: the events are the only
copy. Before that, `git revert`; after, the dump the rehearsal ran on.
