# The Purchase aggregate

Issues: [#725](https://github.com/KucharczykL/timetracker/issues/725),
[#726](https://github.com/KucharczykL/timetracker/issues/726),
[#828](https://github.com/KucharczykL/timetracker/issues/828), member P1 of
the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
Charter: [Access, ownership, purchases, and add-ons](2026-08-09-timetracker-overhaul-design.md#access-ownership-purchases-and-add-ons).
After: [The LibraryEntry aggregate](2026-09-29-issue-719-libraryentry-aggregate-design.md).

P1 is the first member of the stack P1 to P5, which lands in one
`gh stack merge`. No deployed `main` holds P1 without P4 and P5.

## Purpose

A purchase is one financial transaction for one item: a game, a season
pass, a battle pass or an upgrade. It names the copy it paid for, a
`LibraryEntry`. Its amount is a decimal, or unknown. Zero is free (#828).
P1 makes the purchase an event-sourced aggregate with commands, a
projection and an API. It switches no screen and no reader.

## The legacy model steps aside

The legacy `Purchase` row stays live until P5: its forms, its list, the
statistics, the filters and the valuation task read and write it. It
cannot become the projection in place. `games.checks` refuses its
`auto_now` timestamps (E001, E002), its minted UUID default (E005) and its
unregistered `platform` and `related_game` keys (E009). Its through table
`games_purchase_games` holds a foreign key into it, and a rebuild that
reproduces no legacy row would make the swap refuse. Its `removed_at` is
stamped by `games.removal`, not by a projector.

So P1 renames the incumbent. The legacy class becomes `LegacyPurchase`
on table `games_legacypurchase`, and the through table follows. **P5
deletes `LegacyPurchase`, its tables, and every reader and route that
uses it; the rename is temporary.** The new `Purchase` is born on
`games_purchase` in the shape the wave states, less P2's refund columns.
A temporary name on the newcomer was the alternative; the wave organizer
refused it, because its model label would enter event types the stream
keeps forever.

P4 owns the conversion's identities. The wave records the rule: the
first game of a legacy row, in key order, takes the legacy UUID; every
other game of a bundle takes a new one. The new one must be a UUIDv7
(`canonical_uuid_text` refuses any other), and `check_ordering` in
`games/identity_audit.py` must still find UUID order equal to
`(created_at, pk)` order, so P4 states the whole pass under one
`recorded_at`, and idempotency comes from the keys (legacy id and game
id), not from the aggregate id.

### What the rename touches

The class name, its imports and type checks are mechanical. Six
mechanisms key on the model's name or table, and each needs its own edit:

- **The filter machinery.** `filter_for_model` reads
  `globals()[f"{model.__name__}Filter"]`, and `FILTER_MODE_MODELS`,
  `reachable_models`, the builder page and `/api/filter/count` key on
  `_meta.model_name`. So `PurchaseFilter` becomes `LegacyPurchaseFilter`,
  `FILTER_MODE_MODELS["purchases"]` becomes `"legacypurchase"`, and every
  pinned `"purchase"` model key moves (`ts/elements/filter-tree/fixtures.json`,
  `tests/test_filter_tree_contract.py`, `tests/test_filter_builder_page.py`,
  `tests/test_filter_widgets.py`, `tests/test_filters.py`,
  `tests/test_library_api_isolation.py`, `tests/test_html_validity.py`,
  `tests/test_stats_links.py`, `e2e/test_filter_builder_e2e.py`).
  `LegacyPurchase.Meta` states `verbose_name = "purchase"`, so every label
  a person reads stays. The filter *mode* `purchases` and every stored
  field name (`purchase_filter`, `purchase_count`) stay. Without this edit
  the key `"purchase"` resolves to the new projection, whose manager has
  no `for_library`, and the builder answers 500.
- **Labels in data.** The sample fixture's `games.purchase` becomes
  `games.legacypurchase`, rewritten in place, since regeneration needs the
  production database; `load_sample_data`, `anonymize_sample`,
  `tests/test_library_commands.py` and `tests/test_anonymize_sample.py`
  name the label too.
- **The through column.** `RenameModel` renames `purchase_id` to
  `legacypurchase_id`, so `audit_library_ownership` and `anonymize_sample`,
  which name the column, move with it.
- **Table names.** `games/identity_audit.py`,
  `tests/test_uuid_identity_audit.py`, `tests/test_purchase_fk_uuid.py`,
  `tests/test_api.py`.
- **The valuation path.** `games/tasks.py` filters and bulk-updates the
  legacy rows; it is the silent-fallthrough shape, so the grep names it.
- **Registries.** `REMOVABLE_MODELS` and its recount in
  `games/removal.py`, `tests/test_removable_models.py`, the `m2m_changed`
  sender in `games/signals.py`, the price signals.

The Advanced filter route keys on the model name too, so the
purchases builder moves from `/purchase/filter` to
`/legacypurchase/filter` until P5. That bookmark breaks for the stack's
lifetime, which no deployment sees.

The content type `games.purchase` and its permissions move to
`legacypurchase`; the new model gets fresh ones. Nothing reads them.
Related names stay: `Game.purchases`, `Game.addon_purchases`,
`UserLibrary.purchases`. Other URL names, views and readers keep
their behaviour.

A missed site fails silently once the new `Purchase` exists, because
`.objects` and `library` exist on both. So the rename is its own commit,
with no `Purchase` symbol in `games.models`, and mypy, the full suite and
a grep for `games.purchase`, `games_purchase` and the `"purchase"` model
key run at that commit. The new class arrives in a later commit.

### The migrations

The rename migration is written by hand. `make makemigrations` runs
`--noinput`, so the autodetector never asks whether `Purchase` was
renamed and emits a deletion and a creation, which would drop every row.
It holds `RenameModel("Purchase", "LegacyPurchase")` and the index
renames below. The wave doc's `AlterModelTable` is superseded:
only `RenameModel` moves the content type, the through table and its
column. The new `Purchase` arrives in a later migration and a later
commit, so `make check-migrations` is green at each.

### The legacy indexes

`RenameModel` renames the tables and the through column but no index. A
repro on the development database showed every index keeping its
`games_purchase_*` name, and the new table's `library_id` index then fails
with `relation "games_purchase_library_id_1dea77f7" already exists`. The
migration renames every index of the two legacy tables, found through
`pg_index.indrelid` and never by name prefix (the prefix also matches
`games_purchaseconversionstate_*`), primary keys and the unique index
included, replacing the leading `games_purchase` with
`games_legacypurchase`; reverse renames back. The deployment's index
names come from its own history, so `make verify-dump` and
`make verify-baseline ARGS="--migrate"` on a production dump verify the
migration there.

## Storage

Table `games_purchase`, model `Purchase(ProjectionModel)`, written only by
the `Purchases` projector.

| Column | Meaning |
|---|---|
| `id` | the creation event's aggregate id; no default |
| `library` | from the envelope |
| `entry` | `LibraryEntry`, `RESTRICT`, required, `related_name="purchases"` |
| `kind` | `PurchaseKind`: `game`, `season_pass`, `battle_pass`, `upgrade` |
| `name` | product name, blank by default |
| `amount` | `DecimalField(12, 2)`, null unknown, 0 free |
| `currency` | three upper-case letters, blank exactly where `amount` is null |
| `purchased`, bounds, `purchase_recorded_at`, `purchase_note` | the opening endpoint `PURCHASE_DAY` |
| `note` | text |
| `created_at` | the creation's `recorded_at` |
| `removed_at` | the projector's mark |

`Meta.constraints` holds `library_identity_constraint()` (`games.E012`).
CHECKs: `kind` known; `amount >= 0`; currency matches `^[A-Z]{3}$` where
`amount` is not null and is blank where it is null. `alive()` reads the
purchase's mark, the entry's and the tracked game's
(`ancestor_marks = ("entry", "entry__player_game")`). A partial index on
`(library, entry)` covers live rows. `comparison_through` reaches the Game
through `entry__player_game__game`. `Purchase.entry` joins
`AUDITED_PROJECTION_REFERENCES`.

`OpeningEndpoint` `purchase` over `PURCHASE_DAY_COLUMNS` joins `ENDPOINTS`.
The act's noun is "purchase", so every recorded name follows the naming
rule: columns `purchased` beside `purchase_recorded_at`, event
`purchase_corrected`, `CommandName` value `library.purchase.correct_purchase`.
Python identifiers say "day" (`CorrectPurchaseDay`, `PURCHASE_DAY`),
because "correct purchase" reads as correcting the whole row; no record
holds an identifier.

## Events

Stream `library.purchase`, aggregate type `purchase`.

| Event | Payload |
|---|---|
| `created` | `entry` (a `Reference`, kind `libraryentry`), `kind`, `name`, `amount`, `currency`, `note`, `purchase_note`; the day is `effective_time` |
| `kind_changed`, `name_changed`, `note_changed` | the one fact |
| `amount_changed` | `amount` and `currency`, one fact |
| `entry_changed` | `entry` |
| `purchase_corrected` | the opening endpoint's correction |
| `removed`, `restored` | empty |

`amount` travels as canonical text, two decimal places (`"12.50"`), or
null. JSON carries no decimal, and a float is the defect this wave
removes. `AmountText` is a `str` constrained to `^\d{1,10}\.\d{2}$`, with
no sign, so the vocabulary refuses any other spelling. The command
writes it with `f"{amount:.2f}"`, never `str()`, which spells `1E+2`.

`entry` is a `Reference`, so the replay gate checks it against the entry's
creation event. On the new-entry path the row does not exist at `build`,
so the command builds the reference from what it states: one
`entry_reference(entry_id, game_name, access, format)` in
`games/events/references.py`, which `_capture_entry` calls too.


## Commands

`games/commands/purchase.py`. Every command resolves through
`library_purchase_row`: `RowNotHeld` for a key the library does not hold,
and `RowUnreadable` where the purchase's entry, or that entry's tracked
game or private Release, is another library's. It loads the entry with
the purchase, refuses an entry of another library itself, then runs the
two drift checks `library_entry_row` makes, factored out into a function
over a loaded entry that both call. Calling `library_entry_row` would
answer a foreign entry with `RowNotHeld`, a 404, where the row is the
defect. Every refusal has a
sentence. `Unchanged` comes ahead of every refusal. One
`_refuse_a_live_act` refuses a removed purchase, entry or tracked game,
and every command but the creation and the restore calls it.

| Command | Rule |
|---|---|
| `RecordPurchase` | Names `entry_id`, or `new_entry`, an `EntryStatement`; exactly one. `EntryStatement` is a commands-layer `NamedTuple` (release id, access, format, note, and an `ActStatement`), because the fingerprint encodes a tuple and refuses a dataclass. `RecordEntry` keeps its five flat fields, so its pinned fingerprint (`tests/test_endpoint_fingerprints.py`) holds; its `build` packs them into an `EntryStatement`. A new entry is created in the same dispatch by the events `RecordEntry` builds, the tracking pair first where the game is untracked; the shared builder is `entry_creation_events` in `games/commands/libraryentry.py`, answering the events and the new entry's id and reference. A named entry must be live under a live tracked game. |
| `DescribePurchase` | `None` states nothing. `price: StatedPrice`, a `NamedTuple`, states amount and currency together; `StatedPrice(None, "")` is unknown. One event per differing fact. A new entry must be a live entry of the same game. |
| `CorrectPurchaseDay` | `correct_opening_endpoint`, `_refuse_a_live_act` as its `before_event`. |
| `RemovePurchase` | `Unchanged` if removed; refuses under a removed entry or tracked game. This is the charter's void: the stream keeps the money. |
| `RestorePurchase` | `Unchanged` if live; refuses under a removed entry or tracked game. |

The price rule is one function, `check_price`: a signed amount
(`Decimal.is_signed()`, so `-0.00` too), one with more than two places, or
one above `9999999999.99` is refused; a currency is
stripped and upper-cased in `__post_init__`, so restatements fingerprint
alike, and is required exactly where an amount is stated. A command never
quantises: P4 does that for the legacy floats, and a person states cents.

`RemoveEntry` already asks `blocking_referrer`. P1 registers
`BlockingReferrer.on(Purchase, "entry", target=LibraryEntry, sentence=...)`
with the sentence "A purchase names this copy. Remove the purchase first."

## Writes and API

`games/writes/purchase.py`: `record_purchase` answers `RecordedPurchase`
(purchase id, entry id, whether an entry was created, whether the game was
tracked) from `dispatched_events`; `restate_purchase` describes, then
corrects the day, under one correlation; `remove_purchase`,
`restore_purchase`. Each runs under `answered("purchase")`.

`games/reads/purchases.py`: `library_purchases(library)` and
`readable_purchases(library)`. The scope is the purchase's library and
mark, then `library_entries`'s conditions through `entry`: six marks
(purchase, entry, tracked game, Release, Edition, Game) and three library
pins (`library`, `entry__library`, `entry__player_game__library`).

Routes on `/api/purchases/`: `GET /` (`limit`, `offset`, `limit=0`
unbounded), `GET /{id}`, `POST /` (`Idempotency-Key`, 201), `PATCH /{id}`.
Bodies are `extra="forbid"`; a named key is the act; `amount` is
`Decimal | None` with no schema constraint, a JSON number or string in
and a string out, so `check_price` alone refuses a bad amount, with its
sentence at 409; `amount` and
`currency` travel together, as do `purchased` and `purchase_note`, or 422.
`POST` takes `entry_id` or `entry` (the entry body), never both.
Removal has no route in P1, as entries had none in M1.

## Pinned lists

These enumerate projections, events or registries, and grow by the
purchase: `registered_event_types()` in
`tests/test_projection_replay_gate.py` and its count of missing types
(50, then 59); the rebuild table tuples, sorted by table, which gain
`("games_purchase", 0, 0, 0)` last, in the replay-gate, PlayerGame,
Playthrough, HistoricalPlaytime projection and benchmark tests;
`PINNED_DEFAULTS` in `tests/test_projection_model.py`; the expected pairs
in `tests/test_projection_references.py`; the identity tables in
`tests/test_uuid_identity_audit.py`; `CommandName`; the projector package.

## Verification

- The replay gate runs every new event type, including a creation that
  carries an entry and tracks a game.
- A fingerprint test per command, and the price normalisation.
- Two-library tests: another library's entry is 404 on create and on move;
  another library's purchase is never listed.
- `make audit-uuid-identity` passes over the renamed tables.
- The migration applies forward and back on the development database,
  and `make verify-dump` and `make verify-baseline ARGS="--migrate"` pass
  on a production dump.

## Limits

- No screen and no reader change; the Purchases list stays on
  `LegacyPurchase` until P5.
- No refund (P2), no valuation (P3), no conversion (P4).
- A purchase does not move to another game.
- `entry_changed` moves a purchase between copies. P2's refund ends the
  entry's access; P2 refuses or carries that end when a refunded purchase
  moves.

## Follow-up issues to file

None. Every cut item is a later stack member with its own issue; the
wave doc records the rename, the index trap and the event name.
