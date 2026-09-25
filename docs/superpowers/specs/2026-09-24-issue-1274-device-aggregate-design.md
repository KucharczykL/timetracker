# The Device aggregate

Issue: [#1274](https://github.com/KucharczykL/timetracker/issues/1274).
Charter: [Bounded event sourcing](2026-08-09-timetracker-overhaul-design.md#bounded-event-sourcing).

## Purpose

A player buys, renames, sells and loses a device. Thus a device is player
history, and the charter puts it in the event-sourced boundary. This
issue records the facts that exist today. #1275 adds "sold" and "lost".

## Events

The aggregate type is `device`.

| Event | Payload |
|---|---|
| `library.device.created` | `name`, `type` |
| `library.device.name_changed` | `name` |
| `library.device.type_changed` | `type` |
| `library.device.removed` | empty |
| `library.device.restored` | empty |

`type` is one of the six values in `Device.DEVICE_TYPES`. The payload
accepts all text for `name`, because the table accepts it.

## Commands

`games/commands/device.py` has four commands:

- `CreateDevice` refuses a blank name, a name of more than 255
  characters, and an unknown type.
- `DescribeDevice` makes one event for each fact that changes. `None`
  states no fact. It refuses a removed device.
- `RemoveDevice` and `RestoreDevice` give `Unchanged` when the row
  already has that state.

Each refusal has a sentence for the person.

## Projection

`Device` is a `ProjectionModel`. Only the `Devices` projector writes it.
The event gives the key and `created_at`. The projector sets
`removed_at`. Device is not in `REMOVABLE_MODELS`. It stays a
`ReferencedRow`, thus a shell cannot destroy a device that an event
names.

## Reference kind

The `device` kind is `PROJECTED`. A replay does not look for the row in
the table, because the replay writes that table. The replay looks for the
`library.device.created` event in the same stream. Thus a rebuild can
repair a lost row. A stream that names a device without its creation
event stops before the replay starts.

## Default device

`UserLibraryPreferences.default_device` points to a projection row. This
is the only such exception. The swap writes the same keys again in one
transaction, and the foreign key is deferred. Thus the preference
continues to point to the device after a rebuild.

## Write paths

`games/writes/device.py` sends each command through `answered("device")`.
`DeviceForm` is a plain form with a `submission` key, thus a repeated
submit creates one device. The Add, Edit, remove and restore pages and
`POST /api/devices/` use these writes.

## Conversion

Migration `0014` changes the schema. Migration `0015` runs
`games/backfill/device.py` one time:

1. Stop if no device needs conversion.
2. Stop if a device has an unknown type. Show each row.
3. Stop if the code has columns that the database does not have.
4. For each device, append `created`, and `removed` if the device is
   removed. Use the same key and the same times.
5. Replay each library that changed. Stop if a table is different.

`load_sample_data` runs the same pass until you regenerate the fixture.
`anonymize_sample` writes device events, not device rows.

## Proof

- `make verify-replay-parity` is clean after the migration.
- `make render-pages` shows differences only on the Devices list and on
  the seven filter-builder pages. The builder pages lose the comparison
  operands that went through `library` to all devices.
- `make check` is green.
