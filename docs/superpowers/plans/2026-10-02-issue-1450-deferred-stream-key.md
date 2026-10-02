# #1450 plan: defer the stream key

Spec: `docs/superpowers/specs/2026-10-02-issue-1450-deferred-stream-key-design.md`.

1. Test first, `tests/test_retention.py`: `test_purging_a_library_takes_an_addon_and_its_events`
   (Main, DLC with `parent=Main`, `TrackGame(main)`, purge under `atomic()` +
   `purging_library()`; no events, no games). Fails with the issue's IntegrityError.
   Gotcha: needs the module's `untracked_games` mark.
2. `games/migrations/0026_defer_library_event_stream_matches_library.py`: one `RunSQL`,
   `ALTER CONSTRAINT ... DEFERRABLE INITIALLY DEFERRED`, reverse `NOT DEFERRABLE`.
3. `tests/test_event_models.py`: cross-library test calls `connection.check_constraints()`
   inside its atomic block; new `test_every_foreign_key_is_checked_at_commit` asserts
   `pg_constraint` holds no FK with `NOT condeferred` in the current schema.
4. Stale text: `anonymize_sample` comment becomes `TODO(#1454)`; #660 spec, clean-02
   spec and plan say the key is deferred since `0026`.
5. Gate: format, lint-fix, format-check, vale; full `make check` under the lock.
