# The HistoricalPlaytime aggregate

Issue: [#705](https://github.com/KucharczykL/timetracker/issues/705).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).

## Purpose

A historical playtime record states a duration a person did not track as
sittings. Aggregate type `historicalplaytime`; events
`library.historicalplaytime.*`; two projection tables.

## The record

One record has these facts:

- a positive duration, in whole seconds;
- a `when`, at any precision the temporal grammar admits; unknown is permitted;
- a provenance: `estimated`, `manually_entered` or `externally_measured`;
- one or more playthroughs of one `PlayerGame`;
- an optional device;
- the emulated flag;
- a note.

`release` and `source` are reserved keys. They are always null.

## Events

`created` and `restated` share `HistoricalPlaytimeStatementPayload`: a
record is one fact. `removed` and `restored` have empty payloads.

`when` is not in the payload. It is the envelope's `effective_time`. An
unknown `when` is a null `effective_time`.

`player_game` is in the payload, so the projector reads no other table.

Each member of `playthroughs` is `{"id", "playthrough"}`: the join row's
identity and its run, both bare ids, sorted by `playthrough`, no repeat. The
command mints one UUIDv7 per pair; `Restate` keeps the id of each kept run.
A replay then reproduces every key.

Validation refuses an empty list, a repeated run, an unsorted list, a
non-canonical id, a non-positive duration, an unknown provenance, a non-null
`release` or `source`, an extra key and a missing key.

## Commands

`RecordHistoricalPlaytime(statement)`, `RestateHistoricalPlaytime(record_id,
statement)`, `RemoveHistoricalPlaytime(record_id)` and
`RestoreHistoricalPlaytime(record_id)`. The statement is
`HistoricalPlaytimeStatement`, a `NamedTuple` of duration, `when` text,
provenance, playthrough ids, device id, emulated flag and note.

`__post_init__` normalises the statement before the fingerprint: note
stripped and checked, runs deduplicated and sorted, `when` made canonical,
duration truncated to whole seconds. Truncation, not refusal: reclassified
sessions and imports carry clock precision, and one site keeps the
fingerprint and the payload in agreement. It refuses no runs, under one
second, and `when` text the grammar refuses, each with a written sentence.

`build` resolves runs with `library_playthrough` and the device with
`library_device`. It refuses a removed run, a run under a removed game,
another library's run, runs of two games and the imported-history bucket,
each with its own sentence. `Restate` compares the statement with the row
through `columns_for_statement` and answers `Unchanged` when nothing differs.
It resolves the device only when the statement changes it, so a record keeps
a removed device it already names. `Remove` and `Restore` answer `Unchanged`
for the state the row holds, then refuse a record under a removed game or
one naming a removed playthrough.

Every refusal is a `CommandRejected` with a sentence.

## Projections

`HistoricalPlaytime` has `id`, `library`, `player_game`, `duration`, `when`
with generated `when_lower` and `when_upper`, `provenance`, `device`,
`emulated`, `note`, `created_at` and `removed_at`. Constraints:
`library_identity_constraint()`, `duration > 0` and a known provenance.
Index: `(library, when_lower, id)`. `comparison_through` reaches the game in
one hop. `alive()` reads the record's mark and the tracked game's.

`HistoricalPlaytimeRun` has `id`, `library`, `record` and `playthrough`,
unique on `(record, playthrough)`. Its `alive()` reads the record's two marks.

The four foreign keys are in `AUDITED_PROJECTION_REFERENCES`.
`HistoricalPlaytimeRun.playthrough` is in `BLOCKING_REFERRERS`: a live record
keeps its run in place.

The database admits a superset of what the command admits.

## Projector

`HistoricalPlaytimes`, family `CURRENT_STATE`. `created` projects the record
with every column and writes the join rows. `restated` amends every statement
column and replaces the join rows whole. `removed` and `restored` amend
`removed_at`. `columns_for_statement(payload, effective_time)` is the one
mapping from payload to columns.

## Boundary

Only the four commands write the tables. Screens, reads and statistics
belong to later issues of the wave.
