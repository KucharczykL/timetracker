# P1: The Purchase aggregate — implementation plan

Spec: [The Purchase aggregate](../specs/2026-10-01-issue-725-purchase-aggregate-design.md).
Template: M1's LibraryEntry (merge `b89a57af`, `git diff b89a57af^1 b89a57af`).

Implementation is inline. Each task ends with `make format`, `make lint-fix`,
`make format-check`, `make vale` and a commit. Iterate with
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check-fast`
and focused `make test ARGS=…`.

## Task 1 — Rename the incumbent (its own commit)

Files:
- `games/models.py`: `class LegacyPurchase`, `Meta.verbose_name = "purchase"`,
  `verbose_name_plural = "purchases"`. Keep every `related_name`.
- `games/migrations/0026_rename_purchase_legacypurchase.py`, hand-written:
  `RenameModel("Purchase", "LegacyPurchase")`, then `AlterModelOptions`
  for the verbose names, then `RunSQL` (forward and reverse) renaming every
  index whose `indrelid` is `games_legacypurchase` or
  `games_legacypurchase_games` from `games_purchase…` to
  `games_legacypurchase…` (a `DO $$ … $$` loop over `pg_index` joined to
  `pg_class`; reverse loops the other way). Run `make makemigrations` after:
  it must report no changes.
- `games/filters.py`: `PurchaseFilter` → `LegacyPurchaseFilter`, its
  `_comparison_model`, `parse_purchase_filter` keeps its name.
- `common/components/custom_elements.py`: `FILTER_MODE_MODELS["purchases"] = "legacypurchase"`.
- Every importer (`grep -rlw Purchase --include=*.py games common timetracker tests e2e`),
  `games/removal.py`, `games/signals.py`, `games/tasks.py`,
  `games/management/commands/{audit_library_ownership,anonymize_sample,load_sample_data}.py`
  (label `games.legacypurchase`, through column `legacypurchase_id`),
  `games/identity_audit.py` (`games_legacypurchase_games`).
- `games/fixtures/sample.yaml.gz`: relabel `model: games.purchase` →
  `model: games.legacypurchase` with a zcat/sed/gzip -n pipe; check the
  byte-determinism test in `tests/test_anonymize_sample.py` does not compare
  against the committed file before rewriting.
- Pinned model keys: `ts/elements/filter-tree/fixtures.json`,
  `tests/test_filter_tree_contract.py`, `tests/test_filter_builder_page.py`,
  `tests/test_filter_widgets.py`, `tests/test_filters.py`,
  `tests/test_library_api_isolation.py`, `tests/test_html_validity.py`,
  `tests/test_stats_links.py`, `e2e/test_filter_builder_e2e.py`,
  `tests/test_library_commands.py`, `tests/test_anonymize_sample.py`,
  `tests/test_uuid_identity_audit.py`, `tests/test_purchase_fk_uuid.py`,
  `tests/test_api.py`, `tests/test_removable_models.py`.

Gate at this commit: no `Purchase` symbol in `games.models`;
`grep -rn 'games\.purchase\b\|games_purchase\b\|"purchase"' games common tests e2e ts`
shows only intended hits; `make typecheck`; full `make check` once (the
rename touches e2e); `make audit-uuid-identity`; migrate forward and back
(`make migrate ARGS="games 0025"`, then forward).

Gotcha: `make migrate` runs `makemigrations --noinput` first. Never run
it with the model renamed but the migration missing: it writes a
delete-and-create migration.

## Task 2 — Endpoint, model, migration

- `games/models.py`: `PurchaseKind(TextChoices)`; `PURCHASE_DAY_COLUMNS =
  OpeningEndpointColumns(...)` beside `ENTRY_ACQUISITION_COLUMNS`
  (`when="purchased"`, `marker="purchase_recorded_at"`, `note="purchase_note"`);
  `PurchaseQuerySet(RemovableMixin, QuerySet)` with
  `ancestor_marks = ("entry", "entry__player_game")`;
  `class Purchase(ProjectionModel)` per the spec's table, id without
  defaults as `LibraryEntry.id`, `comparison_through =
  (("entry__player_game__game", "Game"),)`. Meta: verbose names
  "purchase", constraints `library_identity_constraint()`,
  `purchase_kind_known`, `purchase_amount_not_negative`,
  `purchase_currency_where_amount` (`Q(amount__isnull=True, currency="") |
  Q(amount__isnull=False, currency__regex=r"^[A-Z]{3}$")`), index
  `live_purchase_per_entry_idx` on `(library, entry)` where live.
- `games/endpoints.py`: `PURCHASE_DAY = OpeningEndpoint.over(...)`, into `ENDPOINTS`.
- `games/projections.py`: `ProjectionReference.on(Purchase, "entry")`.
- `games/reads/referrers.py`: `BlockingReferrer.on(Purchase, "entry",
  target=LibraryEntry, sentence=PURCHASE_NAMES_THE_COPY)`.
- Migration `0027_purchase.py` by `make makemigrations ARGS="games --name purchase"`.

Tests (`tests/test_purchase_model.py`): CHECKs refuse unknown kind,
negative amount, amount without currency, currency without amount,
lower-case currency; `alive()` hides a purchase under a removed entry or
tracked game. `tests/test_projection_model.py` `PINNED_DEFAULTS`;
`tests/test_projection_references.py` pairs; `tests/test_referrers.py`
(`RemoveEntry` refused while a live purchase names the entry, passes when
it is removed). `manage.py check` clean (E009, E012, E014).

## Task 3 — Events

- `games/events/references.py`: `entry_reference(entry_id, *, game_name,
  access, format) -> Reference`; `_capture_entry` calls it.
- `games/events/purchase.py`: `PurchaseKindValue` Literal, `AmountText`
  (`Annotated[str, StringConstraints(pattern=r"^\d{1,10}\.\d{2}$")]`),
  `CurrencyText` (`^[A-Z]{3}$` or `""`), payload TypedDicts, nine specs
  (`created`, `kind_changed`, `name_changed`, `amount_changed`,
  `note_changed`, `entry_changed`, `purchase_corrected` through
  `opening_endpoint_events`, `removed`, `restored`), and constructors;
  `amount_text(amount: Decimal | None) -> str | None` uses `f"{amount:.2f}"`.
- Register the module where `games/events/libraryentry.py` is imported
  (find by `grep -rn "events import libraryentry\|events.libraryentry" games`).

Tests (`tests/test_purchase_events.py`): payload refuses `"12.5"`,
`"-1.00"`, a float, lower-case currency; accepts `None` amount with `""`.

## Task 4 — Projector

`games/projectors/purchase.py`, class `Purchases`, family `CURRENT_STATE`,
one handler per event as `Entries` does; `created_at=event.recorded_at`;
`amount` parsed with `Decimal(text)`. Register in `games/projectors/__init__.py`.

Tests (`tests/test_purchase_projection.py`): each event writes its
columns; replay of a stream reproduces the row.

## Task 5 — Commands and scope

- `games/commands/libraryentry.py`: `EntryStatement(NamedTuple)`;
  `entry_creation_events(context, statement) -> CreatedEntry` (events,
  entry id, reference); `RecordEntry.build` packs its fields and calls it.
  `RecordEntry`'s fields do not change.
- `games/commands/scope.py`: factor `_refuse_a_drifted_entry(context, entry)`
  out of `library_entry_row`; add `library_purchase_row` (select_related
  `entry__player_game`, `entry__release__edition__game`; foreign entry →
  `RowUnreadable`; then the drift checks).
- `games/events/dispatch.py`: `CommandName.PURCHASE_RECORD`, `_DESCRIBE`,
  `_CORRECT_PURCHASE` (`library.purchase.correct_purchase`), `_REMOVE`,
  `_RESTORE`.
- `games/commands/purchase.py`: `StatedPrice(NamedTuple)`, `check_kind`,
  `check_price`, `_refuse_a_live_act`, the five commands per the spec.
  `__post_init__` strips name and note, upper-cases and strips currency,
  normalises the `ActStatement`.

Tests (`tests/test_purchase_command.py`), each refusal by sentence:
- Record: named entry; new entry on a tracked game (two events); new entry
  on an untracked game (four events, one correlation); both or neither of
  `entry_id`/`new_entry` refused; removed entry refused; entry under a
  removed game refused; another library's entry → `RowNotHeld`; price
  rules (signed, `-0.00`, three places, too large, amount without
  currency, currency without amount); currency `" eur "` → `EUR`.
- Describe: one event per differing fact; `Unchanged`; unknown price;
  entry of another game refused; removed purchase refused after `Unchanged`.
- CorrectPurchaseDay: moves the day; `Unchanged`; removed refused.
- Remove/Restore: `Unchanged` first; restore under removed entry refused.
- `library_purchase_row`: a purchase whose entry is another library's →
  `RowUnreadable` (seed by raw update, as M1's tests do).
- Fingerprints (`tests/test_endpoint_fingerprints.py`): one per command,
  including the new-entry variant; M1's `RecordEntry` digest unchanged.

## Task 6 — Writes and reads

- `games/writes/purchase.py`: `PurchaseDraft`, `RecordedPurchase`,
  `record_purchase`, `restate_purchase(actor, purchase, *, kind, name,
  price, note, entry_id, purchased: ActStatement | Keep, correlation_id)`,
  `remove_purchase`, `restore_purchase`; `SUBJECT = "purchase"` (add to
  `SubjectNoun` if it is a Literal). `EntryDraft` gains a method mapping
  onto `EntryStatement`.
- `games/reads/purchases.py`: `library_purchases`, `readable_purchases`
  (select_related entry, game, release, platform).
- `tests/purchases.py`: helpers as `tests/entries.py`.

Tests (`tests/test_purchase_writes.py`): `RecordedPurchase` flags;
restate appends nothing when refused; reads hide each of the six marks
and never list another library's purchase.

## Task 7 — API

`games/api.py`: `purchase_router` on `/purchases`. Schemas
`PurchaseEntryIn` (the entry body), `PurchaseIn` (`entry_id` xor `entry`,
`kind`, `name`, `amount: Decimal | None`, `currency`, `note`, `purchased`,
`purchase_note`), `PurchaseUpdate` (named keys; amount with currency,
purchased with purchase_note, or 422; null refused on plain keys),
`PurchaseOut`. Routes as entries': list, get, post (Idempotency-Key),
patch.

Tests (`tests/test_purchases_api.py`): 201 and the row; amount out as
`"12.50"`; 422 on unknown key, on amount without currency key, on both
entry forms; 409 with `check_price`'s sentence on `12.345`; 404 for
another library's entry and purchase; idempotent repeat;
`tests/test_library_api_isolation.py` gains the purchase routes.

## Task 8 — Gates and pinned lists

- `tests/test_projection_replay_gate.py`: `Purchases.handles` in
  `registered_event_types()`, the missing count 50 → 59, a command run
  through every purchase event, including a new-entry creation that
  tracks a game; snapshot `Purchase` rows.
- Rebuild tuples gain `("games_purchase", 0, 0, 0)` last:
  `tests/test_projection_replay_gate.py`, `test_playthrough_projection.py`,
  `test_historical_playtime_projection.py`, `test_event_benchmark.py`,
  `test_playergame_projection.py`.
- `tests/test_uuid_identity_audit.py`: the new table.
- `make audit-uuid-identity`, `make verify-replay-parity` on the dev DB.

## Task 9 — Docs

CLAUDE.md: the `Purchase` bullet split into `LegacyPurchase` (until P5)
and the `Purchase` projection; the API list. Then the docs sweep.

## Verification on a dump

`make fetch-dump` may be blocked; if so, ask the user for the dump, then
`make verify-dump` and `make verify-baseline ARGS="--migrate"`.
