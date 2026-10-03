# Access and Purchases delivery wave

Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601).
Charter: [Access, ownership, purchases, and add-ons](2026-08-09-timetracker-overhaul-design.md#access-ownership-purchases-and-add-ons),
[Catalog identity](2026-08-09-timetracker-overhaul-design.md#catalog-identity),
[Mandatory, quiet playthroughs](2026-08-09-timetracker-overhaul-design.md#mandatory-quiet-playthroughs)
(the `Purchase.infinite` paragraph above it).
Builds on: [A device's access ends](2026-09-28-issue-1275-device-access-end-design.md)
(the stated endpoint), [The Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md),
[Catalog](../../catalog.md), [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md).

The charter is the contract. The wave issues #719–#736 hold one line each
and link to a branch that no longer exists; where an issue body and the
charter differ, the charter holds, and this document records what the wave
decided where the charter is silent.

## Purpose

A library says two different things about a game. It has the game: a route
of access to one Release, with a beginning and sometimes an end. It paid
for the game: one financial transaction, with an amount, a currency and a
possible refund. Today both live on one row, `Purchase`, and its eight
`ownership_type` words mix three axes: format (Physical, Digital), access
(Rented, Borrowed, Trial, Demo, Pirated) and product (Digital Upgrade). A
demo, a rental and a pirated copy are recorded as purchases at price 0, and
0 also means "I do not remember the price".

The wave moves the library's access onto `LibraryEntry`, makes `Purchase` an
event-sourced aggregate of one item with decimal money, gives DLC its own
catalog identity, splits `infinite` into two explicit facts, and converts
the deployment in one visible cutover, the way charter step 12 asks. The
Access wave and the Purchase wave are one wave because the two aggregates
share one form, one conversion and one set of statistics.

## Product boundary

In:

- `LibraryEntry`: one route of access to one Release, with access, format,
  an acquired day, an end of access with a way, a resume, a note.
- `Purchase` as an aggregate: one item, an entry it names, kind, name,
  decimal amount or unknown, currency, purchased and refunded days, note.
- `PurchaseValuation` in decimals, one per purchase and target currency,
  written by the currency task alone.
- `Game.kind` and `Game.parent`, in IGDB's words.
- `PlayerGame.excluded_from_dropped` beside `excluded_from_unfinished`.
- `Edition.kind`, so a demo or a beta is a prerelease Edition of its
  game with a Release per platform, made and picked like any other; the
  toggle that hides prerelease play is #1361, after #1354.
- The Add to library form, the Games page's Library tab, the Purchases list made
  selectable, the Games list's Access column, Game detail's Library and
  Add-ons sections, filters, presets, statistics, the API.
- The conversion of every existing row, its preflight, its parity gate and
  a review surface for the rows the person wants to look at.

Out, each named in [Cross-wave handoffs](#cross-wave-handoffs): a Release on
a session or a record, bulk end of access, a device's resume and acquired
day, the IGDB importer, the Journal's purchase facts, the exchange-rate
repair surface, the statistics card #1157 draws.

## What the data says

Read on the 2026-09-28 dump. One library, 808 live purchases.

| Fact | Count |
|---|---|
| Digital / Physical / Rented / Demo / Pirated / Borrowed / Digital Upgrade | 678 / 48 / 36 / 34 / 7 / 4 / 1 |
| Refunded, all Digital, median one day after purchase | 221 |
| Rented on Xbox Gamepass / on PlayStation 3, 4 and 5 | 6 / 29 |
| Price 0: Owned digital / non-owned (rental, demo, pirated, borrowed) | 73 / 81 |
| Price 0 and Owned, on Epic Games Store / Steam / PlayStation 5 / other | 19 / 35 / 8 / 11 |
| Bundles (2 to 8 games), 38 games in all | 7 |
| Add-ons: DLC / season pass / battle pass, every one naming the base game as its only game | 35 / 4 / 2 |
| Named purchases: add-ons / games | 41 / 10 |
| Single-game purchases whose platform is not the game's / with no platform | 14 / 8 |
| Games with two or more purchases | 39 |
| `infinite` rows / games / games with an infinite purchase beside a normal one | 33 / 30 / 6 |
| Prices with more than two decimals | 2 |
| Currency spelled in mixed case | 3 |
| Currencies stated: CZK, CNY, USD, EUR, JPY | 5 |
| Games / Editions / Releases; games with two Releases | 863 / 864 / 864; 0 |
| Purchases naming a game the library does not track | 0 |
| Saved purchase presets | 0 |
| Demo purchases / of them games also owned / games holding a hand-made second run for the demo | 34 / 7 / 2 |
| Sessions before the run's start on a game holding a Demo purchase | 1 |
| Sessions before the game's earliest catalog release day / games | 72 / 18 |

The person stopped recording demos as purchases so as not to clog the
library, and played 10 to 20; catalog release days are year-coarse port
dates, so "before release" finds mostly the wrong sessions.

Three readings shape the design. Every row today is the way the library
says "I have this", money or none, so the form that records access stays
one form. Rentals are largely 2021–2022 PlayStation and Gamepass catalog
play, so the charter's `Subscription` word is needed on day one. Every
add-on names the base game, so a DLC has no catalog identity yet and the
conversion must state one.

## Aggregates and storage

#1275 is on `main`. M1 (PR #1362), M2 (PR #1366), M3 (stack #1379:
PRs #1377, #1378, #1380), M7 (PR #1390) and M8 (PR #1397) are on `main`
too, migrations `0020` to `0025`; the next is `0026`. The contracts are
[The LibraryEntry aggregate](2026-09-29-issue-719-libraryentry-aggregate-design.md),
[A copy's access ends and resumes](2026-09-29-issue-721-entry-access-end-design.md),
M3's own,
[Game kind and parent](2026-09-30-issue-1353-game-kind-and-parent-design.md)
and [Excluded from dropped](2026-09-30-issue-1334-excluded-from-dropped-design.md).

### The opening endpoint

The stated endpoint of #1275 is an act a row states after it exists: three
events, stated, corrected, voided. An entry's acquired day and a purchase's
purchased day are different: the creation states them, a correction moves
them, and there is nothing to void, because a row with no acquisition is
no row. The primitive gains an **opening endpoint**: the same columns (the
day, its two bounds, the marker, the note), one correction event, and no
`stated` or `voided` spec. The creation event's `effective_time` is the
day; the projector writes the marker from the creation's `recorded_at`.
`games.E014` holds the columns of both variants. This is M1's first task,
and the purchase's day reuses it.

### LibraryEntry

A new aggregate, stream `library.libraryentry`, projection
`games_libraryentry`, written only by the `Entries` projector.

| Column | Meaning |
|---|---|
| `id` | the aggregate id |
| `library` | the owning library |
| `player_game` | the tracked game, `RESTRICT`, registered in `AUDITED_PROJECTION_REFERENCES`; every read reaches the Game through it, as the other projections do |
| `release` | the Release, `RESTRICT`, through the existing `catalog.release` reference kind; a Release of `player_game`'s game, which a command rule and the replay gate hold |
| `access` | `owned`, `borrowed`, `rented`, `subscription`, `trial`, `demo`, `pirated` |
| `format` | `physical`, `digital`, `unknown` |
| `note` | text |
| `acquired`, `acquired_lower`, `acquired_upper`, `acquisition_recorded_at`, `acquisition_note` | the opening endpoint |
| `access_ended`, bounds, `access_end_recorded_at`, `access_end_note`, `access_end_way` | the stated endpoint |
| `removed_at` | the projector's mark |

The end endpoint's ways are `returned`, `expired`, `revoked`, `refunded`,
`sold`, `lost`, `given_away`, `broken`, `stolen`, and `unstated` ("Not
said"), which a one-click end states with the calendar's day and
`way_words()` renders as nothing; `EndWay` in `games/end_ways.py` grows
by those five, and the entry's payload states its own subset as a
`Literal`.

A resume is a fact, not a void. `access_resumed` is dated, writes the end
columns back to their unstated values, and the history keeps every end.
"Formerly owned" reads `access_end_recorded_at`. #1344 copies this shape
for a device.

Two `CHECK`s admit only the words; a third admits a way exactly where the
marker is set. The row is unique on `(id, library)`; a partial index on
`(library, release)` covers live rows. The reference kind is
`libraryentry`, resolution `PROJECTED`, named as `device` is.

`Release` carries no `library` column, so `LIBRARY_PATHS` in
`games/projections.py` gives a catalog row its path to a library,
`ProjectionReference` carries it as `library_path`, `games.E015` refuses
a path that ends elsewhere, and `visible_row` in `games/commands/scope.py`
resolves a shared row or the library's own through it. So
`audit_library_ownership` reports an entry naming another library's
private Release, `entry_game_violations` reports one whose Release is not
its game's, and the swap's refusal sentence can name either.

### Purchase

`Purchase` becomes an aggregate, stream `library.purchase`, keeping the
same UUIDs. The legacy row cannot become the projection in place: a
`ProjectionModel` fails `games.E001`/`E002`/`E005`/`E009` on the legacy
columns, its mark is `remove()`'s rather than a projector's, the M2M
through table points into it, and its rows hold no events, so a rebuild
would drop them. So P1 renames the incumbent: the legacy class becomes
`LegacyPurchase` on `games_legacypurchase` (`AlterModelTable`, the
through table following, the sample fixture relabelled mechanically),
and the new `Purchase` is born on `games_purchase` in its final shape.
Every reader keeps reading `LegacyPurchase` until P5 switches it; P4's
pass writes one `purchase.created` per (legacy row, game): the first
game in key order keeps the legacy UUIDv7, and the rest of a bundle
mint a UUIDv7 at the pass, since `canonical_uuid_text` refuses any
other version and `make audit-uuid-identity` holds UUID order to
`(created_at, pk)` order; the whole pass states one `recorded_at`, so
`created_at` ties and the key breaks them, and idempotency comes from
the keys (legacy id, game id), never from the aggregate id; P5 drops `LegacyPurchase`, its
tables and every legacy reader, with no rename at the cutover.
`RenameModel` keeps every index's `games_purchase_*` name, so the new
table's own indexes would collide; P1's migration renames the legacy
indexes to `games_legacypurchase_*`, and P5's drop reads them under
that name. The
stack stays one merge, so `main` never holds both.

| Column | Meaning |
|---|---|
| `id`, `library` | as today |
| `entry` | the LibraryEntry, `RESTRICT`, required, registered; a pass or an upgrade names a base game's copy: a live, Owned, unended one, the one on the pass's platform first, then earliest acquired, then key |
| `kind` | `game`, `season_pass`, `battle_pass`, `upgrade` |
| `name` | the product name; blank for a game |
| `amount` | `DecimalField(12, 2)`; null is a price nobody knows; 0 is free |
| `currency` | ISO code; required exactly where `amount` is stated, by `CHECK` |
| `purchased`, bounds, `purchase_recorded_at`, `purchase_note` | the opening endpoint |
| `refunded`, bounds, `refund_recorded_at`, `refund_note` | the stated endpoint |
| `note` | text |
| `removed_at` | the projector's mark |

Gone at the cutover: `games`, `platform`, `related_game`, `type`,
`ownership_type`, `infinite`, the float `price`, `converted_price`,
`converted_currency`, `needs_price_update`, `num_purchases`,
`price_per_game`, `date_purchased`, `date_refunded`, and the three price
signals. Game and platform are read through the entry.

A `ProjectionModel` must hold events for every row: the replay gate
rebuilds every projection, and `games.E014` admits an endpoint on no other
model. So the Purchase aggregate, its conversion and the cutover are one
stack (see [Delivery order](#delivery-order)); no deployed `main` carries
a projection whose rows have no events.

A DLC is a Game, so `dlc` is not a purchase kind.

Two readers walk the M2M that goes. `PURCHASE_RUNS` in
`games/reads/playthrough_completions.py`, which the Purchases list's
Finished column and the `finished` sort read, becomes
`entry__player_game`. `GameFilter.purchase_count` counts
`player_games__entries__purchases`; `purchase_price_total` sums the
valuation amounts at the library's published target through a subquery on
the purchase key.

### PurchaseValuation

Conventional, per the charter. One row per `(purchase, target_currency)`,
holding the purchase's **key**, never a foreign key: nothing outside the
projections may point at a projection row, and a foreign key would block
or empty the swap. Columns: `library` (CASCADE, for the purge),
`purchase_id` a bare UUID, `target_currency`, `amount` Decimal(26,2)
(the product computed in a 60-digit context and quantized once, half
up), `rate` Decimal(24,12) null exactly where the purchase needs none
(same currency, or amount 0) and otherwise equal to the stored
`ExchangeRate`, so a stray same-currency rate row makes nothing stale, the three inputs it read (`source_amount`,
`source_currency`, `rate_year`, the rate's identity being the two
currencies and the year), `version`, `calculated_at`. The currency task is
its sole writer: it values the whole live set per version, and
publication replaces the library's valuations whole in the transaction
that sets `published_version`, so one target per library is ever read.
No row exists for an unknown amount; a free purchase values at 0. The
rate's year is `purchased_lower`'s, then `purchased_upper`'s (an open
start has no lower), then the year of `purchase_recorded_at` in the
calendar zone, since the price is known, and the rate row the valuation
names says which year was read. `ExchangeRate.rate`
becomes Decimal(24,12), migrated through `repr(float)`, the fetch parsing
with `parse_float=Decimal`; the legacy converter keeps its whole-unit
output until P5. `PurchaseOut` answers `valuation`, null or `{amount,
currency}` at the published target.

The per-library run state that #630 built (`PurchaseConversionState`:
requested and published version, status, retry) stays under its name and
points at valuations. Its trigger moves: `Purchase.save()` bumps the
requested version today, and a projector never calls `save()`, so the
write path in `games/writes/purchase.py` calls `request_revaluation(library)`,
which locks the state row and reuses its own `requested_currency`, after any
dispatch that states an amount or moves the day (`VALUATION_EVENTS`:
`created`, `price_changed`, `purchase_corrected`, `restored`), after the dispatch
returns, lossy by design. The task's trigger is `requested > published`
**or** a live purchase with an amount and no valuation at the published
target whose three stored inputs equal the purchase's and whose `rate`
equals the stored `ExchangeRate` (so a corrected rate, #493, invalidates),
the year computed in SQL alone (`valuation_year(zone)`, read by the
task's snapshot and by `stale_purchases` alike) as
`Coalesce(year(purchased_lower), year(purchased_upper),
ExtractYear(purchase_recorded_at, tzinfo=calendar_day_zone(library)))`,
never UTC: a lost bump of any kind costs one day, and a row no
write path saw (P4's pass, any direct appender) is valued by the same
check: the recovery requests every library at rest whose
`stale_purchases` is not empty, and `load_sample_data` requests after
its replay. A purchase whose (currency, rate year) has no rate (a
typo'd code, a future-year pre-order) is skipped and logged at WARNING,
the rest of the library publishes, and the skipped one stays in
`stale_purchases` for the daily recovery to ask again; the legacy
cache keeps its old rule and still fails its run on a missing rate.
#1418 reports the skipped purchases beside #493's repair surface. So
`needs_price_update` has no successor and `dispatch` gains no hook. The
float cache and its writer go at the cutover.

The legacy converter rounds `converted_price` to a whole unit. P4 seeds
valuations from `converted_price` through `publish_valuations(library,
rows)` in `games/valuations.py`, each row built with `seeded(...)`, a
sibling of `value()` under the same rate rule, since a whole-unit amount
is not `amount × rate`, under
the pass's transaction and the state lock (it deletes and inserts the
library's whole set), carrying that rounding with inputs that read
current, then calls `request_revaluation(library)` once, so the
first refresh after the cutover moves every total to the decimal rate,
and the reconciliation prints both.

### Game

`kind`: `main`, `dlc`, `expansion`, `standalone_expansion`. The words are
IGDB's `game_type` words; #782 admits the rest (remake, remaster, port and
the others) when it meets them, and maps one to one. `parent`: a Game,
`RESTRICT`, null exactly where the kind is `main`, IGDB's `parent_game`.
Both are Game columns, written by `save_game_columns` in
`games/catalog_submit.py` from `GameForm`, beside the graph
`state_catalog_graph` writes, and by the conversion pass through the
same two; a shared Game's are shown and never written through a private
form, as its graph is. A parent must be visible to the library, live when
stated, and of kind `main`: IGDB has no DLC of a DLC. A parent removed
later does not cascade; the add-on keeps its key and its parent link
renders as removed. A kind change to an add-on states a parent in the
same submit, and one to `main` clears it; the form refuses the other
pairs with a sentence, the column's `CHECK` behind it, and refuses
`main` to an add-on while any add-on names the game, removed ones
included, since a restore runs no lineage rule and a live-only count
would let one stand an add-on under an add-on. The rules live request-free in
`games/catalog_addons.py`: `state_addon(game, *, kind, parent, library)`
raises `AddonRefused` on one field, runs inside the caller's transaction
and locks the Game and its parent ordered by key; `save_game_columns`
and the conversion pass call it alike. Removing a main game keeps its
add-ons, and the confirmation counts the tracked ones that stay.
`EditionState.kind` is optional, and no kind keeps the stored one, so a
Release added on a new platform never restates a prerelease Edition as
full; `edition_words` names an unnamed prerelease "Prerelease". An add-on is no top-level row of the Games list unless
a `kind` or `parent` leaf appears anywhere in the filter tree, in which
case the base is every kind: the Kind facet is the
switch, Clear returns to main games, and statistics and the backlog read
every kind regardless. So a link into the Games list from a figure that
counts every kind states `kind` INCLUDES every word
(`GameFilter.of_every_kind()`), the stats builders and the Library page's
Games count alike. Under an `OR` each member states it, because a node
ORs its members with its own leaves. The parity test holds stat and link to one
predicate; `GameFilter.narrowing()` skips those leaves, so the Playtime
column's narrowing survives the clause. A private DLC reconciles to IGDB's through the
same redirect as any private Game.

### PlayerGame

`excluded_from_dropped`, stated by `RecordPlayerGameFacts` (its fourth
field, `FINGERPRINT_VERSION` 3) through
`playergame.excluded_from_dropped_changed`, the sibling of
`excluded_from_unfinished_changed`. Each figure that leaves a game out
reads its own fact and nothing else; the rule this wave makes is that no
fact stated for one figure decides another. Nothing was backfilled: P4
states both flags on every game with an infinite purchase. The two
flags are one "Visibility" group, `VISIBILITY_FIELDS` in
`games/models.py`, a `QuickFacetGroup` in the quick bar and a
`FormFieldGroup(look="panel")` on the Game form and bulk Edit.

Both flags are the Visibility group (M8): `VISIBILITY_FIELDS` in
`games/models.py` names them for the Game form and the bulk Edit, and one
`QuickFacetGroup` holds them in the Games quick bar. A later exclusion is
a whole fact (column, event, command field, readers) and joins both
groups too. A command that gains a field increments
`FINGERPRINT_VERSION`, since every field is part of the digest; M8 took
it to 3. Until P4 runs, a game flagged `excluded_from_unfinished` by hand
counts in the dropped figures again; P4 states both facts on every game
with an infinite purchase.

### Edition

A demo is another version of the game, so it is an Edition of that game,
`kind` `prerelease`, with a Release per platform. An open or closed
beta, an alpha, a network test, a playtest or a stress test is the same
word: no reader tells one from another, so the kind holds one word and
the Edition's name says which ("Demo", "Open Beta", "Network Test").
Early Access is the full game sold unfinished, so `full`, as every other
Edition is. The word is a catalog fact, shared as the Edition is, stated
through `CatalogGraphForm` beside the name, and picked in Add to library
as any Release is, told apart by its edition. It is not a playthrough
kind and not a second run: prerelease sessions sit on the game's run, and the
run's start stays the day the full game began. Three readers hold the
word. The backlog reads Owned entries on full editions, or a free demo
download would put the game in it. Before start (#1358) reads sessions
on full editions, since a demo precedes the game by nature. And the
toggle #1361 adds, one library setting stats and lists read alike, hides
sessions on prerelease editions; it needs a session to name its Release,
so it follows #1354. A Trial is the
full game, on its own Edition. An entry on a prerelease Edition states
the access the person likes, Owned for a free download or the charter's
Demo, and a beta's access ends `expired` the day the test closes; no
reader tells prerelease play from the access word, only from the
Edition. `Edition.kind` lands in M7 beside `Game.kind`. The one beta the
dump holds, "Diablo 4 Open Beta", is a private Game with one session and
becomes a prerelease Edition of Diablo IV through #983's merge, not by
the pass.

### FilterPreset

`mode` gains `entries`.

## Commands and events

Every command runs under `answered()`, is fingerprinted for idempotency,
resolves rows through `library_row`, carries a sentence on every refusal,
and answers `Unchanged` ahead of every refusal, as the sibling aggregates
do. Two endpoints on one row keep their order through one shared
`certainly_reversed(*, earlier, later)` in `games/commands/endpoint.py`:
an end certainly before the opening, a resume certainly before the
standing end, and an opening correction certainly after a standing end
are refused, each sentence naming the move; a refund before the
purchased day is the same rule on Purchase. A purchase PATCH is one dispatch: `DescribePurchase` takes the refund as
one statement and states, corrects or voids by presence under the lock,
every rule reading the statement's final days, kind and copy, so
nothing is ordered or checked up front; the take-back sentinel stays
inside the commands, and `restate_purchase` speaks the copy's spelling
(`refund=KEEP` states nothing, `None` voids), answering
`RestatedPurchase(appended, copy_end)` where `copy_end` is `ENDED`,
`MOVED`, `TAKEN_BACK` or `LEFT`, `None` when no refund act was
appended, for P5's message. The copy's PATCH still
restates in two dispatches (`restate_entry`, `Keep`/`KEEP` in
`games/writes/endpoint.py`); #1410 gives it the same one-dispatch shape.

### LibraryEntry

`games/commands/libraryentry.py`, request-free half
`games/writes/libraryentry.py`.

| Command | Event | Rule |
|---|---|---|
| `RecordEntry` | `libraryentry.created` (player game, release, access, format, note, `effective_time` the acquired day) | names the Release alone and derives the game from it; a Release the library cannot see is 404 from scope; a removed Release is refused; an untracked game is tracked inside the same dispatch by prepending `tracking_events(game)`, so the tracked row and the entry share one correlation with no window between them |
| `DescribeEntry` | `access_changed`, `format_changed`, `note_changed`, `release_changed`, one per differing fact | the new Release must be a live Release of the same game |
| `CorrectEntryAcquisition` | `acquisition_corrected` | the opening endpoint's correction |
| `EndEntryAccess`, `CorrectEntryAccessEnd`, `VoidEntryAccessEnd` | `access_ended`, `access_end_corrected`, `access_end_voided` | the primitive's three, with a `before_event` that refuses a removed entry; every way by hand, `refunded` included, since a person may state a refund no purchase records |
| `ResumeEntryAccess` | `access_resumed` (note, `effective_time` the day) | refused with a sentence where no end stands, never `Unchanged`; the fourth act of `ResumableEndpoint` over `ResumableEndpointEvents`, its own type beside the three-act `Endpoint`, in the end's family, projected as a void is, through `resume_endpoint`; a resume of a non-resumable endpoint and a void of an opening one fail in mypy |
| `RemoveEntry`, `RestoreEntry` | `removed`, `restored` | removal takes the copy's live purchases with it, appending `purchase.removed` for each in the same dispatch before `libraryentry.removed`, the confirmation naming them, since a purchase is the money paid for this copy and has no life the copy does not; restore brings back the purchases whose latest `purchase.removed` carries the key of the copy's latest `libraryentry.removed` (`cascaded_purchase_ids`), so Undo restores both and a purchase removed on its own stays removed, with no new event type; restore refuses under a removed PlayerGame or Release. `Purchase.entry` is a `CascadingReferrer` in `CASCADING_REFERRERS`, a registry of its own beside `BLOCKING_REFERRERS`: `referrers_of(LibraryEntry)` is empty, so `blocking_referrer` never reads purchases, `foreign_referrer` reads both registries, and `RemoveEntry` and `RestoreEntry` cascade by hand (P5b; M1 had it refuse, which left a refunded copy with no reachable remedy); `RestoreEntry` builds the `purchase.restored` events itself, since `RestorePurchase` refuses under a removed copy |

The referrer registry is `games/reads/referrers.py`: `BlockingReferrer.on`
takes `target`, and `referrers_of(target)` reads the tuple at each call;
`Purchase.entry` sits in `CASCADING_REFERRERS` instead, which only
`foreign_referrer` reads, and since P5b `RemoveEntry` cascades over the
copy's purchases rather than refusing on them.

### Purchase

`games/commands/purchase.py`, `games/writes/purchase.py`.

| Command | Event | Rule |
|---|---|---|
| `RecordPurchase` | `purchase.created` (entry, kind, name, amount, currency, note, `effective_time` the purchased day) | names an existing entry, or carries a new entry's fields and emits `libraryentry.created` first in the same dispatch, tracking an untracked game ahead of it the way `RecordEntry` does; currency required exactly where an amount is stated |
| `DescribePurchase` | `kind_changed`, `name_changed`, `price_changed` (amount and currency, one fact), `note_changed`, `entry_changed` | the new entry must be a live entry of the same game; `entry_id` is refused while a refund stands, so the coupled end always lies on `purchase.entry`; a kind change under a standing refund is refused unless the same statement takes the refund back (`KIND_UNDER_A_REFUND`), since the kind decides whether the refund ended the copy |
| `CorrectPurchaseDay` | `purchase_corrected` | the opening endpoint's correction; the endpoint's noun is "purchase" (`purchased`, `purchase_recorded_at`, `purchase_note`), as the entry's is "acquisition" |
| `RefundPurchase`, `CorrectPurchaseRefund`, `VoidPurchaseRefund`, and `DescribePurchase`'s `refund` for a PATCH | `refunded`, `refund_corrected`, `refund_voided` | the primitive; a refund of a purchase of kind `game` also appends `libraryentry.access_ended` with way `refunded` on the entry where it is Owned, live and unended, in the same dispatch (a pass or an upgrade names the base game's entry, so its refund leaves the copy held), as the reclassification writes a second aggregate, and a refund whose day certainly precedes the entry's acquired day is refused whole with a sentence naming the move (correct the acquired day first), never appended with the coupling skipped, only where that coupled end is due, since on a non-owned or ended copy no end is stated and nothing is ordered; a refund before the purchase day is always refused, and a purchase-day correction certainly after a standing refund too; `CorrectPurchaseRefund` appends `access_end_corrected` on the copy under the same rule as the void; "the refund's own" is `refund_owns_the_end(library, purchase)` in `games/reads/purchases.py`: the copy's latest end-family event is a stated or corrected end, and the event directly before it in the stream (sequence − 1), under the same `LibraryEvent.idempotency_key`, is a `refunded` or `refund_corrected` of this purchase; adjacency, because a direct appender that reuses one key across appends (the benchmark seeder does) could otherwise lend a hand end to a refund; P5's one-click Refund Undo reads it, widening the answer to the event where it needs one; which one dispatch stamps on every event it appends, an invariant every writer of the column keeps: P2 makes the anonymizer rewrite one key per dispatch rather than per event, and P4's pass and #740 state one key per dispatch too; the void takes that end back only where the entry's marker is still set and its latest end-family event is the refund's own |
| `RemovePurchase`, `RestorePurchase` | `removed`, `restored` | the removal is the charter's void; the stream keeps the money; restore refuses under a removed entry |

### PlayerGame and catalog

`RecordPlayerGameFacts` gains `excluded_from_dropped`, a fourth
`bool | None`. `GameForm` and `save_game_columns` take `kind` and
`parent`.

### Bulk acts

Declared in `games/bulk_actions.py`, Undo through `EventRows`:
`entry.edit` (access, format, note; an empty field keeps), `entry.remove`,
`purchase.edit` (Kind, Price as Keep, Paid with amount and currency, Free or Unknown, Purchased, Note; an empty field keeps),
`purchase.remove`. The Edit acts live beside the others and share
`games/bulk_edit.py`; their Undo reads the one fact-change reader in
`games/reads/fact_change.py`, which `playergame.edit` and `entry.edit`
call and P5's `purchase.edit` calls third.

### API

`GET`/`POST /api/entries/`, `GET`/`PATCH /api/entries/{id}`, and the same
four under `/api/purchases/`. The prefixes are plural, as `/api/games/`,
`/api/devices/` and `/api/platforms/` are; the bodies follow the session
routes: `extra="forbid"`, a named key is the act, an `Idempotency-Key`
header on `POST`, 404 from the command for a row the library does not
hold, 409 with the command's sentence for every other refusal. A stated
endpoint travels as one key: an object states or corrects it, `null`
voids it, an absent key states nothing; a resume is its own `POST
/{id}/resume`. Every endpoint is answered as canonical temporal text
beside its bounds, marker, way and note.

## The conversion

One pass, out of a migration marked `elidable=True`, as #700 and #1274
ran. It runs `ANALYZE` on the tables it reads before its gate reads, as
`verify_reclassification_parity` does. Every event's `recorded_at` is the
pass's instant and its `effective_time` the day the row states.
`source_metadata` names the pass and a review category. Idempotency keys
derive from the legacy purchase id and game id, so a second run appends
nothing. In order:

1. **Bundles (7).** One purchase per game, 38 rows from 7. The amount
   splits by the charter's rule in integer cents: each game takes the
   quotient, and the remainder goes one cent each to games ordered by key.
   The seeded valuation splits by the same rule. Day, refund and words are
   copied.
2. **Add-ons (35 DLC).** A private Game of kind `dlc`, named from the
   purchase with `sort_name = name` (a blank one leads every order), a
   second same-named DLC under another base named "<base>: <name>" and
   reviewed as `renamed_addon` (0 on the dump), parent the base game,
   with a default Edition and one Release on the row's platform, tracked
   as a PlayerGame with default facts. No add-on is among the 14
   mismatched-platform rows. The 6 passes and the
   upgrade stay purchases of their kind on the base entry.
3. **Releases (14).** Where the purchase states a platform the game's
   Releases lack, a private Release on that platform under the default
   Edition; a purchase stating no platform (8) puts its copy on the
   game's default Release.
   **Demo editions (34).** For each Demo purchase, a private Edition of
   kind `prerelease` named "Demo" under its game, with one Release on the
   purchase's platform; the entry of step 4 names that Release. A game
   holding a demo Release beside its full one is in the review surface.
4. **Entries.** One per (purchase, game). Access and format by the table
   below; acquired the purchase day, exact. An Owned copy of a refunded
   `game` purchase is created unended: its end comes with the refund in
   step 5, or no converted refund would own its copy's end. A refunded
   copy that is not Owned takes its end here, way `refunded` on the
   refund day, as a hand-stated one. The 81 non-owned rows at price 0
   become an entry and no Purchase. A game bought twice gets two entries
   on one Release.
5. **Purchases.** Kind (`du` → `upgrade`), name, amount quantized to two
   places (two rows change; the delta is reported), currency upper-cased
   (three rows), 0 → Free on Epic Games Store, else unknown; the two
   endpoints; the entry link. A refund is appended in P2's shape:
   `purchase.refunded` and then, directly after it with nothing between,
   the copy's `libraryentry.access_ended` (way `refunded`), in one append
   under one idempotency key, the copy unended until then, so the refund owns the end and a later void or
   correction reaches it. The pass builds every event through the
   commands' own `build(CommandContext(...))` (`RecordEntry`,
   `RefundPurchase`, `EndEntryAccess`, `RecordPlayerGameFacts`,
   `RemovePurchase`, `RemoveEntry`; the creations through
   `entry_creation_events` and `purchase_created`) and appends through
   `idempotent_append`, one key per (legacy row, game, act), one
   `recorded_at`, one correlation id per library, so every command rule
   applies and the adjacency is `RefundPurchase`'s own; a dispatch cannot
   run in a migration's transaction, a build can. A refusal aborts the
   migration naming the legacy row, which the preflight has shown first.
   The pass reads the legacy rows through the migration's historical
   model, since P4 and P5 ship in one image and the pass runs under P5's
   code where `LegacyPurchase` is gone; everything it writes goes through
   live models and command code, behind a schema guard as #1274's that
   refuses where a live model it touches declares a column the database
   lacks. **So P5 adds no column to a table the pass reads or writes**:
   the projections, the event tables, Game, Edition, Release, Platform,
   `PurchaseConversionState`, `PurchaseValuation`, `ExchangeRate`; its
   review flag on `UserLibraryPreferences` is fine. The migration is
   elided once the deployment records it, as #700 and #1274 were. A pass
   or an upgrade with no base copy records its own, Owned, by the table.
   A removed legacy row is converted, then removed; a row whose only
   games the library removed is skipped and reported as
   `skipped_removed_game`. Valuations are seeded from
   `converted_price` at the current published version; sums per currency
   are compared before and after.
6. **Infinite (30 games).** Both exclusions stated through
   `RecordPlayerGameFacts` on the legacy row's game; an infinite DLC row
   excludes its new DLC Game alone and never the base, since the legacy
   figures left out the DLC purchase alone and excluding the base would
   pull its own finite purchase out of both counts; a removed legacy row
   excludes nothing; the 6 mixed games are printed with the old and
   new backlog counts.
7. The legacy columns go, in the same stack.

The pass is implemented
([contract](2026-10-01-issue-723-purchase-conversion-design.md)) and
rehearsed on the 2026-10-01 dump: 808 rows became 839 planned copies,
833 own copies and 758 purchases, 0 skipped, 0 refusals, 2177 events;
totals reconcile per currency (EUR −0.0050 from the two third-decimal
rows); 221 of 221 refunds ended their copy; 48 Releases created (14
platform, 34 demo); backlog all-time unfinished 282 → 282 and dropped
268 → 267, `mixed_infinite` 3; tracked games 863 → 898; CZK valuations seeded equal to the
legacy converted sum; `make migrate` after `--confirm` appended nothing,
replay parity 0 differing, the identity audit clean. What it found:

- A removal is two keys, `removed` then `removed_copy`: `RemoveEntry`
  reads the projection, which shows the live purchase until the first
  append projects, so one build cannot hold both.
- The pass checks its own key before any catalog write, so a rerun makes
  no Release and no DLC Game, and `created_release` exists only in the
  first run's `source_metadata`: the review surface reads metadata and
  recomputes nothing. Every run walks every row, with no early return but an empty
  legacy table: a held key replays and a new act appends, 4 s and no
  append on the converted dump. A rerun checks each held key's
  fingerprint, the inputs per act, and lists as defects a legacy fact
  changed since its conversion (price, platform, a free row priced), an
  act the row no longer states (a cleared refund, removal or infinite
  flag), and a stale fingerprint version; a refund, removal or infinite
  flag added later is stated on the next run. Schema and replay drift
  raise `PurchaseConversionDrift`.
- The reconciliation judges seeded shares against legacy shares over
  the purchases seeded at a rate, removed ones aside.
- `refund_ends(kind, access, *, ended)` in `games/commands/purchase.py`
  is the one refund-ends-the-copy rule; `identity_taken` in
  `games/catalog_compat.py` the flat-identity check; `seeded` in
  `games/valuations.py` has no caller beyond the pass and leaves with
  its migration.
- A DLC row with `du` ownership is refused. A pass or upgrade without a
  base copy is reviewed as `own_copy_fallback` (1 on the dump), and a
  refunded own copy always ends. Skipped copies and unvalued purchases
  are logged and listed.
- A skipped copy never gets a key; an exclusion skips an untracked game.
- A library with a requested target and nothing published seeds no
  valuation and still requests one run; `publish_valuations` replaces
  whole, so the pass republishes the library's standing valuations
  beside the seeded ones.
- The snapshot encoder refuses an unknown type (`StatsData` holds a
  `range`) rather than guessing; the 2026-10-01 snapshot, 22 scopes, is
  `.dumps/legacy-stats-2026-10-01.json` for P5.
- The autouse tracked-game hook writes a `PlayerGame` without events, so
  a test that runs the pass's replay check needs `untracked_games`.

| Today | Access | Format |
|---|---|---|
| Physical | Owned | Physical |
| Digital | Owned | Digital |
| Digital Upgrade | Owned; the purchase's kind is `upgrade` | Digital |
| Rented, platform Xbox Gamepass | Subscription | Digital |
| Rented, other | Rented | Digital |
| Borrowed | Borrowed | Physical |
| Trial | Trial | Digital |
| Demo | Demo | Digital |
| Pirated | Pirated | Unknown |

The two platform rules (Gamepass, Epic) are the only inferences. Every
inferred row, and every row the pass shaped in a way the person may want
to look at, is in the review surface.

### Preflight and rehearsal

`make verify-purchase-conversion ARGS="--user NAME"` runs the pass
inside a transaction it rolls back: it prints every review list, both
backlog counts and every refusal with its legacy row, so a refusal never
first appears as an aborted deploy. With `--confirm NAME` on a restored
dump it commits and prints the row-level reconciliation: counts per
category, totals per currency before and after, refunded count, entries
by access and format, quantization deltas, valuation sums seeded against
legacy. Both modes write the legacy `StatsData` for every year and
all-time to a JSON snapshot (`--snapshot PATH`), which P5's gate judges
its readers against (see [Statistics](#statistics)); the reconciliation
reads legacy rows beside the projections, so it prints any time before
P5 drops them. `make verify-dump` and
`make verify-baseline ARGS="--migrate"` run on the day's dump before the
deploy. The pre-deploy dump is the rollback.

### Review surface

The Conversion review rows sit inside the Library page's Purchases
section as one `SummaryRow` "Conversion review", its detail holding the
"Hide this review" checkbox above a `SummaryList`: one row per category
holding the label, a one-line reason, its count linking to exactly those
rows, and a Review action (a link on wide screens, ⋯ on narrow); a
category with zero rows is left out. `unknown_price`, `epic_free` and
`quantized` link to the Purchases list, every other category to the
Library tab, whose `Exists` also matches the events of any purchase
naming the copy, since an attached pass appends `purchase.created`
alone. The count is history, not open work: the tag sits on the
conversion's events, so fixing a row does not lower it and only removal
does; the person works through the links, then hides. The review is one
time: #1443 removes the rows, the checkbox and the preference after P5c
and keeps the field and `Category`. On the 2026-10-01 dump: Unknown
price 54, Free on Epic 19, Rounded price 2, Rentals 36, New releases 48,
Demos 34, Mixed infinite 2, DLC as games 35, Split bundles 38, Passes
without a game copy 1, Repurchased games 18, the rest 0.
Every pass append carries `source_metadata = {"origin": "conversion",
"issue": 723, "legacy_purchase": id, "review": [categories]}`, the
categories being `Category` in `games/backfill/purchase_plan.py`
(thirteen, `unknown_price`, `epic_free`, `rental`, `created_release`,
`demo_edition`, `mixed_infinite`, `addon_game`, `quantized`,
`bundle_split`, `own_copy_fallback`, `renamed_addon` among them;
`skipped_removed_game` appends nothing and stays preflight-only). One
field reaches them: `conversion_review`, a choice field on
`PurchaseFilter` and `LibraryEntryFilter` whose choices are `Category`'s
words, compiled as an `Exists` over `LibraryEvent` on the row's key,
origin conversion and the word in `review`; an unknown word and
`INCLUDES_ONLY` are refused at compile. It is the third read that
answers from events beside `batch_aggregate_ids`, because the category
exists nowhere else; it is a link target and no quick facet, and its
words stay stable once shipped, since a stored preset naming one is
refused as unknown if the word goes. The row menus and the bulk tray on
each list do the fixing, and #1432's audit screen reuses the field.
Repurchased games (39) link to the Games list at entry count two or
more; the pass names no session's Release, because no finder is
reliable, and #1354's bulk Edit field is where a person states which
sessions were the demo. A copy recorded by hand between M3 and the
cutover beside a legacy purchase of the same copy becomes two entries,
since no rule tells one copy stated twice from two copies; the preflight
lists such games as a category. A "Hide this review" checkbox on
`UserLibraryPreferences`, a live one, hides the rows and keeps itself;
it is its own toggle, read from nothing else.

The sample fixture is regenerated inside the stack, by P5, from the
day's dump after the rehearsal: `load_sample_data` runs no conversion
pass (one would refuse the loader tests' synthetic legacy rows and add
thousands of appends to every load), P4 leaves the fixture legacy since
every reader still reads legacy rows, and P5, which drops the legacy
table, ships the regenerated fixture with its loader tests rewritten to
the new shape. The anonymizer shifts an entry's and a purchase's days by the game's
offset (both aggregates map through `game_id_by_aggregate`), redraws
amounts, clears names, notes and `source_metadata` (so the sample shows
no conversion review), and re-mints the Edition, Release and DLC Game
rows the entry events reference. It does not randomise which copy a
purchase names: re-pointing would break the refund adjacency
`refund_owns_the_end` reads and move a purchase to another game's copy,
and it hides nothing the copies do not already say. Two of its rules a
later member will meet: a `PROJECTED` reference (a copy) takes its
aggregate's re-minted id, and `rewrite_path` fans out over a list, since
an alias path crossing one (`historicalplaytime playthroughs[].playthrough`)
was never rewritten and the fixture failed to load once the deployment
held records; a record's join ids keep their real timestamps.

## Screens and reads

### Forms

"Copy" is the person's word and "Library" the screens' ("Add to
library", the Library tab, Game detail's Library section); "entry" stays
in code, events and the API. A copy leaves with "I no longer have it"
and returns with "I have it again", never "End access" or "Resume".

**Add to library** replaces Add purchase. M3 built it at its final URL
with the copy's fields; Game detail's inline add fixes the game, and the
standalone page is the same form with a Game picker in front. Game; a
Release picker over the game's live Releases, the sole one preselected,
a row reading platform · edition (named only) · year, whose create row
takes a platform and states a private Release under the default Edition
through the catalog service on a Game the library owns (a shared Game
lists visible Releases only until #1375). This is the selector #893
deferred: visible Releases only, an explicit choice, never inferred.
Then Access, Format, Acquired (a temporal field defaulting to the
calendar's day), Note, and from P5 a three-way Purchase segment on the
"Add to library…" page, never on the one-click add: Paid (amount,
currency), Free, No purchase. An access other than Owned starts on No
purchase and Owned on Paid; a default, changed at will. That segment is
the game's own purchase and nothing more: no Kind, no Name, no copy
picker. A pass, an upgrade or a second purchase of a copy is added
through "Add purchase…" in the copy's ⋯ menu, on Game detail and the
Library tab, a page stating Kind, Name, Paid or Free amount, Purchased
and Note; the Library page's "Add purchase" summary action goes. The
"separate price per game" mode, the row Split and the old page's "Submit
& Create Session" go with the bundle; Add Game's second submit reads
"Submit & Add to library".

Add to library defaults to Paid, so an e2e test that adds a copy through
the form picks "No purchase". A form's shown and hidden rows come from
CSS alone: `FormFieldGroup.class_` names a Tailwind group and
`FormFieldPresentation.row_class` reads it, the strings literal, since an
f-string never reaches Tailwind's scan.

**Edit copy**: access, format, release, acquired, note. The end of
access has its own pages: "I no longer have it" and "I have it again"
each one click or "With details…", and "Edit how it left…" on an ended
copy. The one-click pattern is the wave's for every immediate act: a
`*_now` POST carries a submission key (400 without one), states the act
with the calendar's day (an end with way `unstated`), and offers Undo
keyed on the stream sequence its press appended
(`library/<entry>/end/undo/<sequence>`), which refuses once a later act
overtook it, through `latest_end_act` and `taken_back_end` in
`games/reads/entries.py`; the "With details…" pages offer no Undo. An
edit page carries a stale-page token (`end_seen` in
`games/entry_forms.py`, a hash of marker, way, day and note), so a
correction made since the page opened is refused; the device form
lacks one (#1387). **Edit purchase**: kind, name, amount with Free,
currency, purchased, refund (day, note; "Not refunded" voids), note. The
row Refund act is one click in that pattern, the calendar's day and a
sequence-keyed Undo, corrected on the edit page; the Undo is its own
command, `UndoPurchaseRefund(purchase_id, refunded_at)`, keyed on the
`purchase.refunded` event's own sequence, not the dispatch's last, since
the copy's end is appended after it; it refuses under the lock once a
later refund act overtakes it, and an Undo whose row states no refund is
a defect (`RowUnreadable`). `VoidPurchaseRefund` is unchanged. One-click and Undo routes are
`ORIGIN_AWARE`, as the copy's are. The new refund sets no status: the
legacy one set Abandoned, and Dropped now reads the refund end instead.

### Lists

**Entries** (`entries` mode, its own filter and presets, selectable, the
Library tab beside Games): Game, Platform, Access, Format, Acquired,
Access ended (way · day), Note, Created, and from P5b2 Purchases, one
short line per live purchase showing its price, labelled only for a
non-game kind or a named purchase. Facets
access, format, ended, way, platform, acquired, game. Tray Edit and
Remove; one row menu (`entry_row_menu`, `games/views/entry_menu.py`,
a `DropdownSubmenuItem` holding "Just mark it gone" or "Just add it
back" and "With details…"), then "Edit how it left…" on an ended copy,
Edit, Remove, shared with Game detail (#1352). No navbar item and no
standalone page.

**Purchases** (selectable, the Actions column retired, #1266): Name (the
game, or product · game), Kind, Amount (Free and Unknown as words, the
valuation beside; #1463 restores the legacy shape, one price with the
stated amount in a popover), Purchased, Refunded, Finished, Created. Facets kind,
amount, price state (Paid, Free, Unknown), purchased, refunded, and access
and platform through the entry. Tray Edit and Remove; row menu Edit,
Refund, Remove, the list's own.

**Games**: an Access column, off by default (`AccessBadge`, filled only
where a copy is held now, whose popover says one sentence) and facets
access and format over held copies, scoped through
`context.queryset_for` so the shared-catalog scope holds; `copy_end()`
is the one held-or-ended rule, and `AccessSummary` carries an
`EndedCopy` per ended one; a Kind column and facet, off by default.
**Game detail**: a Library section, on `SECTION_SURFACE_CLASS`, listing
the copies had now grouped by version (`SummaryGroup` over dense
`SummaryRow`s), every per-copy act inline and never one press without
Undo, ended copies out of the section with one muted line pointing at
View all, and from P5 each copy's purchases under its row (a copy with none shows
no line; a refunded pass or upgrade on a held copy is hidden, a refunded
game purchase having ended its Owned copy already; a purchase line has
no ⋯ of its own, its Edit…, Refund and Remove… sitting in the copy's ⋯
menu as one submenu per purchase, beside "Add purchase…"); an Add-ons
section on a main game listing the add-ons the library tracks grouped by
kind, before the Library section and half width beside it from `lg` up,
in the same kit's shapes with no Add button of its own, empty rendering
nothing; an "Add-on of" row on an add-on, linked where the library
tracks the parent.

### Filters and presets

Every day the wave reads or defaults asks the library's calendar (#1360,
#1372): a form's default day is `calendar_today(library)`, never the
process clock, and a test seeds a day through `tests/calendar_days.py`,
since the suite runs with the process clock on another date. A facet
over a timestamp (`created_at`) compiles through `calendar_day_handler`
with `metadata_lookup` naming the column; an endpoint facet reads the
two bound date columns and needs no zone. A filter context comes from
`filter_query_context_for_library`, whose `day_zone` a day predicate
reads once.

`LibraryEntryFilter` is new: access, format, the two endpoints as
intervals and acts, way, platform through the Release, game,
`game_filter`, and from P5 `purchase_filter`. `PurchaseFilter` is rewritten on the new columns:
amount, currency, price state, kind, the two endpoints, `entry_filter`,
`game_filter` through the entry. `GameFilter` gains `kind`, `parent`,
`access`, `format`, `entry_count` and an `entry_filter` relation, and
keeps `purchase_count` and `purchase_price_total` on their new paths.
Saved purchase presets are rewritten once, as `ended` → `completed` was:

| Old key | New key |
|---|---|
| `type` | `kind`; `dlc` → `game_filter.kind` |
| `ownership_type` | `entry_filter.access` and `.format`, by the conversion's table |
| `infinite` | `game_filter.excluded_from_unfinished` |
| `converted_price` | the valuation amount |
| `date_purchased` | `purchased` |
| `is_refunded` | the refund act |
| `platform` | `entry_filter.platform` |

A key the rewrite cannot express leaves the preset refused, as an unknown
key is today, and the conversion report lists it. The deployment holds no
purchase preset.

### Reads

`games/reads/entries.py`: `library_entries()`, `readable_entries()`,
`game_entries()`, `access_summaries()` for the Games column,
`latest_end_act()` and `taken_back_end()` for the sequence-keyed Undo. `games/reads/purchases.py`:
`library_purchases()`, `game_purchases()`, spending through valuations.
Every read states its scope through four marks: entry, PlayerGame,
Release, Game, each a join on a key the row holds. No sum reads a float.
Sessions and records keep `release` reserved; the session form gets no
picker in this wave.

## Statistics

`STATS_SOURCES` gains `ENTRIES`. Every key is classified once; the test
that holds the map complete stays.

**Money** reads purchases through valuations. Total spent and spent per
game sum the library's live, unrefunded purchases whose purchased day lies
in scope by containment, in the library's display currency. Two figures
sit beside any total: `total_spent_unpriced`, the purchases with no
amount ("N with no known price"), and `total_spent_unvalued`, the ones
with an amount and no valuation yet, shown only when not 0. Purchased
count, refunded count and refunded percent read purchases on the two
endpoints.

**Backlog** reads copies, never legacy rows: a copy is a live
`LibraryEntry` on a `full` Edition, Owned, held now (no end standing,
the `copy_end()` rule), joined to the game; a sold copy is no backlog
item, a pass or upgrade has no copy of its own, and a DLC copy counts
through its own Game.
Owned-unfinished: the game is at no done status, has no completion in
scope, is not Abandoned, and `excluded_from_unfinished` is false. Dropped:
Abandoned, or the entry's access ended with way `refunded`, and
`excluded_from_dropped` is false. Bought-and-finished, finished-released
and backlog decrease read entries acquired in scope. A pass has no entry of
its own and stays out, as `only_games_and_dlc` keeps it out today; a DLC's
entry counts through its own tracked game.

**#1157's readers** live here: entries by access and by format, count and
share; spend by access through the entry. The card and the device split
stay #1157.

**Links.** Every builder in `stats_links.py` compiles the same predicate as
its figure over `EntryFilter` or `PurchaseFilter`; the parity test covers
each.

**Parity gate.** In P4 every figure still reads `LegacyPurchase`, which
the pass leaves in place, so P4 writes the legacy `StatsData` for every
year and all-time to a format-2 snapshot (`verify-purchase-conversion
--snapshot`), and P5a's `make verify-purchase-statistics` judges every
key of the new readers against it, explaining every moved legacy key
with one of eleven reasons in `games/purchase_parity.py`;
`legacy_figures(model, ...)` takes the historical model, so P5c keeps
the gate after the class is gone. Rehearsed on the 2026-10-01 dump:
every figure attributed, all-time total spent equal to the legacy sum to
the cent, all ten bench reads under 20 ms, 930 of 1749 rendered pages
differing and each attributed (the 898 game pages by the legacy
Purchases section alone). The legacy page counted a bundle once per
abandoned game through the M2M; the snapshot counts each row once. The population changes the pass makes are the only
admitted differences, each attributed by name and count:

- purchase counts: minus the 81 non-owned rows and plus the 31 rows the
  bundle split adds, each by its year;
- money: identical within the quantized cents; the seeded valuations
  carry the legacy rounding, so the refresh after the cutover is judged
  separately;
- backlog counts: the 6 mixed games, the 35 DLC games now tracked on their
  own, and the 81 rows that are entries and no purchase, by year;
- percentages: recomputed from the attributed counts.

An unattributed difference fails the run. `make bench` gains an
entries-and-purchases workload; every read stays inside the 20 ms budget.
P5a's migration sets `related_name="+"` on `LegacyPurchase`'s relations,
so the builder pickers lose the legacy paths ahead of P5c's drop.

## Delivery order

The entry, catalog and PlayerGame members merge alone, each a PR against
`main`, with `main` incomplete between them as the last wave allowed;
nothing in them converts data, and each holds events for every row it
projects. The Purchase members cannot: a `ProjectionModel` whose rows
hold no events fails the replay gate, so the Purchase aggregate, its
conversion and the cutover are one `gh stack merge`, P1 to P5c, each
member passing the full gate on its own. M1 before M2 before M3; M7 and
M8 any time; the stack after every member, and P5's backlog reads M7's
edition word.

| Member | Issues | Delivers |
|---|---|---|
| M1 (merged, PR #1362, 2026-09-29) | #719, #720, #722 | the opening endpoint whole, its one correction (`CorrectEntryAcquisition`) included, since the replay gate refuses a registered event type no command emits; the LibraryEntry aggregate: schema without the end columns, creation, description, removal and restore as commands with no route, multiple entries, reference kind, `_is_library_scoped` path, the generalised referrer registry, replay gate, the four API routes with `limit`/`offset` |
| M2 (merged, PR #1366, 2026-09-29) | #721 | the end columns and their `CHECK`s in a migration of its own, as `0019` added the device's; access end and resume on the primitive |
| M3 (merged, stack #1379: PRs #1377, #1378, #1380, 2026-09-30) | #1352 | the Library screens: Add to library, Game detail's Library section with its inline acts, the end and resume pages with one-click Undo; the Library tab, `LibraryEntryFilter`, presets, bulk Edit and Remove; the Games tab's Access column and facets |
| M7 (merged, PR #1390, 2026-09-30) | #1353 | `Game.kind` and `Game.parent`, `Edition.kind`: columns, form, `<game-addon>`, `state_addon`, Game detail's Add-ons section and "Add-on of" row, the Games list's main-only base, Kind facet and column, the every-kind clause on links |
| M8 (merged, PR #1397, 2026-09-30) | #1334 | `excluded_from_dropped` and its bulk Edit field, the Visibility group |
| P1 | #725, #726, #828 | the incumbent renamed `LegacyPurchase`; the Purchase aggregate born on `games_purchase`: projection, creation with an entry, description, day correction, removal, API; no reader switched |
| P2 | #727 | refund endpoints and the coupled entry end |
| P3 | #728, #729 | `PurchaseValuation`, decimal rates, the run state re-pointed, the valuation request on the write path |
| P4 | #723, #730, #731, #732, #733 | the conversion pass over `LegacyPurchase` rows, the legacy id kept on a bundle's first game and a UUIDv7 minted for the rest, `verify-purchase-conversion`, the reconciliation |
| P5a | #734, #735, the read half of #1266 | every read, since the stats links point into the Purchases list and a member between the two would emit links its own list refuses: `PurchaseFilter` on the projection and the `purchases` mode on it, `purchase_filter`, `purchase_count` and `purchase_price_total` on the new paths, the saved presets rewritten once, the Purchases list reading the projection with the wave's columns and facets and no row act yet, every statistic through entries, purchases and valuations, `stats_links` with their parity tests, #1157's readers, and the parity command that judges the new readers against P4's snapshot (a command of its own, since P5c drops the table `verify_purchase_conversion` reads) |
| P5b | #724 | every write: the purchase segment on Add to library, Add purchase on a copy, Edit purchase, one-click Refund with sequence-keyed Undo, Remove and Restore through commands, the Purchases list's row menu, Game detail's purchases, and the legacy add, edit, view, Split and Refund routes, `PurchaseForm` and `add_purchase.ts` retired; inside the stack P5a still writes through the legacy form, so a purchase added there shows nowhere until P5b, a state `main` never holds |
| P5b2 | the rest of #1266 | the Purchases list selectable, tray Edit and Remove (`purchase.edit`, `purchase.remove`, `EventRows`), the Conversion review section with its Hide toggle, and the Library tab's Purchases column |
| P5c | #736 | `LegacyPurchase`, its tables, routes, signals and float cache dropped and the fixture regenerated; the pass, `verify-purchase-conversion` and its reconciliation **stay**, reading the historical model off migration state and refusing once the drop has run, since `0031` imports the pass and the deploy day needs the rolled-back preflight and a fresh snapshot of that day's dump; #1448 removes them at the squash; implemented ([contract](2026-10-02-issue-736-legacy-purchase-drop-design.md)): the tooling reads the model off the `0034` state through `legacy_purchase_model()` (`games/backfill/legacy_model.py`), everything #1448 removes carries the comment `conversion-tooling`, the `legacy_purchase` test fixture makes the tables inside the test's transaction and refuses `transaction=True`; the currency task keeps its failed status and one retry for `DatabaseError` alone, `MissingExchangeRate` gone; the fixture regenerated at 899 games, 933 editions, 947 releases, 833 copies, 758 purchases, 9530 events |
| P6 | #1450 | the library event stream's key made deferrable, so `purge-library` works on a library holding a parented add-on with events, the shape every converted library has; a test refuses an immediate foreign key in the schema |

Each member passes the full gate on its own against a fresh database.
Each gets its own specification and plan before code. An issue delivered
inside a member says so in its body and closes with it.

## What this design forecloses

- **Moving a purchase to another copy** is #1437, after P5b.
- **Moving an entry or a purchase to another game.** `release_changed`
  and `entry_changed` stay inside one game. A row recorded on the wrong
  game is removed and recorded again, and the removed purchase's money
  stays in the stream under the old game. The cost of lifting it later is
  a command that restates `player_game`, and every reader that caches the
  game key.
- **A pass without a copy.** A pass or an upgrade is added from a copy's
  ⋯ menu, so it always names a copy the library holds; on a game with
  no copy the person adds one first (Add to library, No purchase). A
  pass on a game the library never owned therefore needs a copy that
  says so, in the access word of the person's choosing.
- **One end per entry at a time.** The projection holds the latest end;
  the stream holds them all, and a resume leaves nothing on the row. So
  the day-order rules see only what the row holds: after an end and a
  resume, a new end dated between them passes, and so does an
  acquisition correction dated after the resumed end. An end the copy
  resumed from can no longer be corrected or voided, and a mistaken
  resume is taken back by stating the end again. A list of a copy's
  lendings is a stream read nothing renders yet. The cost of lifting it
  is a `resumed` day with bounds, held until the next end clears it,
  which would floor the next end and an acquisition correction and make
  the resumed end correctable again.
- **Demo play placed by hand.** A session is demo play through the
  Release it names (#1354). A session that names none is counted
  everywhere, as before; the bulk Edit Release field places existing
  ones. Nothing infers a demo from the game, the run or the day.
- **A refund of a non-owned entry.** The refund ends access only on an
  Owned entry; a refunded subscription or rental keeps its own end, stated
  by hand.
- **Removing a refunded purchase.** The removal voids the money and
  leaves the copy's end alone, as it leaves the entry the purchase
  created; the copy's state is the person's to restate.
- **Two refunded purchases of one copy.** The copy's end is the first
  refund's; the second finds the copy ended and couples nothing, so
  voiding the first takes the end back while the second refund stands.

## Cross-wave handoffs

- **A Release on a session or a record** is #1354's: the session and
  record forms, bulk Edit and both APIs state it, and `stated_release`
  (`games/commands/scope.py`) refuses a new one the library holds no
  live copy of. The held value skips that check and the removal check,
  as a held device does.
- **Bulk end of access over copies** is #1355, beside #1345, on the
  bulk runner; it reads `latest_end_act` and voids only where the
  batch's own event is still the latest of the end's family, as
  #1256's Undo does. **A platform across many copies** is #1382, which
  resolves each game's Release on the platform and refuses a row whose
  game holds none, never creating one.
- **#1344** swaps the device's `endpoint_events(...)` for
  `resumable_endpoint_events(..., resumed="library.device.access_resumed")`
  and `Endpoint.over` for `ResumableEndpoint.resuming`, no primitive work;
  **#1347** copies the opening endpoint. **#1346** decides where a sale price lives; this wave puts no
  money on an end.
- **#782** maps IGDB `game_type` to `Game.kind` one to one and admits the
  remaining words.
- **#983** merges duplicate private Games into one Game's Editions, the
  lift of the foreclosure above: it restates `player_game` on runs,
  records and copies, re-parents add-ons, reconciles the four PlayerGame
  facts, and merges a demo filed as a Game into a prerelease Edition;
  after P5c and #654's redirect, in epic #602.
- **#762** and **#750** read the Purchase projection this wave leaves.
- **#773** closes with P5 where every legacy field is gone, or keeps what
  remains.
- **#1337**'s bundle case disappears with the M2M; the issue keeps the
  general rule.
- **#493** is unchanged; a forgotten rate now invalidates valuations.
- **#889** later moves the per-platform figures onto the Release the entry
  names.
- **#1157** draws its card from this wave's readers.
- **#1432** moves the two spend side figures onto the Library page and
  later grows into the audit screen every data gap reports to, P5b's
  conversion review and #1418's unvaluable purchases included; it
  follows P5b and blocks nothing in the stack.
- **#1383** redesigns Game detail after P5 and #1353, so every section
  the wave adds is on the page it redraws; the wave's sections take the
  library kit's shapes meanwhile (`SummaryGroup`, `SummaryList`, `Chip`,
  `SECTION_SURFACE_CLASS`) and invent no markup of their own.
- **#1385** opens every add and edit form in a modal once #1384 lands,
  Game detail's with #1383's mockups; until then each act the wave adds
  is its own page, and every page keeps working as one after.
- **#1358**'s Before start inherits #1354's clause:
  `outside_interval_handler(..., unless=...)` keeps a session on a
  prerelease Edition out of `outside_playthrough_dates`, on both
  halves. **#1361**, the toggle that hides demo play from statistics
  and lists, reads `edition_kind` through the session's and the
  record's `release` column.

## Deployment

Deployed on 2026-10-02 after the stack (P1 to P6, PRs #1403 to #1458)
merged: the deployment's data differed from the rehearsed 2026-10-01
dump by one session changed and one added, so the pass ran on the
rehearsed shape; the post-deploy dump is the sample fixture's source
(#1454).

One image carries the stack. The container's startup `migrate` runs the
pass; the pre-deploy dump is the rollback. The pass's migration is
`RunPython` alone, so the rehearsal on that day's dump is: restore it;
`make migrate ARGS="games 0030_purchasevaluation"`; `make
verify-purchase-conversion ARGS="--user NAME --snapshot S"` (rolled back,
a fresh legacy snapshot of that day); `ARGS="--confirm NAME"` (committed,
reconciliation printed); `make migrate ARGS="games
0034_conversion_review_hidden"`, which appends nothing, proving
idempotency on real data; `make migrate` (the drop); `make
verify-purchase-statistics ARGS="--snapshot S"`; then `make
verify-replay-parity`, `make verify-dump`, `make verify-baseline
ARGS="--migrate"`. Rehearsed under P5c on the 2026-10-01 dump: steps 1
to 7 green (808 legacy rows, 758 purchases, 221 of 221 refunds, every
figure attributed), replay parity and `verify-dump` clean;
`verify-baseline --migrate` reported 14 rows from seven `CHECK`
constraints, a spelling difference and no drift: `pg_dump`/`pg_restore`
rewrite a varchar `CHECK`'s text once and it is then a fixed point, and
a constraint `--migrate` added to the restored copy kept the pre-trip
spelling. #1451 (PR #1460) makes `verify-baseline` round-trip both
databases after their last write, and step 8 is green on that dump. The
rule: a tool comparing catalogs reads both sides after the same number
of dump and restore trips, since a write after a restore reopens the
gap. #1450, also
pre-existing: `purge-library` fails for a library holding an add-on Game
with a parent and events, the shape every converted library has after
the deploy; its fix (the stream key made deferrable) is the stack's last
member, P6, its migration the next number after P5c's, never ahead of
the stack, since the stack's ten migrations are named by number in
specs, the rehearsal and the tooling; one image then carries the pass
and the deferral. After it: the review surface, the first valuation
refresh and its printed totals; the fixture already shipped with P5. The valuation
task's daily schedule row must exist in production, since the recovery
runs on it.

## Verification contract

- Every member: full `make check`; the replay gate through every new
  event type; a fingerprint test per command; two-library tests: a shared
  Release yields independent entries, another library's private Release
  answers 404, another library's entry or purchase is never read, and the
  ownership audit reports an entry naming a foreign private Release.
- Every screen member: `make render-pages` before and after on one
  database, every difference attributed in the PR.
- P4: the reconciliation printed from the day's dump and pasted into the
  PR; every statistics difference attributed.
- P5: `make bench` inside budget; the Orca checks listed on #1335 with a
  recipe each.
- After every merge: a docs-only PR carries the change into this document
  and a comment onto each open sibling issue.

## Decisions

- Access and Purchases are one wave (charter step 12).
- A Purchase creates its entry; an entry can exist with no Purchase.
- An entry's command names the Release alone and derives the game
  (`RecordEntry`, `DescribeEntry`); M3's form and P1's creation take the
  same shape. An untracked game is tracked inside the same dispatch,
  never by track-and-retry.
- An entry names its PlayerGame and its Release; a purchase names its
  entry. No column outside the projections points at either.
- `amount` null is unknown, 0 is free; the form has a Free box.
- Zero-price conversion: Epic Games Store rows free, the rest unknown, all
  in the review surface.
- An entry names one visible Release, required; the conversion creates a
  Release per platform the purchase names.
- DLC is a Game with `kind` and `parent` in IGDB's words; passes and the
  upgrade are Purchase kinds.
- `infinite` converts to both exclusion facts; #1334 is in the wave.
- The backlog reads Owned copies held now; every exclusion is its own
  fact. The Games column and facets read the same state.
- An immediate act is one click with a sequence-keyed Undo, never a
  page; a detailed one is a page with no Undo.
- "Copy" and "Library" are the person's words; "entry" is the code's.
- Entry and purchase days are endpoints at any precision; the opening
  ones have no void.
- Entry, catalog and PlayerGame members merge alone; the Purchase
  aggregate, the conversion and the cutover are one stack.
- #1275 landed before the wave and is its dependency, not a member.
- A demo, a beta or a test is an Edition of kind `prerelease`, one word
  for all, made and picked like any other; no run kind. The backlog and
  Before start read full editions; hiding prerelease play is one toggle,
  after #1354.

## Follow-up issues filed

- #1352, the Library screens (M3)
- #1353, `Game.kind` and `Game.parent` (M7)
- #1354, a Release on a session and a record
- #1355, bulk end of access over entries
- #1361, a toggle that hides prerelease play (after #1354)
- #1375, a library's own Release under a shared Edition
- #1418, report the purchases no rate can value (epic #602, beside #493)
- #1437, move a purchase to another copy (after P5b)
- #1354, the Release a session or record was played on; ruled 2026-10-03:
  it adds the full-editions clause to `outside_playthrough_dates` (a
  prerelease Release is never outside dates); a move to another game
  clears the Release through `release_changed(None)` in the same
  dispatch, counted in the answer and restated by the bulk move's Undo,
  and `historicalplaytime.moved` carries `release: None`; resume carries
  no Release; a changed Release must name a Release the library holds a
  live copy on, ended or not, hinted as an ended device is, and nothing
  checks it again afterwards; Bulk Edit's Release field mirrors the
  playthrough field. Implemented: `ReleaseReference` is a plain
  `Annotated` alias, since a `type` statement hides the metadata the
  arity scan strips; the ownership audit's `release_game_violations`
  filters null Releases before its negated lookup; the entry commands
  and the session commands share one set of Release sentences
- #1486, a Release column on the Sessions and Historical lists (after #1354)
- #1487, quick facets for edition kind on the Playtime lists (after #1354)
- #1476, a moved run implies no status on its new game (found on
  #1466's first use; the endpoint writer's Played/Completed rule applies at
  the target); implemented: `games/writes/implied_status.py` holds the rule
  and the status write, and both the endpoint acts and the move call
  them. A move reads the endpoints held before its draft, so the Edit
  page's Played box asks the status again after the move
- #1466, move a playthrough to another game: the conversion's DLC Games
  hold no run the base game recorded before them, and Edit playthrough
  locks the game (filed 2026-10-03 from the DLC as games review). A
  record follows through its own `historicalplaytime.moved`, because a
  restatement stamps `restated_at` and blocks the reclassification's
  Undo. A reader that keys a past act on `run.player_game` reads the
  wrong game after a move: batch Undo reads `run_game_at_batch`.
- #1463, the purchase amount shows one price again, the original in a
  popover
- #1468, a refunded purchase shows on neither copy screen: Game detail's
  copy cards and the Library tab's Purchases column read `held_purchases`,
  unrefunded only, and the previous copies sit behind a note; every live
  purchase of a copy, refunded struck through, and the note a disclosure
  (filed 2026-10-03 from the review; pairs with #1463)
- #1443, remove the one-time Conversion review rows after P5c, keeping
  `conversion_review` and `Category`
- #1448, remove the conversion pass and its gates at the squash: done.
  PR #1474 (with #1443) deployed as `main-f0b2c89` on 2026-10-03, the
  squash recorded beside the 18 originals; #1472 (PR #1482,
  `main-bf1e975`) took the originals and `replaces`, and the 18-row
  cutover `DELETE` ran the same day, leaving four history rows
  ([Squashing](../../migration-squash.md), "Step two, 2026-10-03"). The
  next migration is `0038`. This document's trim is the close-out's. Ruled 2026-10-03, with
  #1443: one PR, not a stack. It holds #1443, the
  squash of `0019`–`0036` with `replaces` (`0029` and `0035`
  `elidable=True`, both data only; `0031` already, its body a refusal
  naming the squash), and the tooling: `games/backfill/`,
  `verify-purchase-conversion`, `seeded`, the legacy test fixture and
  every `conversion-tooling` test, and `verify-purchase-statistics` with
  `games/purchase_parity.py`, whose only input the rehearsal wrote. The
  tooling cannot outlive the squash by a PR: a fresh database takes the
  squashed file, the replaced nodes leave the graph, and
  `legacy_purchase_model()` cannot render `0034` (measured). The 18
  replaced files, `replaces` and the cutover `DELETE` wait for the
  deployment to record the squash and are their own issue, as #1081 was.
  `games/stats_parity.py` stays. The field, `Category` and its labels
  stay whatever #1432 does; the reasons and targets go with the rows.
  The timeless rewrite of this document is the organizer's close-out and
  lands first; the step-two issue then trims Conversion, Preflight and
  Deployment to what the events left behind, as the Session conversion's
  were
- #1450, `purge-library` fails on an add-on Game with a parent and events
- #1451, `verify-baseline` round-trips both databases (PR #1460, with
  #1454: the anonymizer re-mints the stream head at its first event)
- #1432, the Library page as the one place for purchase data gaps, later
  a library-wide audit screen that absorbs P5b's review surface and
  #1418's report; after P5b, outside the stack, mockup first
- #1382, set the platform across many copies on the Library tab
- #1383, the Game detail redesign, after P5 and #1353
- #1384, the `<form-dialog>` element, and #1385, the epic that opens
  every add and edit form in a modal, tied to #1383
- #1381, #1386, #1387: a row divider in light mode, overflow facet
  chevrons, the device form's stale-page gap
