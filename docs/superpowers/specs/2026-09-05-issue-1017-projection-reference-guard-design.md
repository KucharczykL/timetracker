# The projection reference guard and the swap's answer

Issue [#1017](https://github.com/KucharczykL/timetracker/issues/1017). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).
Depends on [#679](https://github.com/KucharczykL/timetracker/issues/679),
which shipped the first foreign key between two projection tables.

Two gaps share one cause: nothing enumerates the foreign keys out of a
projection table. The ownership audit cannot know it missed one, and the
rebuild cannot say which one stopped it.

## The topology module

`games/projections.py` answers "which tables are projections, and which rows
outside their own library can they name".

`projection_models()` moves here from `games/events/rebuild.py`. The move is
for clarity, not necessity: an audit query has nothing to do with rebuilding,
and leaving it in `rebuild.py` would make that module the home of the audited
list as well. `rebuild.py` and `games/events/benchmark.py` import the moved
name, so `tests/test_projection_rebuild.py` keeps its import.

The module states four things:

```
class ProjectionReference(NamedTuple):
    model, field

AUDITED_PROJECTION_REFERENCES: tuple[ProjectionReference, ...]

def projection_models(apps) -> tuple[type[ProjectionModel], ...]
def projection_references(apps) -> tuple[ProjectionReference, ...]
def unaudited_projection_references(apps) -> tuple[ProjectionReference, ...]
def cross_library_violations(references, library_ids) -> list[str]
```

### What the walk finds

`projection_references` walks `projection_models(apps)` and yields every
concrete foreign key whose remote model carries a `library` field.

That condition, and not "the remote model is a projection", is the one that
matches the cost. Three consequences:

- `Playthrough.player_game` is found, as #1017 asks.
- `PlayerGame.game` is found. It is `RESTRICT` into `Game`, `Game` carries a
  `library`, and a `PlayerGame` in one library naming a `Game` in another
  blocks that library's purge forever. Nothing audits it today, and a
  projection-to-projection walk would never demand it.
- The `library` column itself is excluded, because `UserLibrary` has no
  `library` field of its own. No special case states it.

`on_delete` does not narrow the walk. `RESTRICT` means the library holding the
referenced row can never be purged. `CASCADE` is worse, not better: a purge, or
a swap, in one library would take rows out of another. The check reports the
`on_delete` by name rather than assuming one.

`AUDITED_PROJECTION_REFERENCES` therefore holds two pairs: `PlayerGame.game`
and `Playthrough.player_game`. The result of the walk is sorted by table then
column, so a check message has a stable order.

### The violation query

`cross_library_violations` runs one query per pair, keyed on the field's
`attname` rather than a rebuilt `"<name>_id"` string:

```
model.objects
  .filter(Q(library_id__in=ids) | Q(<field>__library_id__in=ids))
  .filter(<field>__library__isnull=False)
  .exclude(<field>__library_id=F("library_id"))
  .values_list("pk", <field>.attname)
```

The `isnull` clause is unconditional, and it is load-bearing. Django compiles
`exclude()` to mean "not equal, nulls included": it puts `IS NOT NULL`
conjuncts *inside* the negation, so a NULL on either side gives `NOT(FALSE)`
and is reported as a violation. The clause is on the *referenced row's*
library, not on the foreign key, and it answers both nulls at once — a NULL
foreign key produces no joined row, and a joined row with no library is a
shared row that crosses no boundary.

Both cases are live. `Game.library` is `null=True, default=None`, so a
`PlayerGame` naming a global catalog game would be reported as a violation
without it. The six hand-written blocks in the audit command spell the same
clause, `platform__library__isnull=False` among them, for the same reason.

Each violation reads `Playthrough.player_game: <id> names PlayerGame <id>`.
The text is derived from the pair, not written per relation: a guard that
forces a new relation to be registered cannot also demand prose for it, so the
prose of today's line — "playthrough … , tracked game …" — goes.

## The completeness check

`games.E009` lives in `games/checks.py`, beside `check_projection_models`,
under `@register(Tags.models)` and with the same `app_configs` filtering. It
reports one `Error` per unaudited pair, naming the relation and its `on_delete`.

The hint states the cost of leaving it unaudited: the row is invisible to every
query a rebuild runs, so a cross-library value is found only when the swap
refuses at commit. The remedy is one line in `AUDITED_PROJECTION_REFERENCES`.

A check, not a test: `manage.py check` runs it, and so does every `migrate`,
every `make dev`, and container start. A developer who adds the relation learns
before the suite does.

`games.E010` is the same check read the other way: one `Error` per pair the
registry holds and the walk no longer finds. A stale pair passes E009 and fails
later, inside the query the audit builds from it — worst of all inside the
handler that reads it to explain a refused swap. A pair whose model the
registry under check does not hold belongs to another registry and is not
stale.

## The audit command

`_cross_library_violations` loses its projection block and calls
`cross_library_violations(library_ids)`, which reads the registry itself.

The six blocks for ordinary models stay hand-written. They are not derivable
the same way: each names its own join path (`device__library` against
`game__library`), and one of them audits an M2M through table. #1017 scopes the
relations out of a projection, which the check can complete.

The command now reports `PlayerGame.game` violations it never reported before.
That is a new true answer, not a new failure mode, but the implementation
confirms no existing test plants such a row.

## The swap's answer

The foreign keys on `games_playthrough` are `DEFERRABLE INITIALLY DEFERRED`, so
a violation raises at commit, not at the statement. `swap_in` therefore wraps
its whole `transaction.atomic()` block rather than the cursor. Django's
`_commit()` runs inside `wrap_database_errors`, so the exception is a Django
`IntegrityError` whose `__cause__` is a psycopg error carrying `.sqlstate` —
the same chain an execute-time failure produces. `StreamSequenceMismatch` is a
`CommandConflict`, not an `IntegrityError`, so the wider block does not swallow
it.

`retry.py` states `FOREIGN_KEY_VIOLATION = "23503"` beside `UNIQUE_VIOLATION`
and promotes both `_sqlstate` and `_constraint_name` to public `sqlstate_of`
and `constraint_name_of`. It stays their home: reading the diagnostics off a
driver error is what that module already does.

### Not every 23503 is a cross-library reference

Three different failures raise `23503` at the swap, and only one of them is
this issue's subject:

1. a projection row in another library naming a row this rebuild did not
   reproduce — the subject;
2. two projectors in one library disagreeing, so the swap's own `DELETE` takes
   a row a sibling projection still names;
3. a `RESTRICT` reference to a row outside the projections, such as a
   `PlayerGame` whose `Game` is gone.

Cases 2 and 3 find nothing cross-library. An error that named them as a
cross-library reference would send an operator to `audit_library_ownership`,
which would answer `Cross-library links: 0`.

`swap_in` therefore re-raises any `IntegrityError` of another state unchanged,
and for `23503` raises one `SwapRefusedByReference` carrying the library id,
the constraint name from the diagnostics, the staged `TableDiff`s, and the
result of `cross_library_violations` scoped to that library. The block has
already rolled back when the handler runs — `in_atomic_block` is False and
`needs_rollback` is False — so the connection answers that query.

The sentence has two shapes. When the violation list is not empty it names the
library, lists the offending pairs, states that nothing was swapped and the
live rows are unchanged, and gives
`manage.py audit_library_ownership --all-libraries`. When the list is empty it
names the library and the constraint, and states that the audit finds no
cross-library pair, so the referenced row is missing for another reason.

Nothing on this path retries. `rebuild_projections` catches only
`StreamSequenceMismatch`, and `swap_in` does not use `run_in_transaction`, so
`is_retryable` is never consulted — the new error rises through the attempt
loop untouched.

`manage.py rebuild_projections` answers it as it already answers
`UnresolvedReferences`: it prints the carried `TableDiff` lines through the
existing `_write_table`, then raises a `CommandError` with the sentence.
Without the carried tables the command would print no diff at all, because it
calls `_write_report` only after `rebuild_projections` returns.

### What the diff can and cannot say

The issue states that a rebuild "reports green and then fails at the swap".
That is one step off, and the correction does not change the deliverable.

The swap restores exactly the keys its `DELETE` removed. It can only break a
foreign key when the replay of the referenced library reproduces one key fewer,
and that library's own diff reports the same rows as `only_live`. A check run
against the planted repro below prints `only_live: 1`. No zero-drift path
exists: `_DIFF`'s live subquery is scoped `WHERE library_id = %s`, identically
to `_DELETE_LIVE_ROWS`; a shadow row for another library shows as
`only_rebuilt`; and generated columns are excluded from `insertable_columns`
and recomputed by the same expression.

What the diff cannot report is the cause. A shadow table is
`CREATE TEMP TABLE (LIKE … INCLUDING ALL)`, which copies no foreign key; the
creation payload carries a bare `ReferenceId`, so `require_resolvable_references`
never reads it; and the diff is scoped to one `library_id`, so the row on the
other side of the boundary is outside every query it runs. An operator reads
`only_live: 1`, decides the rebuild is the repair, and gets a psycopg
`IntegrityError` naming a constraint. The sentence supplies what the diff
structurally cannot.

## Verification

`tests/test_projection_references.py`, new:

- the real app registry has no unaudited pair;
- `projection_references()` finds `PlayerGame.game` and
  `Playthrough.player_game`, and not either `library` column;
- `games.E009` reports an unaudited pair. The test calls
  `check_projection_references(apps=shelf._meta.apps)` directly, the way
  `tests/test_projection_model.py:23` already does. A `run_checks()` call
  would prove nothing: `isolate_apps` swaps `Options.default_apps` and leaves
  `django.apps.apps` untouched, so the synthetic models are invisible to the
  global registry. That is also why no existing check test regresses.
- The synthetic pair is `Entry.shelf` from the existing
  `declare_projection_models()` in `tests/test_projection_targets.py`. It is
  `CASCADE`, which the walk finds, because `Shelf` inherits `library` from
  `ProjectionModel`.

`tests/test_library_commands.py`: the derived violation line, at both sites
that pin it — the relation-name loop and the exact-prose assertion. Two cases
for the widened walk: a `PlayerGame` naming a `Game` in another library is
reported, and a `PlayerGame` naming a `Game` with no library at all is not.

`tests/test_projection_rebuild.py`, one `transaction=True` case: a `PlayerGame`
planted in library B with no event behind it, a `Playthrough` in library A
naming it, then a rebuild of B. The replay of B reproduces nothing, the swap's
`DELETE` takes the planted row, and the commit refuses. Two authoring notes:

- the module carries `pytestmark = pytest.mark.untracked_games`, so a
  `Game.objects.create()` produces no `PlayerGame`; plant it explicitly;
- the violation fires on the `DELETE` side, so the assertion matches on the two
  ids and the constraint, never on "insert or update".

A second case covers the empty-violation shape: the same rebuild with the
`Playthrough` in library B as well, which raises `23503` with nothing
cross-library, and gets the second sentence.

Then `make check`, whole.

## Reversibility

No migration, no schema change, no data change. Every part is a code change
that a revert undoes. `games.E009` reports on a registry a revert takes with
it, so it cannot leave a half-registered relation.

## Out

Any change to the projection schema. Any repair of an existing violation. The
six hand-written blocks for ordinary models. Detecting a cross-library
reference during phases 1 to 3 of a rebuild, which would need the shadow tables
to carry foreign keys.
