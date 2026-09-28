# A device's access ends, and the stated endpoint beneath it

Issue: [#1275](https://github.com/KucharczykL/timetracker/issues/1275).
After: [The Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md).
Charter: [Bounded event sourcing](2026-08-09-timetracker-overhaul-design.md#bounded-event-sourcing),
[LibraryEntry](2026-08-09-timetracker-overhaul-design.md#libraryentry).

Decided with the user on 2026-09-28.

## Purpose

A player sells a console, loses a handheld, gives a phone away. Removal is
the wrong tool for any of these: removal takes a row out of the library,
and a sold device is still history — its sessions and records name it.
This issue lets a library state that its access to a device **ended**, in
one of five ways, on a day at any precision, with a note; and correct or
take back that statement.

The shape is not new. A playthrough's start and completion already are
exactly this: a day stated as a `TemporalValue`, two generated bound
columns, a marker naming the act, a note, and a `_corrected` and
`_voided` event beside the act (#681, #1010, #1256). The device end is the
third copy; the charter's `LibraryEntry` "acquired date and optional
access-ended date" (#721) are the fourth and fifth, and #727's refund may
be a sixth. So this issue first extracts that shape into one primitive,
moves the playthrough onto it, and then builds the device end as its
second consumer.

## Delivery

One `gh stack`, two members, merged atomically:

1. **The stated-endpoint primitive**, with playthrough start and
   completion moved onto it. No behaviour changes; every recorded event
   type, command name and column keeps its spelling.
2. **Device access end**, built on the primitive.

Member 1 is refactor-only and could land alone, but the primitive's
interface is shaped by two consumers; member 2 is the second, so they
review and land together.

## Decisions

| Question (from the issue) | Answer |
|---|---|
| One act or one per way? | One act, `access_ended`, carrying a `way` word. A new way is one enum value and one CHECK widening, not an event family. |
| Verb | `access_ended`, the charter's word for `LibraryEntry`, so both aggregates speak one verb. |
| Ways | `sold`, `lost`, `given_away`, `broken`, `stolen`. |
| A day, at what precision? | `effective_time`, a `TemporalValue` at any precision the grammar knows, null for an unknown day — as playthrough endpoints. (Purchases' dates are plain `DateField`s; they are not the precedent the issue named.) |
| A note? | Yes; the empty string is no note. |
| Offered in the session/record device picker? | Yes, labelled with its way, after held devices when the box is empty. Back-dating a session on a sold device is ordinary. |
| Offered as the default device? | No. |
| How the Devices list shows it | An Access column and two quick facets; the bare list still shows every device. |
| Counts in device totals after the act? | No figure exists yet. The rule, recorded on #1157: a device split counts every session on its own day, whatever the device's access. |
| Undo | A void, as #1256: the device reads as held again. |
| Where it is stated | The Device Add and Edit forms. No new route, no row-menu item, no bulk act yet. |

## Member 1: the stated-endpoint primitive

### What an endpoint is

An endpoint is one act a projection row can state at most once at a time:
it happened (marker set), on a day or on none (`when`), with a note, and —
for an endpoint that has ways — in one way. It can be stated, corrected
(day, note, way; the marker keeps the instant the act was recorded), and
voided (every column back to what a row holds before any act).

### The descriptor

`games/endpoints.py` declares `Endpoint`, a frozen value naming one
endpoint on one projection model:

- `model`, and the column names: `when`, `lower`, `upper`, `marker`,
  `note`, and `way` or none;
- `stated`, `corrected`, `voided`: its three `EventSpec`s;
- `ways`: the admitted `EndWay` members, empty for an endpoint without
  ways.

Playthrough declares two: `PLAYTHROUGH_START` (`started`,
`started_lower`, `started_upper`, `start_recorded_at`, `start_note`) and
`PLAYTHROUGH_COMPLETION`. Device declares `DEVICE_ACCESS_END`. A registry
beside the descriptor lists every endpoint, for the check and the replay
gate.

### Columns stay declared by hand

Each model still spells its columns in its class body, through small field
factories (`endpoint_when()`, `endpoint_bound(when, "lower")`,
`endpoint_marker()`, `endpoint_note()`, `endpoint_way(ways)`), so mypy and
django-stubs see every field and the migration autodetector needs no
trick. A class decorator or `locals()` injection would hide the fields
from both; that is the cost this design refuses.

`endpoint_constraints(endpoint)` returns the CHECKs an endpoint needs —
for a way endpoint, the way words, and marker-and-way null together — and
the model's `Meta` spreads it beside `library_identity_constraint()`. A
new system check, `games.E014`, refuses a registered endpoint whose model
lacks a named column, whose bound columns are not `GeneratedField`s over
`when`, or whose `Meta` lacks the endpoint's constraints (the lesson of
`games.E012`: an abstract `Meta` is shadowed, so the check reads the real
one).

### Events

`games/events/endpoint.py` holds:

- `EndWay`, a `StrEnum` of every way any endpoint admits. Recorded
  spelling is the lowercase word.
- `EndpointPayload(note)` and `WayEndpointPayload(way, note)`.
- `endpoint_events(aggregate_type, *, stated, corrected, voided, payload)`,
  which builds and registers the three specs from **explicit** type
  strings. Playthrough's six keep their recorded names
  (`library.playthrough.started`, `.start_corrected`, `.start_voided`, …).

A way endpoint's payload `Literal` is the endpoint's own subset, so a
device event naming `refunded` fails validation even after #721 widens
`EndWay`.

### Projector

`Projector` gains three handlers' worth of help, keyed by the descriptor:
`stated` amends marker = `recorded_at`, `when` = `effective_time`, note and
way; `corrected` amends `when`, note and way, never the marker; `voided`
amends all five to null or `""`. Playthrough's projector swaps its six
hand-written endpoint handlers for these; its other handlers are
untouched.

### Reads

`games/reads/endpoints.py` takes `StatedEndpoint` (gaining `way: EndWay |
None`) and `stated(row, endpoint) -> StatedEndpoint | None`.
`games/reads/playthrough_endpoints.py` keeps `stated_start` and
`stated_completion` as one-line calls, because ten call sites read better
naming the endpoint than passing a descriptor.

### Commands

`games/commands/endpoint.py` holds the three build skeletons as functions
over the descriptor, not as dataclass bases: a base would move each
command's fields into a shared name, and a command's fields are its
idempotency fingerprint. Each aggregate's commands keep their own fields
(`playthrough_id`, `device_id`) and `CommandName`, and call:

- `state_endpoint(row, endpoint, statement)`: refuses a stated endpoint
  (sentence names correcting it), else the `stated` event.
- `correct_endpoint(row, endpoint, statement)`: refuses an unstated one
  ahead of any comparison, answers `Unchanged` for the statement the row
  holds, else the `corrected` event.
- `void_endpoint(row, endpoint)`: `Unchanged` where nothing is stated,
  else the `voided` event.

Each takes the aggregate's sentences, and the aggregate calls its own
rules around them — playthrough's reversed-endpoints refusal and its
removed-run and removed-game refusals stay in `games/commands/playthrough.py`,
in the order they run today. `ActStatement(when, note)` moves to
`games/commands/endpoint.py` unchanged, and `WayActStatement(when, way,
note)` sits beside it. They stay two types because a `NamedTuple`
fingerprints as an array: a third field, even `None`, would change every
playthrough statement's fingerprint (a test pins one recorded
fingerprint).

### Writes and form

`EndpointStatement` in `games/writes/playthrough.py` generalizes to
`games/writes/endpoint.py` as `restate_endpoint(actor, row, endpoint,
statement, commands)`: nothing stated and none wanted is nothing; none
stated, one wanted is the act; one stated, none wanted is the void; both,
and they differ, is the correction.

`EndpointFieldset` (`games/endpoint_form.py`) is the form half: a way
select whose first choice is "not ended" (or a has-happened checkbox for an
endpoint without ways), a `TemporalWidget`, and a note, cleaning to
`ActStatement | None`. The playthrough form adopts it only where the
rendered page stays the same; `make render-pages` on member 1 shows no
difference, or the swap is left for later.

### Filter

`endpoint_filter_fields(endpoint, *, label)` in `games/filters.py` returns
the `FilterField`s an endpoint offers: its interval through
`temporal_interval_handler(when, lower, upper)`, whether it is stated
through `bool_isnull_handler(marker, invert=True)`, and its way as a
choice. `PlaythroughFilter` spreads it for `started`/`completed` and
`is_started`/`is_completed` under their current keys, so no saved preset
changes.

### Proof for member 1

Every existing playthrough test passes untouched; the replay gate is
clean; `make render-pages` shows no difference; a fingerprint test pins
that a playthrough command posted before the refactor replays as a repeat
after it.

## Member 2: device access end

### Events

| Event | Payload |
|---|---|
| `library.device.access_ended` | `way`, `note` |
| `library.device.access_end_corrected` | `way`, `note` |
| `library.device.access_end_voided` | empty |

Dated by `effective_time`. `way` admits the five device ways.

### Projection

`Device` gains `access_ended` (`TemporalValueField`), `access_ended_lower`
and `access_ended_upper` (generated), `access_ended_at` (marker),
`access_ended_note` and `access_end_way`, with the endpoint's constraints.
One schema migration; no conversion, since every existing device reads as
held.

### Commands

In `games/commands/device.py`: `EndDeviceAccess(device_id, statement)`,
`CorrectDeviceAccessEnd(device_id, statement)`,
`VoidDeviceAccessEnd(device_id)`, each with its own `CommandName`. The
first two refuse a removed device; `VoidDeviceAccessEnd` answers
`Unchanged` ahead of that refusal, as the playthrough voids do. A way is
required for the act and the correction.

### Write path and form

`restate_device` in `games/writes/device.py` dispatches `DescribeDevice`,
then the endpoint restate, under one `correlation_id` and one
`answered("device")`. `DeviceForm` hosts an `EndpointFieldset` labelled
"Access": "Held" first, then Sold, Lost, Given away, Broken, Stolen; the
day and note show once a way is chosen. Add Device may state an end at
creation (a device recorded after it was sold): `CreateDevice` then the
act, one correlation. `POST /api/devices/` states no end.

### Reads

- **Picker.** `/api/devices/search` and the forms' option resolvers keep
  offering an ended device, with its label `"Name · Sold"` and
  `data.access_ended` set; with an empty box, held devices lead, then
  ended ones, each group in today's order.
- **Default device.** The settings forms offer held devices only.
  `UserLibraryPreferences.default_device` answers `None` for an ended
  device and keeps `default_device_id`, so a void restores the default.
  Its `clean()` refuses an ended device.
- **No refusal** on a session or record naming an ended device, whatever
  its day: the player states both facts, and #1157 counts sessions by
  their own day.

### Devices list

- An **Access** column (`key="access"`), shown by default: "Held", or the
  way and the day at its precision ("Sold · May 2021", "Lost", no day).
- `DeviceFilter` spreads `endpoint_filter_fields(DEVICE_ACCESS_END,
  label="Access ended")` as `access_ended`, `is_access_ended` and
  `access_end_way`; `QUICK_FACETS["devices"]` gains the way (none reads
  "Held") and the day.
- A sort key `access_ended` on `access_ended_lower`, nulls last.
- The bare list shows every device, held and ended.

### Proof for member 2

Command tests (every refusal, `Unchanged`, correction of way alone),
projector and replay gate (the three events join
`tests/test_projection_replay_gate.py`), restate helper cases, picker
label and order, default device, the list column, facets and sort, and one
e2e: Edit a device to Sold in a month, see the column, set it back to
Held.

## What this design forecloses

- **An endpoint with its own extra fact** (a sale price on `sold`) needs a
  payload subtype and a correction that carries it; the skeleton functions
  take the payload from the caller, so the cost is one type, not a fork.
- **Two concurrent ends of one device** cannot be stated; a device held,
  sold, bought back and sold again states one end at a time, and the
  second sale overwrites the first through a correction. Buying back is
  a void today; a real re-acquisition waits for an acquired endpoint.
- **A way whose meaning differs by aggregate** is one `EndWay` word read
  in two places. #721 must not reuse a word with a different meaning.

## Not in this issue, filed

- A bulk tray act `device.end_access` on the Devices list.
- A sale price on a `sold` end.
- A device's acquired endpoint (`access_started`), symmetric with
  `LibraryEntry`'s acquired date.

## Comments to post

- **#721**: build on the primitive; add `returned`, `expired`,
  `revoked`, `refunded` to `EndWay`; "formerly owned" reads the marker.
- **#727**: a refund may end access through #721's act; its own date may
  use the primitive.
- **#1157**: the device split's rule above.
- **#601**: the primitive exists, and which issues build on it.
