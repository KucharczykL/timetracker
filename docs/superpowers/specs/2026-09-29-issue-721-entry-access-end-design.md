# A copy's access ends and resumes

Issue: [#721](https://github.com/KucharczykL/timetracker/issues/721), member
M2 of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
After: [The LibraryEntry aggregate](2026-09-29-issue-719-libraryentry-aggregate-design.md),
[A device's access ends](2026-09-28-issue-1275-device-access-end-design.md).

## Purpose

A library returns a rental, sells a disc or gets its money back. The copy
stays, because purchases and history name it. A copy can also come back.
That is a new fact with a day. A void says that the end did not occur.

## The resume act

A stated endpoint can have a fourth act, `resumed`.

- `ResumableEndpoint` holds `ResumableEndpointEvents`, whose `specs` and
  `family` include the resume. `resume_endpoint` takes only a
  `ResumableEndpoint`, so a resume of another endpoint is a type error.
- `project_resumed` writes the unstated columns. The row keeps nothing of
  the resume.
- `resume_endpoint` refuses where no end stands. It never answers
  `Unchanged`.
- `normalized` and `certainly_reversed` are in `games/commands/endpoint.py`.

## Storage and events

`LibraryEntry` has `access_ended`, its two bounds, `access_end_recorded_at`,
`access_end_note` and `access_end_way`. Two CHECKs hold the way. The nine
`ENTRY_WAYS` are `returned`, `expired`, `revoked`, `refunded`, `sold`,
`lost`, `given_away`, `broken` and `stolen`.

Events: `library.libraryentry.access_ended`, `access_end_corrected`,
`access_end_voided`, `access_resumed`.

## Commands

An unknown way is refused first. `EndEntryAccess`, `CorrectEntryAccessEnd`
and `VoidEntryAccessEnd` then answer `Unchanged` before they refuse a
removed copy or game. `ResumeEntryAccess` never answers `Unchanged`; it
refuses a copy with no end first. A person can state `refunded`.

The day order refuses only what is certainly impossible:

| Act | Refused when |
|---|---|
| End, or its correction | before the acquisition |
| Resume | before the standing end |
| Acquisition correction | after a standing end |

## Writes and API

`restate_entry` takes `access_end`. `KEEP` states nothing and `None` voids.
Before it dispatches, it refuses a stated day that is certainly reversed
against the other day, stated or kept. It moves the acquisition first only
where the new end certainly precedes the acquisition that the row holds.
A void always dispatches, so the command decides under the lock.

`PATCH /api/entries/{id}` takes `access_end`, `{ended, way, note}` or null.
`POST /api/entries/{id}/resume` takes `{resumed, note}`.

## Limits

- The row holds the latest end. The day order compares with the row
  only. An earlier end cannot be corrected after a resume. To take back a
  resume, state the end again. A `resumed` column would remove these
  limits.
- A refund certainly before the acquired day is refused.
- No screen, and `RecordEntry` states no end. #1352 adds both.
- #1344 adds a device's resume.
