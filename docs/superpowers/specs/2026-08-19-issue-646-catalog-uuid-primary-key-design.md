# Catalog UUID primary keys

This record explains the constraints behind using UUIDv7 as the primary key for
`Game` and `Platform`. It complements the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md)
with details that are not evident from the final model declarations.

`Game.id` and `Platform.id` are UUIDv7 primary keys. The catalog has no legacy
integer identity. `games_purchase_games.game_id` and every foreign key to the
catalog use those primary keys.

## PostgreSQL and Django migration constraints

Promoting a unique field to a primary key is not a normal `AlterField` when
foreign keys target that field through `to_field`.

Django removes the old unique constraint when the field becomes a primary key.
PostgreSQL refuses to remove it while referencing foreign keys depend on its
index. `sqlmigrate` does not reveal the failure reliably: it resolves constraint
names by introspecting the live, pre-migration database, whereas `migrate`
resolves them after earlier operations have changed the schema. A real migration
run against PostgreSQL is therefore required to verify this class of change.

The referencing constraints must be removed before promotion and recreated
afterward. `DROP ... CASCADE` is unsuitable because it can silently remove
constraints that Django's migration state still declares.

### Do not rename a referenced `to_field`

`RenameField` is unsafe when historical migrations contain relations whose
`to_field` names the field being renamed. `ProjectState.rename_field` mutates the
referring relation's `remote_field.field_name`, while cloned model states share
the field objects. A forward migration can consequently mutate historical states
held by the same `MigrationExecutor`. A later reverse/forward cycle then renders
the pre-promotion relation against the wrong target type and can attempt to cast
`uuid_v7` to `bigint`.

The catalog migration uses `SeparateDatabaseAndState`:

- The state operations remove the integer `id` and UUID `uuid` fields and add a
  UUIDv7 `id` primary key. They use `RemoveField` plus `AddField`, never
  `RenameField`.
- A `RunPython` operation owns the PostgreSQL DDL. It runs after the state
  operations, so Django's schema-editor helpers can create foreign keys and
  indexes from the final model state and retain Django's naming conventions.

This shape is safe to reverse and reapply within one migration-executor process.

### Operation order

The database operations have a required order:

1. Backfill and reconcile a UUIDv7 through-table column, set deferred
   constraints to immediate, and replace `games_purchase_games.game_id` with
   that column.
2. Remove every foreign key that targets the catalog fields being promoted.
3. For each catalog table, remove the integer primary key, rename the UUID
   column to `id`, add the new primary key, and remove the redundant unique
   constraint.
4. Recreate all foreign keys, the through-table pair uniqueness constraint, and
   the through-table indexes.

Deferred constraints must be made immediate before altering the affected tables;
otherwise pending trigger events prevent the DDL. The through table must convert
first because its `game_id` initially depends on the integer `games_game.id`.

Dropping the through table's `game_id` column also drops its pair-uniqueness and
column indexes. Django's migration state does not notice that loss, so the
migration recreates them explicitly through the schema editor.

## Reverse behavior

The forward migration destroys the integer-to-UUID mapping. Reconstructing
integer values would create new identities that merely resemble the old ones,
so rollback with catalog data is deliberately unsupported and raises an error
before changing the schema.

An empty database can reverse to the earlier structural shape. This keeps
migration graph traversal usable for migration tests without claiming that a
populated deployment is reversible. Restoring a populated deployment requires a
backup containing the original identity mapping.

The emptiness guard is the first reverse action, which means it is attached to
the last forward operation.

## Runtime identity contracts

Changing a primary-key type affects more than ORM fields. Any interface that
parses, serializes, renders, or stores an identity must carry the same type.

### Routes

Catalog routes use the strict `uuidv7` converter. The converter is registered in
`games/urls.py`, beside the routes that depend on it, because that URL module is
also valid when imported under an alternative root URL configuration.

Legacy integer URLs cannot redirect: the migration intentionally removes the
mapping required to construct a UUID destination. Catalog slug policy remains
independent of the identifier converter.

### API schemas

Active Ninja request parameters and schema fields that identify a catalog object
use the shared `UUIDv7` annotated type. A plain `uuid.UUID` is insufficient
because it accepts other UUID versions, which the model's `UUIDv7Field` rejects
later at the ORM boundary. Validation belongs at the API boundary so malformed
or wrong-version identities produce a client error instead of an internal error.

Search option schemas are entity-specific. Game and platform option values are
UUIDv7, while an entity that still has an integer primary key retains an integer
option type. A union would describe no endpoint precisely and would weaken the
contract.

Custom-element properties and generated TypeScript types represent catalog
identities as strings. Treating a UUID-valued attribute as a JavaScript number
produces `NaN`, which JSON serializes as `null`.

### Filter criteria

Set criteria encode the primary-key type of their target. Catalog facets use
`UUIDMultiCriterion`; integer-keyed facets use `MultiCriterion`. A UUID criterion
must be registered in both criterion registries with kind `"set"`.

UUID criterion serialization converts values and label keys to strings because
JSON cannot encode `uuid.UUID` objects. Deserialization applies the strict UUIDv7
parser so a serialize/parse round trip returns the typed criterion. This matters
for filters built server-side as well as values arriving from a query string.

The target-specific criterion classes are intentional. Resolving the coercer
from model metadata would require field context in the context-free
`_SetCriterion.from_json` API, while accepting both integers and UUIDs would stop
rejecting identities of the wrong type.

### Generic identity tooling

Fixture loading declares each target identity in
`FixtureRelationship.reference_field`. Relationships to promoted models use
`"pk"`; relationships to models that still expose a separate UUID use
`"uuid"`. Every promotion must update this metadata explicitly.

Anonymization resolves the identity field dynamically instead of assuming that
it is named `uuid`. The resolved identity is `id` for promoted models and `uuid`
for models that still expose a separate UUID.

Identity rewrites use queryset `update`; Django forbids `bulk_update` of primary
keys. Referrer remapping compares against the resolved target field, includes
explicit many-to-many through models, and enumerates
`_meta.get_fields(include_hidden=True)`. `related_objects` omits relations whose
`related_name` ends in `"+"`, which would leave those references stale.
Deferrable constraints are not a substitute for checking this: a transaction
intentionally marked for rollback may never run the deferred constraint checks.

Fixture records store a promoted catalog UUID in `pk` and do not duplicate it in
`fields.uuid`. Relationship values remain strings so YAML serialization is
portable.

## Persisted filter compatibility

`FilterPreset.find_filter` and `FilterPreset.object_filter` store criterion
values as raw JSON, so a schema migration cannot discover their foreign-key
meaning automatically. There is no generic integer-to-UUID remapper after the
source mapping has been removed.

Stale criteria fail parsing and degrade to an "Ignored invalid filter" message
over an unfiltered page rather than raising a server error. A deployment with
persisted filters must migrate or invalidate them before applying an identity
promotion that destroys the relevant mapping.

## Invariants

The catalog cutover is correct only when all of these remain true:

- `Game.id` and `Platform.id` are UUIDv7 primary keys and have no redundant UUID
  unique constraint.
- Every catalog foreign key targets the new `id` column with its expected
  nullability and delete behavior.
- Every purchase-to-game link survives the through-table conversion.
- The purchase/game pair uniqueness constraint and both supporting indexes are
  enforced in PostgreSQL, not merely present in Django's state.
- Catalog model-level uniqueness constraints remain enforced.
- UUIDv4, malformed UUID, and legacy integer API identities are rejected at the
  request boundary; valid UUIDv7 identities reach the ORM.
- UUID-valued criteria round-trip through JSON, including labels, and stale
  criteria degrade safely.
- Catalog routes resolve UUIDv7 values and reject integers.
- Forward migration with data, empty reverse migration, and repeated
  reverse/forward cycles all exercise a real PostgreSQL database.
- The identity audit contains no stale integer-primary-key or through-column
  exception for the catalog.

The same constraints apply to later UUID primary-key promotions: detach foreign
keys before promoting, avoid `RenameField` for referenced `to_field` targets,
verify with a real migration rather than `sqlmigrate`, restore implicit indexes
explicitly, validate the full external identity surface, and treat populated
rollback as a data-restoration problem when the old mapping is destroyed.
