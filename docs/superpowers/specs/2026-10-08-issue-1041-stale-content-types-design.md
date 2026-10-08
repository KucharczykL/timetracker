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
- Raw SQL does not reach the dependent rows. It must delete four tables in
  order. The Django command deletes through the ORM collector, which finds
  them.
- The entrypoint makes one `manage.py` call, to keep cold starts short. The
  sweep runs inside that process. It costs one query per installed app.
- The command is idempotent. A start that finds nothing stale deletes
  nothing.

## Scope

- The command reads installed apps only. It does not take
  `--include-stale-apps`. A DEBUG-only app (admin, debug toolbar) is not
  installed in production, and its rows stay.
- In the database, only `auth_permission` has a foreign key to
  `django_content_type`. No application model refers to a content type.
- `--no-input` deletes without a prompt. Without it, the command asks for
  confirmation on standard input, which a container start does not answer.

## Evidence

The 2026-10-03 production dump held two stale content types,
`games.legacypurchase` and `games.session`, with four permissions each. After
`migrate`, the command removed both and their permissions. A second run
removed nothing.

## Tests

`tests/test_bootstrap_container.py` holds the order of the nested commands. It
also creates a stale content type with a permission, a user grant and a group
grant, runs the startup command, and checks that all four are gone and that a
live model's content type stays.
