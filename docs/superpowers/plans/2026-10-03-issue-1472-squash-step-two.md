# Plan: #1472, the fourth squash's step two

Spec: `docs/superpowers/specs/2026-10-03-issue-1448-purchase-conversion-squash-design.md`,
"Step two". Precedent: PR #1343 (`c031f9cf`).

## Task 1 — files

- `git rm` the eighteen `games/migrations/00{19..36}_*.py` originals
  (not the squash, not `0037`).
- Squash: delete the `replaces = [...]` block.
- `make check-migrations`: no changes.

## Task 2 — tests

- `git rm tests/test_purchase_preset_rewrite.py` (module-level import of
  `0032`; every test reads it).
- `tests/test_exchange_rates.py`: drop `RATE_MIGRATION`, the
  `import_module` import if unused, and
  `test_the_copy_keeps_the_shortest_spelling`.
- `tests/test_purchase_squash.py`: drop `CONVERSION`, `_apps`,
  `test_the_conversion_refuses_legacy_rows`,
  `test_the_conversion_passes_an_empty_table`, unused imports.
- Grep `import_module("games.migrations.00` afterwards: only the squash.

## Task 3 — docs

- `docs/migration-squash.md`: a "Step two, 2026-10-03" section after the
  fourth squash: deploy facts, what went, the `DELETE` block for the
  eighteen names, the order rule, the rollback `INSERT` pointer to the
  2026-09-28 section. Trim the fourth-squash section's "Step two
  (#1472) waits…" paragraph.
- CLAUDE.md lines naming `0026`, `0028`, `0032`, `0035`: say the squash.
- Makefile usage examples naming retired `0023_…`/`0024_…`: current names.

## Task 4 — rehearsal and gate

- Save the `DELETE` as `cutover.sql` in the scratchpad.
- `make verify-dump DUMP=<post-deploy dump>`: "No migrations to apply".
- `make verify-baseline DUMP=<post-deploy dump> ARGS="--normalize cutover.sql --migrate"`: identical.
- Docs sweep (delete this plan), full `make check`, draft PR.

Gotcha: the post-deploy dump is
`/home/lukas/git/timetracker/.dumps/timetracker-2026-10-03T115845Z.dump`.
