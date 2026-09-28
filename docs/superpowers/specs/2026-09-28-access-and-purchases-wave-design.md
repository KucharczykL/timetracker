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
| Rented on Xbox Gamepass / on PlayStation 4 and 5 | 6 / 29 |
| Price 0: Owned digital / non-owned (rental, demo, pirated, borrowed) | 73 / 81 |
| Price 0 and Owned, on Epic Games Store / Steam / PlayStation 5 / other | 19 / 35 / 8 / 11 |
| Bundles (2 to 8 games) | 7 |
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

Three readings shape the design. Every row today is the way the library
says "I have this", money or none, so the form that records access stays
one form. Rentals are largely 2021–2022 PlayStation and Gamepass catalog
play, so the charter's `Subscription` word is needed on day one. Every
add-on names the base game, so a DLC has no catalog identity yet and the
conversion must state one.

## Aggregates and storage

The #1275 stack lands first. This wave's first migration is `0020`.

### LibraryEntry

A new aggregate, stream `library.libraryentry`, projection
`games_libraryentry`, written only by the `Entries` projector.

| Column | Meaning |
|---|---|
| `id` | the aggregate id |
| `library` | the owning library |
| `release` | the Release, `RESTRICT`, through the existing `catalog.release` reference kind |
| `access` | `owned`, `borrowed`, `rented`, `subscription`, `trial`, `demo`, `pirated` |
| `format` | `physical`, `digital`, `unknown` |
| `note` | text |
| `acquired`, `acquired_lower`, `acquired_upper`, `acquisition_recorded_at`, `acquisition_note` | the acquired endpoint |
| `access_ended`, bounds, `access_end_recorded_at`, `access_end_note`, `access_end_way` | the end endpoint |
| `removed_at` | the projector's mark |

Both endpoints are declared through `games/endpoints.py` and their columns
through `games/endpoint_fields.py`; `games.E014` holds each against the
model. The acquired endpoint has no void: the creation states it, a
correction moves it, and an unknown day is null. The end endpoint's ways
are `returned`, `expired`, `revoked`, `refunded`, `sold`, `lost`,
`given_away`, `broken`, `stolen`; `EndWay` in `games/end_ways.py` grows by
the first four, and the entry's payload states its own subset as a
`Literal`.

A resume is a fact, not a void. `access_resumed` is dated, writes the end
columns back to their unstated values, and the history keeps every end.
"Formerly owned" reads `access_end_recorded_at`. #1344 copies this shape
for a device.

Two `CHECK`s admit only the words; a third admits a way exactly where the
marker is set. The row is unique on `(id, library)`; a partial index on
`(library, release)` covers live rows. The reference kind is
`library.libraryentry`, resolution `PROJECTED`, as the device's is.
`Purchase.entry` is registered in `AUDITED_PROJECTION_REFERENCES`.

### Purchase

`Purchase` becomes an aggregate, stream `library.purchase`, on the same
table and the same UUIDs; the projection is swapped in place, never
re-minted.

| Column | Meaning |
|---|---|
| `id`, `library` | as today |
| `entry` | the LibraryEntry, `RESTRICT`, required; a pass or an upgrade names the base game's entry |
| `kind` | `game`, `season_pass`, `battle_pass`, `upgrade` |
| `name` | the product name; blank for a game |
| `amount` | `DecimalField(12, 2)`; null is a price nobody knows; 0 is free |
| `currency` | ISO code; required exactly where `amount` is stated, by `CHECK` |
| `purchased`, bounds, `purchase_recorded_at`, `purchase_note` | the purchased endpoint; the creation states it |
| `refunded`, bounds, `refund_recorded_at`, `refund_note` | the refund endpoint |
| `note` | text |
| `removed_at` | the projector's mark |

Gone at the cutover: `games`, `platform`, `related_game`, `type`,
`ownership_type`, `infinite`, the float `price`, `converted_price`,
`converted_currency`, `needs_price_update`, `num_purchases`,
`price_per_game`, `date_purchased`, `date_refunded`, and the three price
signals. Game and platform are read through the entry's Release. Between
M4 and S2 the new columns are nullable and no deployed writer states them;
S2 makes them `NOT NULL` after the conversion.

A DLC is a Game, so `dlc` is not a purchase kind.

### PurchaseValuation

Conventional, per the charter. One row per `(purchase, target_currency)`:
`amount` decimal, the rate's identity and version, `calculated_at`. The
currency task is its sole writer. No row exists for an unknown amount; a
free purchase values at 0. `ExchangeRate.rate` becomes a decimal. The
per-library run state that #630 built (requested and published version,
status, retry) stays and points at valuations; the float cache and its
writer go at S2.

### Game

`kind`: `main`, `dlc`, `expansion`, `standalone_expansion`. The words are
IGDB's `game_type` words; #782 admits the rest (remake, remaster, port and
the others) when it meets them, and maps one to one. `parent`: a Game,
`RESTRICT`, null exactly where the kind is `main`, IGDB's `parent_game`.
Both are stated through `state_catalog_graph` and `CatalogGraphForm`; a
parent must be visible to the library. A private DLC reconciles to IGDB's
through the same redirect as any private Game.

### PlayerGame

`excluded_from_dropped`, stated by `RecordPlayerGameFacts` through
`playergame.dropped_exclusion_changed`. Each figure that leaves a game out
reads its own fact and nothing else; the rule this wave makes is that no
fact stated for one figure decides another.

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
| `RecordEntry` | `libraryentry.created` (access, format, note, `effective_time` the acquired day) | a Release the library cannot see is 404 from scope; a removed Release is refused; an untracked game is tracked first, as the session path does |
| `DescribeEntry` | `access_changed`, `format_changed`, `note_changed`, `release_changed`, one per differing fact | the new Release must be a live Release of the same game |
| `CorrectEntryAcquisition` | `acquisition_corrected` | the primitive's `correct_endpoint` |
| `EndEntryAccess`, `CorrectEntryAccessEnd`, `VoidEntryAccessEnd` | `access_ended`, `access_end_corrected`, `access_end_voided` | the primitive's three, with a `before_event` that refuses a removed entry |
| `ResumeEntryAccess` | `access_resumed` (note, `effective_time` the day) | refused where no end stands |
| `RemoveEntry`, `RestoreEntry` | `removed`, `restored` | removal refuses while a live Purchase names the entry, through a registry entry on `Purchase.entry` beside `BLOCKING_REFERRERS`, with a sentence naming the move; restore refuses under a removed PlayerGame or Release |

### Purchase

`games/commands/purchase.py`, `games/writes/purchase.py`.

| Command | Event | Rule |
|---|---|---|
| `RecordPurchase` | `purchase.created` (kind, name, amount, currency, note, `effective_time` the purchased day, `entry`) | names an existing entry, or carries a new entry's fields and emits `libraryentry.created` first under one correlation id, as `TrackGame` emits two; currency required exactly where an amount is stated |
| `DescribePurchase` | `kind_changed`, `name_changed`, `amount_changed` (amount and currency, one fact), `note_changed`, `entry_changed` | the new entry must be a live entry of the same game |
| `CorrectPurchaseDay` | `purchase_day_corrected` | the primitive |
| `RefundPurchase`, `CorrectPurchaseRefund`, `VoidPurchaseRefund` | `refunded`, `refund_corrected`, `refund_voided` | the primitive; a refund also appends `libraryentry.access_ended` with way `refunded` on the entry where it is Owned, live and unended, under the same correlation id; the void takes that end back only while it is still the latest event of the entry's end family, the rule the batch Undo uses |
| `RemovePurchase`, `RestorePurchase` | `removed`, `restored` | the removal is the charter's void; the stream keeps the money |

### PlayerGame and catalog

`RecordPlayerGameFacts` gains `excluded_from_dropped`. `state_catalog_graph`
takes `kind` and `parent`.

### Bulk acts

Declared in `games/bulk_actions.py`, Undo through `EventRows`:
`entry.edit` (access, format, note; an empty field keeps), `entry.remove`,
`purchase.edit` (amount with Free, currency, kind, name, note; keep),
`purchase.remove`. The Edit acts live beside the others and share
`games/bulk_edit.py`.

### API

`GET`/`POST /api/entries/`, `GET`/`PATCH /api/entries/{id}`, and the same
four under `/api/purchases/`, shaped as the session routes: bodies
`extra="forbid"`, a named key is the act, an `Idempotency-Key` header on
`POST`, 404 from the command for a row the library does not hold, 409 with
the command's sentence for every other refusal.

## The conversion

One pass, out of a migration marked `elidable=True`, as #700 and #1274
ran. `ANALYZE` first. Every event's `recorded_at` is the pass's instant and
its `effective_time` the day the row states. `source_metadata` names the
pass and a review category. Idempotency keys derive from the legacy
purchase id and game id, so a second run appends nothing. In order:

1. **Bundles (7).** One purchase per game. The amount splits by the
   charter's rule in integer cents: each game takes the quotient, and the
   remainder goes one cent each to games ordered by key. The seeded
   valuation splits by the same rule. Day, refund and words are copied.
2. **Add-ons (35 DLC).** A private Game of kind `dlc`, named from the
   purchase, parent the base game, with a default Edition and a Release on
   the base's platform, tracked as a PlayerGame with default facts. The 6
   passes and the upgrade stay purchases of their kind on the base entry.
3. **Releases (15).** Where the purchase's platform is not the game's, a
   private Release on that platform under the default Edition.
4. **Entries.** One per (purchase, game). Access and format by the table
   below; acquired the purchase day, exact; an end with way `refunded` on
   the refund day where one exists. The 81 non-owned rows at price 0
   become an entry and no Purchase.
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

Nothing else is inferred. Every inferred row is in the review surface.

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
link to the Entries list at Access: Rented. Created Releases (15) and mixed
games (6), which no filter expresses, render as rows read from the pass's
batch ids through `batch_aggregate_ids`, each linking to its edit page. A
"Hide this review" checkbox on `UserLibraryPreferences` closes the section;
it is its own toggle, not read from anything else.

The sample fixture is regenerated after the cutover. The anonymizer moves
an entry's and a purchase's dated facts by the game's offset, as it moves a
device's.

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
in place of a Release. The "separate price per game" mode and the row
Split go with the bundle.

**Edit entry**: access, format, release, acquired, access end (way, day,
note; "Held" voids, "Resumed" states the fact), note. **Edit purchase**:
kind, name, amount with Free, currency, purchased, refund (day, note; "Not
refunded" voids), note. The row Refund act stays immediate with today's
day, corrected on the edit page.

### Lists

**Entries** (`entries` mode, its own filter and presets, selectable):
Game, Platform, Access, Format, Acquired, Access ended (way · day),
Purchases, Created. Facets access, format, ended, way, platform, acquired,
game. Tray Edit and Remove; row menu Edit, End access, Resume, Remove.

**Purchases** (selectable, the Actions column retired, #1266): Name (the
game, or product · game), Kind, Amount (Free and Unknown as words, the
valuation beside), Purchased, Refunded, Finished, Created. Facets kind,
amount, price state (Paid, Free, Unknown), purchased, refunded, and access
and platform through the entry. Tray Edit and Remove; row menu Edit,
Refund, Remove.

**Games**: an Access column ("Owned · Digital", or "2 entries") and facets
access and format over live entries; a Kind column and facet, off by
default. **Game detail**: a Library section listing entries with their
purchases beneath and the add and edit acts; an Add-ons section on a main
game; a parent link on an add-on.

### Filters and presets

`EntryFilter` is new: access, format, the two endpoints as intervals and
acts, way, platform through the Release, game, `game_filter`,
`purchase_filter`. `PurchaseFilter` is rewritten on the new columns:
amount, currency, price state, kind, the two endpoints, `entry_filter`,
`game_filter` through the entry. `GameFilter` gains `kind`, `parent`,
`access`, `format`, `entry_count` and an `entry_filter` relation. Saved
purchase presets are rewritten once, as `ended` → `completed` was:

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
Release, Game. No sum reads a float. Sessions and records keep `release`
reserved; the session form gets no picker in this wave.

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
`games/stats_parity.py`: money keys identical within the two quantized
cents, counts identical, backlog keys allowed to differ only by the 6
mixed games and the 35 DLC games now tracked on their own. An unattributed
difference fails the run. `make bench` gains an entries-and-purchases
workload; every read stays inside the 20 ms budget.

## Delivery order

The #1275 stack merges first. Members M1–M8 merge alone, each a PR against
`main`, with `main` incomplete between them as the last wave allowed;
nothing in them converts data. S1 and S2 are one `gh stack merge`, so
`main` never carries a half-converted Purchase. M1 before M2 before M3;
M4 after M1; M5 and M6 after M4; M7 and M8 any time; S1 after every member.

| Member | Issues | Delivers |
|---|---|---|
| M1 | #719, #720, #722 | the LibraryEntry aggregate: schema, creation, description, removal, multiple entries, reference kind, replay gate, API |
| M2 | #721 | acquired correction, access end and resume on the primitive |
| M3 | new | the Entries screens: list, filter, presets, bulk Edit and Remove, the Games Access column and facets, Game detail's Library section, the entry forms |
| M4 | #725, #726, #828 | the Purchase aggregate on the same table, new columns nullable; creation with an entry, description, day correction, removal; legacy writers untouched |
| M5 | #727 | refund endpoints and the coupled entry end |
| M6 | #728, #729 | `PurchaseValuation`, decimal rates, the run state re-pointed; the float writer stays until S2 |
| M7 | new | `Game.kind` and `Game.parent`: columns, service, form, Game detail add-ons, Games facet |
| M8 | #1334 | `excluded_from_dropped` and its bulk Edit field |
| S1 | #723, #730, #731, #732, #733 | the conversion pass, `verify-purchase-conversion`, the reconciliation |
| S2 | #724, #736, #734, #735, #1266 | every read and write switched: the Add to library form, the Purchases list selectable, filters, presets, statistics and links, #1157's readers, the review surface, the legacy columns dropped |

Each member gets its own specification and plan before code. An issue
delivered inside a member says so in its body and closes with it.

## Cross-wave handoffs

- **A Release on a session or a record** stays reserved `None`. The picker
  this wave builds is the one #690 and #705 deferred; a follow-up issue
  puts it on the session and record forms, with the rule that a session
  names a Release only where the library holds an entry on it.
- **Bulk end of access over entries** is a follow-up beside #1345.
- **#1344** copies `access_resumed`; **#1347** copies the acquired
  endpoint. **#1346** decides where a sale price lives; this wave puts no
  money on an end.
- **#782** maps IGDB `game_type` to `Game.kind` one to one and admits the
  remaining words.
- **#762** and **#750** read the Purchase projection this wave leaves.
- **#773** closes with S2 where every legacy field is gone, or keeps what
  remains.
- **#1337**'s bundle case disappears with the M2M; the issue keeps the
  general rule.
- **#493** is unchanged; a forgotten rate now invalidates valuations.
- **#889** later moves the per-platform figures onto the Release the entry
  names.
- **#1157** draws its card from this wave's readers.

## Deployment

One image carries S1 and S2. The container's startup `migrate` runs the
pass; the pre-deploy dump is the rollback. Before the deploy, on that
day's dump: `make verify-purchase-conversion ARGS="--confirm NAME"`,
`make verify-replay-parity`, `make verify-dump`, `make verify-baseline
ARGS="--migrate"`. After it: the review surface, then the fixture PR.

## Verification contract

- Every member: full `make check`; the replay gate through every new
  event type; a fingerprint test per command; two-library tests: a shared
  Release yields independent entries, another library's private Release
  answers 404, another library's entry or purchase is never read.
- Every screen member: `make render-pages` before and after on one
  database, every difference attributed in the PR.
- S1: the reconciliation printed from the day's dump and pasted into the
  PR; every statistics difference attributed.
- S2: `make bench` inside budget; the Orca checks listed on #1335 with a
  recipe each.
- After every merge: a docs-only PR carries the change into this document
  and a comment onto each open sibling issue.

## Decisions

- Access and Purchases are one wave (charter step 12).
- A Purchase creates its entry; an entry can exist with no Purchase.
- `amount` null is unknown, 0 is free; the form has a Free box.
- Zero-price conversion: Epic Games Store rows free, the rest unknown, all
  in the review surface.
- An entry names one visible Release, required; the conversion creates a
  Release per platform the purchase names.
- DLC is a Game with `kind` and `parent` in IGDB's words; passes and the
  upgrade are Purchase kinds.
- `infinite` converts to both exclusion facts; #1334 is in the wave.
- The backlog reads Owned entries; every exclusion is its own fact.
- Entry and purchase days are stated endpoints at any precision.
- Members merge alone; the conversion and the cutover are one stack.
- #1275 is not in the wave: its stack is the wave's dependency.

## Follow-up issues to file

1. Entries screens (M3).
2. `Game.kind` and `Game.parent` (M7).
3. A Release on a session and a record.
4. Bulk end of access over entries.
