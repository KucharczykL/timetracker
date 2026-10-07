# Access and Purchases delivery wave

Date: 2026-09-28. Deployed: 2026-10-02.

Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601).
Charter: [Access, ownership, purchases, and add-ons](2026-08-09-timetracker-overhaul-design.md#access-ownership-purchases-and-add-ons),
[Catalog identity](2026-08-09-timetracker-overhaul-design.md#catalog-identity),
[Mandatory, quiet playthroughs](2026-08-09-timetracker-overhaul-design.md#mandatory-quiet-playthroughs)
(the `Purchase.infinite` paragraph above it).
Builds on: [A device's access ends](2026-09-28-issue-1275-device-access-end-design.md)
(the stated endpoint), [The Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md),
[Catalog](../../catalog.md), [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md).

The charter is the contract. The wave issues #719–#736 held one line each;
where an issue body and the charter differed, the charter held, and this
document records what the wave decided where the charter was silent. Each
member's specification holds its own detail; this document holds the shape,
the decisions, and what the deployment found.

## Purpose

A library says two different things about a game. It has the game: a route
of access to one Release, with a beginning and sometimes an end. It paid
for the game: one financial transaction, with an amount, a currency and a
possible refund. Before the wave both lived on one row, `Purchase`, whose
eight `ownership_type` words mixed three axes: format (Physical, Digital),
access (Rented, Borrowed, Trial, Demo, Pirated) and product (Digital
Upgrade). A demo, a rental and a pirated copy were recorded as purchases at
price 0, and 0 also meant "I do not remember the price".

The wave moved the library's access onto `LibraryEntry`, made `Purchase` an
event-sourced aggregate of one item with decimal money, gave DLC its own
catalog identity, split `infinite` into two explicit facts, and converted
the deployment in one visible cutover, the way charter step 12 asks. Access
and Purchases were one wave because the two aggregates share one form, one
conversion and one set of statistics.

## Product boundary

In:

- `LibraryEntry`: one route of access to one Release, with access, format,
  an acquired day, an end of access with a way, a resume, a note.
- `Purchase` as an aggregate: one item, the copy it names, kind, name,
  decimal amount or unknown, currency, purchased and refunded days, note.
- `PurchaseValuation` in decimals, one per purchase and target currency,
  written by the currency task alone.
- `Game.kind` and `Game.parent`, in IGDB's words.
- `PlayerGame.excluded_from_dropped` beside `excluded_from_unfinished`.
- `Edition.kind`, so a demo or a beta is a prerelease Edition of its game
  with a Release per platform, made and picked like any other.
- Add to library, the Library tab, the Purchases list made selectable, the
  Games list's Access column, Game detail's Library and Add-ons sections,
  filters, presets, statistics, the API.
- The one-time conversion of every legacy row, with its preflight, parity
  gate and review surface, all of which have since left (see
  [The conversion](#the-conversion)).

Out, each handed to a named issue under [Cross-wave handoffs](#cross-wave-handoffs).

## What the data said

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
| Single-game purchases whose platform is not the game's / with no platform | 14 / 8 |
| `infinite` rows / games / games with an infinite purchase beside a normal one | 33 / 30 / 6 |
| Prices with more than two decimals / currency in mixed case | 2 / 3 |
| Demo purchases / of them games also owned | 34 / 7 |

Three readings shaped the design. Every row was the way the library said
"I have this", money or none, so the form that records access stayed one
form. Rentals were largely 2021–2022 PlayStation and Gamepass catalog play,
so the charter's `Subscription` word was needed on day one. Every add-on
named the base game, so a DLC had no catalog identity and the conversion
had to state one. The person had stopped recording demos as purchases so
as not to clog the library, and had played 10 to 20.

## Aggregates and storage

Contracts:
[The LibraryEntry aggregate](2026-09-29-issue-719-libraryentry-aggregate-design.md),
[A copy's access ends and resumes](2026-09-29-issue-721-entry-access-end-design.md),
[The Purchase aggregate](2026-10-01-issue-725-purchase-aggregate-design.md),
[A purchase is refunded](2026-10-01-issue-727-purchase-refund-design.md),
[Purchase valuations](2026-10-01-issue-728-purchase-valuation-design.md),
[Game kind and parent](2026-09-30-issue-1353-game-kind-and-parent-design.md),
[Excluded from dropped](2026-09-30-issue-1334-excluded-from-dropped-design.md).

### The opening endpoint

The stated endpoint of #1275 is an act a row states after it exists:
three events, stated, corrected, voided. An entry's acquired day and a
purchase's purchased day are different: the creation states them, a
correction moves them, and there is nothing to void, because a row with no
acquisition is no row. The primitive gained an **opening endpoint**: the
same columns (the day, its two bounds, the marker, the note), one
correction event, and no `stated` or `voided` spec. The creation event's
`effective_time` is the day; the projector writes the marker from the
creation's `recorded_at`. `games.E014` holds the columns of both variants.

### LibraryEntry

Stream `library.libraryentry`, projection `games_libraryentry`, written
only by the `Entries` projector. A row names its `player_game` (`RESTRICT`,
registered) and its `release` (`RESTRICT`, a Release of that game, held by
a command rule and the replay gate), states `access` (`owned`, `borrowed`,
`rented`, `subscription`, `trial`, `demo`, `pirated`), `format`
(`physical`, `digital`, `unknown`), a note, the acquisition as the opening
endpoint, the end of access as the stated endpoint with a way, and the
projector's mark.

The end's ways are `returned`, `expired`, `revoked`, `refunded`, `sold`,
`lost`, `given_away`, `broken`, `stolen`, and `unstated` ("Not said"),
which a one-click end states with the calendar's day. A resume is a fact,
not a void: `access_resumed` is dated, writes the end columns back, and the
history keeps every end. "Formerly owned" reads `access_end_recorded_at`.

`Release` carries no `library` column, so `LIBRARY_PATHS` in
`games/projections.py` gives a catalog row its path to a library,
`ProjectionReference` carries it as `library_path`, `games.E015` refuses a
path that ends elsewhere, and `visible_row` in `games/commands/scope.py`
resolves a shared row or the library's own through it. The ownership audit
reports an entry naming another library's private Release and one whose
Release is not its game's.

### Purchase

Stream `library.purchase`, projection `games_purchase`, written only by
the `Purchases` projector. The legacy row could not become the projection
in place: a `ProjectionModel` fails the projection checks on the legacy
columns, its mark was `remove()`'s rather than a projector's, the M2M
through table pointed into it, and its rows held no events. So the
incumbent was renamed `LegacyPurchase`, the new `Purchase` was born on
`games_purchase` in its final shape, the conversion wrote one
`purchase.created` per (legacy row, game), and the drop took the legacy
tables and every legacy reader at the cutover, all inside one stack so
`main` never held both.

A row names its `entry` (`RESTRICT`, required; a pass or an upgrade names
a base game's copy), states `kind` (`game`, `season_pass`, `battle_pass`,
`upgrade`), `name` (blank for a game), `amount` (`Decimal(12, 2)`; null is
a price nobody knows, 0 is free), `currency` (required exactly where an
amount is, by `CHECK`), a note, the purchase day as the opening endpoint,
the refund as the stated endpoint, and the projector's mark. A DLC is a
Game, so `dlc` is not a purchase kind. Game and platform are read through
the copy.

### PurchaseValuation

Conventional, per the charter. One row per `(purchase, target_currency)`,
holding the purchase's **key**, never a foreign key: nothing outside the
projections points at a projection row. `amount` is `Decimal(26, 2)`,
rounded half up once, beside the three inputs it read (`source_amount`,
`source_currency`, `rate_year`) and the `rate`, null exactly where the
purchase needs none. The currency task is its sole writer: it values the
whole live set per version and publishes the library's set whole. The
rate's year is `purchased_lower`'s, then `purchased_upper`'s, then the year
of `purchase_recorded_at` in the calendar zone, computed in SQL alone
(`valuation_year`). `ExchangeRate.rate` is `Decimal(24, 12)`.

The run state `PurchaseConversionState` keeps its name and points at
valuations. The write path calls `request_revaluation(library)` after any
dispatch that states an amount or moves the day (`VALUATION_EVENTS`); the
task's trigger is `requested > published` **or** a live purchase in
`stale_purchases`, which also catches a corrected rate (#493) and a row no
write path saw; the daily recovery asks every library at rest. A purchase
whose (currency, rate year) has no rate is skipped at WARNING and stays
stale for the recovery to ask again (#1418 reports them). No `save()` hook
and no `dispatch` hook: `needs_price_update` has no successor.

### Game

`kind`: `main`, `dlc`, `expansion`, `standalone_expansion`, IGDB's
`game_type` words; #782 admits the rest when it meets them. `parent`: a
Game, `RESTRICT`, null exactly where the kind is `main`. `state_addon` in
`games/catalog_addons.py` alone sets both and refuses with `AddonRefused`
on one field: a parent must be visible to the library, live when stated,
and of kind `main`; `main` is refused to an add-on while any add-on names
the game. Removing a main game keeps its add-ons. An add-on is no
top-level row of the Games list unless a `kind` or `parent` leaf appears
anywhere in the filter tree, in which case the base is every kind; a link
whose figure counts every kind states `GameFilter.of_every_kind()`.

Ruled on the person's word after the wave: the catalog follows IGDB. A
remaster or a remake is a separate Game with a parent, as IGDB files it;
an Edition maps IGDB's versions alone (a GOTY or Deluxe cut). #782 carries
the mapping and must split "names a parent" from "hidden from the Games
list by default", since a remaster must stand in the list as a game of
its own.

### PlayerGame

`excluded_from_dropped`, stated by `RecordPlayerGameFacts` through
`playergame.excluded_from_dropped_changed`, the sibling of
`excluded_from_unfinished_changed`. Each figure that leaves a game out
reads its own fact and nothing else: no fact stated for one figure
decides another. The two flags are one "Visibility" group
(`VISIBILITY_FIELDS`) on the Game form, the bulk Edit and the quick bar.
The conversion stated both on every game with an infinite purchase.

### Edition

A demo is another version of the game, so it is an Edition of that game,
`kind` `prerelease`, with a Release per platform. An open or closed beta,
an alpha, a network test, a playtest or a stress test is the same word:
no reader tells one from another, so the kind holds one word and the
Edition's name says which. Early Access is the full game sold unfinished,
so `full`, as every other Edition is; a Trial is the full game on its own
Edition. It is not a playthrough kind and not a second run: prerelease
sessions sit on the game's run. Three readers hold the word: the backlog
reads Owned copies on full editions, Before start reads sessions on full
editions, and #1361's toggle hides prerelease play from statistics and
lists through the Release a session or a record names (#1354). An entry
on a prerelease Edition states the access the person likes, and a beta's
access ends `expired` the day the test closes.

## Commands and events

Every command runs under `answered()`, is fingerprinted for idempotency,
resolves rows through `library_row`, carries a sentence on every refusal,
and answers `Unchanged` ahead of every refusal. Two endpoints on one row
keep their order through one shared `certainly_reversed` in
`games/commands/endpoint.py`: an end certainly before the opening, a
resume certainly before the standing end, and an opening correction
certainly after a standing end are refused, each sentence naming the move.

**LibraryEntry** (`games/commands/libraryentry.py`, writes
`games/writes/libraryentry.py`): `RecordEntry` names the Release alone,
derives the game, and tracks an untracked game inside the same dispatch
through `tracking_events`; `DescribeEntry` states each differing fact,
the new Release a live Release of the same game; `CorrectEntryAcquisition`
is the opening endpoint's correction; `EndEntryAccess`,
`CorrectEntryAccessEnd`, `VoidEntryAccessEnd` are the primitive's three
and `ResumeEntryAccess` the fourth act of a `ResumableEndpoint`, a type
of its own so a resume of a non-resumable endpoint fails in mypy;
`RemoveEntry` takes the copy's live purchases with it in the same
dispatch (`Purchase.entry` is a `CascadingReferrer`, a registry beside
`BLOCKING_REFERRERS` that only `foreign_referrer` reads), and
`RestoreEntry` brings back the purchases whose latest removal shares the
copy's key, so a purchase removed on its own stays removed.

**Purchase** (`games/commands/purchase.py`, writes
`games/writes/purchase.py`): `RecordPurchase` names a held copy or
carries a new copy's fields and emits `libraryentry.created` first;
`DescribePurchase` states each differing fact, the refund included, so a
PATCH is one dispatch, and refuses a kind change under a standing refund
unless the same statement takes the refund back, since the kind decides
whether the refund ended the copy; `CorrectPurchaseDay` is the opening
endpoint's correction; `RefundPurchase`, `CorrectPurchaseRefund`,
`VoidPurchaseRefund` are the primitive's three. A refund of a `game`
purchase ends its Owned, live, unended copy, way `refunded`, in the same
dispatch; a correction or a void moves that end only while
`refund_owns_the_end` says so: the copy's latest end-family event directly
follows a refund act of this purchase under one idempotency key. One
dispatch stamps one key on every event it appends, an invariant every
writer of the column keeps, the anonymizer included. `RemovePurchase` is
the charter's void; the stream keeps the money.

**Bulk acts**, declared in `games/bulk_actions.py` with Undo through
`EventRows`: `entry.edit`, `entry.remove`, `entry.end` (#1355),
`purchase.edit`, `purchase.remove`. The Edit acts share
`games/bulk_edit.py` and one fact-change reader.

**API**: `GET`/`POST /api/entries/`, `GET`/`PATCH /api/entries/{id}`,
`POST /api/entries/{id}/resume`, and the same under `/api/purchases/`.
The bodies follow the session routes: `extra="forbid"`, a named key is the
act, an `Idempotency-Key` header on `POST`, 404 from the command for a row
the library does not hold, 409 with the command's sentence for every other
refusal. A stated endpoint travels as one key: an object states or
corrects it, `null` voids it, an absent key states nothing.

## Screens and reads

"Copy" is the person's word and "Library" the screens' ("Add to library",
the Library tab, Game detail's Library section); "entry" stays in code,
events and the API. A copy leaves with "I no longer have it" and returns
with "I have it again". Screens contract:
[The Library screens](2026-09-29-issue-1352-library-screens-design.md),
[Every purchase write](2026-10-01-issue-724-purchase-writes-design.md),
[Purchase reads](2026-10-01-issue-735-purchase-reads-design.md),
[Purchases selectable](2026-10-02-issue-1266-purchases-selectable-design.md).

**Add to library** replaces Add purchase: Game, a Release picker over the
game's live Releases (the sole one preselected; its create row states a
private Release under the default Edition on a Game the library owns),
Access, Format, Acquired (defaulting to the calendar's day), Note, and a
three-way Purchase segment, Paid, Free, No purchase, on the standalone page
only. That segment is the game's own purchase and nothing more; a pass, an
upgrade or a second purchase is added through "Add purchase…" in the
copy's ⋯ menu. **Edit copy** states access, format, release, acquired,
note; the end of access has its own pages. **Edit purchase** states kind,
name, amount with Free, currency, purchased, refund, note.

**The one-click pattern** is the wave's for every immediate act: a `*_now`
POST carries a submission key, states the act with the calendar's day (an
end with way `unstated`), and offers Undo keyed on the stream sequence its
press appended, which refuses once a later act overtook it; the "With
details…" pages offer no Undo. Refund's Undo is its own command,
`UndoPurchaseRefund`, keyed on the `purchase.refunded` event's sequence.
An edit page carries a stale-page token, so a correction made since the
page opened is refused.

**Lists.** The Library tab (`entries` mode, selectable) lists every copy
with its live purchases' prices; the Purchases list (selectable) shows
Name, Kind, Amount (one price, the valuation, the stated amount in a
popover), Purchased, Refunded, Finished; the Games list has an Access
column and facets over held copies, and a Kind column and facet; Game
detail's Library section lists the copies had now grouped by version with
every per-copy act inline and each copy's purchases under its row, a
note counting the previous copies and their purchases (#1468), and an
Add-ons section on a main game.

**Filters.** `LibraryEntryFilter` is new; `PurchaseFilter` was rewritten
on the new columns and its saved presets rewritten once; `GameFilter`
gained `kind`, `parent`, `access`, `format`, `entry_count` and
`entry_filter`. Every day the wave reads or defaults asks the library's
calendar, never the process clock. `conversion_review`, a choice field on
both filters over the conversion's `Category` words, reads the pass's
tags from events and is the one way to the converted population; its
words stay stable, since a stored preset naming one is refused if the
word goes.

**Reads.** `games/reads/entries.py` and `games/reads/purchases.py` state
every scope through the marks of entry, PlayerGame, Release and Game. No
sum reads a float.

## Statistics

`STATS_SOURCES` gained `ENTRIES`. **Money** reads purchases through
valuations: total spent and spent per game sum the library's live,
unrefunded purchases whose purchased day lies in scope, in the library's
display currency, with "N with no known price" and the unvalued count
beside any total. **Backlog** reads copies, never legacy rows: a copy is a
live entry on a `full` Edition, Owned, held now; a sold copy is no backlog
item, a pass has no copy of its own, and a DLC copy counts through its own
Game. Dropped reads Abandoned or an end of access with way `refunded`,
each exclusion its own fact. **Links**: every builder in `stats_links.py`
compiles the same predicate as its figure, and the parity test covers
each. #1157's readers (entries by access and format, spend by access)
live here; the card stays #1157.

## The conversion

The pass ran once, out of a migration since squashed; what it left behind
is the events. Contract:
[Convert every legacy purchase](2026-10-01-issue-723-purchase-conversion-design.md).

It planned one copy per (legacy row, game) and stated each through the
commands' own `build` under `conversion:723:<act>:<legacy>:<game>` keys,
one `recorded_at`, so every command rule applied and a rerun appended
nothing. Bundles split by integer cents; DLC rows got their own `dlc`
Game under the base, with a default Edition and one Release; a purchase
naming a platform the game's Releases lacked got a private Release; each
Demo purchase got a prerelease Edition named "Demo"; the 81 non-owned
rows at price 0 became a copy and no Purchase; Epic Games Store rows at
0 became Free and the rest Unknown; a refund was appended as
`purchase.refunded` and then the copy's `access_ended` under one key, so
the refund owns the end; both exclusions were stated on every game with
an infinite purchase, an infinite DLC excluding its new Game alone.
Valuations were seeded from the legacy converted price at the published
version, and the first refresh after the cutover moved every total to the
decimal rate.

| Legacy word | Access | Format |
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

The two platform rules (Gamepass, Epic) were the only inferences. Every
pass append carries `source_metadata` naming the pass and its review
categories, which `conversion_review` reads. A one-time review surface on
the Library page listed each category's count and link until the person
hid it; #1443 removed the rows, the checkbox and the preference once the
review was done, and the field stayed.

On the deployed library: 808 legacy rows became 833 copies and 758
purchases, 0 skipped, 0 refusals; totals reconciled per currency (EUR
−0.0050 from two third-decimal rows); 221 of 221 refunds ended their
copy; 48 Releases created (14 platform, 34 demo); backlog unfinished 282
→ 282 and dropped 268 → 267; tracked games 863 → 898; every statistics
figure attributed against the legacy snapshot, all-time total spent equal
to the cent; replay parity 0 differing. What the pass found:

- A removal is two keys, `removed` then `removed_copy`: `RemoveEntry`
  reads the projection, which shows the live purchase until the first
  append projects, so one build cannot hold both.
- A copy recorded by hand between the Library screens and the cutover
  beside a legacy purchase of the same copy became two copies, since no
  rule tells one copy stated twice from two copies; the review listed
  them as "Repurchased games".
- The pass named no session's Release, because no finder was reliable;
  #1354's bulk Edit field is where a person states which sessions were
  the demo.
- A bench run straight after a bulk conversion plans against empty
  statistics; the pass ran `ANALYZE` on the tables it read.

The conversion tooling (`games/backfill/`, `verify-purchase-conversion`,
`verify-purchase-statistics`, the seeded valuation, the legacy test
fixture) left with the fourth squash: a fresh database takes the squashed
file, the replaced nodes leave the graph, and the historical model cannot
be rendered, so the tooling could not outlive the squash by a PR. The
squash's first operation refuses a database whose legacy tables still
hold rows. See [Squashing](../../migration-squash.md), "Step two,
2026-10-03".

## Delivery order

The entry, catalog and PlayerGame members merged alone, each a PR against
`main`, with `main` incomplete between them; nothing in them converted
data, and each held events for every row it projected. The Purchase
members could not: a `ProjectionModel` whose rows hold no events fails
the replay gate, so the Purchase aggregate, its conversion and the cutover
were one `gh stack merge`, each member passing the full gate on its own.

| Member | Issues | Delivered |
|---|---|---|
| M1 (PR #1362) | #719, #720, #722 | the opening endpoint; the LibraryEntry aggregate, commands, reference kind, `LIBRARY_PATHS`, the generalised referrer registry, replay gate, the API |
| M2 (PR #1366) | #721 | the end columns; access end and resume on the primitive |
| M3 (stack #1379) | #1352 | the Library screens: Add to library, Game detail's Library section, the end and resume pages with one-click Undo, the Library tab, `LibraryEntryFilter`, presets, bulk Edit and Remove, the Games tab's Access column |
| M7 (PR #1390) | #1353 | `Game.kind`, `Game.parent`, `Edition.kind`, `state_addon`, the Add-ons section, the Games list's main-only base |
| M8 (PR #1397) | #1334 | `excluded_from_dropped`, the Visibility group |
| P1 (PR #1403) | #725, #726, #828 | the incumbent renamed; the Purchase aggregate born on `games_purchase` |
| P2 (PR #1408) | #727 | the refund endpoint and the coupled copy end |
| P3 (PR #1417) | #728, #729 | `PurchaseValuation`, decimal rates, the valuation request on the write path |
| P4 (PR #1425) | #723, #730–#733 | the conversion pass, its preflight and reconciliation |
| P5a (PR #1431) | #734, #735 | every read: `PurchaseFilter` on the projection, the presets rewritten, the Purchases list, every statistic through entries, purchases and valuations, the links and their parity tests, the statistics gate |
| P5b (PR #1439) | #724 | every write: the purchase segment on Add to library, Add and Edit purchase, one-click Refund with Undo, the legacy routes retired |
| P5b2 (PR #1445) | #1266 | the Purchases list selectable, the conversion review, the Library tab's Purchases column |
| P5c (PR #1452) | #736 | `LegacyPurchase`, its tables, routes, signals and float cache dropped; the fixture regenerated |
| P6 (PR #1458) | #1450 | the library event stream's key made deferrable, so `purge-library` works on a library holding a parented add-on with events |

Migrations `0020` to `0036`, since squashed into one.

**Deployed on 2026-10-02.** One image carried the stack; the container's
startup `migrate` ran the pass on the day's data, which differed from the
rehearsed 2026-10-01 dump by one session changed and one added. The
rehearsal, on a restored dump: migrate to the valuation table, the pass
rolled back with a fresh legacy snapshot, the pass committed with its
reconciliation, the next migration appending nothing (idempotency on real
data), the drop, the statistics gate against the snapshot, then replay
parity, `verify-dump` and `verify-baseline --migrate`. The last found a
spelling difference and no drift: `pg_dump` and `pg_restore` rewrite a
varchar `CHECK`'s text once, so a tool comparing catalogs reads both
sides after the same number of trips (#1451). After the deploy: the
schedule row for the valuation task existed, the first refresh published
12 of 12 purchases at the decimal rate, `stale_purchases` was empty, and
the post-deploy dump became the sample fixture's source (#1454).

## What this design forecloses

- **Moving a copy to another game.** `release_changed` and
  `entry_changed` stay inside one game. A copy recorded on the wrong game
  is removed and recorded again, and the removed purchase's money stays in
  the stream under the old game. Lifting it is #983's merge of Games into
  Editions, which restates `player_game` on runs, records and copies. A
  run's move was lifted first: #1466.
- **A pass without a copy.** A pass or an upgrade is added from a copy's
  ⋯ menu, so it always names a copy the library holds.
- **One end per copy at a time.** The projection holds the latest end;
  the stream holds them all, and a resume leaves nothing on the row. An
  end the copy resumed from can no longer be corrected or voided, and a
  mistaken resume is taken back by stating the end again. Lifting it is a
  `resumed` day with bounds, held until the next end clears it.
- **Demo play placed by hand.** A session is demo play through the
  Release it names (#1354); nothing infers a demo from the game, the run
  or the day.
- **A refund of a non-owned copy.** The refund ends access only on an
  Owned copy; a refunded subscription or rental keeps its own end, stated
  by hand.
- **Two refunded purchases of one copy.** The copy's end is the first
  refund's; the second finds the copy ended and couples nothing.

## Cross-wave handoffs

Delivered after the wave, each with its own contract:

- **#1354**, the Release a session or a record was played on, which also
  carried the full-editions clause into `outside_playthrough_dates`; a
  move to another game clears the Release in the same dispatch; resume
  carries none; a changed Release must name a Release the library holds a
  live copy on, ended or not.
- **#1361**, the toggle that hides prerelease play, after #1354.
- **#1355**, bulk end of access over copies, on `games/bulk_access_end.py`,
  which #1345 declares the device act on; the batch Undo guard is one
  function over an endpoint's event family.
- **#1382**, the platform across many copies, resolving each game's
  Release on the platform and never creating one.
- **#1466**, a run moved to another game, with #1476's implied status.
- **#1463** and **#1468**, one price in the Amount cell, and the previous
  copies and their purchases counted on Game detail.
- **#1443**, the review surface removed; **#1448** and **#1472**, the pass
  and its tooling removed at the fourth squash.
- **#1450**, **#1451**, **#1454**: the deferrable stream key, the
  baseline's round trip, the anonymizer's stream head.

Still open:

- **#1375**, a library's own Release under a shared Edition.
- **#1345**, bulk end of access over devices, on #1355's module.
- **#1437**, move a purchase to another copy from Edit purchase.
- **#1418**, report the purchases no rate can value, beside #493's repair
  surface; **#1432**, the Library page as the one place for data gaps.
- **#782**, IGDB `game_type` mapped onto `Game.kind`, with the list
  visibility split; **#983**, duplicate private Games merged into one
  Game's Editions, the lift of the foreclosure above.
- **#1157**'s card, drawn from this wave's readers; **#889**, the
  per-platform figures moved onto the Release the copy names; **#1383**,
  the Game detail redesign; **#1499**, then **#1384** and **#1385**,
  the modal layer and the form dialog.

## Decisions

- Access and Purchases are one wave (charter step 12).
- A Purchase creates its copy; a copy can exist with no Purchase.
- A copy's command names the Release alone and derives the game; an
  untracked game is tracked inside the same dispatch.
- A copy names its PlayerGame and its Release; a purchase names its copy.
  No column outside the projections points at either.
- `amount` null is unknown, 0 is free.
- Zero-price conversion: Epic Games Store rows free, the rest unknown.
- DLC is a Game with `kind` and `parent` in IGDB's words; passes and the
  upgrade are Purchase kinds; a remaster or a remake is a Game with a
  parent, an Edition is an IGDB version.
- `infinite` converted to both exclusion facts; every exclusion is its own
  fact, and no fact stated for one figure decides another.
- The backlog reads Owned copies held now on full editions.
- An immediate act is one click with a sequence-keyed Undo, never a page;
  a detailed one is a page with no Undo.
- Copy and purchase days are endpoints at any precision; the opening ones
  have no void.
- Only a `game` refund ends the copy, and ownership of that end is by
  adjacency under one idempotency key per dispatch.
- Removing a copy cascades over its purchases; a purchase removed on its
  own stays removed when the copy is restored.
- A demo, a beta or a test is an Edition of kind `prerelease`, one word
  for all, no run kind.
- Valuations store their inputs; the task's trigger is a version bump or a
  stale row; a purchase without a rate is skipped, never a failed run.
- A conversion builds through the commands' own `build` under idempotent
  keys, so every command rule applies and a rerun appends nothing.
- The catalog follows IGDB, not our own prose.
- A workflow or Makefile change is a code change for the gate: the suite
  outgrew a hosted runner during this wave, so CI runs the static half
  alone and the local full `make check` is the only gate.
