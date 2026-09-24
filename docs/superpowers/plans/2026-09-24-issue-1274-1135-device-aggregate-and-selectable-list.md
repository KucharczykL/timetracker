# Device aggregate and selectable Devices list: implementation plan

**Goal:** Ship #1274 (Device as an event-sourced aggregate, existing rows
converted) and #1135 (the Devices list selectable, bulk Remove with Undo,
the Actions column retired) on one branch, #1274 first in the history.

**Specs:** read them first; every "why" lives there.

- [The Device aggregate](../specs/2026-09-24-issue-1274-device-aggregate-design.md)
- [Select devices and remove them in bulk](../specs/2026-09-24-issue-1135-devices-list-selectable-design.md)

## Global constraints

- Run everything through `make`; iterate with `make check-fast`; the gate is
  the full `make check`, e2e included.
- Python 3.14; complete-word identifiers; named compound types and PEP 695
  aliases for primitive roles.
- Every `CommandRejected` carries `sentence=`. Commands resolve rows only
  through `games/commands/scope.py`.
- No dispatch inside a transaction: a test that dispatches through a write
  wrapper needs `transaction=True`. Test fixtures that only need a device
  row call `append_command` inside `transaction.atomic()`, which nests.
- Code comments state intent, never history or issue numbers.
- Recorded vocabulary (event types, aggregate type, payload keys, command
  names) is frozen once merged.

## Task 1: The `PROJECTED` resolution

Files: `games/events/references.py`, `games/events/reconcile.py`,
`games/retention.py`, `games/management/commands/load_sample_data.py`,
`tests/test_event_references.py`, `tests/test_retention.py`,
`tests/test_reference_reconciliation.py`.

1. `Resolution.PROJECTED = "projected"`. `ReferenceKind` gains
   `created_by: EventTypeName | None = None`; `__post_init__` refuses a
   `PROJECTED` kind without it and any other kind with it. The `device` kind
   becomes `PROJECTED`, `created_by="library.device.created"` (a string: the
   event module imports this one).
2. `reconcile_references`: a `PROJECTED` kind is checked, and its gaps are the
   index rows of that kind with no `LibraryEvent` of `created_by` in the same
   library under `aggregate_id = referenced_id` (`~Exists`, an anti-join).
   `unresolved_among` takes the library for this case.
3. `must_be_retained`: `REQUIRED` and `PROJECTED` both retain.
4. `load_sample_data._validate_records`: a reference of a `PROJECTED` kind
   passes when the fixture holds a `games.libraryevent` of `created_by` under
   that aggregate id, or a row (the committed fixture).
5. Tests: kind registry refusals; a stream naming a device it never created
   is unresolved; the same stream with the creation resolves; shipped kinds
   are `REQUIRED` or `PROJECTED`.

## Task 2: Events, commands, projector, schema

Files: create `games/events/device.py`, `games/commands/device.py`,
`games/projectors/device.py`, `games/migrations/0014_device_projection.py`;
modify `games/events/dispatch.py` (`CommandName`), `games/projectors/__init__.py`,
`games/models.py` (`Device`, `ProjectionModel` docstring),
`games/removal.py` (drop Device), `tests/test_removable_models.py`.

1. Events: `DeviceTypeValue = Literal[...]` of the six stored values (pinned
   by a test against `Device.DEVICE_TYPES`), payloads `DeviceCreatedPayload`
   (`name: str`, `type`), `DeviceNameChangedPayload`, `DeviceTypeChangedPayload`,
   `DeviceMarkPayload`; five `EventSpec`s under aggregate `device`; constructors
   `device_created(name, type, device_id=None)` (mints `uuid.uuid7()`),
   `device_name_changed`, `device_type_changed`, `device_removed`,
   `device_restored`.
2. `CommandName.DEVICE_CREATE/DESCRIBE/REMOVE/RESTORE`.
3. Commands per the spec. Normalisation: strip `name` in `__post_init__`; `_check_name` (blank, over 255) and `_check_type` raise
   `CommandRejected` with sentences. `DescribeDevice` resolves with
   `library_device`; `RemoveDevice`/`RestoreDevice` with `library_device_row`.
4. Projector `Devices` (CURRENT_STATE): `created` → `project(Device, event,
   name=, type=, created_at=event.recorded_at)`; changes → `amend`; marks →
   `amend(removed_at=...)`.
5. Model: `class Device(ProjectionModel, ReferencedRow)`; id
   `UUIDv7Field(primary_key=True, editable=False, default=NOT_PROVIDED,
   db_default=NOT_PROVIDED)` as `PlayerSession`; drop the own `library` field;
   `created_at = DateTimeField(editable=False)`; `Meta.constraints =
   (library_identity_constraint(),)`. Keep `objects`.
6. `make makemigrations ARGS="games --name device_projection"`, reviewed.
7. Remove Device from `REMOVABLE_MODELS` and the test builders.
8. `make check-fast` to see the whole blast radius before Task 3.

## Task 3: Test helpers and the test suite

Files: create `tests/devices.py`, `e2e/devices.py`; modify every test that
creates or removes a device.

1. `create_device(library, name="…", type=Device.UNKNOWN) -> Device` and
   `remove_device_row(device)`: `append_command` of `CreateDevice` /
   `RemoveDevice` inside `transaction.atomic()`, as the library's owner, a
   fresh key and correlation id each.
2. Replace every `Device.objects.create(...)`, `Device(...)`-then-save,
   `remove(device)`, and `Device.objects...update(removed_at=...)` in
   `tests/` and `e2e/` with the helpers. `created_at` stated in a test becomes
   the event's instant only where the test reads it (freeze time or read the
   row back).
3. `tests/test_projection_rebuild.py` seven models;
   `tests/test_projection_replay_gate.py` emits all five device events
   (and its hard-coded count follows).
4. New `tests/test_device_command.py`, `tests/test_device_projection.py`.

## Task 4: Writes, forms, views, API

Files: create `games/writes/device.py`; modify `games/forms.py`
(`DeviceForm`), `games/views/device.py`, `games/api.py`,
`games/api_creation.py`, `tests/test_library_form_isolation.py`, view and
API tests.

1. Writes per the spec, subject `"device"`; `create_device` answers the
   created `Device`, read back through `created_aggregate_id`.
2. `DeviceForm(forms.Form)`: `name` (CharField, max 255, autofocus),
   `type` (ChoiceField over `Device.DEVICE_TYPES`, initial Unknown),
   `submission` (hidden UUID, initial `uuid.uuid7()`), `submission_key(act)`;
   `for_device(device)` initial helper for Edit.
3. Views: add/edit validate the form, call the write under
   `submission_key`, map `CommandFailed` to a form error; remove through
   `confirm_and_apply(action=...)` keeping the ConfirmPage details and the
   `UndoOffer`; restore through `restore_and_return(action=partial(restore_device ...))`.
4. `POST /api/devices/`: held name answered as before; else validate
   `DeviceForm` (raise `RowRefused(refusal_sentence(form))`), dispatch,
   answer 201.
5. `api_creation.py` docstrings become the platform's.

## Task 5: Conversion

Files: create `games/backfill/__init__.py`, `games/backfill/device.py`,
`games/migrations/0015_device_conversion.py`,
`tests/test_device_conversion.py`; modify `load_sample_data.py`,
`docs/migration-squash.md`.

1. `convert_devices(library=None) -> DeviceConversion`: refuse bad types by
   row (`DeviceConversionRefused`); for each unconverted row, oldest first,
   `idempotent_append` created (+ removed) with the spec's keys, actor,
   correlation id, metadata and `recorded_at`; answer the libraries touched.
2. `gate(libraries)`: `rebuild_projections(library, mode=CHECK,
   models=projection_models())` (live classes) must report no difference.
3. Migration 0015: `RunPython(convert_and_gate, noop, elidable=True)`,
   depends on 0014.
4. `load_sample_data`: conversion after deserialize, then the existing
   rebuild.
5. Tests per the spec (call the pass directly on rows written with the
   plain manager, which is what a deployment holds).

## Task 6: Sample anonymiser

Files: `games/management/commands/anonymize_sample.py`,
`tests/test_anonymize_sample.py`.

1. `games.Device` leaves `DUMP_LABELS`, stays in `IDENTITY_MODELS`.
2. Event pass: device events take offset zero, `recorded_at = FIXED_EPOCH`,
   aggregate id through `replacements_by_model[Device]`, excluded from
   `_group_replacements`; `created`/`name_changed` payload `name` is the
   scrubbed row name.
3. Tests read device names from `created` events.

## Task 7: The selectable Devices list (#1135)

Files: `games/bulk_removal.py`, create `games/reads/device_departures.py`,
`games/views/device_menu.py`; modify `games/views/device.py`,
`tests/test_bulk_removal.py`, create `tests/test_bulk_device_removal.py`,
`e2e/test_bulk_device_removal_e2e.py`.

1. `device_scope`, `device_resolution` (annotated `with_sessions`),
   `remove_one_device`, `restore_one_device`, `DEVICE_PREVIEW`,
   `REMOVE_DEVICE`, `DEVICE_GONE`.
2. `device_row_menu`.
3. View per the spec.
4. Tests per the spec; fix every test reading the Actions cells.

## Task 8: Docs and the gate

1. Docs per the spec's Docs section; `CLAUDE.md` models section gains Device.
2. `make render-pages` after, on the migrated dev database; attribute
   every differing file.
3. `make verify-replay-parity`.
4. Full `make check`.
