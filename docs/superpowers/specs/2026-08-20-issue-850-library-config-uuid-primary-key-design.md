# Library configuration UUID primary keys

Status: approved 2026-08-20. Issue: #850 (ID-14). Parent phase: #600.
Depends on ID-05/#643, ID-08/#846, ID-10/#645, and migrations through
`0015_purchase_uuid_primary_key`.

## Identity contract

`Device` and `FilterPreset` expose only
`id = UUIDv7Field(primary_key=True, editable=False)`. Their existing UUIDv7
values become the primary keys; no replacement identities are minted and the
integer-to-UUID mapping is destroyed. `Session.device` and
`UserLibraryPreferences.default_device` continue to use the same UUID-valued
columns, but target `Device.id` without transitional `to_field="uuid"`.

Every HTML route, Ninja schema, filter criterion, form option, and settings or
preset operation that carries one of these identities uses strict UUIDv7.
Legacy integers, malformed UUIDs, and other UUID versions are rejected at the
boundary. Library-scoped querysets remain authoritative for user isolation.

## Migration structure

Migration `0016_library_config_uuid_primary_key` uses
`SeparateDatabaseAndState`. State removes integer `id` and secondary `uuid`,
adds a UUIDv7 `id` primary key for each model, and removes `to_field` from the
two Device relations. State uses `RemoveField` plus `AddField`, never
`RenameField`, because renaming a referenced `to_field` mutates shared
historical relation state and corrupts reverse/reapply cycles.

The PostgreSQL operation first drops every foreign key targeting
`games_device`, then promotes both tables by dropping integer `id`, renaming
`uuid` to `id`, adding the primary key, and removing the redundant unique
constraint. It verifies row counts and recreates the two Device foreign keys
with Django-generated names. No through table or relation backfill exists in
this slice.

The migration proves that the Device library FK/index, FilterPreset library FK
and `(library, mode, name)` uniqueness, Session/default-device indexes, and all
referential constraints remain present and enforced. `sqlmigrate` is not
verification; the migration runs against PostgreSQL.

## Reverse and deployment behavior

Forward promotion destroys the integer identities, so populated rollback is
unsupported. Reverse locks both promoted tables in `ACCESS EXCLUSIVE` mode and
checks them together before mutation. If either has rows, reverse directs the
operator to restore a pre-migration backup. If both are empty, reverse restores
bigint identity primary keys, separate unique UUIDv7 columns, and the two
foreign keys targeting `Device.uuid`. Reverse/reapply must work in one
`MigrationExecutor` instance.

Deployment requires a database backup, `make audit-uuid-identity` before and
after migration, and the full `make check` gate. The audit drops the two ID-14
primary-key inventory entries but retains the six permanent residual rows;
follow-up #879 decides whether that inventory check remains useful.

## Runtime cleanup

`SessionFilter.device` becomes `UUIDMultiCriterion`, with direct `device_id`
lookups now that the FK attname is the canonical identity. The integer-only
`MultiCriterion`, its registry entries, and its tests are removed. The final
`seed_related_initial` call and helper are removed.

Device edit/delete routes, device search/session output, session-device PATCH,
and the default-device setting use UUIDv7. Preset list values and delete paths
also use UUIDv7. The select behavior replaces its dead numeric mode with an
explicit `empty_is_null` option so the UUID travels as a string while “No
device” sends JSON null.

Fixture Device/FilterPreset identities move from `fields.uuid` to `pk`, and
Session's Device relationship returns to `reference_field="pk"`. Generic
identity rewriting remains responsible for fixture/anonymizer references.
Scrubbed Device names use stable ordinals rather than embedding a UUID that is
subsequently rewritten.

FilterPreset JSON is preserved byte-for-byte. Per the cutover wave's recorded
zero-production-preset assumption, this slice does not introduce an integer
criterion remapper; stale external saved criteria continue through the existing
invalid-filter degradation path.

## Verification invariants

- Both tables have one non-null `uuid_v7` primary key with a database default
  and no redundant UUID unique constraint.
- Every row, scalar value, JSON value, Device reference, index, uniqueness
  rule, and ownership boundary survives promotion.
- Device and preset APIs serialize UUID strings and reject integer/non-v7
  identities before ORM lookup.
- Device criteria serialize and parse strict UUIDv7 values, and no integer set
  criterion implementation remains.
- Populated reverse fails before mutation; empty reverse and same-executor
  reverse/reapply restore the exact historical structure.
- The committed fixture and anonymize/load round trip use promoted primary-key
  representation deterministically.
