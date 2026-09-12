# Squashing the migration history

The `games` app has one migration. It was reached once, on 2026-09-12, by
replacing 50 files with a single hand-written `0001_initial` and carrying the
deployment over by hand. This is what that cost, and what to do differently.

Read [Database contract](database.md#schema-and-migrations) for what the
current baseline carries that no model declares.

## Do it a different way next time

Use `manage.py squashmigrations`, and let it write `replaces = [...]`.

That attribute is how Django retires an old history on its own: the loader sees
a replacement, treats every migration it names as applied, and the deployment
needs no operator SQL and no `--fake` at all. The whole cutover procedure below
is the price of not having it.

`squashmigrations games 0048` was measured before the reset and rejected on
three findings, and only the first is durable:

1. it optimized 226 operations to 211, because the history's 20 `RunPython`
   calls are optimizer barriers;
2. it needed the functions hand-ported out of 18 migrations;
3. it left both legacy tables in the squashed state, so it fixed neither the
   blocker nor CLEAN-02's own migrations.

The second and third were true of that history at that moment. The first is a
rule worth acting on now: **mark every data migration `elidable=True` when you
write it.** That flag is read in exactly one place -- `Operation.reduce()`,
reached from `squashmigrations` -- so an unmarked `RunPython` stops the
optimizer dead, and a history full of them cannot be squashed into anything
smaller than itself. Marked, they are dropped and the optimizer runs through.
A history written that way squashes properly, and the only part of this
document that still applies is the rehearsal in step 6.

Regenerate a baseline by hand only when that has been tried and measured.

If you regenerate anyway, **give the file a name the deployment's history does
not already hold**. Ours was named `0001_initial`, and so was the app's real
first migration from before an earlier squash. `migrate` matched on the name,
read the baseline as applied, and printed:

```text
No migrations to apply
```

Nothing failed. The legacy tables stayed, 84 rows went on naming files that no
longer existed, and the deploy reported success. A name like
`0051_squashed_0001_to_0050` cannot do that.

## What the autodetector will not write for you

A regenerated baseline is `makemigrations` output plus everything Django has no
operation for. There is no `CreateFunction` and no `CreateDomain`; the complete
operation set is 22 entries and none of them makes a function, a domain, or a
composite foreign key. Ours needed four `RunSQL` artifacts:

- the `uuid_v7` domain;
- the `temporal_value` domain and its 17 functions;
- `ALTER COLUMN ... SET NOT NULL` for two generated columns. **Django writes no
  nullability clause at all into a generated column's definition**, so a
  `CREATE TABLE` leaves one nullable however the field is declared. Both of
  ours had reached NOT NULL through an `AlterField` the squash replaced;
- the composite foreign key holding an event's stream against its library.

Quote function bodies from `pg_get_functiondef` against the migrated
deployment, never merge them by hand out of the migrations that wrote them. The
comparison below reads a definition as one string, and a hand-merge differs by
whitespace.

## Steps

1. Rebase onto `origin/main` and branch.

2. Confirm every deployment has applied everything you are replacing. One
   deployment exists, so this is one query:

   ```bash
   podman exec postgres psql -At -U timetracker -d timetracker \
     -c "SELECT count(*) FROM django_migrations WHERE app = 'games'"
   ```

   A squash replaces migrations by their result. A database that has not
   applied one of them cannot be carried over, only rebuilt.

3. Write the replacement file, and the raw-SQL artifacts it needs.

4. Take the old files out. Expect test harnesses to break here: a test that
   migrates backward to a state whose tables no longer exist cannot reach it.
   `flush` builds its `TRUNCATE` list from the models, so a table that exists
   in the database and is declared by no model is left out of the statement and
   PostgreSQL refuses the whole thing:

   ```text
   cannot truncate a table referenced in a foreign key constraint
   ```

   This killed two earlier attempts at the same removal. Resetting the history
   is the fix; patching `flush` is not.

   Triage those files rather than taking them out wholesale. Ours held about 60
   live assertions sitting beside the historical harnesses -- identity rules,
   relations, filters -- and deleting the files would have quietly dropped real
   coverage.

5. `make check-migrations`, so model state and migration state agree, then the
   full `make check`. Never a hand-picked subset.

6. Rehearse on a copy of the deployment:

   ```bash
   make fetch-dump
   ```

   ```bash
   make verify-baseline ARGS="--normalize cutover.sql --record 0051_squashed"
   ```

   `--normalize` applies the operator statements to the restored copy;
   `--record` writes the history row the operator's `migrate --fake` writes.
   The run then builds a second database from the migrations alone and compares
   seven catalogs. **A differing row is a stop.** With `replaces =` neither
   option is needed, and the bare `make verify-baseline` is the whole
   rehearsal.

   Keep the operator statements in a file the branch carries, so the rehearsal
   is reproducible in review, and take the file out once the deployment is
   carried over. Ours lived inside `scripts/verify_baseline.py`, which is why
   it outlived its one use.

7. Deploy the image the merge builds. Its startup `migrate` does the right
   thing only if step 2's name rule was followed.

8. Apply the operator statements, then record the history, **back to back**:

   ```bash
   podman exec -i postgres psql -X --single-transaction -v ON_ERROR_STOP=1 \
     -U timetracker -d timetracker -f - < cutover.sql
   podman exec timetracker python manage.py migrate --fake games 0051_squashed
   ```

   Between those two the app has no recorded history, and container startup
   runs `migrate`. A restart in that window applies the baseline for real,
   `CREATE TABLE` meets tables that exist, and the container crash-loops. Do
   not restart anything in between, and keep the pre-cutover dump as the
   rollback.

9. Read the post-state: one row in `django_migrations` for the app, no dropped
   table left, `migrate --check` exiting 0.

## Lessons

**Write the operator statements to be safe to run twice.** `DROP TABLE IF
EXISTS`, deletes filtered by a subquery, renames guarded by a lookup over
`pg_constraint`. Renaming a constraint that is already renamed is an error
rather than a no-op, which is what the lookup is for.

**Raw SQL does not reach what the ORM's collector reaches.** The migration we
replaced removed a content type through the ORM, which finds the permission
rows naming it. The same statement as SQL fails:

```text
update or delete on table "django_content_type" violates foreign key
constraint "auth_permission_content_type_id_2f476e4b_fk_django_co"
```

Order the deletes yourself: `auth_user_user_permissions`, then
`auth_group_permissions`, then `auth_permission`, then `django_content_type`.

**Converge the deployment on the fresh build's names, not the reverse.** Six
NOT NULL constraints were named after a column called `uuid` that had since
been renamed. PostgreSQL names such a constraint after the column, so a fresh
build named them differently and the two schemas would have differed by six
strings forever. Renaming them on the deployment was one guarded `DO` block;
entrenching the old names in the baseline would have been permanent.

**Compare catalogs, not `pg_dump` text.** `pg_dump` writes a table's columns in
the order they were added, so two databases holding the same schema produce
different text. Read `pg_catalog` and sort every answer. Collapse whitespace in
a function definition so each one is a single row -- otherwise a line that one
routine gained and another lost cancels out and the comparison passes.

**Measure the claims instead of reasoning about them.** That a deploy which
skips the cutover prints `No migrations to apply` was found by restoring the
dump and running it, not by reading Django. So was the missing nullability on
generated columns.

**Keep printing and applying separate, and know which one you ran.** The old
`make cutover-sql` only printed its statements; running it changed nothing
anywhere, which is easy to misread in either direction.
