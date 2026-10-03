# Plan: #1443 + #1448, one PR

Specs: `docs/superpowers/specs/2026-10-03-issue-1443-conversion-review-removal-design.md`,
`docs/superpowers/specs/2026-10-03-issue-1448-purchase-conversion-squash-design.md`.

Iterate with `make check-fast` / focused `make test ARGS=…` under the
shared lock. Before each commit: `make format`, `make lint-fix`,
`make format-check`, `make vale`.

## Task 1 — the squash (#1448)

Files: `games/migrations/0019_device_access_end_squashed_0036_defer_library_event_stream_matches_library.py`
(tool output, already generated), `0029`, `0035` (`elidable=True`),
`0031`.

1. Guard function `refuse_unconverted_data(apps, schema_editor)` at the
   top of the squash: one `SELECT EXISTS` per table (`games_purchase`,
   `games_exchangerate`) on `schema_editor.connection`; raise
   `RuntimeError` with the two-remedy sentence. First operation:
   `migrations.RunPython(refuse_unconverted_data, migrations.RunPython.noop, elidable=True)`.
2. `0031.convert` raises `RuntimeError` ("drop and rebuild this
   database"); no import.
3. Tests, new `tests/test_purchase_squash.py`:
   - guard passes on the test database (empty legacy-shaped tables:
     the live `games_purchase` and `games_exchangerate` hold nothing);
   - guard raises after `ExchangeRate.objects.create(...)`;
   - guard raises after a live `Purchase` row (reuse a purchase
     factory from `tests/` if one exists; else skip this case);
   - `0031.convert(None, None)` raises.
   Import modules with `importlib.import_module`.
4. `make lint-fix` the squash (I001).

Gotcha: the guard runs inside the squash's transaction; a raise rolls
back the whole migration, which is the point.

## Task 2 — tooling removal (#1448)

Delete: `games/backfill/` whole;
`games/management/commands/verify_purchase_conversion.py`,
`verify_purchase_statistics.py`; `games/purchase_parity.py`;
`tests/legacy_purchases.py`, `tests/test_legacy_model.py`,
`tests/test_purchase_conversion.py`, `tests/test_purchase_conversion_plan.py`,
`tests/test_purchase_stats_parity.py`, `tests/test_verify_purchase_conversion.py`,
`tests/test_purchase_migrations.py`.

Edit:
- `tests/conftest.py`: drop the `legacy_purchase` import.
- `games/valuations.py`: drop `seeded`; `tests/test_purchase_valuation.py`:
  drop its tests and import.
- `tests/test_purchase_preset_rewrite.py`: drop `converted` and
  `test_a_rewritten_preset_matches_the_same_rows`.
- `Makefile`: drop both `verify-purchase-*` targets and their comments.
- Grep `conversion-tooling` afterwards: no hit outside docs.

## Task 3 — review removal (#1443)

- `games/views/conversion_review.py`: delete; `games/views/library.py`:
  Purchases section holds `purchases_summary` alone.
- `games/models.py`: drop `conversion_review_hidden`,
  `set_conversion_review_hidden`. `make makemigrations ARGS="games --name remove_conversion_review_hidden"`
  → `0037`, check its dependency names the squash.
- `timetracker/settings_commands.py`: drop
  `change_library_conversion_review_hidden` and its `__all__` entry.
- `games/api.py`: drop route, two schemas, the imports
  (`CONVERSION_REVIEW_HIDDEN`, `change_library_conversion_review_hidden`,
  `StrictBool`).
- `games/forms.py`: drop `ConversionReviewForm`.
- `games/conversion_review.py`: `REVIEW_LABELS: Final[Mapping[Category, str]]`;
  drop `ReviewWords`, `ReviewTarget`, `CONVERSION_REVIEW_HIDDEN`,
  `RECONCILIATION_ONLY`, `Category.SKIPPED_REMOVED_GAME`;
  `REVIEWED = tuple(REVIEW_LABELS)`.
- `games/filters.py:184`: read `REVIEW_LABELS[word]`.
- Tests: delete `tests/test_conversion_review_rows.py`,
  `e2e/test_conversion_review_e2e.py`; `tests/test_conversion_review_filter.py`
  asserts `set(REVIEWED) == set(Category)` and reads labels;
  `tests/test_library_page_isolation.py` count 25 → measured (expect 24),
  docstring drops "the review one".

## Task 4 — docs

- `docs/migration-squash.md`: replace "Passes waiting for a squash" with
  "The fourth squash, 2026-10-03" (range, elided passes, guard,
  barriers, rehearsal result, step two pending, next number `0038`).
- CLAUDE.md: command-table rows for both `verify-purchase-*`; the
  `LegacyPurchase` paragraph and #723 paragraph to Device/Session
  wording; the #735 `verify-purchase-statistics` sentence; the #1266
  review/preference sentence.
- Comment #1432 (field replaces the review lists).
- File step-two issue (spec's follow-up) with `gh issue create`.

## Task 5 — rehearsal and gate

- `make verify-baseline DUMP=.dumps/timetracker-2026-10-02-post-deploy.dump ARGS="--migrate"`
  (0037 applies on the copy; catalogs identical).
- `make verify-dump DUMP=.dumps/timetracker-2026-10-01.dump` must
  refuse with the guard's sentence.
- Then docs sweep (delete this plan, spec timeless), full `make check`.
