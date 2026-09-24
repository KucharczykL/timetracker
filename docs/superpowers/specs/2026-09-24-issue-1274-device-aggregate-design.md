# The Device aggregate

Issue: [#1274](https://github.com/KucharczykL/timetracker/issues/1274).
Blocks [#1135](https://github.com/KucharczykL/timetracker/issues/1135).
Charter: [Bounded event sourcing](2026-08-09-timetracker-overhaul-design.md#bounded-event-sourcing),
amended on 2026-09-24.

## Purpose

A device is something a player owns: bought, renamed, sold, lost, retired.
The charter moved Devices inside the event-sourced boundary. This issue
states what exists today as events: a device's creation, its name, its
type, its removal and its restoration. Aggregate type `device`; events
`library.device.*`; one projection table, `Device`, the table that exists
today, keeping every key.

Sold and lost are new facts and belong to #1275.

## Events

| Event | Payload |
|---|---|
| `library.device.created` | `name`, `type` |
| `library.device.name_changed` | `name` |
| `library.device.type_changed` | `type` |
| `library.device.removed` | empty |
| `library.device.restored` | empty |

A name and a type are two facts, so a change of each is its own event,
as `DescribePlaythrough` and `DescribeSession` state theirs. The whole
statement is not restated: one field changed is one event in the Audit
History, which is the reading a person asks for.

`name` is text. `type` is one of the six values `Device.DEVICE_TYPES`
stores, a `Literal` in the payload, so an unknown type is refused at
validation. The payload admits any text as `name`, including blank: the
database admits a superset of what the command admits, and the payload
admits what the table admits.

No event carries an `effective_time`. A device's facts are about the
library, not about a day of play.

## Commands

`CreateDevice(name, type)`, `DescribeDevice(device_id, name, type)`,
`RemoveDevice(device_id)` and `RestoreDevice(device_id)`, in
`games/commands/device.py`. Command names `library.device.create`,
`.describe`, `.remove`, `.restore`.

`__post_init__` strips `name`. Every stated value is normalised before
the fingerprint, so a restatement with other whitespace is one statement.

- `CreateDevice` refuses a blank name, a name longer than the column's 255
  characters, and a type outside the six, each with a sentence. It refuses
  no name the library already holds: the column states no rule of its own
  today, and the device picker's create row answers a held name before it
  dispatches (`POST /api/devices/`, below). It mints the aggregate id as a
  UUIDv7 in the event constructor, as `historicalplaytime_created` does.
- `DescribeDevice` states `name`, `type`, or both; `None` is a fact it does
  not state. It resolves a live device through `library_row`, so a removed
  device refuses with a sentence naming Restore. It applies the same
  refusals as the creation, then answers one event per differing fact, and
  `Unchanged` when nothing differs.
- `RemoveDevice` and `RestoreDevice` resolve through `library_device_row`
  (removed or not), answer `Unchanged` for the state the row holds, and
  otherwise append their event. Removal refuses nothing else: sessions and
  records naming a removed device keep naming it, as today, and the
  per-row confirmation says how many sessions do.

Every refusal is a `CommandRejected` with a sentence. A device another
library holds is `RowNotHeld`, through `Refusal`'s default.

## The projection

`Device` becomes a `ProjectionModel`:

- `id` is `UUIDv7Field(primary_key=True, default=NOT_PROVIDED,
  db_default=NOT_PROVIDED)`: the event's aggregate id, never a fresh one
  (`games.E004`, `games.E005`).
- `library` is the inherited foreign key. `related_name` moves from
  `devices` to `+`; nothing but migration 0001 names the old accessor.
- `created_at` is a plain `DateTimeField(editable=False)`, the creation
  event's `recorded_at` (`games.E002` refuses `auto_now_add`).
- `removed_at` is the projector's, the removal event's `recorded_at`,
  null while live.
- `Meta` states `library_identity_constraint()`.
- The manager stays `RemovableLibraryQuerySet`: `for_library()` is the
  live read every list, picker and form already calls.

Device leaves `REMOVABLE_MODELS` (and `tests/test_removable_models.py`'s
builders), as Playthrough and PlayerSession did: a command states its
mark. Device stops being a `ReferencedRow`, and its `pre_delete` receiver
goes: see the reference kind below.

`AUDITED_PROJECTION_REFERENCES` already lists `PlayerSession.device` and
`HistoricalPlaytime.device`, so the audit walk needs nothing new.

## The projector

`Devices`, family `CURRENT_STATE`, in `games/projectors/device.py`,
listed in `games/projectors/__init__.py` so the vocabulary registers at
app load. `created` projects the row with `name`, `type`, `created_at`
and a null `removed_at`. `name_changed` and `type_changed` amend their
column. `removed` and `restored` amend `removed_at`.

## The reference kind

The `device` reference kind stays registered: recorded session and record
payloads carry `{"kind": "device", ...}` and nothing upcasts them. Its
resolution moves from `REQUIRED` to `EVIDENCE_ONLY`.

`REQUIRED` promises that a replay finds the row in a table the replay does
not write, and `require_resolvable_references` checks that promise against
the live table before the first event. A projection makes the promise
backwards: the replay writes the row, so a library whose device rows were
lost could not be rebuilt, the one situation a rebuild exists for. That
is why a session's run and a run's tracked game are bare ids, not kinds
(`games/events/playersession.py`).

What `REQUIRED` protected stays protected, by the projection's own
guarantees:

- No path destroys a device row. The projector never deletes; the swap
  deletes and reinserts the same keys in one transaction; purge takes the
  events with the rows.
- A session or record naming a device the replay does not produce is
  refused at the swap's commit by the deferred foreign key
  (`SwapRefusedByReference`), which is how a session naming a run the
  replay lost is refused today.

The snapshot in each payload remains the evidence the durable-reference
rule asks for.

## The default device

`UserLibraryPreferences.default_device` is conventional data pointing at
a projection row, which `ProjectionModel`'s docstring forbids. It keeps
the foreign key, and the docstring names it as the one exception, for
these reasons:

- The swap reinserts the same keys inside one transaction, and every
  foreign key is `DEFERRABLE INITIALLY DEFERRED`, so the preference
  survives a rebuild.
- A replay that loses the device is refused at commit rather than
  silently nulling the preference, the same answer a projection
  reference gets.
- A default device is a library preference, which the charter keeps
  conventional (`PlayerLibraryPreferences`). Moving it to an event of its
  own would put a preference inside the boundary to satisfy a rule meant
  for projection tables.

## Write paths

`games/writes/device.py` is the request-free half: `create_device`,
`describe_device`, `remove_device`, `restore_device`, each under
`answered("device")`, each taking `idempotency_key`, `correlation_id`
and `source_metadata` and answering `CommandResult`, as
`games/writes/playersession.py` does. `create_device` also answers the
created row, read back through `created_aggregate_id`.

- `DeviceForm` becomes a plain `Form` with `name` and `type`, the shape
  `PlaythroughForm` took. Add and Edit validate it, call the write, and
  put a `CommandFailed` sentence on the form rather than a 500.
- The remove route becomes `confirm_and_apply` with the removal as its
  action and `UndoOffer` pointing at `restore_device`; the restore route's
  action is the restoration. Both keep their URLs.
- `POST /api/devices/` keeps answering a held name without a write. It
  validates `DeviceForm` and dispatches `create_device`; `created_by_form`
  stays for platforms, which remain conventional.
- The default-device setting is untouched.

## Conversion

Migration `0014` alters the schema above and runs one data pass,
`elidable=True` per [Squashing](../../migration-squash.md), with a
`noop` reverse. The pass lives in `games/backfill/device.py`, so
`load_sample_data` runs the same code.

For each device row holding no `library.device.created` event, oldest
`created_at` first, it appends through `idempotent_append`:

- `library.device.created` under the row's own id, `name` and `type` as
  stored, `recorded_at` the row's `created_at`;
- `library.device.removed` where `removed_at` is set, `recorded_at` the
  row's `removed_at`.

The actor is the library's owner, each device takes a correlation id of
its own, and `source_metadata` is `{"origin": "backfill", "issue": 1274}`.
Keys are `backfill:1274:device:{created,removed}:<device>`. Commands are
not used: a command refuses a blank name the table may hold, and the
conversion states what the table holds.

The row keeps its key, so every session, record, preference and recorded
reference keeps naming it. The pass then asks `rebuild_projections` in
check mode, over the projection models this migration's schema holds,
for each library it touched, and refuses the migration on any difference.
A second pass appends nothing.

## Sample data

The committed fixture holds device rows and no device events.
`load_sample_data` loads it, runs the conversion pass, and rebuilds, so
the sample converts exactly as a deployment does. `anonymize_sample`
stops dumping `games.Device`: the table is a projection, and a
regenerated fixture carries its events instead. The event pass maps a
device event's aggregate id through the device replacements, and writes
the anonymised device name into `created` and `name_changed` payloads
rather than blanking it, so a replay reproduces the scrubbed rows.

## Tests

`tests/devices.py` holds `create_device(library, name=..., type=...)`,
which dispatches `CreateDevice` as the library's owner; `e2e/` gets its
twin. Every `Device.objects.create` in `tests/` and `e2e/` goes through
it, and every direct `removed_at` write goes through `remove_device`, so
no test states a projection row the stream does not hold.

- `tests/test_device_command.py`: every refusal, `Unchanged`, one event
  per differing fact, a removed device refusing a description.
- `tests/test_device_projection.py`: each handler, and replay equality.
- `tests/test_device_conversion.py`: a converted library replays equal,
  removed devices convert removed, a second pass appends nothing, a
  session naming a converted device keeps naming it.
- `tests/test_projection_replay_gate.py` emits every device event.
- `tests/test_projection_rebuild.py` pins seven projection models.

## Proof

- `make verify-replay-parity` on a restored dump after migrating.
- `make render-pages` before and after on one database: no differing
  file. This issue changes no page's markup.
- The full `make check`.

## Not in this issue

- Sold and lost (#1275).
- The selectable Devices list (#1135).
- A uniqueness rule on device names.
