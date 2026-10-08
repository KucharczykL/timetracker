# One library scope for every maintenance command

Issue #1066.

## Problem

Management commands name the data they act on by a user or a library.
Each command resolves that name itself. The rules and the sentences
differ:

- `rebuild_projections` refuses an empty `--all-libraries`.
  `audit_library_ownership` accepts it and reports a pass.
- `rebuild_projections` reads `--user ""` as a username.
  `audit_library_ownership` tests truthiness, so `--user ""` falls
  through to `options["library_id"]`, which is `None`, and answers
  "Library None does not exist."
- A missing user reads "No user is named 'x'." in one command,
  "No user 'x'." in another, "User 'x' or their library does not
  exist." in a third and "User 'x' does not exist." in four more.
- Four commands that read `user.library` raise an uncaught
  `RelatedObjectDoesNotExist` for a user without a library.
- `benchmark_events` repeats `rebuild_projections`'s library-id parse.

## Design

`games/management/library_scope.py` is the one module. It holds:

- `add_scope_arguments(parser, *, verb)`: the required, mutually
  exclusive group `--user`, `--library` (dest `library_id`),
  `--all-libraries`. `verb` fills each help line.
- `scoped_libraries(options) -> list[UserLibrary]`: the libraries the
  group names, in key order, with `user` selected.
- `user_named(username, *, users: UserRows | None = None) -> User`: one
  user by name. `users` lets a caller lock (`select_for_update`); the
  catch reads `users.model.DoesNotExist`.
- `library_of_user(username) -> UserLibrary`, with `user` selected.
- `library_by_id(raw_id: str | UUID) -> UserLibrary`. A `UUID` passes
  unparsed; `call_command` hands one through unchanged.

### Rules, stated once

1. `--all-libraries` that finds no library is refused: "--all-libraries
   found no library, so there was nothing to act on." An empty census reads as
   a clean one otherwise. The sentence is shorter than
   `rebuild_projections`'s old one on purpose: it now serves both.
2. `--user` is tested with `is not None`. `--user ""` is a username and
   answers "No user is named ''." One rule for every name: a lookup
   that finds nothing. (The module #772 removed refused an empty name
   with its own sentence; this reverses that.)
3. A missing user and a user without a library are two sentences: "No
   user is named 'x'." and "User 'x' owns no library."
4. A library id that is not a UUID answers "'x' is not a library id.";
   a UUID no library holds answers "No library <uuid>."
5. No group member set is refused: "Name --user, --library or
   --all-libraries." argparse enforces the group, but `call_command`
   with `library_id=None` or `all_libraries=False` passes it.

### Callers

- `rebuild_projections`, `audit_library_ownership`: the group and
  `scoped_libraries`. Their `_resolve_libraries` go.
- `render_pages`, `verify_reclassification_parity`, `load_sample_data`,
  `anonymize_sample`: `library_of_user`, since each reads the library.
- `purge_user_library`: `user_named` under `select_for_update`. It
  purges a user who may hold no library.
- `benchmark_events`: `library_by_id`; its `--seed` conflict check stays
  in the command.

`audit_library_ownership --all-libraries` still lists users without a
library while one library exists. Under rule 1 a database with no
library at all exits non-zero with the scope sentence instead: every
user then lacks one, so the list adds nothing.
`test_all_libraries_audit_reports_a_user_missing_their_library` keeps
a second, libraried user so it still reaches the list.

## Tests

`tests/test_library_scope.py` states each rule once, against the module.
Command tests keep one case each that proves the command reads the
module. `tests/test_library_commands.py:198` and
`tests/test_stats_parity.py:632` match "does not exist" for a missing
user and move to "No user is named".

## Follow-up issues to file

None.
