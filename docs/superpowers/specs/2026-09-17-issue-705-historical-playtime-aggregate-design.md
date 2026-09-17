# The HistoricalPlaytime aggregate, its events, commands and projections

Date: 2026-09-17

Issue: [#705](https://github.com/KucharczykL/timetracker/issues/705)
Wave: [Historical Playtime delivery wave](2026-09-17-historical-playtime-wave-design.md)

## Problem

A Historical Playtime Record states a duration a person did not track as
sittings. Production holds about 4,700 hours of such durations stored as
Duration-only sessions, and the wave that gives them a home starts here: the
aggregate, its events, the commands that write it, and the two tables that
project it. Nothing writes or reads them when this issue merges; #706 gives
them a form, #709 reads them, #1098 converts the sessions.

## The record

One record carries a positive whole-second duration; a `when` at any precision
the temporal grammar admits, unknown allowed; a provenance; one or more
playthroughs of one PlayerGame; an optional device; the emulated flag; a note.
Release and source are reserved and always null.

Provenance is `HistoricalPlaytimeProvenance(TextChoices)`: `estimated`,
`manually_entered`, `externally_measured`. Full words, because a recorded
payload is never upcast. The command admits all three; which ones a form offers
is #706's.

## The events

Namespace `library.historicalplaytime.*`, aggregate type `historicalplaytime`,
following the rule #689 stated: the aggregate's model name, lowercased. Four
specs in `games/events/historical_playtime.py`, registered in
`DEFAULT_EVENT_TYPES`.

`created` and `restated` share one payload type, because a record is one fact
and both events state the whole of it:

```python
@with_config(STRICT_SCHEMA)
class HistoricalPlaytimeStatementPayload(TypedDict):
    player_game: ReferenceId          # bare id, as PlaythroughCreatedPayload
    playthroughs: list[HistoricalPlaytimeRunPayload]  # at least one, no repeat
    duration_seconds: int             # positive
    provenance: Literal["estimated", "manually_entered", "externally_measured"]
    device: Reference | None
    emulated: bool
    note: NoteText
    release: None                     # reserved for ACCESS (#719-#724)
    source: None                      # reserved for the importer (#798)
```

`when` is not in the payload. It is the envelope's `effective_time`, where the
charter puts what a player says happened and where a playthrough endpoint's
date already rides. An unknown `when` is a null `effective_time`, the spelling
`Playthrough.started` uses for an unknown day.

`player_game` is in the payload although the runs imply it: the projector
writes the record's `player_game` column from the payload alone and never
reads another projection to find it, so a rebuild of a library that lost rows
still runs. The command proves the runs share it.

Each member of `playthroughs` is `{"id": ReferenceId, "playthrough":
ReferenceId}`: the join row's own identity and the run it names. Both are bare
ids, as a session's run is, for the reason `PlayerSessionCreatedPayload`
states: a required `ReferenceKind` on a projection row would make replay's
reference check read the live table before the first row. The list is sorted
by `playthrough` text and holds no repeated run; the command canonicalises it,
so two statements naming the same runs in another order compare equal.

The join row carries its identity in the event because every projection key
is a UUIDv7 minted at creation: `UUIDv7Field` refuses any other version and
the identity audit walks every `uuid_v7` primary key. A key derived from the
pair would be refused; a key minted by the projector would differ on every
replay and the rebuild's whole-row diff would never be empty. So the command
mints one v7 per pair, and `Restate` reuses the id of every run the record
already names, minting only for runs it adds. The command's fingerprint reads
the statement, not the minted ids, so an honest retry fingerprints alike and
answers from the idempotency record.

`release` and `source` are typed `None`, not `Reference | None`: the validator
refuses any value until the issue that defines one widens the type. A key
holding null rather than an absent key, so that under `extra="forbid"` the two
are not two spellings of one fact.

`removed` and `restored` carry the empty payload their session twins carry.

Payload validation refuses: an empty `playthroughs`, a repeated id, a
non-canonical id, an unsorted list, a non-positive duration, a provenance no
member spells, a non-null `release` or `source`, an extra key, a missing key.

## The commands

Four, in `games/commands/historical_playtime.py`, four new `CommandName`
members: `HISTORICALPLAYTIME_RECORD`, `_RESTATE`, `_REMOVE`, `_RESTORE`.

```python
class HistoricalPlaytimeStatement(NamedTuple):
    duration: timedelta
    when: str | None                  # canonical temporal text; None is unknown
    provenance: HistoricalPlaytimeProvenance
    playthrough_ids: tuple[uuid.UUID, ...]
    device_id: uuid.UUID | None
    emulated: bool
    note: str

RecordHistoricalPlaytime(statement)
RestateHistoricalPlaytime(record_id, statement)
RemoveHistoricalPlaytime(record_id)
RestoreHistoricalPlaytime(record_id)
```

A `NamedTuple`, for the reason `TimingStatement` is one: the idempotency
fingerprint encodes it as an array. `timedelta` fingerprints since #689.

`__post_init__` canonicalises: the note stripped and checked with
`check_note`; `playthrough_ids` deduplicated and sorted; `when` parsed with
`parse_temporal_value` so a string the grammar refuses is refused before the
fingerprint, with the parser's sentence; the duration truncated to whole
seconds and refused under one second.

`build` resolves each run through `library_playthrough`, so a removed run, a
run under a removed game and another library's run answer with the sentences
#1011 and #1062 settled. Then it refuses, each with its own sentence:

- runs of two different PlayerGames: "Historical playtime belongs to one game.
  Choose playthroughs of the same game.";
- the imported-history bucket among the runs: `INTO_THE_BUCKET`'s twin, "That
  is the imported-history bucket. Record historical playtime on one of the
  game's playthroughs instead.";
- a device of another library or a removed device, through `_library_device`,
  which is moved from the session module to `games/commands/scope.py` so both
  callers share it.

`Record` appends `created` with a fresh UUIDv7 as `aggregate_id` and the
parsed `when` as `effective_time`. `Restate` resolves the live record through
`library_row`, compares the statement to the row column for column through
the projector's own mapping (never a copy of it, for the reason
`CorrectSessionTiming` gives), answers `Unchanged("This record already states
that.")` when equal, and otherwise appends `restated`. `Remove` and `Restore`
mirror `RemoveSession` and `RestoreSession`: a removed record refuses a second
removal with `Unchanged`, a live one refuses a restore the same way.

Every refusal a person can act on is a `CommandRejected` with a sentence,
which `answered()` answers directly. No new exception type is introduced, so
`tests/test_command_answers.py`, which walks the module, has nothing to place.

## The projections

Two `ProjectionModel` tables.

`HistoricalPlaytime`:

| column | from |
|---|---|
| `id` | `aggregate_id` |
| `library` | the event |
| `player_game` FK, RESTRICT | payload |
| `duration` DurationField | `duration_seconds` |
| `when` `TemporalValueField`, null | `effective_time` |
| `when_lower`, `when_upper` generated DateField | `TemporalLowerBound`/`UpperBound("when")`, the `Playthrough.started_*` pattern |
| `provenance` CharField, choices | payload |
| `device` FK, RESTRICT, null | payload |
| `emulated` | payload |
| `note` | payload |
| `created_at` | the creation event's `recorded_at` |
| `removed_at`, null | the removal event's `recorded_at` |

Constraints: `library_identity_constraint()`; `historicalplaytime_duration_positive`
(`duration > 0`); `historicalplaytime_provenance_known`. Index
`(library, when_lower, id)` for the containment reads #709 writes.

`comparison_through = (("player_game__game", "Game"),)`, as the session
declares its path to the game, so #1097's filter reaches the catalog through
one hop.

`HistoricalPlaytimeRun`, the join:

| column | from |
|---|---|
| `id` | the member's `id` in the payload |
| `library` | the event |
| `record` FK to `HistoricalPlaytime`, RESTRICT | `aggregate_id` |
| `playthrough` FK, RESTRICT | the member's `playthrough` |

Unique `(record, playthrough)`. The projector writes join rows with
`library_rows(...).bulk_create`, not `project()`, whose key is the aggregate's.
Its queryset states `alive()` as `filter(record__removed_at__isnull=True)`: the
join has no mark of its own, and `_skips_removed_rows` asks only that the
manager state the method.

Four pairs join `AUDITED_PROJECTION_REFERENCES`: `(HistoricalPlaytime,
"player_game")`, `(HistoricalPlaytime, "device")`, `(HistoricalPlaytimeRun,
"record")`, `(HistoricalPlaytimeRun, "playthrough")`.
`tests/test_projection_references.py` fails until they do.

`BLOCKING_REFERRERS` gains `BlockingReferrer.on(HistoricalPlaytimeRun,
"playthrough", sentence="Historical playtime is recorded on this playthrough.
Restate it onto another playthrough, or remove it, before removing this
one.")`, so `RemovePlaythrough` refuses while a live record names the run and
`foreign_referrer` reports a foreign one.

## The projector

`HistoricalPlaytimes` in `games/projectors/historical_playtime.py`, family
`CURRENT_STATE`, four handlers:

- `_created`: `project(HistoricalPlaytime, …)` with every column named, then
  the join rows through `library_rows(HistoricalPlaytimeRun, event).bulk_create`,
  one per member, each with the member's id.
- `_restated`: `amend(HistoricalPlaytime, …)` with every statement column
  named, as `columns_for_timing` names all eight; then the join rows of the
  record in the event's library are deleted through `library_rows` and
  projected again. A derived set is replaced whole, never patched.
- `_removed` and `_restored`: `amend` of `removed_at`, as the session's.

The mapping from payload to columns is one function,
`columns_for_statement(payload, effective_time)`, which `Restate`'s
comparison also reads.

## Registration and gates

Both tables are `managed`, so `projection_models` finds them and the rebuild
registry, the shadow tables and `rebuild_projections` take them without a
list to edit. The replay gate (`tests/test_projection_replay_gate.py`) gains
`HistoricalPlaytimes.handles` in `registered_event_types`, a record in every
leg of `build_stream` (one naming two runs, one restated onto one run, one
removed, one removed and restored), and both tables in `rows_of`.

Migration `0002_historical_playtime`, generated with `make makemigrations`,
checked with `make check-migrations`.

## Boundary

Out: every screen and form (#706), every read of the tables and every
statistic (#709), the list and its filter (#1097), the split presentation
(#710), `ReclassifySessionAsHistoricalPlaytime` and the
`playersession.reclassified` event (#1098), the bench workload (#1099).
Nothing writes the tables and nothing reads them when this merges; that is
what makes it incomplete rather than inconsistent, so it merges alone.

## What later issues inherit

- **#706** offers `estimated` and `manually_entered`; the command admits all
  three. Its form posts a `HistoricalPlaytimeStatement`.
- **#709** reads `when_lower`/`when_upper` for containment and the
  `(library, when_lower, id)` index.
- **#1097** reads `comparison_through` for the game hop and declares no `run`
  field.
- **#1098** appends `created` from a session's columns and a fifth session
  event; `RestoreSession` learns a refusal there, not here.
- **#798** widens `source` from `None` to an object and adds the column; the
  event type does not change.
- **ACCESS** widens `release` the same way.

## Verification

- Payload validation refuses each case listed above, and the event type
  spellings are pinned.
- Every command refusal answers with its sentence; two PlayerGames, the
  bucket, a removed run, a foreign run, a removed device, zero runs, a
  repeated run, an unparseable `when`, a sub-second duration.
- `Restate` with an equal statement in another run order appends nothing.
- Both CHECKs refuse the rows they should, proven through `IntegrityError`.
- The join ids are the payload's: a replay reproduces them, and a restate
  that keeps a run keeps its join id.
- `RemovePlaythrough` refuses a run a live record names, admits it once the
  record is removed, and reports a foreign record's library.
- Replay from an empty stream reproduces both tables exactly, through
  `rebuild_projections --check`; the whole-row diff is empty after a restate.
- `AUDITED_PROJECTION_REFERENCES` holds the four pairs and `manage.py check`
  is clean.
- The full `make check` gate passes.
