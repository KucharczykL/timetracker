# Stale content types leave on startup

Issue: [#1041](https://github.com/KucharczykL/timetracker/issues/1041)

## Rule

The container's startup command, `bootstrap_container`, runs
`remove_stale_contenttypes --no-input` directly after `migrate`. A model that
a migration drops loses its `django_content_type` row on the same deploy. Its
`auth_permission` rows and their user and group grants go with it.

No migration and no operator statement removes a content type.

## Why startup

- A migration that removes content types must name each model. The next
  squash deletes that migration, and the work moves to hand-run SQL.
- Raw SQL does not cascade. It must delete four tables in order. The Django
  command deletes through the ORM collector, which takes that order.
- The entrypoint makes one `manage.py` call, to keep cold starts short. The
  sweep runs inside that process. It reads `django_content_type` in one
  query; each stale type adds its delete.
- The command is idempotent. A start that finds nothing stale deletes
  nothing.

## Behaviour

- The sweep runs at verbosity 2. The container log names each content type
  it deletes.
- `--no-input` deletes without a prompt. Without it, the command reads
  standard input, and a container start hangs or fails.
- The collector reaches only installed models. A table outside them with a
  foreign key to `django_content_type` refuses the delete. The startup
  command then fails with a `CommandError` that names the table and the
  constraint, and the container does not start. In the database, only
  `auth_permission` has such a key today.

## Scope

- The command reads installed apps only. It does not take
  `--include-stale-apps`. A DEBUG-only app (`debug_toolbar`,
  `django_extensions`) is not installed in production, and its rows stay.
- An older image does not know a newer image's models. A rollback deletes
  their content types and permissions, and a later `migrate` creates new
  permissions without the grants. The app checks no permission, so a
  rollback loses nothing it reads.

## Evidence

The 2026-10-03 production dump held two stale content types,
`games.legacypurchase` and `games.session`, with four permissions each. After
`migrate`, the command removed both and their permissions. A second run
removed nothing.

## Tests

`tests/test_bootstrap_container.py` holds:

- the order of the nested commands;
- a stale content type, its permission and grants removed, and named in the
  output;
- a live model's permissions and an uninstalled app's rows kept, over two
  runs;
- a foreign key from a table outside the apps stopping startup with a
  `CommandError` that names the table.
