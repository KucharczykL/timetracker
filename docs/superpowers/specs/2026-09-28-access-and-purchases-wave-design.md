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
- `Edition.kind`, so a demo is an Edition of its game with a Release per
  platform, made and picked like any other; the toggle that hides demo
  play is #1361, after #1354.
- The Add to library form, the Entries list, the Purchases list made
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
| Single-game purchases whose platform is not the game's | 15 |
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

#1275 is on `main`. This wave's first migration is `0020`.

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
`sold`, `lost`, `given_away`, `broken`, `stolen`; `EndWay` in
`games/end_ways.py` grows by the first four, and the entry's payload
states its own subset as a `Literal`.

A resume is a fact, not a void. `access_resumed` is dated, writes the end
columns back to their unstated values, and the history keeps every end.
"Formerly owned" reads `access_end_recorded_at`. #1344 copies this shape
for a device.

Two `CHECK`s admit only the words; a third admits a way exactly where the
marker is set. The row is unique on `(id, library)`; a partial index on
`(library, release)` covers live rows. The reference kind is
`libraryentry`, resolution `PROJECTED`, named as `device` is.

`Release` carries no `library` column, so `ProjectionReference.on` cannot
register `release` today. M1 teaches `_is_library_scoped` a path
(`edition__game__library`), so `audit_library_ownership` reports an entry
naming another library's private Release, and the swap's refusal sentence
can name it.

### Purchase

`Purchase` becomes an aggregate, stream `library.purchase`, on the same
table and the same UUIDs; the projection is swapped in place, never
re-minted.

| Column | Meaning |
|---|---|
| `id`, `library` | as today |
| `entry` | the LibraryEntry, `RESTRICT`, required, registered; a pass or an upgrade names the base game's entry |
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
or empty the swap. Columns: `amount` decimal, the rate's identity and
version, `calculated_at`. The currency task is its sole writer. No row
exists for an unknown amount; a free purchase values at 0.
`ExchangeRate.rate` becomes a decimal.

The per-library run state that #630 built (requested and published
version, status, retry) stays and points at valuations. Its trigger moves:
`Purchase.save()` bumps the requested version today, and a projector never
calls `save()`, so the write path in `games/writes/purchase.py` requests a
valuation after any dispatch that states an amount (`created`,
`amount_changed`, `restored`). The task finds every live purchase with an
amount and no valuation at the published version and target, so
`needs_price_update` has no successor. The float cache and its writer go
at the cutover.

The legacy converter rounds `converted_price` to a whole unit. The seeded
valuations carry that rounding; the first refresh after the cutover moves
every total to the decimal rate, and the reconciliation prints both.

### Game

`kind`: `main`, `dlc`, `expansion`, `standalone_expansion`. The words are
IGDB's `game_type` words; #782 admits the rest (remake, remaster, port and
the others) when it meets them, and maps one to one. `parent`: a Game,
`RESTRICT`, null exactly where the kind is `main`, IGDB's `parent_game`.
Both are Game columns, written by `save_game_columns` in
`games/catalog_submit.py` from `GameForm`, beside the graph
`state_catalog_graph` writes; a parent must be visible to the library. A
private DLC reconciles to IGDB's through the same redirect as any private
Game.

### PlayerGame

`excluded_from_dropped`, stated by `RecordPlayerGameFacts` through
`playergame.excluded_from_dropped_changed`, the sibling of
`excluded_from_unfinished_changed`. Each figure that leaves a game out
reads its own fact and nothing else; the rule this wave makes is that no
fact stated for one figure decides another.

### Edition

A demo is another version of the game, so it is an Edition of that game,
`kind` `demo`, with a Release per platform. An open or closed beta, an
alpha, a network test, a playtest or a stress test is the same shape
with the word `beta`: a build that closes, where a demo stays. The
Edition's name says which ("Open Beta", "Network Test"); the kind says
what the machinery reads. Early Access is the full game sold unfinished,
so `full`, as every other Edition is. The word is a catalog fact, shared as the Edition is, stated
through `CatalogGraphForm` beside the name, and picked in Add to library
as any Release is, told apart by its edition. It is not a playthrough
kind and not a second run: demo sessions sit on the game's run, and the
run's start stays the day the full game began. Three readers hold the
word. The backlog reads Owned entries on full editions, or a free demo
download would put the game in it. Before start (#1358) reads sessions
on full editions, since a demo precedes the game by nature. And the
toggle #1361 adds, one library setting stats and lists read alike, is
the set of edition kinds hidden, so hiding demos never decides betas; it
needs a session to name its Release, so it follows #1354. A Trial is the
full game, on its own Edition. An entry on a demo or a beta states the
access the person likes, Owned for a free download or the charter's
Demo, and a beta's access ends `expired` the day the test closes; no
reader tells demo play from the access word, only from the Edition.
`Edition.kind` lands in M7 beside `Game.kind`. The one beta the dump
holds, "Diablo 4 Open Beta", is a private Game with one session and
becomes a beta Edition of Diablo IV by hand, not by the pass.

### FilterPreset

`mode` gains `entries`.

## Commands and events

Every command runs under `answered()`, is fingerprinted for idempotency,
resolves rows through `library_row`, carries a sentence on every refusal,
and answers `Unchanged` ahead of every refusal, as the sibling aggregates
do.

### LibraryEntry

`games/commands/libraryentry.py`, request-free half
`games/writes/libraryentry.py`.

| Command | Event | Rule |
|---|---|---|
| `RecordEntry` | `libraryentry.created` (player game, release, access, format, note, `effective_time` the acquired day) | a Release the library cannot see is 404 from scope; a removed Release is refused; the Release must belong to the tracked game; an untracked game is tracked first, as the session path does |
| `DescribeEntry` | `access_changed`, `format_changed`, `note_changed`, `release_changed`, one per differing fact | the new Release must be a live Release of the same game |
| `CorrectEntryAcquisition` | `acquisition_corrected` | the opening endpoint's correction |
| `EndEntryAccess`, `CorrectEntryAccessEnd`, `VoidEntryAccessEnd` | `access_ended`, `access_end_corrected`, `access_end_voided` | the primitive's three, with a `before_event` that refuses a removed entry |
| `ResumeEntryAccess` | `access_resumed` (note, `effective_time` the day) | refused where no end stands |
| `RemoveEntry`, `RestoreEntry` | `removed`, `restored` | removal refuses while a live Purchase names the entry, with a sentence naming the move; restore refuses under a removed PlayerGame or Release |

`BlockingReferrer.on` refuses a field that is not a key to a run. M1
gives it the target model as a parameter, so `Purchase.entry` registers
beside the two run referrers with the same `alive()` rule.

### Purchase

`games/commands/purchase.py`, `games/writes/purchase.py`.

| Command | Event | Rule |
|---|---|---|
| `RecordPurchase` | `purchase.created` (entry, kind, name, amount, currency, note, `effective_time` the purchased day) | names an existing entry, or carries a new entry's fields and emits `libraryentry.created` first in the same dispatch, as `TrackGame` emits two; currency required exactly where an amount is stated |
| `DescribePurchase` | `kind_changed`, `name_changed`, `amount_changed` (amount and currency, one fact), `note_changed`, `entry_changed` | the new entry must be a live entry of the same game |
| `CorrectPurchaseDay` | `purchase_day_corrected` | the opening endpoint's correction |
| `RefundPurchase`, `CorrectPurchaseRefund`, `VoidPurchaseRefund` | `refunded`, `refund_corrected`, `refund_voided` | the primitive; a refund also appends `libraryentry.access_ended` with way `refunded` on the entry where it is Owned, live and unended, in the same dispatch, as the reclassification writes a second aggregate; the void takes that end back only where the entry's marker is still set and its latest end-family event is the refund's own |
| `RemovePurchase`, `RestorePurchase` | `removed`, `restored` | the removal is the charter's void; the stream keeps the money; restore refuses under a removed entry |

### PlayerGame and catalog

`RecordPlayerGameFacts` gains `excluded_from_dropped`, a fourth
`bool | None`. `GameForm` and `save_game_columns` take `kind` and
`parent`.

### Bulk acts

Declared in `games/bulk_actions.py`, Undo through `EventRows`:
`entry.edit` (access, format, note; an empty field keeps), `entry.remove`,
`purchase.edit` (amount with Free, currency, kind, name, note; keep),
`purchase.remove`. The Edit acts live beside the others and share
`games/bulk_edit.py`.

### API

`GET`/`POST /api/entries/`, `GET`/`PATCH /api/entries/{id}`, and the same
four under `/api/purchases/`. The prefixes are plural, as `/api/games/`,
`/api/devices/` and `/api/platforms/` are; the bodies follow the session
routes: `extra="forbid"`, a named key is the act, an `Idempotency-Key`
header on `POST`, 404 from the command for a row the library does not
hold, 409 with the command's sentence for every other refusal.

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
   purchase, parent the base game, with a default Edition and a Release on
   the base's platform, tracked as a PlayerGame with default facts. No
   add-on is among the 15 mismatched-platform rows. The 6 passes and the
   upgrade stay purchases of their kind on the base entry.
3. **Releases (15).** Where the purchase's platform is not the game's, a
   private Release on that platform under the default Edition.
   **Demo editions (34).** For each Demo purchase, a private Edition of
   kind `demo` named "Demo" under its game, with one Release on the
   purchase's platform; the entry of step 4 names that Release. A game
   holding a demo Release beside its full one is in the review surface.
4. **Entries.** One per (purchase, game). Access and format by the table
   below; acquired the purchase day, exact; an end with way `refunded` on
   the refund day where one exists. The 81 non-owned rows at price 0
   become an entry and no Purchase. A game bought twice gets two entries
   on one Release.
5. **Purchases.** Kind (`du` → `upgrade`), name, amount quantized to two
   places (two rows change; the delta is reported), currency upper-cased
   (three rows), 0 → Free on Epic Games Store, else unknown; the two
   endpoints; the entry link. Valuations are seeded from `converted_price`
   at the current published version; sums per currency are compared before
   and after.
6. **Infinite (30 games).** Both exclusions stated through
   `RecordPlayerGameFacts`; the 6 mixed games are printed with the old and
   new backlog counts.
7. The legacy columns go, in the same stack.

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

`make verify-purchase-conversion` is read-only: it prints every review
list and both backlog counts. With `--confirm NAME` on a restored dump it
runs the pass and prints the reconciliation: counts per category, totals
per currency, refunded count, entries by access and format, quantization
deltas, and every statistics difference with its attribution (see
[Statistics](#statistics)). `make verify-dump` and
`make verify-baseline ARGS="--migrate"` run on the day's dump before the
deploy. The pre-deploy dump is the rollback.

### Review surface

A "Conversion review" section on the Library page, one row per category
with its count. Unknown price (54) and Epic free (19) link to the
Purchases list with its price-state facet and platform set. Rentals (30)
link to the Entries list at Access: Rented. Repurchased games (39) link to
the Games list at entry count two or more. Created Releases (15) and mixed
games (6), which no filter expresses, render as rows: the pass tags their
`libraryentry.created` and `playergame` events with the category in
`source_metadata`, the section reads those events by the pass's
correlation id through `batch_aggregate_ids`, and each row links to its
edit page. A Release writes no event, so the row is the entry that names
it. Demo editions (34, of which 30 games hold sessions) link to the
Games list at entry access Demo; the pass names no session's Release,
because no finder is reliable, and #1354's bulk Edit field is where a
person states which sessions were the demo. A "Hide this review" checkbox on `UserLibraryPreferences` closes the
section; it is its own toggle, read from nothing else.

The sample fixture is regenerated after the cutover. The anonymizer
shifts an entry's and a purchase's days as it shifts a purchase's today,
by the row's own jitter, and randomises which entry a purchase names as it
randomises the through table today.

## Screens and reads

### Forms

**Add to library** replaces Add purchase: one submit records one item.
Game; a Release picker over the game's live Releases, the sole one
preselected, whose create row takes a platform and states a private
Release through the catalog service. This is the selector #893 deferred:
visible Releases only, similar ones told apart by platform, edition and
date, an explicit choice, never inferred. Then Access, Format, Acquired (a
temporal field), Note, and a three-way Purchase segment: Paid (amount,
currency), Free, No purchase. An access other than Owned starts on No
purchase and Owned on Paid; a default, changed at will. Kind and Name
appear for a pass or an upgrade, which name an existing entry of the game
in place of a Release; on a game with no entry the picker offers to record
one, Owned and Digital, in the same submit. The "separate price per game"
mode and the row Split go with the bundle.

**Edit entry**: access, format, release, acquired, access end (way, day,
note; "Held" voids, "Resumed" states the fact), note. **Edit purchase**:
kind, name, amount with Free, currency, purchased, refund (day, note; "Not
refunded" voids), note. The row Refund act stays immediate with today's
day, corrected on the edit page.

### Lists

**Entries** (`entries` mode, its own filter and presets, selectable, a
navbar item beside Purchases): Game, Platform, Access, Format, Acquired,
Access ended (way · day), Purchases, Created. Facets access, format,
ended, way, platform, acquired, game. Tray Edit and Remove; row menu Edit,
End access, Resume, Remove.

**Purchases** (selectable, the Actions column retired, #1266): Name (the
game, or product · game), Kind, Amount (Free and Unknown as words, the
valuation beside), Purchased, Refunded, Finished, Created. Facets kind,
amount, price state (Paid, Free, Unknown), purchased, refunded, and access
and platform through the entry. Tray Edit and Remove; row menu Edit,
Refund, Remove.

**Games**: an Access column ("Owned · Digital", or "2 entries") and facets
access and format over live entries, annotated through `player_games` so
the shared-catalog scope holds; a Kind column and facet, off by default.
**Game detail**: a Library section listing entries with their purchases
beneath and the add and edit acts; an Add-ons section on a main game; a
parent link on an add-on.

### Filters and presets

`EntryFilter` is new: access, format, the two endpoints as intervals and
acts, way, platform through the Release, game, `game_filter`,
`purchase_filter`. `PurchaseFilter` is rewritten on the new columns:
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

`games/reads/entries.py`: `library_entries()`, `game_entries()`, the
per-game access summary the Games column reads. `games/reads/purchases.py`:
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
in scope by containment, in the library's display currency. "N with no
known price" prints beside any total an unknown amount left out. Purchased
count, refunded count and refunded percent read purchases on the two
endpoints.

**Backlog** reads entries with Owned access, live, joined to the game.
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

**Parity gate.** `make verify-purchase-conversion --confirm` judges every
`StatsData` key, for every year and all-time, by a rule stated per key in
`games/stats_parity.py`, which gains a second comparison shape beside the
session-row one. The population changes the pass makes are the only
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

## Delivery order

The entry, catalog and PlayerGame members merge alone, each a PR against
`main`, with `main` incomplete between them as the last wave allowed;
nothing in them converts data, and each holds events for every row it
projects. The Purchase members cannot: a `ProjectionModel` whose rows
hold no events fails the replay gate, so the Purchase aggregate, its
conversion and the cutover are one `gh stack merge`, P1 to P5. M1 before
M2 before M3; M7 and M8 any time; the stack after every member, and P5's
backlog reads M7's edition word.

| Member | Issues | Delivers |
|---|---|---|
| M1 | #719, #720, #722 | the opening endpoint whole, its one correction (`CorrectEntryAcquisition`) included, since the replay gate refuses a registered event type no command emits; the LibraryEntry aggregate: schema without the end columns, creation, description, removal and restore as commands with no route, multiple entries, reference kind, `_is_library_scoped` path, the generalised referrer registry, replay gate, the four API routes with `limit`/`offset` |
| M2 | #721 | the end columns and their `CHECK`s in a migration of its own, as `0019` added the device's; access end and resume on the primitive |
| M3 | #1352 | the Entries screens: list, filter, presets, navbar item, bulk Edit and Remove, the Games Access column and facets, Game detail's Library section, the entry forms |
| M7 | #1353 | `Game.kind` and `Game.parent`, `Edition.kind`: columns, form, Game detail add-ons, Games facet |
| M8 | #1334 | `excluded_from_dropped` and its bulk Edit field |
| P1 | #725, #726, #828 | the Purchase aggregate: projection, creation with an entry, description, day correction, removal, API |
| P2 | #727 | refund endpoints and the coupled entry end |
| P3 | #728, #729 | `PurchaseValuation`, decimal rates, the run state re-pointed, the valuation request on the write path |
| P4 | #723, #730, #731, #732, #733 | the conversion pass, `verify-purchase-conversion`, the reconciliation |
| P5 | #724, #736, #734, #735, #1266 | every read and write switched: the Add to library form, the Purchases list selectable, filters, presets, statistics and links, #1157's readers, the review surface, the legacy columns and the float writer dropped |

Each member passes the full gate on its own against a fresh database.
Each gets its own specification and plan before code. An issue delivered
inside a member says so in its body and closes with it.

## What this design forecloses

- **Moving an entry or a purchase to another game.** `release_changed`
  and `entry_changed` stay inside one game. A row recorded on the wrong
  game is removed and recorded again, and the removed purchase's money
  stays in the stream under the old game. The cost of lifting it later is
  a command that restates `player_game`, and every reader that caches the
  game key.
- **A pass without an entry.** A pass or an upgrade names an entry. The
  form records one in the same submit where the game has none, so the
  person is never blocked, but a pass on a game the library does not own
  is recorded as owning it.
- **One end per entry at a time.** The projection holds the latest end;
  the stream holds them all. A list of a copy's lendings is a stream read
  nothing renders yet.
- **Demo play before #1354.** A session is demo play through the
  Release it names, and no session names one until #1354; until then a
  demo session is a session on the game's run, counted everywhere.
  The cost of an earlier answer is a run kind or a session flag that
  #1354 would then have to reconcile with the Release.
- **A refund of a non-owned entry.** The refund ends access only on an
  Owned entry; a refunded subscription or rental keeps its own end, stated
  by hand.

## Cross-wave handoffs

- **A Release on a session or a record** stays reserved `None`. The picker
  this wave builds is the one #690 and #705 deferred; #1354 puts it on the
  session and record forms, with the rule that a session names a Release
  only where the library holds an entry on it.
- **Bulk end of access over entries** is #1355, beside #1345.
- **#1344** copies `access_resumed`; **#1347** copies the opening
  endpoint. **#1346** decides where a sale price lives; this wave puts no
  money on an end.
- **#782** maps IGDB `game_type` to `Game.kind` one to one and admits the
  remaining words.
- **#762** and **#750** read the Purchase projection this wave leaves.
- **#773** closes with P5 where every legacy field is gone, or keeps what
  remains.
- **#1337**'s bundle case disappears with the M2M; the issue keeps the
  general rule.
- **#493** is unchanged; a forgotten rate now invalidates valuations.
- **#889** later moves the per-platform figures onto the Release the entry
  names.
- **#1157** draws its card from this wave's readers.
- **#1358**'s Before start reads sessions on full editions once #1354
  lets a session name a demo Release; #1354 owns that clause, and its
  bulk Edit Release field is how an existing demo session is placed.
  Until then a demo session counts as one nobody has placed yet. **#1361**, the toggle that hides demo
  play from statistics and lists, follows #1354.

## Deployment

One image carries the stack. The container's startup `migrate` runs the
pass; the pre-deploy dump is the rollback. Before the deploy, on that
day's dump: `make verify-purchase-conversion ARGS="--confirm NAME"`,
`make verify-replay-parity`, `make verify-dump`, `make verify-baseline
ARGS="--migrate"`. After it: the review surface, the first valuation
refresh and its printed totals, then the fixture PR.

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
- The backlog reads Owned entries; every exclusion is its own fact.
- Entry and purchase days are endpoints at any precision; the opening
  ones have no void.
- Entry, catalog and PlayerGame members merge alone; the Purchase
  aggregate, the conversion and the cutover are one stack.
- #1275 landed before the wave and is its dependency, not a member.
- A demo is an Edition of kind `demo`, made and picked like any other;
  no run kind. The backlog and Before start read full editions; hiding
  demo play is one toggle, after #1354.

## Follow-up issues filed

- #1352, the Entries screens (M3)
- #1353, `Game.kind` and `Game.parent` (M7)
- #1354, a Release on a session and a record
- #1355, bulk end of access over entries
- #1361, a toggle that hides demo play (after #1354)
