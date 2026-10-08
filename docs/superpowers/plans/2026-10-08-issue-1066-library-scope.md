# Plan: one library scope (#1066)

Spec: `docs/superpowers/specs/2026-10-08-issue-1066-library-scope-design.md`.

## Task 1: module + tests

- `games/management/library_scope.py` (no `__init__.py`, namespace pkg):
  `UserRows = QuerySet[User, User]`, `add_scope_arguments`,
  `scoped_libraries`, `user_named`, `library_of_user`, `library_by_id`.
  User type: `django.contrib.auth.models.User`, as render_pages.
- `tests/test_library_scope.py`: rules 1–5 against the module
  (options dicts, no command).

## Task 2: multi-library commands

- `rebuild_projections`, `audit_library_ownership` on the module; drop
  `_resolve_libraries`, dead imports (`UUID`, `get_user_model`,
  `ValidationError`).
- `tests/test_projection_rebuild.py`: keep one `--user` case; move unknown
  user / no library / empty username / empty census to the module test.
- `tests/test_library_commands.py:814`: add a libraried second user.

## Task 3: single-user commands

- `render_pages`, `verify_reclassification_parity`, `load_sample_data`,
  `anonymize_sample` → `library_of_user`; `purge_user_library` →
  `user_named` (lock via `users=`); `benchmark_events` → `library_by_id`.
- `tests/test_library_commands.py:198`, `tests/test_stats_parity.py:632`
  → `match="No user is named"`.

## Gotchas

- `call_command` lets every group member be None/False (rule 5).
- `load_sample_data` success line keeps `username`.
