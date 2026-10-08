# One library scope for every maintenance command

Issue #1066.

## Rule

A management command that names a user or a library resolves the name
through `games/management/library_scope.py`. No command resolves one
itself. The module states each refusal once, so every command answers
alike.

## Interface

- `add_scope_arguments(parser, *, verb)` adds the required, mutually
  exclusive group `--user`, `--library` (dest `library_id`) and
  `--all-libraries`. `verb` fills each help line.
- `scoped_libraries(options)` returns the libraries the group names, in
  key order, with `user` selected.
- `library_of_user(username)` returns the library of one user, with
  `user` selected.
- `user_named(username, *, users=None)` returns one user. A caller that
  locks passes `users=User.objects.select_for_update()`.
- `library_by_id(raw_id)` takes text or a `UUID`.

## Refusals

1. `--all-libraries` that finds no library is refused: "--all-libraries
   found no library, so there was nothing to act on." An empty census
   must not read as a clean one.
2. `--user ""` is a username. The module tests `--user` with
   `is not None`, so an empty name answers "No user is named ''."
3. A missing user and a user without a library have two sentences:
   "No user is named 'x'." and "User 'x' owns no library."
4. Text that is not a UUID, or a UUID that is not version 7, answers
   "'x' is not a library id." A UUIDv7 that no library holds answers
   "No library <uuid>."
5. A group with no member set is refused: "Name --user, --library or
   --all-libraries." argparse enforces the group, but `call_command`
   can pass every member unset.

## Callers

- `rebuild_projections` and `audit_library_ownership` use the group and
  `scoped_libraries`.
- `render_pages`, `verify_reclassification_parity`, `load_sample_data`
  and `anonymize_sample` use `library_of_user`, because each reads the
  library.
- `purge_user_library` uses `user_named` under a lock. It purges a user
  that may hold no library.
- `benchmark_events` uses `library_by_id`. Its `--seed` conflict stays
  in the command.

## Consequence

`audit_library_ownership --all-libraries` lists each user without a
library while at least one library exists. With no library at all,
rule 1 refuses the run. Every user then lacks a library, so the list
adds nothing.

## Tests

`tests/test_library_scope.py` tests each refusal against the module.
Command tests keep the cases that prove each command reads the module.
