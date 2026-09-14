# Convert legacy Sessions into PlayerSession facts

Issue [#700](https://github.com/KucharczykL/timetracker/issues/700). The model
is [the Playthrough conversion](2026-09-06-issue-684-playthrough-conversion-design.md),
whose module CLEAN-02 took out with the table it read; its shape is recovered
from `9fa80537^` rather than invented again. The census it builds on is
[#699](2026-09-12-issue-699-session-preflight-design.md); the aggregate it
writes is [#689](2026-09-13-issue-689-playersession-aggregate-design.md).

The legacy `Session` table records that a game was played, when, for how long,
on what device. The conversion states every row as `PlayerSession` events,
names a run for each, and mints the imported-history bucket where a game needs
one. It writes no legacy row. It changes no read path and no write path.

Every claim below about production was read off the dump taken 2026-09-12,
restored with `make restore-dump`, not reasoned out.

## Delivery

One migration, `0004_playersession_conversion`, converts, gates, and commits.
Any mismatch rolls the run back; the reverse is `noop`. `load_sample_data`
calls `convert_library()` after it replays the fixture's events, and refuses the
load on a mismatch, so a development database holds the projection the
deployment holds.

The migration imports the concrete models, as `0045` did, because the
conversion appends through the live vocabulary and projectors, and is
`elidable=True` for the same reason `0045` was: a squash may drop it once it
has run. #772 replaces
the callable with `RunPython.noop` when it drops `Session`, and takes
`games/backfill/` out with it. Both are recorded in #772 now.

**This branch is the first member of the wave's stack** — #700, #1047, #702's
members, #704 — opened with `gh stack init` and `gh stack submit`, and landed
only by `gh stack merge` once #704 is green. It is never merged alone. #601
says the intermediate states are "harmless on `main`"; that rests on the
quadlet holding no `AutoUpdate`, so `latest` moves only when someone restarts
the unit. The stack makes the convention a mechanism.

## Module

`games/backfill/appending.py` and `games/backfill/mismatch.py` return
unchanged from `9fa80537^`: `append_one` appends one event under one key with a
stated `recorded_at`, and `Mismatch[Code]` is one reason a gated pass must not
commit.

`games/backfill/playersession.py` is the pass. It imports `classify_timing`,
`assign_run`, `RunInterval`, `MODE_VERDICTS` and `preflight_library` from
`games/preflight/session.py`, so the report and the conversion cannot name one
row two ways. It imports `normalized_timing`, `timing_payload` and
`check_note` from `games/commands/playersession.py` — the module functions
`CreateSession` already shares, made public by dropping the underscore and
nothing else — so every value refusal the command states, the conversion
states, as `CommandRejected`.

It does not dispatch `CreateSession`. A conversion states an identity and a
past instant, which no command does and no later issue asks for: #1054 is a
restatement, #748 a rebuild, HIST its own aggregate, #714 the bulk form of a
move. Widening `dispatch()` to take a past `recorded_at` would let a command
backdate what a person stated, for one caller that #772 takes away.

The walk pages the games the library owns — `Game.objects.filter(library=library)`,
as the census does — through `keyset_pages`, 200 per page, and takes each
game's `Session` rows live and removed alike, ordered by id. It walks games,
not tracking rows, so a row on an untracked, removed-tracking, removed or
shared game is *visited* and refused by name rather than left as an anonymous
residual. The residual it does count, by a separate query, is
`Session.objects.filter(game__library=library).count()` against the rows
converted, and it must be zero.

Every read names its columns with `.only()` — `SESSION_FIELDS`,
`PLAYERGAME_FIELDS`, `PLAYTHROUGH_FIELDS` — as `0045` did with
`_PLAYEVENT_FIELDS`: the migration runs against the concrete models while the
schema stands at `0004`, so a column a later stack member adds to any of these
tables would make a bare query fail with "column does not exist" on the
deployment and in `make verify-dump`. #1047, #702 and #704 are told: a column
added to `Session`, `PlayerGame`, `Playthrough` or `PlayerSession` needs no
entry here, because the lists name only what `0004` reads, and a renamed or
dropped column named here fails `0004` loudly.

## One row, one statement

`classify_timing(row)` answers one of six verdicts. Three are modes:

| verdict | statement | duration |
|---|---|---|
| `timed` | `TimedTiming(start, day_zone, started_at_zone, end, ended_at_zone)` | elapsed |
| `duration_only` | `DurationOnlyTiming(day, duration_manual)` | stated |
| `corrected` | `CorrectedTiming(start, end, duration_total, day_zone, zones)` | stated |

A Corrected statement takes `duration_total`, never `duration_manual`: legacy
adds the manual part to the elapsed time, the mode replaces it. Production
holds no such row, so a test states the arithmetic on a synthetic one —
`Session.duration_total == PlayerSession.effective_duration` for every verdict.

`running` — no end, zero manual — is a Timed statement with no end **when the
row is removed**, and a refusal when it is live. The order is: refuse a NULL
`duration_manual` first, then `normalized_timing`, then `timing_payload`. A person finishes or corrects
a live one before the cutover; a removed one is nobody's to act on, and refusing
it would have #772 destroy the record. Production holds two, both removed.
`negative_elapsed` and `negative_manual` refuse; production holds none.
`duration_manual IS NULL` refuses ahead of the verdict: `classify_timing` reads
NULL as zero, and the census counts the row under `manual_duration_null`
beside the verdict, so the two still agree on every row that converts.
Production holds none. The two removed rows in production are exactly the two
running rows, so check 1's removal branch is exercised on them and nothing
else.

A stated duration must be whole seconds and, for Duration-only, above zero;
`timing_payload` refuses the rest. Production's 142 manual durations are whole
seconds; the 1,672 sub-second intervals are elapsed Timed time, which no
payload states.

`day_zone` is the library's display zone, `DISPLAY_TIME_ZONE` resolved for the
library's user, which is the zone every legacy day-grained read groups in. A
Duration-only row's `day` is `timestamp_start` read in that zone; the instant
itself is evidence, not a column. `known_zone` refuses a display zone either
tzdata set lacks.

Endpoint zones convert as recorded: NULL becomes `None`, never `""`. The 56
production rows stating an end zone and no start zone keep exactly that. The
legacy comment says NULL meant "assume the display zone", and `None` still
means unstated, so nothing is invented.

The device converts as named, removed or not — the projection's key is
`RESTRICT`, the row exists, and the fact stood. A device of another library
refuses; it is the drift `audit_library_ownership` reports. The note is
stripped, then `check_note` refuses what JSONB cannot hold. Production: 2,690
rows name a device, none removed, none foreign; 367 notes, none padded, none
holding a NUL byte.

Two events per removed row, one per live row:

- `library.playersession.created`, aggregate id **the legacy `Session.id`**,
  `recorded_at` the row's `created_at`. Every bookmarked session URL keeps
  working and #704's parity needs no mapping table.
- `library.playersession.removed`, `recorded_at` the row's `removed_at`.

Event identities come from `identity_at(recorded_at)`. The 98 production rows
whose `created_at` precedes their start are fine: the envelope dates the act by
`effective_time` and the recording by `recorded_at`, and nothing orders one
against the other.

`source_metadata` on every event:

```json
{"origin": "backfill", "issue": 700,
 "legacy": {"timestamp_start": "...", "timestamp_end": null,
            "timestamp_start_timezone": null, "timestamp_end_timezone": "Europe/Prague",
            "duration_manual_microseconds": 0,
            "duration_calculated_microseconds": 5400000000,
            "duration_total_microseconds": 5400000000, "created_at": "...",
            "verdict": "timed", "assignment": "sole_run", "claimers": null}}
```

Durations are microseconds, because 1,672 Timed rows hold sub-second elapsed
intervals and evidence truncated to seconds is not evidence. Nothing reads it.
It is the only place the dropped time-of-day of a Duration-only row, the
elapsed part of a Corrected row, and the reason a row landed where it did
survive #772.

## Assignment and the bucket

Per game, the live ordinary runs become `RunInterval`s from the generated
bound columns, in `created_at, id` order. The day is the start read in the
display zone. `assign_run` answers:

- `SOLE_RUN` — that run, whatever the day.
- `CONTAINED` — the one dated run that claims the day.
- `BUCKET` — the game's imported-history run.

The bucket is one run per game, not per library. Before minting, the pass
resolves a live `imported_history` run of the game by query; only where none
stands is one minted, when the first row reaches `BUCKET`, at the migration's
instant, because minting it is the importer's act: `playthrough_created(player_game, kind="imported_history",
playthrough_id=identity_at(now))`, then
`playthrough_name_changed(name="Imported history — needs sorting")`, under one
correlation id. Numbering and Game detail already skip the kind; ORG
(#714–#717) inherits it, and `MoveSessionToPlaythrough` is the only way out.
Production: one game, two rows in UTC, one in Europe/Prague.

A row whose game has no live `PlayerGame` — untracked, tracking row removed,
catalog game removed, or a shared game — has no run to name and **refuses the
migration**, naming the row and the category. A row skipped here is a row #772
destroys. Production holds none in any category, and the census already counts
all four.

## Keys and identity

- `backfill:700:playersession:created:<session>`
- `backfill:700:playersession:removed:<session>`
- `backfill:700:playthrough:bucket:<player_game>`
- `backfill:700:playthrough:bucket_name:<player_game>`

`command_input` names only identities that are stable across passes. A
session's input is `{"session": id, "assignment": outcome}` plus the run for a
`SOLE_RUN` or `CONTAINED` row; a `BUCKET` row's input names the outcome word
and no run, because the run it landed on is the identity this pass mints,
fresh per pass, and naming it would answer a second pass with
`IdempotencyKeyMismatch` in place of the no-op the key promises. The bucket's
own input is `{"player_game": id}`.

## The gate

After the walk, before commit, per library. A mismatch is a `Mismatch[Code]`;
the migration prints one machine-readable line to stderr and names the first
three in the exception.

1. **Row to row.** Every converted row's columns equal the legacy row's
   statement: mode, instants, zones, day, `effective_duration == duration_total`,
   device, note, emulated, and the removal mark. Live and removed populations
   are compared apart.
2. **Census.** The pass's `timed`, `duration_only`, `corrected`,
   `running_removed`, `removed`, `sole_run`, `contained` and `bucket` equal
   `preflight_library(library)`'s `timed`, `duration_only`, `corrected`,
   `running`, `removed`, `sole_run`, `contained_secondary` and
   `bucket_secondary`. The secondary column is `activity_clock(library).zone`,
   which resolves the same `DISPLAY_TIME_ZONE` the pass seeds `day_zone` from;
   a test pins that rather than assuming it. `rows_unreached == 0`.
3. **Bucket.** At most one live `imported_history` run per game, holding
   exactly the `BUCKET` rows, present only where one was needed.
4. **Playtime.** `differing(playtime_figures(library, display_zone(library)))`
   is empty: every figure #697 compares agrees between the legacy source and
   the projection, read in the zone the rows were seeded in.
5. **Counts.** Legacy `Session` rows in scope, live and removed, equal
   `PlayerSession` rows of the library, live and removed.
6. **Identity ordering** for `games_playersession` and `games_playthrough`
   (the bucket is a key this pass mints), and the audit holds an entry for
   both.
7. **Replay.** `rebuild_projections(library, mode=CHECK)`: on every
   `TableDiff`, `only_live`, `only_rebuilt` and `differing` are zero, and
   `head_at_diff == replayed_through`.

Two passes over unchanged data print the same bytes and the second appends
nothing.

## Boundary

Out: every screen, every write path, the run pickers, the dormancy clock, the
zone a library counts days in (#1047), the fixture's session rows (#772 turns
them into events), and any read of the projection.

## Verification

- A synthetic legacy row of each verdict converts to the row the mode
  defines, and `Session.duration_total == PlayerSession.effective_duration`.
- A removed running row converts to a Timed row with no end and a mark; a live
  one refuses.
- Each refusal fires: negative interval, negative manual, null manual, unknown
  display zone, a note holding a NUL byte, a device of another library, a row
  with no live `PlayerGame` in each of its four categories.
- End-zone-only rows keep a stated end zone and an unstated start zone.
- A removed device converts as named.
- Sole run, one claimer, no claimer, two dated claimers (synthetic overlap):
  the last two reach one bucket per game, minted once.
- A second pass appends nothing and the counts are byte-identical.
- The gate refuses on each mismatch code, one test per code.
- Replay from an empty stream reproduces every converted row.
- `load_sample_data` converts the fixture and the gate passes on it.
- `UNREACHABLE_KINDS` in `tests/test_playergame_playthrough_gate.py` still
  holds: the bucket is an importer's kind, not a command's.
- The full `make check` gate passes.

## Recorded elsewhere

- #772: noop the callable, take `games/backfill/` out.
- #601: the four-issue stack, and why "harmless on `main`" holds.
- #702: the bucket exists; the move command is the only way out of it.
- #1047, #702, #704: `0004` reads named columns of four tables; a column they
  rename or drop fails it.
- #689's design: its identity note said reuse passes because every converted
  row shares one `created_at`; the rows carry their own, and reuse passes
  because the legacy ids already order by `created_at` (zero inversions on
  the dump). The sentence is corrected there.
- The wave review: the delivery note on #700.
