# Purchase UUID primary-key promotion

ID-13 / #849 promotes the already populated `Purchase.uuid` to the sole
primary key. It is the Purchase-sized Wave E slice: small enough to review and
reverse structurally, but complete at every Purchase identity boundary. It
follows the catalog promotion in #646 and the Session/play-history promotion
in #848.

## Identity contract and boundary

After `0015_purchase_uuid_primary_key`, `Purchase` exposes only:

```python
id = UUIDv7Field(primary_key=True, editable=False, serialize=False)
```

The existing UUID values become those primary-key values exactly. The migration
does not mint replacements, retain the integer `id`, keep a separate `uuid`
field, preserve an integer-to-UUID map, or offer a redirect/compatibility
alias. Row contents, ownership, timestamps, games links, and ordering remain
unchanged. `games_purchase_games.id` is the auto-created through row's
permanent bigint primary key; it is not a Purchase identity and is not part of
this promotion.

`Purchase.games` remains Django's auto-created many-to-many relation. Its
through table is now half converted by #646: `game_id` already is a `uuid_v7`
foreign key to `games_game.id`; `purchase_id` alone remains bigint. Django
cannot make an auto-created intermediary target a non-primary key, so this is
the deferred mirror of #646's `game_id` conversion, not an explicit-through
model change.

Every private Purchase lookup remains library-scoped. A valid UUID only reaches
`owned_or_404(Purchase.objects.for_library(library), library, id=purchase_id)`;
possession of another library's UUID must still yield 404. This implements the
charter's private-by-construction rule rather than treating UUIDs as capability
tokens.

## Migration shape

`0015_purchase_uuid_primary_key` depends on `0014_session_playhistory_uuid_primary_key`
and uses `SeparateDatabaseAndState` followed by `RunPython`.

State removes `Purchase.id` and `Purchase.uuid` and adds the UUIDv7 field named
`id`. It must use `RemoveField` plus `AddField`, never `RenameField`.
`ProjectState.rename_field` mutates shared referring relation objects when a
historical relation names `to_field`; a later reverse/reapply in the same
`MigrationExecutor` can then render the old schema with the wrong type. The
database operation owns the PostgreSQL DDL after the state describes the final
model, so schema-editor helpers can generate the final constraint names.

### Forced forward order

The order below is required, not an optimization:

1. Add nullable `games_purchase_games.purchase_uuid uuid_v7`.
2. Backfill it with `UPDATE ... FROM games_purchase`, matching the old
   bigint `purchase_id` to `games_purchase.id`. Reconcile the through-row
   count, zero NULL/unmatched holding values, and distinct linked-Purchase
   count before and after conversion. No source UUID or link may change.
3. Execute `SET CONSTRAINTS ALL IMMEDIATE` before the first `ALTER TABLE`.
   The backfill leaves a pending trigger event on the table's deferrable,
   initially deferred foreign key; without this guard PostgreSQL rejects the
   subsequent DDL with pending trigger events.
4. Drop `purchase_id`, rename `purchase_uuid` to `purchase_id`, and set it
   `NOT NULL`. Dropping the old column intentionally cascades away its foreign
   key, its ordinary `purchase_id` index, and the `(purchase_id, game_id)`
   unique constraint/index.
5. Promote `games_purchase`: record its row count, drop its bigint primary-key
   column, rename `uuid` to `id`, add the UUID primary key, drop the redundant
   `UNIQUE (id)` constraint, and assert the row count is unchanged.
6. Recreate the through-table foreign key, independent `purchase_id` index,
   and `(purchase_id, game_id)` uniqueness after the promotion.

The through conversion must precede dropping `games_purchase.id`: the old
through foreign key depends on it. The unique pair must be rebuilt even though
Django's migration state continues to list `unique_together`; state drift
checks cannot observe a PostgreSQL constraint silently removed by `DROP
COLUMN`.

Constraint recreation uses the final historical models and Django's schema
editor: `_create_fk_sql` for the Purchase relation,
`_create_index_sql` for `purchase_id`, and `alter_unique_together` for the
pair. It uses the same FK suffix convention as #646 rather than hard-coded
names or `DROP ... CASCADE`; #646's generated names are also the names this
second conversion must safely introspect and restore. The resulting
`purchase_id` is a non-null `uuid_v7` foreign key to `games_purchase.id`, has
its independent index, and is jointly unique with `game_id`.

## Reverse contract

Forward promotion destroys the original integer-to-UUID mapping. A populated
reverse would have to invent integer identities and is therefore unsupported.

The reverse first acquires one `ACCESS EXCLUSIVE` lock covering both
`games_purchase` and `games_purchase_games`, then checks both row counts while
that lock is held. If either table has rows, it raises before any schema mutation
and tells the operator to restore a backup taken before this migration. Locking
both tables before the combined check prevents a concurrent through link or
Purchase insert from entering between validation and DDL.

Only when both are empty may reverse restore the preceding structural shape:

- `games_purchase` regains bigint `id` generated by default as an identity
  primary key and a separate unique `uuid_v7` column with the UUIDv7 database
  default;
- `games_purchase_games.purchase_id` becomes non-null bigint again and points
  to that bigint Purchase key; and
- the prior Purchase FK, `purchase_id` index, and `(purchase_id, game_id)`
  unique constraint are recreated through the schema editor's generated naming
  mechanisms.

This structural empty reverse makes migration-graph traversal and a
reverse/reapply test valid without claiming a deployed, populated rollback is
safe.

## Runtime identity boundaries

The seven existing Purchase identity routes switch from `<int:purchase_id>` to
`<uuidv7:purchase_id>`:

| Route name | Path suffix |
| --- | --- |
| `edit_purchase` | `edit` |
| `delete_purchase` | `delete` |
| `view_purchase` | `view` |
| `refund_purchase_confirmation` | `refund/confirm` |
| `refund_purchase` | `refund` |
| `split_purchase_confirmation` | `split/confirm` |
| `split_purchase` | `split` |

The associated view and helper parameters are `UUID` values. Valid UUIDv7
values reverse and resolve; integer strings, malformed values, and UUIDv4 do
not reach an ORM lookup. There is no integer redirect because no mapping
survives. The add-for-game route remains governed by `game_id`; it is not a
Purchase identity route.

Purchase has no identity-bearing Ninja API endpoint. This slice does not add
one or alter API identity schemas. Filters, saved presets, statistics, currency
conversion, split/refund semantics, and canonical slug policy are also outside
this outcome. #647 owns the latter policy; this issue converts only the seven
bare Purchase routes.

## Fixture representation

Each `games.purchase` fixture record stores the promoted UUIDv7 identity in
`pk` and omits `fields.uuid`. Its relationships (including `games` values),
record order, and unrelated fields remain unchanged. The compressed YAML keeps
its deterministic gzip representation.

The loader and anonymizer already resolve promoted identities through `pk` and
unpromoted identities through `uuid`; they receive no Purchase-specific branch
unless a behavior test demonstrates one is necessary. Fixture and sample-load
tests must cover committed-sample loading plus deterministic anonymize/load
round trips.

## Audit inventory

ID-13 removes exactly its two completed entries:

- `RESIDUAL_INTEGER_RELATIONS[("games_purchase_games", "purchase_id")]`;
- `RESIDUAL_INTEGER_PRIMARY_KEYS["games_purchase"]`.

It leaves the permanent through-row-primary-key exemption and every other
Wave E inventory entry intact. The through-table tripwire is rewritten, not
deleted: it must assert both relation columns are `uuid_v7` foreign keys to
their promoted primary keys, while the direct through-model duplicate insert
continues to prove pair uniqueness is enforced by PostgreSQL.

## Verification sequence

All verification uses PostgreSQL; `sqlmigrate` is not evidence for this
Python-owned DDL. Run commands through the project environment, retain the
Makefile's default `PYTEST_WORKERS`, and do not force serial mode.

1. Add focused migration/identity tests before implementation. They must cover
   the final model contract; UUID/row/value/link preservation; physical domain,
   primary key, default, FK, index, and pair uniqueness; duplicate and UUIDv4
   rejection; the rewritten tripwire; audit inventory; empty reverse; populated
   reverse refusal before mutation; exclusive reverse locking; and reverse then
   reapply through one `MigrationExecutor`. Run them first to demonstrate the
   missing implementation failure, then again after the migration.
2. Run `direnv exec . make test ARGS="tests/test_purchase_uuid_primary_key.py tests/test_purchase_identity.py tests/test_purchase_fk_uuid.py tests/test_uuid_identity_audit.py"`.
3. Add and run `tests/test_purchase_runtime_identity.py`, covering UUIDv7
   reverse/resolve, integer and UUIDv4 rejection, owned read/actions, and
   foreign-library 404 for all seven routes:
   `direnv exec . make test ARGS="tests/test_purchase_runtime_identity.py"`.
4. Add fixture-shape and sample round-trip coverage, transform only Purchase
   fixture identities, then run the relevant fixture/anonymizer tests with
   `direnv exec . make test ARGS="tests/test_anonymize_sample.py tests/test_library_commands.py"`.
5. Exercise the live PostgreSQL migration and schema gates in order:
   `direnv exec . make migrate`, `direnv exec . make audit-uuid-identity`, and
   `direnv exec . make check-migrations`.
6. Run the full default-worker gate: `direnv exec . make check`.

The final review compares the complete diff with #849 and its ID-09, ID-10,
and ID-11 handoffs; the #848 and #646 promotion records; the UUID cutover wave
plan; and the charter requirements for small reversible slices, complete UUID
cutover without integer aliases/routes, PostgreSQL-only verification, and
library isolation.

## Invariants

- `Purchase.id` is the sole UUIDv7 primary key with a database default and no
  redundant unique identity constraint.
- Every existing Purchase UUID, row, scalar value, ownership relation, and
  purchase/game link survives exactly.
- `games_purchase_games.purchase_id` is a non-null UUIDv7 FK, independently
  indexed and pair-unique with the already UUIDv7 `game_id`.
- Populated reverse fails before mutation under a two-table exclusive lock;
  empty reverse and reverse/reapply restore the earlier structure.
- The seven Purchase routes reject integers and non-v7 UUIDs, and every private
  lookup remains library-scoped.
- Fixture output represents promoted Purchase identity at `pk` deterministically
  and does not retain `fields.uuid`.
