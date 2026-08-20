# Session and play-history UUID primary keys

This record explains the constraints behind using UUIDv7 as the primary key for
`Session`, `PlayEvent`, and `GameStatusChange`. It follows the
[catalog primary-key promotion](2026-08-19-issue-646-catalog-uuid-primary-key-design.md)
and the boundaries established by the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md).

All three models already have populated, unique UUIDv7 columns created by
ID-03/#641. ID-12/#848 promotes those values without minting replacements:
the former `uuid` value becomes the row's `id`, and the legacy integer `id`
ceases to exist. No alias or integer-to-UUID redirect map remains.

## Scope and identity contract

After the cutover:

- `Session.id`, `PlayEvent.id`, and `GameStatusChange.id` are
  `UUIDv7Field(primary_key=True, editable=False)` fields. There is no separate
  `uuid` field and no redundant unique constraint beside the primary key.
- The existing UUID value of every row is preserved exactly. Row ownership,
  ordering, timestamps, generated fields, and relationships do not change.
- Exactly the three corresponding entries disappear from
  `RESIDUAL_INTEGER_PRIMARY_KEYS`. The rest of the identity audit inventory is
  unchanged.
- HTML and Ninja interfaces accept UUIDv7 identifiers only. Legacy integers,
  malformed UUIDs, and UUIDs of other versions do not resolve.
- Library-owned objects continue to be selected through `owned_or_404`; an
  identifier belonging to another library remains a 404.

Purchase, Device, FilterPreset, slug canonicalization, filters, saved presets,
statistics, custom elements, TypeScript, and unrelated anonymizer behavior are
outside this slice. Device identities and all device-valued request or response
fields remain integers until ID-14/#850.

## PostgreSQL and Django migration constraints

The migration is
`games/migrations/0014_session_playhistory_uuid_primary_key.py`, following
`0013_catalog_uuid_primary_key`. It uses `SeparateDatabaseAndState` for the same
historical-state safety reason as the catalog promotion:

- State operations remove integer `id` and UUID `uuid`, then add
  `id = UUIDv7Field(primary_key=True, editable=False, serialize=False)` for each
  model.
- State uses `RemoveField` plus `AddField`, never `RenameField`. A state-level
  rename is the wrong abstraction for an identity promotion and risks mutating
  historical relation state during reverse/forward migration-executor cycles.
- A `RunPython` operation owns the PostgreSQL DDL and runs after the state
  operations, so the runtime migration state already describes the final model
  contract.

For each of `games_session`, `games_playevent`, and
`games_gamestatuschange`, the database operation drops the integer primary key
and column, renames `uuid` to `id`, adds the UUID primary key, and removes the
now-redundant UUID unique constraint. It records and reconciles the row count
for every table. The rename preserves each existing UUID, its `uuid_v7` domain,
and its database default. Tests additionally prove the old integer column and
separate UUID column are absent, the version constraint and database default
remain effective, and duplicate or wrong-version identities are rejected.

Unrelated indexes and every outbound foreign key must survive. In particular:

- `Session.game`, `PlayEvent.game`, and `GameStatusChange.game` continue to
  reference `Game.id`.
- `Session.device` continues to reference `Device.uuid` during the mixed
  ID-12-to-ID-14 window.
- The session timestamp index and the ordinary foreign-key indexes remain
  present.

`sqlmigrate` is not sufficient evidence for custom Python-owned DDL: it does not
execute the migration against the live schema or prove the resulting constraint
graph. The migration must be applied with `make migrate` against PostgreSQL.

### Why there is no relation detachment

The catalog promotion had to detach foreign keys that targeted `Game.uuid` and
`Platform.uuid`: PostgreSQL would not drop either redundant unique constraint
while those foreign keys depended on its index.

No foreign key targets `Session.uuid`, `PlayEvent.uuid`, or
`GameStatusChange.uuid`. The relations on these models are outbound and target
`Game.id` or `Device.uuid`; changing the owning row's primary key does not
change those foreign-key columns or their target indexes. The old UUID unique
constraints therefore have no dependants to detach, and the migration must not
drop and recreate unrelated foreign keys.

### Why there is no through-table conversion

The catalog wave converted `games_purchase_games.game_id` because that
auto-created through table referenced the integer `Game.id` being destroyed.
There is no many-to-many or explicit through table whose foreign key points at
`Session`, `PlayEvent`, or `GameStatusChange`. This wave consequently has no
through column to backfill, no pair-uniqueness constraint to rebuild, and no
through-table index to restore.

These absences are part of the design, not omitted catalog steps: introducing
relation detachment or through-table conversion here would expand the mutation
surface without protecting any dependency.

## Reverse behavior

Forward migration destroys the integer-to-UUID mapping. Reconstructing integer
values would invent identities that only resemble the originals, so populated
rollback is unsupported.

Reverse first checks all three tables together. If any contains a row, it raises
with guidance to restore a backup taken before the migration, before performing
any schema mutation. When all three are empty, reverse restores the earlier
structural shape: a bigint identity primary key plus a separate unique UUIDv7
column with its database default. This supports migration-graph traversal and a
reverse/reapply cycle in one `MigrationExecutor` without claiming that deployed
data is reversible.

## Runtime identity surfaces

### HTML routes

The nine routes whose object identity changes use the registered `uuidv7`
converter:

| Model | Routes |
| --- | --- |
| `PlayEvent` | edit, delete |
| `Session` | clone from an existing session, edit, finish, reset, delete |
| `GameStatusChange` | edit, delete |

Their view parameters are typed as `UUID`. The default integer sentinel on
`delete_session` is removed. Valid UUIDv7 values reverse and resolve; integers
and UUIDv4 values do not. There are no redirect routes because the mapping from
an old integer to its UUID no longer exists.

The converter swap does not decide canonical slug-plus-UUID URL structure.
That policy remains with ID-15/#647; this slice only makes the existing nine
bare-identifier routes usable after their models' primary keys change.

### Ninja API

Every active identity-bearing path parameter for Session and PlayEvent uses
the shared strict `UUIDv7` type:

- PlayEvent GET, PATCH, and DELETE paths.
- Session GET, general PATCH, and device PATCH paths.

`PlayEventOut.id` and `SessionOut.id` also use `UUIDv7`, producing UUID strings
on the wire. `SessionDeviceUpdate.device_id` remains integer-valued because
`Device` has not been promoted. Boundary validation rejects integer and UUIDv4
path values before an ORM lookup; valid UUIDv7 values continue through
library-scoped `owned_or_404` queries.

### Session cloning

Django does not apply a field default merely because a loaded instance's
primary key is cleared. Cloning must therefore assign a fresh UUIDv7 primary
key explicitly before saving. The clone keeps the established reset behavior
for timestamps, time zones, and note content, and both source lookup and saved
row remain scoped to the caller's library.

## Fixture and sample-data contract

The committed fixture adopts Django's promoted-identity representation:

- Every `games.session` and `games.playevent` record moves its former
  `fields.uuid` value to `pk` and removes `fields.uuid`.
- Relationship values are unchanged. They already name the identity required
  by the target field: catalog primary keys for `game`, and `Device.uuid` for
  `Session.device`.
- The fixture has no `games.gamestatuschange` records, so no corresponding row
  transform is needed.

The transformation is mechanical and retains record ordering and all unrelated
fields. YAML is recompressed with deterministic gzip metadata so repeated
generation remains byte-stable.

No production change is expected in `load_sample_data` or `anonymize_sample`.
The loader already treats fixture `pk` as the default relationship identity,
and the anonymizer's identity writer already selects `id` when a model's
primary key is a `UUIDv7Field` and `uuid` otherwise. Tests must prove that
assumption through fixture-shape validation, deterministic generation, loading
the committed sample, and anonymize/load round trips rather than accepting it
from inspection alone.

## Verification sequence

Behavior changes follow test-driven development:

1. Add focused migration and identity tests and observe their pre-change
   failures. Prove all former UUIDs become primary keys, row counts and
   relationships survive, legacy columns disappear, UUIDv7 database defaults
   and constraints remain correct, unrelated indexes and outbound foreign keys
   remain present and enforced, empty reverse succeeds, and populated reverse
   fails before mutation with backup guidance. Exercise reverse and reapply
   through one migration executor.
2. Add route, view, API, isolation, and clone tests and observe the integer
   contract fail. Cover all nine HTML routes, all six Ninja paths, UUID-string
   response IDs, fresh clone identity, integer and UUIDv4 rejection, and
   representative cross-library 404s.
3. Add fixture-shape, deterministic-output, committed-sample-load, and
   anonymize/load round-trip coverage before transforming the fixture.
4. Run the focused migration, identity, route, API, and fixture suites.
5. Apply the migration to real PostgreSQL with `make migrate`, then run
   `make audit-uuid-identity` and `make check-migrations`.
6. Run the full `make check` gate with the Makefile's unchanged default
   `PYTEST_WORKERS`.

The cutover is complete only when the model declarations, PostgreSQL schema,
HTML resolver, Ninja schemas, ownership behavior, fixture representation, and
identity audit all describe the same UUIDv7-only identities.

## Documentation handoff

After implementation, update the UUID cutover wave plan with the delivered
ID-12 behavior, rollback policy, route ownership, and lessons inherited from
#646. Record on #647 that #848 necessarily converted the nine bare UUID routes,
while slug-plus-UUID canonicalization remains in #647's scope.
