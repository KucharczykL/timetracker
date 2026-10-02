# The legacy purchase is gone: implementation plan

**Goal:** drop `LegacyPurchase` and everything that reads it, keep the
conversion tooling on the historical model, regenerate the sample fixture.

**Spec:** [2026-10-02-issue-736-legacy-purchase-drop-design.md](../specs/2026-10-02-issue-736-legacy-purchase-drop-design.md)

## Global constraints

- Every pytest run wrapped: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS=…`.
- Before each commit: `make format`, `make lint-fix`, `make format-check`, `make vale`, read by exit code.
- Comments ≤ 7 words, no issue refs. Tooling #1448 removes carries the comment `conversion-tooling`.
- Commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Full `make check` once, at the end.

---

### Task 1: Historical model accessor and test fixture

**Files:**
- Create: `games/backfill/legacy_model.py` (`conversion-tooling`)
- Create: `tests/legacy_purchases.py` (`conversion-tooling`), registered in `tests/conftest.py` the way other fixture modules are
- Modify: `games/management/commands/verify_purchase_conversion.py`, `games/backfill/purchase_reconciliation.py` (marker only)

**Interfaces:**
- `LEGACY_STATE: Final = ("games", "0034_conversion_review_hidden")`
- `legacy_purchase_model() -> type[Model]`: `MigrationLoader(None, ignore_no_migrations=True).project_state(LEGACY_STATE).apps.get_model("games", "LegacyPurchase")`, cached with `functools.cache`.
- `class LegacyTableGone(Exception)`; `require_legacy_table(connection) -> type[Model]` raises it when `games_legacypurchase` is absent from `connection.introspection.table_names()`.
- Fixture `legacy_purchase` (needs `db`): asserts `connection.in_atomic_block` (a transactional test is refused with a message naming the reason); `schema_editor.create_model(model)` and yields the model. The rollback removes the table.

**Tests** (`tests/test_legacy_model.py`, `conversion-tooling`):
- the fixture's model accepts `objects.create(library_id=…, price_currency="EUR", date_purchased=…)` and `.games.add(game.pk)`;
- `require_legacy_table` raises `LegacyTableGone` without the fixture and answers the model with it;
- `verify_purchase_conversion --user X` without the table: `CommandError` with one sentence ("The legacy purchase table is gone; …").

**Gotcha:** until Task 2 lands, the live class still owns `games_legacypurchase`, and `create_model` collides. So do Task 1 and Task 2 in one commit: write the fixture first, then the migration.

### Task 2: Migration 0035 and the model drop

**Files:**
- Modify: `games/models.py` (delete `LegacyPurchaseQueryset` and `LegacyPurchase`; drop now-unused imports such as `floatformat`, `pluralize`, `label_with_details`, `NullIf` if unused)
- Create: `games/migrations/0035_delete_legacypurchase.py` via `make makemigrations ARGS="games --name delete_legacypurchase"`, then append a `RunPython` that deletes `django_q.Schedule` rows with `func="games.tasks.calculate_price_per_game"` (noop reverse; dependency on the django_q migration 0031 names)
- Modify: `games/signals.py` (both `m2m_changed` receivers and the import)
- Modify: `games/removal.py` (`REMOVABLE_MODELS` without it, `_recount_purchases` and its `_AFTER_STAMP` entry, the `:106` comment)
- Modify: `games/tasks.py` (legacy half; keep the `DatabaseError` failure and retry; docstring "Value the snapshot; publish if current."; delete `calculate_price_per_game`)
- Modify: `games/apps.py` (commented schedule block)
- Modify: `games/management/commands/audit_library_ownership.py` (count and three checks)
- Modify: `games/identity_audit.py` (residual entry; docstring reason)
- Modify: `games/management/commands/verify_purchase_conversion.py` (`require_legacy_table(connection)` in place of the class; `legacy_rows`, `legacy_statistics`, `legacy_figures` take that model)

**Tests:** every module in Task 3's list collects; `make typecheck` green.

**Gotchas:**
- The generated migration emits `RemoveField`s before `DeleteModel`; keep that.
- Run `make makemigrations` with `--check` afterwards so nothing else is pending.
- `test_the_rename_moves_every_name_and_reverses` walks back through 0035's `CreateModel`. Run it right away.

### Task 3: Tests move off the live class

Classify every file from `git grep -l -i legacypurchase tests e2e`:

- **Delete** (they test code that goes): `test_price_update.py`, `test_generated_purchase_price_columns.py`, `test_purchase_related_game.py`, `test_removal_purchases.py`; the legacy halves of `test_library_conversion.py` (the `save()`/edit rules, the legacy-row retry tests), `test_library_models.py`, `test_purchase_valuation.py` (`test_a_legacy_row_without_a_rate_still_fails_the_run`, `test_a_failed_valuation_write_rolls_back_the_legacy_cache`), `test_retention.py` (rows and `bundle_count`), `test_purchase_identity.py`, `test_purchase_fk_uuid.py` and `test_platform_fk_uuid.py` legacy cases, `test_site_settings_currency.py` legacy cases.
- **Rewrite on a new subject:**
  - retry scheduling: monkeypatch `games.tasks.publish_valuations` to raise `DatabaseError`; assert one ONCE schedule and status FAILED (new cases in `test_purchase_valuation.py`);
  - `test_statistics_never_pair_new_total_with_previous_currency`: a `Purchase` with a valuation;
  - `test_filters.py`: GeneratedField→number on `PlayerSession.effective_duration`; nullable date on `Purchase.refunded_lower`; `_PurchaseStub` on `Purchase`; the forward M2M cases on an `isolate_apps` model with `games = ManyToManyField(Game)`;
  - `test_date_criterion_expression.py`, `test_catalog_hierarchy.py:388`, `test_column_priority_contract.py`, `test_game_display_order.py`, `test_sentinel_removal.py`, `test_session_formatting.py`, `test_sort_header_parity.py`, `test_rendered_pages.py`, `test_render_pages.py`, `test_view_authentication.py`: drop the legacy row or use `Purchase`/`tests/purchases.py` builders;
  - `test_uuid_identity_audit.py`: expected sets lose the legacy table; the orphan-row case states a doctored through table;
  - `test_removable_models.py`: builder map;
  - `test_purchase_preset_rewrite.py`: reads only the retired key; keep it where it tests the rewrite, drop live-class uses.
- **Historical model through `legacy_purchase`:** `test_purchase_conversion.py`, `test_purchase_stats_parity.py` (`legacy_library` fixture; `test_the_historical_model_answers_alike` loses `transaction=True` and compares the fixture model with the 0031 state), `test_verify_purchase_conversion.py`, `test_library_reconciliation.py`. Instances become keys; `num_purchases` is stated where a figure reads it.
- `test_purchase_migrations.py`: the conversion case reads `LegacyPurchase` from the executor's state at 0030.

Run each file as it moves: `make test ARGS="tests/<file> -x"`.

### Task 4: Anonymizer on the new shape

**Files:** `games/management/commands/anonymize_sample.py`, `tests/test_anonymize_sample.py`

- `DUMP_LABELS`: `Platform, Game, Edition, Release, LibraryEventStreamHead, LibraryEvent, LibraryEventReference, ExchangeRate`. `PORTABLE_LIBRARY_MODELS` loses legacy. `GENERATED_FIELDS` becomes Release's five generated columns (they are serialized; loaddata discards them).
- `IDENTITY_MODELS = (Platform, Device, Game, Edition, Release)`. `_resequence_identity` orders by `created_at, pk` where the model has `created_at`, else by `pk` at `FIXED_EPOCH`.
- Prune: delete other libraries' projection rows (Purchase, LibraryEntry, HistoricalPlaytimeRun/HistoricalPlaytime, PlayerSession, Playthrough, PlayerGame, then the calendar and valuations, every model keyed by library) before Games. Derive the list from `DEFAULT_WIRING`'s projection models plus `PurchaseValuation`, never by hand.
- Delete the legacy purchase block and the `reassignable_game_ids` guard.
- Projected references: after `aggregate_replacements` exists, rewrite each payload reference whose kind's resolution is `PROJECTED` and not a device (it already maps) to `aggregate_replacements[old]`, label kept; the same for `LibraryEventReference.referenced_id`. Capture labels before the remap.
- `counts` reports games, entries, purchases, sessions, events.

**Tests:**
- round trip: a library with an entry, a purchase, a refund and the copy's end loads through `load_sample_data` and replays (`library.purchase.created`'s `entry` reference names the re-minted entry);
- `test_every_reference_follows_the_new_uuid` covers `libraryentry` and `catalog.release`;
- Edition and Release ids change and stay UUIDv7;
- determinism per `--seed` holds;
- the prune leaves no row of a second library, with that library holding a purchase.

### Task 5: Loader on the new shape

**Files:** `games/management/commands/load_sample_data.py`, `tests/test_library_commands.py`

- `LOADABLE_MODELS` adds `games.edition`, `games.release`; `PRIVATE_MODELS` stays the models with a library field.
- `FIXTURE_RELATIONSHIPS`: `game.parent→game`, `edition.game→game` (required), `release.edition→edition` (required), `release.platform→platform`.
- Release platforms remap through `platform_uuids`, like a Game's.
- The valuation request reads `state.requested_version != state.published_version or stale_purchases(...)`.
- The inline YAML in tests drops legacy rows and gains an edition, a release, an entry event and a purchase event; the collision test names a Release.

### Task 6: Regenerate the fixture and rehearse

1. `make restore-dump DUMP=.dumps/timetracker-2026-10-01.dump`; export its URL.
2. Rehearse the spec's steps 2–8 on it with `--user` the owner. Paste the outputs into the PR body.
3. `DATABASE_URL=… make anonymize-sample ARGS="--user <owner> --seed 1 --force"`.
4. `make loadsample` into a fresh dev database; check the Purchases list, the Library tab and the statistics on the dev server.
5. `make drop-dump`.

**Gotcha:** `make migrate` runs `makemigrations --noinput` first; harmless on a clean tree.

### Task 7: Docs

- CLAUDE.md: the LegacyPurchase model entry, the Signals section, the GeneratedField note, "Six removable models", the `num_purchases` convention, the anonymizer's description, `verify-purchase-conversion`'s table row (historical model; refuses after the drop).
- `docs/database.md:79`, `docs/event-retention.md:250`.
- Wave doc via the organizer session (SendMessage).

### Task 8: Gate, PR, review

The full gate, then `gh stack submit --auto < /dev/null`, a draft PR closing #736 and linking the spec, and the five-agent review.
