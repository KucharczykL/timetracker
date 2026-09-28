# A device's access ends

Issue: [#1275](https://github.com/KucharczykL/timetracker/issues/1275).
After: [The Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md).
Charter: [LibraryEntry](2026-08-09-timetracker-overhaul-design.md#libraryentry),
[Naming](../../event-retention.md#naming).

## Purpose

A player sells, loses, gives away, breaks or loses to theft a device. The
device stays in the library, because sessions and records name it. Removal
is a different act.

## The stated endpoint

An endpoint is one act that a row states one time: the act, a day of any
precision or no day, a note, and optionally a way. The act is stated,
corrected or voided. A correction keeps the marker. A void writes the
columns back to their values before the act.

- `games/endpoints.py`: `Endpoint` names the columns and the three event
  specs. `ENDPOINTS` lists each endpoint.
- `games/endpoint_fields.py`: the field factories and
  `endpoint_constraints`. Each model declares its columns in its class
  body. `games.E014` compares each endpoint with its model.
- `games/events/endpoint.py`: `endpoint_events` registers three specs.
  The caller spells each type.
- `Projector.project_stated`, `project_corrected`, `project_voided`.
- `games/commands/endpoint.py`: `state_endpoint`, `correct_endpoint`,
  `void_endpoint`. Each command keeps its own fields, so its fingerprint
  does not change. A `before_event` hook holds the aggregate's own rules.
- `games/writes/endpoint.py`: `endpoint_move` chooses the act from
  presence only. The command compares values under the lock.
- `endpoint_filter_fields` gives the interval, the act and the way.

The playthrough start and completion use this primitive. Their types,
command names, fields, columns and filter keys did not change.

## Device access end

| Event | Payload |
|---|---|
| `library.device.access_ended` | `way`, `note` |
| `library.device.access_end_corrected` | `way`, `note` |
| `library.device.access_end_voided` | empty |

The way is `sold`, `lost`, `given_away`, `broken` or `stolen`. The day is
`effective_time`.

`Device` has `access_ended` and its two bounds, `access_end_recorded_at`,
`access_end_note` and `access_end_way`. Two CHECKs admit only the known
ways, and a way only where the marker is set.

`EndDeviceAccess`, `CorrectDeviceAccessEnd` and `VoidDeviceAccessEnd`
refuse a removed device. The void answers `Unchanged` first. `CreateDevice`
can state an end in the same build.

## Screens

- The Device form has Access, the day and a note. "Held" takes back an
  end, together with its day and note.
- Pickers offer an ended device after the held devices, with the way as a
  hint.
- `default_device` is none for an ended device. The key stays. The
  library page shows the ended default with a reason.
- The Devices list has an Access column, two facets, and a sort by day.

## Limits

- The library cannot state that it got a device back. A void says that
  the end did not occur.
- A session after the end is not refused.
- #1157 counts each session on its own day.
