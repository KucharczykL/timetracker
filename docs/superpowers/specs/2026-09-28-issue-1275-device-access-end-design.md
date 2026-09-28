# A device's access ends, and the stated endpoint beneath it

Issue: [#1275](https://github.com/KucharczykL/timetracker/issues/1275).
After: [The Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md).
Charter: [Bounded event sourcing](2026-08-09-timetracker-overhaul-design.md#bounded-event-sourcing),
[LibraryEntry](2026-08-09-timetracker-overhaul-design.md#libraryentry),
[Naming](../../event-retention.md#naming).

Decided with the user on 2026-09-28.

## Purpose

A player sells a console, loses a handheld, gives a phone away. Removal is
the wrong tool for any of these: removal takes a row out of the library,
and a sold device is still history — its sessions and records name it.
This issue lets a library state that its access to a device **ended**, in
one of five ways, on a day at any precision, with a note; correct that
statement; and take it back when it was recorded in error.

The shape is not new. A playthrough's start and completion already are
exactly this: a day stated as a `TemporalValue`, two generated bound
columns, a record marker, a note, and a `_corrected` and `_voided` event
beside the act (#681, #1010, #1256). The device end is the third copy; the
charter's `LibraryEntry` "acquired date and optional access-ended date"
(#721) are the fourth and fifth, and #727's refund may be a sixth. So this
issue first extracts the shape into one primitive, moves the playthrough
onto it, and then builds the device end as its second consumer.

## Delivery

One `gh stack`, two members, merged atomically:

1. **The stated-endpoint primitive**, with playthrough start and
   completion moved onto it. No behaviour changes; every recorded event
   type, command name, command field, column, filter key and rendered page
   keeps its spelling.
2. **Device access end**, built on the primitive.

Member 1 could land alone, but its interface is shaped by two consumers;
member 2 is the second, so they review and land together.

## Decisions

| Question (from the issue) | Answer |
|---|---|
| One act or one per way? | One act, carrying a `way` word. A new way is one enum value and one CHECK widening, not an event family. |
| Verb | `access_ended`, the charter's word for `LibraryEntry`, so both aggregates speak one verb. |
| Ways | `sold`, `lost`, `given_away`, `broken`, `stolen`. |
| A day, at what precision? | `effective_time`, a `TemporalValue` at any precision the grammar knows, null for an unknown day — as playthrough endpoints. (Purchases' dates are plain `DateField`s, not the precedent the issue named.) |
| A note? | Yes; the empty string is no note. |
| Offered in the session/record device picker? | Yes, marked with its way, after held devices when the box is empty. Back-dating a session on a sold device is ordinary. |
| Offered as the default device? | No. |
| How the Devices list shows it | An Access column and quick facets; the bare list still shows every device. |
| Counts in device totals after the act? | No figure exists yet. The rule, recorded on #1157: a device split counts every session on its own day, whatever the device's access. |
| Undo | A void, as #1256, and only for a record made in error: an end of access is a fact and a void is a retraction, two verbs ([Naming](../../event-retention.md#naming)). |
| Where it is stated | The Device Add and Edit forms. No new route, no row-menu item, no bulk act yet. |

## Member 1: the stated-endpoint primitive

### What an endpoint is

An endpoint is one act a projection row states at most once at a time: it
happened (record marker set), on a day or on none (the stated column), with
a note, and — for an endpoint that has ways — in one way. It can be stated,
corrected (day, note, way; the marker keeps the instant the act was first
recorded), and voided (every column back to what a row holds before any
act).

### The descriptor

`games/endpoints.py` declares `Endpoint`, a frozen value naming one
endpoint on one projection model:

- `model`, and the column names: `when`, `lower`, `upper`, `marker`,
  `note`, and `way` or none;
- `stated`, `corrected`, `voided`: its three `EventSpec`s, and `family`,
  the three together, which `games/bulk_playthrough_acts.py` reads today
  as hand-built tuples;
- `ways`: the admitted `EndWay` members, empty for an endpoint without
  ways.

Playthrough declares `PLAYTHROUGH_START` (`started`, `started_lower`,
`started_upper`, `start_recorded_at`, `start_note`) and
`PLAYTHROUGH_COMPLETION`. Device declares `DEVICE_ACCESS_END`. A registry
lists every endpoint, for the system check and the replay gate.

### Columns stay declared by hand

Each model spells its columns in its class body through small field
factories (`endpoint_when()`, `endpoint_bound(when, "lower")`,
`endpoint_marker()`, `endpoint_note()`, `endpoint_way(ways)`, which sets
`choices` from the ways so the set facet and the builder read them), so mypy and
django-stubs see every field and the migration autodetector needs no
trick. A class decorator or `locals()` injection would hide the fields
from both; that cost is refused. The factories must build exactly the
fields Playthrough holds today: member 1's proof includes
`makemigrations --check`.

`endpoint_constraints(endpoint)` returns `()` for an endpoint without
ways, so Playthrough gains no constraint and no migration. For a way
endpoint it returns two CHECKs: the way is one of the endpoint's words or
`""`, and the way is `""` exactly where the marker is null. Both are
superset rules — no command states a row either refuses — so they back
the command rather than replace it.

A new system check, `games.E014`, refuses a registered endpoint whose
model lacks a named column, whose bound columns are not `GeneratedField`s
whose expression is `TemporalLowerBound`/`TemporalUpperBound` over `when`,
or whose real `Meta.constraints` lacks the endpoint's constraints (the
lesson of `games.E012`: an abstract `Meta` is shadowed).

### Events

`games/events/endpoint.py` holds:

- `EndWay`, a `StrEnum` of every way any endpoint admits; recorded spelling
  is the lowercase word.
- `EndpointPayload(note)`, which playthrough's specs keep.
- `endpoint_events(aggregate_type, *, stated, corrected, voided,
  payload, voided_payload)`, which builds and registers the three specs
  from **explicit** type strings. Playthrough's six keep their names and
  module constants (`PLAYTHROUGH_STARTED`, …).

A way endpoint declares its own payload `TypedDict` whose `way` is a
`Literal` of its own subset, so a device event naming `refunded` fails
validation after #721 widens `EndWay`.

### Projector

`Projector` gains three helpers keyed by the descriptor: `stated` amends
the marker to `recorded_at`, `when` to `effective_time`, the note and the
way; `corrected` amends `when`, the note and the way, never the marker;
`voided` amends all of them to null or `""`. Playthrough's projector swaps
its six endpoint handlers for these; no other writer touches those
columns (the status side effect goes through `record_facts`).

### Reads

`games/reads/endpoints.py` takes `StatedEndpoint`, which gains `way:
EndWay | None`, and `stated(row, endpoint) -> StatedEndpoint | None`.
`stated_start` and `stated_completion` stay in
`games/reads/playthrough_endpoints.py` as one-line calls; ten call sites
read better naming the endpoint.

### Commands

`games/commands/endpoint.py` holds three build skeletons as functions over
the descriptor. Each command keeps its own class, fields, `CommandName`
and resolve; the skeleton takes the resolved row, the statement, the
aggregate's sentences, and one `before_event` hook, and returns the events
or `Unchanged`:

- `state_endpoint`: where the endpoint is stated, the identical statement
  is `Unchanged` and any other is refused (the sentence points to
  correcting); then `before_event`; then the `stated` event.
- `correct_endpoint`: an unstated endpoint is refused ahead of any
  comparison; the identical statement is `Unchanged`; then
  `before_event`; then the `corrected` event.
- `void_endpoint`: an unstated endpoint is `Unchanged`; then
  `before_event`; then the `voided` event.

This reproduces today's order exactly (checked against all six
playthrough commands). Playthrough's state and correct
commands resolve through `_live_run` before the skeleton (removed run and
removed game refused first) and pass the reversed-endpoints refusal as
`before_event`; its voids resolve through `library_playthrough` and pass
the two removal refusals as `before_event`, after the `Unchanged`.

`CreatePlaythrough` has no row to compare and keeps building its endpoint
events by hand, now through the descriptor's `stated` spec. `record_run`'s
adopt branch, `games/writes/playthrough_endpoints.py` and the bulk acts in
`games/bulk_playthrough_acts.py` reach the skeleton only through the six
commands, so they are unaffected.

Functions rather than dataclass bases, because each command's fields are
its idempotency fingerprint (`canonical_command_input` encodes the
dataclass's fields by name), and the commands name their row differently
(`playthrough_id`, `device_id`). `ActStatement(when, note)` moves to
`games/commands/endpoint.py` unchanged and stays importable from
`games.commands.playthrough`; `WayActStatement(when, way, note)` sits
beside it. They stay two types because a `NamedTuple` encodes as an array,
so a third field would change the fingerprint of every `CreatePlaythrough`
that states an endpoint. Member 1 adds a test pinning one recorded
fingerprint for each playthrough endpoint command and for
`CreatePlaythrough`.

### Writes

`games/writes/endpoint.py` holds the pure decision
`endpoint_move(stated, wanted) -> EndpointMove`: nothing stated and none
wanted is nothing; none stated and one wanted is the act; one stated and
none wanted is the void; both is the correction. It never compares values:
the read is taken before dispatch's lock, so equality is the command's
`Unchanged` under the lock, and a racer's correction between the read and
the dispatch is overwritten by this person's statement rather than
silently kept.

What "none wanted" means is the caller's. Playthrough's edit never voids —
a blank field restates the act without a day, and a correction carries
the note the endpoint already states — so `games/writes/playthrough.py`
keeps `_state_endpoint`, its early return, its note carry and
`_statement_order`; past the early return it calls `endpoint_move`, which
then answers only the act or the correction, as the inline choice does
today. The device form states the whole endpoint, so its
write passes the form's statement straight through.

No shared form component in this issue: the playthrough form has no note
field and states endpoints as two day fields, so a fieldset would have one
consumer. The device form builds its three fields itself; #721 extracts
the fieldset when it has a second consumer.

### Filter

`endpoint_filter_fields(endpoint, *, interval_label, stated_label,
way_label)` in `games/filters.py` returns an `EndpointFilterFields`
named tuple — `interval` (`temporal_interval_handler(when, lower,
upper)`, `metadata_lookup=lower`), `stated` (`bool_isnull_handler(marker,
invert=True)`), and `way` (a choice, or none). Each filter class still
declares its dataclass attributes and places the entries into its own
`fields` mapping in its own order, so `PlaythroughFilter` keeps `started`,
`completed`, `is_started`, `is_completed` in today's order under today's
labels, and no preset or builder page changes.

### Proof for member 1

Every existing playthrough test passes untouched; the replay gate is
clean; `makemigrations --check` finds nothing; `manage.py check` runs
`games.E014` over both playthrough endpoints, and a test pins
`endpoint_constraints` to `()` for each; `make render-pages` at both
commits on one database shows no difference; the new fingerprint test
passes before and after the refactor.

## Member 2: device access end

### Events

| Event | Payload |
|---|---|
| `library.device.access_ended` | `way`, `note` |
| `library.device.access_end_corrected` | `way`, `note` |
| `library.device.access_end_voided` | empty |

Dated by `effective_time`. `way` admits the five device ways.

### Projection

`Device` gains, by the naming rule for an act whose time a person states:
`access_ended` (`TemporalValueField`, the stated day),
`access_ended_lower` and `access_ended_upper` (generated),
`access_end_recorded_at` (the record marker), `access_end_note` and
`access_end_way` (`""` where no end is stated, as every string column
here), with the endpoint's two constraints. One schema migration; no
conversion, since every existing device reads as held.

### Commands

In `games/commands/device.py`, each with its own `CommandName`:

- `EndDeviceAccess(device_id, statement: WayActStatement)`,
  `CorrectDeviceAccessEnd(device_id, statement)`: resolve through
  `library_device_row` and refuse a removed device in this aggregate's own
  sentence ("That device was removed. Put it back before changing what it
  records."), not `library_device`'s picker sentence; then the skeleton.
- `VoidDeviceAccessEnd(device_id)`: resolve, the skeleton's `Unchanged`
  first, the removed-device refusal as `before_event`.
- A `check_way` beside `check_type` refuses a way outside the device's
  five with a sentence, ahead of the payload's own validation, which would
  answer a defect.
- `CreateDevice` gains `access_end: WayActStatement | None = None` and
  returns the creation and, where stated, the `access_ended` event in one
  build, so Add Device stays one dispatch under its `submission` key. The
  new field changes `CreateDevice`'s fingerprint; a submission retried
  across the deployment is refused as a reused key, which is accepted.

### Write path and form

`describe_device` in `games/writes/device.py` becomes `restate_device`,
which dispatches `DescribeDevice` and then the endpoint move
(`EndDeviceAccess`, `CorrectDeviceAccessEnd` or `VoidDeviceAccessEnd`),
under one `correlation_id`, each through `answered("device")`.

`DeviceForm` gains an Access select — "Held" first, then Sold, Lost,
Given away, Broken, Stolen — a `TemporalField` day and a note, cleaning to
`WayActStatement | None`. All three are `required=False`, and an absent or
empty Access cleans to Held, because `POST /api/devices/` binds the same
form with name, type and submission alone. Help text beside "Held" says it takes back a
recorded end; getting a device back is not yet stated (below).
`POST /api/devices/` states no end.

### Reads

- **Picker.** `/api/devices/search` and the forms' option resolvers keep
  offering an ended device. Its label stays its name, so the create row's
  exact-label match is unchanged. An option gains an optional `hint`,
  rendered as muted trailing text ("Sold") that no match reads. The type is
  hand-written on both sides, not generated: `NotRequired[str]` on
  `SearchSelectOption` (`common/components/search_select.py`), the Ninja
  `PickerOption` schema `search_devices` answers, `_option_row` for the
  server-rendered row, which carries it as `data-hint`, and in
  `ts/elements/search-select.ts` the interface, `buildRow`, and
  `optionFromRow`, which reads `data-hint` back into `hint` rather than
  into `data`. Pills show no hint. With an empty box, held devices lead,
  then ended ones, each group in today's order.
- **Default device.** `UserLibraryPreferences.default_device` answers
  `None` for an ended device and keeps `default_device_id`, so a void
  restores the default; `clean()` does not change, so a later save never
  trips on a kept id. Every reader of the property (the session form's
  initial, the API) therefore seeds no device. The settings page reads the
  stored device itself: it shows an ended default as the current value
  with its hint and help text ("Sold, so new sessions name no device;
  choose another"), offers only held devices beside it, and a save that
  keeps it posts it back unchanged, so opening the page never clears the
  kept id. The Devices count card's queryset is not narrowed.
  `PATCH /api/library/default-device` refuses a newly chosen ended device
  through `RowRefused`, 422 with a sentence and a toast.
- **No refusal** on a session or record naming an ended device, whatever
  its day: the player states both facts, and #1157 counts sessions by
  their own day.

### Devices list

- An **Access** column (`key="access"`), shown by default: "Held", or the
  way and the day at its precision ("Sold · May 2021", "Lost").
- `DeviceFilter` declares `access_ended`, `is_access_ended` and
  `access_end_way` and places `endpoint_filter_fields(DEVICE_ACCESS_END,
  …)` into `fields`. `QUICK_FACETS["devices"]` gains `is_access_ended`
  (bool, "Access ended") and `access_end_way` (set over the five ways),
  which need no widget work.
- A sort key `access_ended` on `access_ended_lower`, nulls last.
- The bare list shows every device, held and ended.

### Sample data

`anonymize_sample` offsets device events by zero today: offsets are keyed
per game through `game_id_by_aggregate`, which holds no device, and no
device fact carried a day. An `access_ended` event does. A `device_offsets`
map, seeded per device key before the keys are reassigned, replaces the
zero branch; the end's `recorded_at` then follows from the last dated day,
as other events' do, so a later `removed` inherits it and creation stays
at the fixed epoch. Projections are rebuilt on load, so no row is
rewritten. `tests/test_anonymize_sample.py` pins the offset and that
order.

### Proof for member 2

Command tests (every refusal, `Unchanged`, a correction of the way alone,
a foreign way, `CreateDevice` with an end); projector and replay gate (the
three events join `tests/test_projection_replay_gate.py`, through create
with an end, correct, void, remove); a test that no command path reaches
either CHECK; the move decision; `POST /api/devices/` still creating from
name and type alone; picker hint and order, including a row rebuilt from
the DOM; default device, the settings page with an ended default, and the
PATCH; the list column, facets and sort; the anonymizer; and one e2e:
Edit a device to Sold in a month, see the column, set it back to Held.

## What this design forecloses

- **Getting a device back.** A device sold and bought back, or lost and
  found, cannot be stated: a void says the end never happened, and a
  correction restates the same end. #721 adds `access restored` for
  `LibraryEntry`; the device gains the same fact in a follow-up, and until
  then one end at a time is all a device states.
- **An endpoint with its own extra fact** (a sale price on `sold`) needs
  its own payload and statement type; the skeletons take both from the
  caller, so the cost is types, not a fork.
- **A way whose meaning differs by aggregate** is one `EndWay` word read
  in two places. #721 must not reuse a word with another meaning.

## Not in this issue, filed

- Device access restored: the fact of getting a device back.
- A bulk tray act on the Devices list.
- A sale price on a `sold` end.
- A device's acquired endpoint, symmetric with `LibraryEntry`'s acquired
  date.

## Comments to post

- **#721**: build on the primitive; add `returned`, `expired`,
  `revoked`, `refunded` to `EndWay`; extract the fieldset; "formerly
  owned" reads the record marker.
- **#727**: a refund may end access through #721's act; its own date may
  use the primitive.
- **#1157**: the device split's rule above.
- **#601**: the primitive exists, and which issues build on it.
