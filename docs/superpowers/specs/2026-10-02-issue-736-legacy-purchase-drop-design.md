# The legacy purchase is gone

Issue: [#736](https://github.com/KucharczykL/timetracker/issues/736),
member P5c of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md),
the last member of stack #1409.

## What goes

Migration `0035_delete_legacypurchase` drops `LegacyPurchase`, its
through table `games_legacypurchase_games`, and every index P1 renamed
to `games_legacypurchase_*`. It is generated, and it reverses in schema.
With the table go:

- the float cache: `converted_price`, `converted_currency`,
  `needs_price_update`, `num_purchases`, `price_per_game`, and the legacy
  half of `convert_library_prices` (`LegacySnapshotRow`, the legacy loop,
  `_required_rate`, `MissingExchangeRate`, the legacy check in
  `_changed_since`). The task values purchases alone. A missing rate
  already skips one purchase with a warning; the failed status and its
  one retry stay for a `DatabaseError`;
- `LegacyPurchase.save()`'s conversion request;
- the two `m2m_changed` receivers in `games/signals.py`;
- `LegacyPurchase` in `REMOVABLE_MODELS` and the Game removal's
  `_recount_purchases`;
- the three legacy checks in `audit_library_ownership` and its count;
- `games_legacypurchase_games` in `RESIDUAL_INTEGER_PRIMARY_KEYS`, the
  identity audit's only auto-created through table. `include_auto_created`
  stays, and its test states a doctored through table, as the residual
  inventory's test already does;
- `calculate_price_per_game` and its commented schedule in `games/apps.py`.
  The function only removed its own lingering schedule row, so 0035
  removes that row instead.

The stale `legacypurchase` content type stays; nothing reads it.

`RETIRED_FILTER_MODELS` keeps `legacypurchase`, so a stored filter that
names it is refused with its sentence and never read as an unknown model.

No legacy route is left: P5b retired them.

## What stays until the squash

Migration `0031_purchase_conversion` runs the pass in the deploying image,
so the pass, `verify_purchase_conversion` and the reconciliation stay
until the deployment records 0031 and the history is squashed (#1448).

They read the historical model. `legacy_purchase_model()`
(`games/backfill/legacy_model.py`) answers `LegacyPurchase` from the
migration state `0034_conversion_review_hidden`, and raises
`LegacyTableGone` where the table is absent, so the command refuses with
one sentence after the drop. Every module and fixture #1448 removes
carries the comment `conversion-tooling`, so one grep finds them.

The deploy-day rehearsal, on that day's dump, every step after the first
with `DATABASE_URL` set to the URL the restore prints:

1. `make restore-dump`;
2. `make migrate ARGS="games 0030_purchasevaluation"`;
3. `make verify-purchase-conversion ARGS="--user X --snapshot S"` (rolled
   back);
4. the same with `--confirm X`;
5. `make migrate ARGS="games 0034_conversion_review_hidden"`, which
   appends nothing once every library holding legacy rows was confirmed;
6. `make migrate`, the drop;
7. `make verify-purchase-statistics ARGS="--user X --snapshot S"`;
8. `make verify-replay-parity`, `make verify-dump`,
   `make verify-baseline ARGS="--migrate"`.

## The sample fixture

The anonymizer keeps which copy a purchase names. A refund's copy end
follows the refund on the copy the purchase names, and a pass names its
base game's copy; another copy breaks both. The entries already say which
games the library holds, so a move hides nothing. Days shift by the game's
offset, amounts are redrawn, names and notes cleared, and
`source_metadata` cleared, so the sample shows no conversion review.

`make anonymize-sample` reads the new shape. The fixture carries Platform,
Game (the conversion's DLC Games included, `parent` remapped), Edition,
Release, the event store and ExchangeRate; no legacy rows.

- Edition and Release join the identity re-minting at `FIXED_EPOCH` in
  key order, since neither has a `created_at`.
- A reference to a projection row (`LibraryEntry`, `Resolution.PROJECTED`)
  is captured from the row and then takes the aggregate's new id, as a
  device reference does; the payload and `LibraryEventReference` both.
  Today only devices take that path, so a purchase would name a stale
  copy and the loader would refuse it.
- The prune removes another library's projection rows before its Games,
  since the projections hold `RESTRICT` keys.
- A DLC Game the conversion named after the legacy purchase is a Game
  like any other: `name_overrides` covers its name, as it covers every
  Game's. Edition names ship as catalog data.

`load_sample_data` loads Edition and Release, which carry no library
field, and checks four more relationships: `game.parent`, `edition.game`,
`release.edition`, `release.platform`, the last remapped as a Game's
platform is. A valuation run is requested where `stale_purchases` is not
empty or the state is behind. The fixture is regenerated from the
2026-10-01 dump, restored and migrated through the pass.

## Tests

A test that builds legacy rows reads the historical model. The fixture
`legacy_purchase` (`tests/legacy_purchases.py`) renders the state at 0034
once per process and creates the model's table and through table with
`schema_editor.create_model` inside the test's own transaction; the
rollback takes both away. It refuses a `transaction=True` test, whose
flush would meet an undeclared table. The historical model takes keys,
not instances (`library_id=`, `.games.add(game.pk)`), and has no
`save()` rules, signals or `for_library()`, so a test states
`num_purchases` where a figure reads it.

`test_purchase_migrations.py` steps through 0035 itself; its conversion
case reads the model from the executor's state.

Tests of the float cache, the signals, the recount and the legacy model's
own rules go with the code they test, the module-wide transactional
`test_retention.py` legacy half included. A test that used
`LegacyPurchase` as a generic subject (a GeneratedField, a nullable date,
a removable model, a UUID foreign key) takes another model with that
shape. No live model keeps a forward many-to-many field, so the filter
tests of that branch declare one on an isolated test model; the branch
stays, since a model may declare one again. Exact-list
pins move with the lists: the identity audit's tables, the removable
models' builders, the anonymizer's generated keys, the loader's inline
YAML.

`docs/database.md` and `docs/event-retention.md` drop the legacy columns
they name.

## Follow-up issues

- #1448 removes the pass and its tooling at the squash.
