# The LibraryEntry aggregate

Issues: [#719](https://github.com/KucharczykL/timetracker/issues/719),
[#720](https://github.com/KucharczykL/timetracker/issues/720),
[#722](https://github.com/KucharczykL/timetracker/issues/722), member M1 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
Charter: [LibraryEntry](2026-08-09-timetracker-overhaul-design.md#libraryentry),
[Durable references](2026-08-09-timetracker-overhaul-design.md#durable-references),
[Shared and private catalog records](2026-08-09-timetracker-overhaul-design.md#shared-and-private-catalog-records).
Builds on: [A device's access ends](2026-09-28-issue-1275-device-access-end-design.md)
(the stated endpoint), [The Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md),
[Catalog](../../catalog.md).

## Purpose

A library says that it has a game: one route of access to one Release, with
an access word, a format and the day it was acquired. That fact is a
`LibraryEntry`. A library can hold several entries on one Release, because a
person can own a physical copy beside a digital one, or buy the same game
twice. An entry is stated, described, corrected, removed and restored by
commands, and only the `Entries` projector writes its row.

This member delivers the aggregate and its API. The end of access, the
resume, the screens and the purchase that names an entry are later members.

## The opening endpoint

The stated endpoint of #1275 is an act a row states after it exists: stated,
corrected, voided. An entry's acquired day is different. The creation states
it, a correction moves it, and nothing voids it: a row with no acquisition
is no row.

The primitive gains an **opening endpoint**:

- `games/endpoint_fields.py`: `OpeningEndpointColumns` names the day, its
  two bounds, the marker and the note. It has no way and no
  `unstated_columns()`. `opening_marker()` is a `DateTimeField` that admits
  no null, because every row holds the act.
- `games/events/endpoint.py`: `OpeningEndpointEvents` holds one spec,
  `corrected`; `opening_endpoint_events` registers it.
- `games/endpoints.py`: `OpeningEndpoint.over(columns, events)`. `ENDPOINTS`
  lists both shapes, and `games.E014` checks the columns of both. An opening
  endpoint has no way, so `endpoint_constraints` answers none for it.
- `Projector.opening_columns(endpoint, event)` answers the columns a creation
  handler writes: the day from `effective_time`, the marker from
  `recorded_at`, the note from the payload.
- `correct_endpoint` in `games/commands/endpoint.py` takes any endpoint whose
  events state a `corrected` spec. `state_endpoint` and `void_endpoint` keep
  the three-event shape. `stated()` in `games/reads/endpoints.py` reads both.
- `endpoint_move` is not used by an opening endpoint: presence never changes,
  so a restatement is always a correction, and the command compares values
  under the lock.

The purchased day of a Purchase reuses this variant in a later member.

## Storage

Table `games_libraryentry`, written only by the `Entries` projector, family
`CURRENT_STATE`. The first migration is `0020`.

| Column | Meaning |
|---|---|
| `id` | the aggregate id, a `UUIDv7Field` with no default |
| `library` | the owning library |
| `player_game` | the tracked game, `RESTRICT`, `related_name="entries"` |
| `release` | the Release, `RESTRICT`, `related_name="+"`; a live Release of `player_game`'s game |
| `access` | one of `owned`, `borrowed`, `rented`, `subscription`, `trial`, `demo`, `pirated` |
| `format` | one of `physical`, `digital`, `unknown` |
| `note` | text; the empty string is none |
| `acquired`, `acquired_lower`, `acquired_upper`, `acquisition_recorded_at`, `acquisition_note` | the opening endpoint |
| `created_at` | the creation event's `recorded_at` |
| `removed_at` | the projector's mark; null is live |

`EntryAccess` and `EntryFormat` are `TextChoices` on the model; the events
spell the same words as `Literal`s, pinned by a test. Two `CHECK`s admit only
the words. The row is unique on `(id, library)`. A partial index on
`(library, release)` covers live rows. There is no uniqueness on the Release:
two entries with the same words are two copies, and only the idempotency key
absorbs a double submit.

No column of the end of access is here. Member M2 adds them in its own
migration, as `0019` added the device's.

`LibraryEntryQuerySet.alive()` reads the entry's mark and the `player_game`'s,
as a session's does. The catalog marks belong to the read layer.

## Events

Stream `library.libraryentry`, aggregate type `libraryentry`.

| Event | Payload |
|---|---|
| `library.libraryentry.created` | `player_game` (a bare `ReferenceId`, as a run's), `release` (a `catalog.release` `Reference`), `access`, `format`, `note`, `acquisition_note`; `effective_time` is the acquired day |
| `.access_changed` | `access` |
| `.format_changed` | `format` |
| `.note_changed` | `note` |
| `.release_changed` | `release` (a `Reference`) |
| `.acquisition_corrected` | `note`; `effective_time` is the day |
| `.removed`, `.restored` | empty |

`player_game` is a bare id because the row may not exist while the creation
composes, and a REQUIRED kind on a projection row would make the replay's
check read the live table. `release` is a `Reference`: the Release is
conventional catalog data the retention guard keeps while any event names
it, and the replay's reconciliation refuses a stream naming a Release that
left.

The reference kind `libraryentry` is `PROJECTED`, created by
`library.libraryentry.created`. Its capture labels the game's name and
details the access and format words. Nothing names an entry in this member;
the Purchase does in a later one.

## Commands

`games/commands/libraryentry.py`. Every command runs under `answered()`,
resolves rows through `games/commands/scope.py`, carries a sentence on every
refusal and answers `Unchanged` ahead of every refusal.

| Command | Rule |
|---|---|
| `RecordEntry(release_id, access, format, note, acquired: ActStatement)` | the Release resolves through `visible_row`; a Release the library cannot see is absent; a removed Release, Edition or Game is refused with a sentence; the game is the Release's, never named twice; an untracked game raises `PlayerGameNotTracked` |
| `DescribeEntry(entry_id, access, format, note, release_id)` | `None` states nothing; one event per differing fact; the new Release must be a live Release of the row's game; a removed entry or a removed PlayerGame is refused |
| `CorrectEntryAcquisition(entry_id, statement: ActStatement)` | the primitive's correction; the same statement answers `Unchanged`; a removed entry or PlayerGame is refused |
| `RemoveEntry(entry_id)` | already removed answers `Unchanged`; a removed PlayerGame is refused; then the referrer registry is asked, which holds no entry referrer yet; then a foreign referrer is `RowUnreadable` |
| `RestoreEntry(entry_id)` | live answers `Unchanged`; a removed PlayerGame or a removed Release is refused |

Words are checked ahead of the payload's validation, as `check_way` does for
a device, so a foreign word is a sentence rather than a defect. Every stated
text is stripped in `__post_init__`, ahead of the fingerprint; the acquired
day is normalised through `stated_date`.

The event builder `libraryentry_created` takes an optional `entry_id`, as
`device_created` does, so a later command can mint one beside its own event.

## Scope and references

`games/projections.py` gains `LIBRARY_PATHS`, one path per catalog model
that reaches a library through its parents: `Release` through
`edition__game__library`, `Edition` through `game__library`. A model with a
`library` column has the path `library`. Four readers share it:

- `_is_library_scoped` answers true for a model the map names, so the
  reference walk finds `LibraryEntry.release` and `games.E009` demands its
  registration.
- `ProjectionReference` carries the path, and `cross_library_violations`
  joins through it. `AUDITED_PROJECTION_REFERENCES` gains
  `(LibraryEntry, "player_game")` and `(LibraryEntry, "release")`. An entry
  naming another library's private Release is reported by
  `audit_library_ownership`, and the swap's refusal sentence names it.
- `visible_row(context, reads, refusal, **lookup)` in
  `games/commands/scope.py` resolves a row that is shared or the library's
  own, through the model's path. The caller states whether removed rows are
  read. `TrackGame` resolves its Game through it and keeps its sentence.
- `library_row` is unchanged.

## Referrer registry

`games/reads/playthrough_referrers.py` becomes `games/reads/referrers.py`.
`BlockingReferrer.on(model, field_name, *, target, sentence)` takes the model
the field names and refuses a field that names another. `blocking_referrer`
and `foreign_referrer` take any projection row and read the entries whose
target is the row's model. The two run entries stay. `RemoveEntry` asks both,
so the Purchase's registration in a later member is one line.

## Writes, reads, API

`games/writes/libraryentry.py`, subject `entry`:

- `record_entry(actor, draft, *, correlation_id, idempotency_key)`: on
  `PlayerGameNotTracked` it tracks the game and states the entry again, once,
  as `record_playthrough` does, and answers `RecordedEntry(entry_id,
  tracked_the_game)`.
- `restate_entry`: the correction first, then the description, under one
  correlation, so a refused correction leaves the description unsent.
- `remove_entry`, `restore_entry`.

`games/reads/entries.py`:

- `library_entries(library)`: live entries, with the library stated on the
  entry and its PlayerGame, and five marks read: entry, PlayerGame, Release,
  Edition, Game. `UnscopedRead` on a missing library.
- `readable_entries(library)`: the row path the API serves, with the game,
  the Release and its platform selected.
- `game_entries(library, game)`.

Routes on `/api/entries/`, in `games/api.py`:

| Route | Body and answer |
|---|---|
| `GET /` | `limit` (100, `0` unbounded) and `offset`; rows in `created_at, id` order |
| `POST /` | `release_id`, `access`, `format`, `note`, `acquired` (canonical temporal text or null); `Idempotency-Key` header; 201 and the row |
| `GET /{id}` | the row, else 404 |
| `PATCH /{id}` | `access`, `format`, `note`, `release_id` describe; `acquired` corrects; a named key is the act |

Every body is `extra="forbid"`. A row the library does not hold answers 404,
from the command, and every other refusal 409 with the command's sentence.
The row answered carries the game's name and id, the Release's id and
platform name, the two words, the note, the acquired day beside its bounds,
the marker and its note, `created_at`.

No screen, no filter and no route for removal in this member.

## Verification

- Replay gate: `build_stream` dispatches every new event type, records two
  entries on one Release and removes one; `rows_of`, `row_versions`,
  `empty_projections` and the neighbour cover the sixth table; the
  fingerprints test pins every new command.
- Two libraries: a shared Release yields one independent entry each; another
  library's private Release answers 404 from `RecordEntry` and from the
  `release_id` of `DescribeEntry`; another library's entry answers 404 on
  `GET` and `PATCH`; an entry rewritten to name a foreign private Release is
  reported by `audit_library_ownership`.
- Commands: one test per refusal sentence; `Unchanged` ahead of each refusal;
  the untracked game is tracked first and the entry recorded once.
- Checks: `games.E009`, `E012` and `E014` pass; `test_command_scope_guard`,
  `test_command_answers` and `test_projector_scope_guard` walk the new
  modules.
- The full `make check`.

## Limits

- An entry never moves to another game. `release_changed` stays inside one
  game; a row on the wrong game is removed and recorded again.
- `RemoveEntry` refuses nothing for a Purchase yet. Member P1 registers
  `Purchase.entry` as a referrer, one line, and states the sentence.
- The end of access, its ways and the resume are M2. The screens, the filter,
  the presets and the removal routes are M3.
- Two entries with the same words on one Release are two copies. No rule
  tells them apart, and none should.
