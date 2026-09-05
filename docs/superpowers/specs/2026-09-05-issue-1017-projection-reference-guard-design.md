# The projection reference guard

`games/projections.py` states which tables are projections, and which rows
outside their own library they can name.

## The walk

`projection_references()` walks every managed `ProjectionModel`. It yields
each concrete foreign key whose referenced model carries a concrete
`library` field. The field must be concrete: `UserLibrary.user` declares
`related_name="library"`, so a reverse relation answers to that name.

The condition is the referenced model, not its being a projection. This
matches the cost. `PlayerGame.game` is `RESTRICT` into a library-scoped
`Game`, and a value across libraries stops a purge forever. `on_delete`
does not narrow the walk. `CASCADE` is worse than `RESTRICT`, because a
purge takes rows out of the other library.

`UserLibrary` holds no library, so the `library` column excludes itself.

## The registry

`AUDITED_PROJECTION_REFERENCES` holds the pairs the ownership audit reads.
`ProjectionReference.on()` is the one construction path. It refuses a field
that is not a foreign key, and a field that names a row no library owns.

`games.E009` reports a pair the walk finds and the registry omits.
`games.E010` reports a pair the registry holds and the walk does not find.
A stale pair passes E009 and fails later, in the query the audit builds
from it. Both are system checks, so `manage.py check`, `migrate` and
container start run them.

## The violation query

`cross_library_violations(library_ids)` runs one query for each registered
pair. It reads the base manager, because a removed row keeps its key. It
filters the referenced row's library non-null. Django compiles `exclude()`
as "not equal, nulls included", so a shared catalog row with no library
reads as a violation without that filter.

Each violation reads `Playthrough.player_game: <id> names PlayerGame <id>`.

## The swap's answer

The foreign keys are `DEFERRABLE INITIALLY DEFERRED`, so a violation raises
at commit. `swap_in` wraps the whole transaction block. A violation raised
before the swap begins rises unchanged: the prologue writes a stream head
whose own key is not this one.

For SQLSTATE 23503 in the swap, `swap_in` raises `SwapRefusedByReference`.
The error carries the library id, the constraint name, the driver detail,
the staged diffs, and the audit result. The block has rolled back, so the
audit query runs.

The sentence has three shapes: the pairs the audit finds, no pair, or an
audit that could not run. 23503 has three producers, and only one is a
reference across libraries. Two projectors in one library can disagree, and
a `RESTRICT` reference can name a row outside the projections.

`manage.py rebuild_projections` prints the carried diffs to stderr, then
raises a `CommandError` with the sentence.
