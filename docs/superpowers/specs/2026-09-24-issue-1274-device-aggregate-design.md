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
  not state. It resolves a live device through `library_device`, whose
  sentence for a removed device already names Restore. It applies the same
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
mark. It stays a `ReferencedRow`, and its `pre_delete` receiver stays: a
shell or script that destroys a device an event names is refused, as
today. The projector never deletes, and the swap and purge do not reach
the guard.

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
resolution moves from `REQUIRED` to a third value, `PROJECTED`.

`REQUIRED` promises that a replay finds the row in a table the replay does
not write, and `require_resolvable_references` checks that promise against
the live table before the first event. For a projection the promise runs
the other way: the replay writes the row, so checking the live table would
refuse to rebuild a library whose device rows were lost, the one situation
a rebuild exists for. `EVIDENCE_ONLY` would be false as well: the session
and record projectors write `payload["device"]["id"]` into a RESTRICT
foreign key, so the row must exist when the swap commits.

`PROJECTED` states the truth: the stream that names the row also creates
it. A `ReferenceKind` that is `PROJECTED` names its creation event type
(`created_by`, here `library.device.created`), and `__post_init__` refuses
a `PROJECTED` kind without one and any other kind with one.

- `reconcile_references` checks a `PROJECTED` kind against the stream: an
  anti-join of the reference index to the library's events of the
  creation type under the referenced id. A stream naming a device it never
  created is refused before the first row, with the reconciliation's
  sentence, rather than at the swap's commit as a bare foreign-key
  violation the swap's sentence would send to a cross-library audit.
- `must_be_retained` answers as for `REQUIRED`: a row an event names is
  kept. Nothing in the application deletes one either way.
- `load_sample_data`'s validator accepts a `PROJECTED` reference where the
  fixture holds the creation event under that id, instead of a row.

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

`games.E009` and `games.E010` walk references out of projections, so they
do not see this one; `audit_library_ownership` already reports a default
device of another library. The reference kind's stream check keeps a
lost device from reaching the swap at all.

## Write paths

`games/writes/device.py` is the request-free half: `create_device`,
`describe_device`, `remove_device`, `restore_device`, each under
`answered("device")`, each taking `idempotency_key`, `correlation_id`
and `source_metadata` and answering `CommandResult`, as
`games/writes/playersession.py` does. `create_device` also answers the
created row, read back through `created_aggregate_id`.

- `DeviceForm` becomes a plain `Form` with `name`, `type` and a hidden
  `submission` UUID, the shape `HistoricalPlaytimeForm` took. Its
  `submission_key(act)` keys the dispatch, so a submit posted twice
  creates one device. Add and Edit validate it, call the write, and put a
  `CommandFailed` sentence on the form rather than a 500.
- The remove route becomes `confirm_and_apply` with the removal as its
  action and `UndoOffer` pointing at `restore_device`; the restore route's
  action is the restoration. Both keep their URLs.
- `POST /api/devices/` keeps answering a held name without a write. It
  validates `DeviceForm` and dispatches `create_device`, answering a
  refusal through `RowRefused` at 422 as before; `created_by_form` and its
  docstring become the platform's alone, since platforms remain
  conventional.
- The default-device setting is untouched.

## Conversion

Two migrations, as the session conversion took (schema, then data):

- `0014` alters the schema above: the key loses its database default,
  `created_at` loses `auto_now_add`, the identity constraint is added, the
  library relation's name moves to `+`.
- `0015` runs one data pass, `elidable=True` per
  [Squashing](../../migration-squash.md), with a `noop` reverse. Nothing
  follows it in that migration: a schema change after rows written under
  deferred foreign keys meets PostgreSQL's pending trigger events.

The pass lives in `games/backfill/device.py`, so `load_sample_data` runs
the same code: `convert_devices()` over every library, or
`convert_devices(library)` over one, in one transaction of its own that
nests where a caller holds one, then `require_replay_parity(libraries)`. It first reads every device's `type`, and refuses the
migration with a sentence naming each row whose type is not one of the
six, since the payload's `Literal` would otherwise refuse mid-transaction
without naming a row. Then, for each device row holding no
`library.device.created` event, oldest `created_at` first, it appends
through `idempotent_append`, one call per event, because each takes its
own `recorded_at`:

- `library.device.created` under the row's own id, `name` and `type` as
  stored, `recorded_at` the row's `created_at`;
- `library.device.removed` where `removed_at` is set, `recorded_at` the
  row's `removed_at`.

The actor is the library's owner (every library has one), each device
takes a correlation id of its own, and `source_metadata` is
`{"origin": "backfill", "issue": 1274}`. Keys are
`backfill:1274:device:{created,removed}:<device>`. Commands are not used:
a command refuses a blank name the table may hold, and the conversion
states what the table holds.

The row keeps its key, so every session, record, preference and recorded
reference keeps naming it. The events are appended after the session and
record events that already name those devices; the stream orders them by
sequence, and a replay's swap checks foreign keys at commit, so nothing
reads the order. It does rule out a future check that a reference follows
its creation in the stream; the stream check above compares sets, not
positions.

For each library it converted at least one row of, the pass then asks
`rebuild_projections` in check mode and refuses the migration on any
difference. It passes the live projection classes explicitly: the
migration's historical models do not subclass `ProjectionModel`, so
`projection_models()` over them is empty. A library it converted nothing
of is not replayed, so a fresh test database never runs the replay under
later code. A second pass appends nothing.

## Sample data

The committed fixture holds device rows and no device events.
`load_sample_data` loads it, runs the conversion pass, and only then
rebuilds: a rebuild before the conversion would swap the loaded rows out
for none. A fixture that already carries device events converts nothing,
so the call is a no-op for a regenerated fixture.

`anonymize_sample` stops dumping `games.Device`: the table is a projection,
and a regenerated fixture carries its events instead. Its event pass
treats a device event by its aggregate type:

- no day offset, since a device event carries no day, and `recorded_at`
  the fixed epoch the device rows already take, so the row's key, the
  event's instant and the identity audit's order agree;
- the aggregate id mapped through the Device replacements, the map the
  row and every recorded reference already use, and kept out of the
  fresh mint the other aggregates take;
- the anonymised device name written into `created` and `name_changed`
  payloads rather than blanked, so a replay reproduces the scrubbed rows.

The committed fixture cannot be regenerated here, since that reads the
deployment's database after it migrates. Until it is, the conversion in
`load_sample_data` stays, and `games/backfill/device.py` with it.
[Squashing](../../migration-squash.md) says so: the next squash that
elides `0015` removes both, after `make anonymize-sample` has written a
fixture carrying device events.

## Tests

`tests/devices.py` holds `create_device(library, name=..., type=...)`,
which dispatches `CreateDevice` as the library's owner; `e2e/` gets its
twin. Every `Device.objects.create` in `tests/` and `e2e/` goes through
it, and every direct `removed_at` write or `remove(device)` goes through
`remove_device`, so no test states a projection row the stream does not
hold.

New:

- `tests/test_device_command.py`: every refusal, `Unchanged`, one event
  per differing fact, a removed device refusing a description.
- `tests/test_device_projection.py`: each handler, and replay equality.
- `tests/test_device_conversion.py`: a converted library replays equal,
  removed devices convert removed, a type outside the six refuses by row,
  a second pass appends nothing, a session naming a converted device keeps
  naming it, a stream naming a device it never created is refused by the
  reconciliation.

Changed by design:

- `tests/test_event_references.py`: a shipped kind resolves at replay when
  it is `REQUIRED` or `PROJECTED`; the kind registry refuses a
  `PROJECTED` kind without `created_by`.
- `tests/test_retention.py`: `must_be_retained(device)` holds for a
  `PROJECTED` kind; the registered-kinds and cascade-guard cases keep
  Device, which stays a `ReferencedRow`.
- `tests/test_library_form_isolation.py`: `DeviceForm` is no ModelForm.
- `tests/test_anonymize_sample.py`: device names are read from `created`
  events, not from dumped rows.
- `tests/test_projection_replay_gate.py` emits every device event.
- `tests/test_projection_rebuild.py` pins seven projection models.
- `tests/test_removable_models.py` drops Device's builder.

## Docs

`docs/event-references.md` (the kind table and the third resolution),
`docs/event-retention.md`, `docs/library.md` (the default device),
`docs/migration-squash.md` (the transitional pass), the `ProjectionModel`
docstring, and `CLAUDE.md`'s models section.

## Proof

- `make verify-replay-parity` on a restored dump after migrating.
- `make render-pages` before and after on one database, migrated between
  the two. The seven filter-builder pages differ, in their field-comparison
  operands alone: an operand reaching from Game, Platform or Purchase through
  `library` to the library's devices (`library__devices__*`) is gone, and so is
  every `library__*` operand on Device. A projection's `library` is a scoping
  relation the operand walk never follows, and `library.devices` is no
  accessor any more; both kinds of operand compared a row with every device,
  or every row, of the library, which no filter asks. The Devices list
  differs by #1135.
- The full `make check`.

## Not in this issue

- Sold and lost (#1275).
- The selectable Devices list (#1135).
- A uniqueness rule on device names.
- A default device that names a removed device. Removing one leaves the
  preference as it is, as today, and the session form's live queryset
  drops the initial.
