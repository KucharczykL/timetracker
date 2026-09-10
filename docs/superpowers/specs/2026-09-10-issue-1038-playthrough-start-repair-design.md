# State a start for the runs the conversion left empty

Issue [#1038](https://github.com/KucharczykL/timetracker/issues/1038). It
repairs the default branch of [the legacy PlayEvent
conversion](2026-09-06-issue-684-playthrough-conversion-design.md).

#684 states a `Playthrough` from a legacy `PlayEvent` row. A tracked game that
holds no such row takes a default run, and that default states `created` alone.
Most tracked games hold no row: a person marked a game Played, logged a session
and moved on. Their Game detail reads `Playthrough 1` with `Started` as `-`.

## The rule

A run in scope takes one `started`, dated by the earlier of its two evidence
days. A run that holds no evidence keeps both acts unstated. No run takes a
`completed`.

A run is in scope when its kind is ordinary, its `removed_at` is null, both
markers are null, its `PlayerGame` is live on a live `Game`, and its
`playthrough_created` event names origin `backfill` and issue 684. The last
condition carries the weight: a blank run a person made, and a blank run #679
states at track time, are both left alone.

The status day is the earliest known day among the library's #676
`playergame.status_changed` events that name the run's `PlayerGame` and a status
of played, completed, retired or abandoned. The session day is the earliest
local day among live sessions on the library's own live `Game`. A status day is
frozen in the zone #676 ran in; a session day is read in the viewer's zone.

No run takes a completion. Legacy abandoned, retired and completed each say a
run ended, but stating one would invent finishes no screen ever showed.

## The pass

`games/backfill/playthrough_start.py` appends one `playthrough_started` per
repaired run. It appends events and dispatches no command, because scope admits
neither refusal a command would carry. The idempotency key names the run and
issue 1038, and `source_metadata` names the source that won, plus the status
behind a status day. Nothing reads that provenance today. It is what finds these
rows again: a start an ending status dated, and a start the two zones may have
moved by a day, are each selectable through it and no other way.

The report and the migration summary both count the pairs whose two days lie one
day apart. Two clocks alone can state that gap, so the number says how much of
the evidence a zone artifact could explain.

#684's `reconcile()` reads a repaired run as owing no legacy row. Without that
amendment it reports three mismatches for each one.

## The gate

Migration `0048_playthrough_start_repair` runs the pass, checks it, then
commits. Any mismatch the pass adds rolls the whole run back. The checks are:
the scope read something, where the library holds backfilled runs at all; each
repaired run states the day the reader computed; a run holding no evidence
states no act; no run outside scope moved; no completion was stated; the count
of runs stating no act fell by exactly the number repaired; and #684's own gate
reports nothing new. That gate is read before the pass as well as after, because
a start a person states on a converted run reads to it as a run owing a legacy
row it never had.

The first check is the one that reads a pass that did nothing. Every other check
compares what the pass stated against what the rows say, so a scope matching no
run passes them all. A library holding creation events that name origin
`backfill` and no issue 684 says the metadata moved out from under the filter.

`make report-playthrough-starts` prints the same figures, read-only, against a
restored copy. `make verify-dump` rehearses the migration.

## Reversibility

The stream is append-only, so a rebuild does not take these events back. The
migration's reverse is a no-op. `CorrectPlaythroughStart` states a better day
for any one run afterwards.

## Out of scope

A wrong `PlayerGame` status, the `finished()` split between the statistics page
and the Purchase list, and the condition word for a dropped run each belong to
their own issue.
