# A copy's access ends and resumes

Issue: [#721](https://github.com/KucharczykL/timetracker/issues/721), member
M2 of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
Charter: [LibraryEntry](2026-08-09-timetracker-overhaul-design.md#libraryentry).
After: [The LibraryEntry aggregate](2026-09-29-issue-719-libraryentry-aggregate-design.md),
[A device's access ends](2026-09-28-issue-1275-device-access-end-design.md).

## Purpose

A library returns a rented game, lets a subscription lapse, sells a disc, or
gets its money back. The copy stays in the library, because purchases and
history name it. The charter says: "acquired date and optional access-ended
date", and "Formerly owned" derives from ended access.

A copy can also come back: a lent disc is returned, a subscription is taken
again. That is a new fact with a day, not a retraction. A void says that the
end did not occur. A resume says that access started again on a day.

## The resume act

The stated endpoint gains an optional fourth act. #1344 uses the same shape
for a device, so the primitive holds it, not the entry.

- `games/events/endpoint.py`: `EndpointEvents.resumed` is an
  `EventSpec | None`, `None` by default. `specs` answers the members that
  are present; registration and every caller that walks the events read
  `specs`, never the tuple itself. `family` is `tuple[EventType, ...]` and
  includes the resume when it is present, so a reader of "the latest
  event of this endpoint" sees a resume. `endpoint_events(...,
  resumed=...)` registers it. Its payload is `EndpointPayload` (`note`).
  The day is `effective_time`.
- `Projector.project_resumed(endpoint, event)` writes `unstated_columns()`,
  as a void does. The projection keeps nothing of the resume. The day and
  the note are in the stream only.
- `games/commands/endpoint.py`: `resume_endpoint(row, endpoint, statement:
  ActStatement, *, sentences, before_event)`. It refuses where no end
  stands. `EndpointSentences` gains `nothing_to_resume`, a `Rejection`,
  last and `None` by default, because only an endpoint with a resume
  states it.
- An endpoint with `resumed=None` has no resume. `resume_endpoint` raises
  `TypeError` for it.
- A resume may state no day, as every other act may: "I got it back, I do
  not know when". The row then reads as it does after a void; the stream
  tells the two apart.
- `normalized(statement)` moves into `games/commands/endpoint.py` and takes
  either statement shape. The copies in the device and entry modules go.

After a resume the endpoint is unstated, so the next end is a new
`access_ended`, not a correction. The projection holds the latest end. The
stream holds every end and every resume.

## Day order

`endpoints_certainly_reversed` and its helper `_bounding_qualifier` move
out of `games/commands/playthrough.py` into `games/commands/endpoint.py`
as `certainly_reversed(*, earlier, later)`. `earlier` takes the start's
side of the qualifier rule and `later` the end's, as `started` and
`completed` did. The rule does not change: refuse only what is certainly
impossible. A qualifier or an open bound refuses nothing. The playthrough
commands, `games/writes/playthrough.py` and their tests call the moved
function.

Three entry refusals use it. Each sentence names the move that works.

| Act | Refused when |
|---|---|
| End or correct the end | the end is certainly before the acquisition |
| Resume | the resume is certainly before the standing end |
| Correct the acquisition | a standing end is certainly before the new day |

P2 uses the same function for a refund before the purchased day.

## Storage

Migration `0021` adds to `games_libraryentry`: `access_ended`,
`access_ended_lower`, `access_ended_upper`, `access_end_recorded_at`
(null is no end), `access_end_note`, `access_end_way`, through
`games/endpoint_fields.py`. `endpoint_constraints` adds two CHECKs: the way
is a known word or empty, and a way stands exactly where the marker is set.

`ENTRY_WAYS` in `games/models.py` lists nine ways: `returned`, `expired`,
`revoked`, `refunded`, `sold`, `lost`, `given_away`, `broken`, `stolen`.
`EndWay` in `games/end_ways.py` gains the first four, and `END_WAY_LABELS`
gains their labels. The
device keeps its five ways. `ENTRY_ACCESS_END_COLUMNS` in `games/models.py`
and `ENTRY_ACCESS_END = Endpoint.over(...)` in `games/endpoints.py` stand
beside the acquisition. `ENDPOINTS` lists it. `games.E014` holds it.

## Events

| Event | Payload |
|---|---|
| `library.libraryentry.access_ended` | `way`, `note` |
| `library.libraryentry.access_end_corrected` | `way`, `note` |
| `library.libraryentry.access_end_voided` | empty |
| `library.libraryentry.access_resumed` | `note` |

`EntryWayValue` is a `Literal` of the nine ways. The day is
`effective_time` on every event but the void.

## Commands

`games/commands/libraryentry.py`. Every command answers `Unchanged` for a
state the row holds before it refuses. `before_event` refuses a removed
entry or a removed `PlayerGame`, then the day order.

| Command | Rule |
|---|---|
| `EndEntryAccess` | `WayActStatement`. The way is checked with a sentence before the payload. A standing end is refused; the same end is `Unchanged`. |
| `CorrectEntryAccessEnd` | Refused where no end stands. The same end is `Unchanged`. |
| `VoidEntryAccessEnd` | `Unchanged` where no end stands. |
| `ResumeEntryAccess` | `ActStatement`. Refused with a sentence where no end stands; that is not `Unchanged`, because the row did not resume. This refusal comes before the removed-entry refusal, because a restore does not make a resume possible. |
| `CorrectEntryAcquisition` | Gains the day-order refusal against a standing end. |

Four `CommandName` members name the new commands. Each normalizes its
statement with the shared `normalized()`, so restatements fingerprint
alike.

A person can state `refunded` by hand. That states that the money came
back. The backlog's Dropped reads the way as the person stated it. P2's
coupled end appends nothing where an end already stands.

## Writes and API

`games/writes/libraryentry.py`:

- `restate_entry` takes `access_end`: a `WayActStatement`, `None` for no
  end, or `KEEP` for no statement. `KEEP` is a sentinel of this module's
  own, because `None` already means a void. `acquired` takes `KEEP` for no
  statement too, so both endpoints spell "not stated" alike. It chooses
  the end's act with `endpoint_move`. One correlation.
- The write refuses a draft whose own new acquisition and new end are
  certainly reversed, before it dispatches anything, because no act
  withdraws a committed one. Then the description goes first. Then the
  end and the acquisition go in the order that never holds a reversed pair
  in between, as `restate_run` orders a run's two endpoints: the
  acquisition first where the new end is certainly before the acquisition
  the row holds, else the end first. A refusal leaves every later act
  unsent.
- `resume_entry_access(actor, entry, statement, *, correlation_id,
  idempotency_key)`.

`games/api.py`:

- `EntryUpdate.access_end`: an object `{ended, way, note}` states or
  corrects the end, `null` voids it, and an absent key states nothing. The
  object refuses an unknown key. It is one object, not flat keys beside
  `acquired`, because the end needs three states and a day has only two
  spellings. The playthrough routes read `started: null` as an act with no
  day; here an end with no day is `{"ended": null, "way": ...}`, and the
  null object is the void. The validator that refuses a present null does
  not list `access_end`.
- `POST /api/entries/{id}/resume` with `{resumed, note}` and an optional
  `Idempotency-Key`. It answers the row.
- `EntryOut` gains `access_ended` as canonical temporal text, its two
  bounds, `access_end_recorded_at`, `access_end_way` and `access_end_note`.

## Verification

- Primitive: resume, its refusal, `family` with and without a resume, and
  `TypeError` for an endpoint that has none. `tests/test_endpoint_primitive.py`
  walks `specs`, not the tuple.
- One fingerprint test per new command.
- Every refusal and every `Unchanged`, the order of `Unchanged` before a
  refusal, and each day-order sentence.
- Projector: end, correct, void, resume, then a second end; the row holds
  the second end.
- The replay gate through every new event type. The four types join
  `Entries.handles`, and the gate's count of unexercised types grows by
  four.
- `EntryWayValue` equals `ENTRY_WAYS`, as the device's pair is held.
- Two libraries: another library's entry answers 404 on each route.
- API: each `access_end` shape, `null`, absence, an unknown way (422), and
  the resume route. A resume repeated under one `Idempotency-Key` answers
  the row again; repeated without a key it answers 409, because no end
  stands.
- `restate_entry`: a draft reversed in itself is refused with nothing
  appended; a copy moved wholly earlier and one moved wholly later both
  land.
- The playthrough tests import the moved function under its new name and
  keywords, and assert what they asserted before.

## Limits

- No screen. The entry form, the list, the filters and the Device form
  fieldset shared by both forms are M3 (#1352).
- `RecordEntry` states no end. If M3's form records an ended copy in one
  submit, M3 adds it.
- A device cannot resume yet. #1344 wires `library.device.access_resumed`
  on this primitive.
- A resume states no way. It only says that access started again.
- The projection holds the latest end and nothing of a resume, as the wave
  forecloses. So:
  - The day-order rules compare against what the row holds and nothing
    else. After an end in 2020 and a resume in 2022, an end in 2021 and an
    acquisition in 2023 both pass.
  - After a resume, the earlier end cannot be corrected or voided.
  - Nothing takes back a resume. A mistaken resume is fixed by stating the
    end again. The stream keeps the resume, as it keeps any statement that
    a later one corrects.

  The cost to lift this: a `resumed` day with its two bounds on the row,
  held until the next end clears it. It gives the next end and an
  acquisition correction a floor, and it makes the earlier end
  correctable again. A list of a copy's lendings is a stream read that
  nothing renders. #1344 inherits the same projection.
- P2's refund states the coupled end under the same day-order rule. A
  refund certainly before the acquired day is refused whole, with a
  sentence that says to correct the acquired day first.
- Bulk end of access is #1355.
