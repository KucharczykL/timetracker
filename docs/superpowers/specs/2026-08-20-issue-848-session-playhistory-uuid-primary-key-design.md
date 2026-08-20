# Session and play-history UUID primary keys

This record explains the constraints behind using UUIDv7 primary keys for
`Session`, `PlayEvent`, and `GameStatusChange`. It builds on the migration
lessons from the
[catalog primary-key promotion](2026-08-19-issue-646-catalog-uuid-primary-key-design.md).

## Identity contract

Each model exposes `id = UUIDv7Field(primary_key=True, editable=False)` and no
separate `uuid` field. Promotion preserves every existing UUID exactly; it does
not mint replacement identities. The legacy integer identifiers and their
integer-to-UUID mapping no longer exist.

Row ownership, ordering, timestamps, generated fields, and relationships are
unchanged. Other models' identities are outside this promotion.

## Migration structure

Migration `0014_session_playhistory_uuid_primary_key` follows the catalog
primary-key migration and uses `SeparateDatabaseAndState`:

- State operations remove integer `id` and UUID `uuid`, then add
  `id = UUIDv7Field(primary_key=True, editable=False, serialize=False)` for
  each model.
- State uses `RemoveField` plus `AddField`, never `RenameField`. A state-level
  rename can mutate shared historical relation state and make reverse/reapply
  cycles render earlier migrations against the wrong identity type.
- A following `RunPython` operation owns the PostgreSQL DDL after migration
  state already describes the promoted models.

For each table, the database operation records its row count, drops the integer
primary-key column, renames `uuid` to `id`, adds the UUID primary key, removes
the redundant UUID unique constraint, and verifies that the row count did not
change. Renaming the existing column preserves its `uuid_v7` domain, value,
version constraint, and database default.

`sqlmigrate` is not sufficient evidence for this transition because it does
not execute the Python-owned DDL against the live constraint graph. The
migration must be exercised against PostgreSQL, including reverse and reapply
through one `MigrationExecutor` instance.

### Relations and indexes

No foreign key targets the former `Session.uuid`, `PlayEvent.uuid`, or
`GameStatusChange.uuid` fields. Their relations are outbound and continue to
target `Game.id` or `Device.uuid`. The promotion therefore does not detach or
recreate foreign keys.

No many-to-many or explicit through table points at these identities, so there
is no through column to backfill and no through-table uniqueness constraint or
index to rebuild.

These absences are deliberate. Relation detachment or through-table conversion
would expand the mutation surface without protecting a dependency. The session
timestamp index, ordinary foreign-key indexes, and every outbound foreign-key
constraint remain present and enforced.

## Reverse behavior

Forward migration destroys the integer-to-UUID mapping. Reconstructing integer
values would invent identities that merely resemble the originals, so
populated rollback is unsupported.

Reverse acquires an `ACCESS EXCLUSIVE` lock on all three tables before checking
whether any contains data. If any table is populated, it raises with guidance
to restore a pre-migration backup before performing schema mutation. Locking
before the combined check prevents a concurrent insert from entering a later
table between validation and DDL.

When all three tables are empty, reverse restores the earlier structural shape:
a bigint identity primary key plus a separate unique UUIDv7 column with its
database default. This supports migration-graph traversal without claiming
that deployed data is reversible.

## Runtime identity boundaries

### HTML routes

The strict `uuidv7` converter applies to the identity-bearing routes affected
by the promotion:

| Model | Routes |
| --- | --- |
| `PlayEvent` | edit, delete |
| `Session` | clone, edit, finish, reset, delete |
| `GameStatusChange` | edit, delete |

Their view parameters are `UUID` values. Valid UUIDv7 identifiers reverse and
resolve; legacy integers, malformed UUIDs, and other UUID versions do not. No
integer redirect exists because the migration removes the mapping required to
construct one. Canonical slug policy is a separate concern.

### Ninja API

PlayEvent GET, PATCH, and DELETE paths and Session GET, general PATCH, and
device PATCH paths use the strict shared `UUIDv7` type. `PlayEventOut.id` and
`SessionOut.id` use the same type and serialize as UUID strings. This promotion
does not change device-valued request data.

Boundary validation occurs before ORM lookup. Valid identifiers still flow
through `owned_or_404` over a library-scoped queryset, so knowing another
library's UUID does not bypass isolation.

### Defaulted primary keys and Django object state

A UUID primary-key default is assigned before an unsaved model reaches the
database. Code must therefore use `instance._state.adding`, not
`instance.pk is None`, when distinguishing add forms from edit forms.

Cloning a loaded Session assigns a fresh UUIDv7 explicitly. Changing the
primary key does not reset the loaded instance's adding state, so the clone is
saved with `force_insert=True`. This prevents Django's update-first save path
from overwriting an existing Session if the generated UUID collides.

The clone retains the established timestamp, time-zone, and note resets. Its
source lookup remains library-scoped, and a primary-key collision fails without
changing the source or colliding row.

## Fixture and sample-data contract

Promoted fixture records store their identity in `pk`:

- `games.session` and `games.playevent` records move the former `fields.uuid`
  value to `pk` and omit `fields.uuid`.
- Relationship values, record order, and unrelated fields remain unchanged.
- A model with no committed sample rows requires no record transformation.

The fixture uses deterministic gzip metadata. Generic sample loading and
anonymization resolve a promoted UUID identity through the primary key and a
non-promoted UUID identity through its explicit UUID field; promotion requires
no model-specific production branch in either command.

## Invariants

The promotion is correct only while all of these remain true:

- The three `id` columns are non-null `uuid_v7` primary keys with database
  defaults and no redundant identity uniqueness constraint.
- Existing UUIDs, scalar values, relationships, indexes, and outbound foreign
  keys survive promotion exactly.
- Populated reverse fails before mutation; empty reverse and reverse/reapply
  remain structurally valid.
- Runtime boundaries reject integers and non-v7 UUIDs while library isolation
  remains authoritative.
- Session creation recognizes Django's adding state, and cloning always
  performs an unconditional insert.
- Fixture generation, loading, and anonymize/load round trips preserve the
  promoted identity representation deterministically.
