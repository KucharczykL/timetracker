# Every purchase read on the projections (P5a)

Issues: [#734](https://github.com/KucharczykL/timetracker/issues/734),
[#735](https://github.com/KucharczykL/timetracker/issues/735), the read
half of [#1266](https://github.com/KucharczykL/timetracker/issues/1266).
Member P5a of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md),
on top of P4 ([Convert every legacy purchase](2026-10-01-issue-723-purchase-conversion-design.md)).

P5 is cut in three. P5a moves every read; P5b (#724, the rest of #1266)
moves every write and adds Game detail's purchases and the review
surface; P5c (#736) drops `LegacyPurchase` and regenerates the sample.
Reads go first because the statistics link into the Purchases list, so
the list, its filter and the statistics move together. Between P5a and
P5b the legacy Add purchase form writes rows no read shows, and the dev
sample, which holds legacy rows and no purchase events, shows no
purchase; the stack merges whole, so `main` holds neither state.

## Purchase filter

`PurchaseFilter` (`games/filters.py`) filters the `Purchase` projection;
model key `purchase`, found by `filter_for_model` by name.

| Field | Reads |
|---|---|
| `kind` | `kind` |
| `name`, `note` | text columns |
| `amount`, `currency` | the stated price; a null amount is unknown |
| `price_state` | `paid` (above 0), `free` (0), `unknown` (null), own handler |
| `valuation` | the current valuation's amount; null without one |
| `purchased` | the opening endpoint's interval |
| `refunded`, `is_refunded` | the refund's interval and act (`endpoint_filter_fields`) |
| `access`, `format` | `entry__access`, `entry__format` |
| `platform` | `entry__release__platform` |
| `game` | `entry__player_game__game` |
| `created_at` | `calendar_day_handler` |
| `search` | name, the game's name, the platform's name |
| `entry_filter`, `game_filter` | through `entry` and `entry__player_game__game` |

**The valuation alias.** `PurchaseQuerySet.annotated_for_filtering(library=None)`
registers `valuation_amount` and `rate_year`, as `Playthrough` registers
its condition aliases: with a library, the subquery `with_valuation`
states; without one, an alias that resolves and refuses to compile
(`UnscopedValuationAlias`). So validation (`FilterQueryContext.for_validation`)
accepts a filter naming `valuation`, and only an unscoped execution
raises. `with_valuation(purchases, library)` becomes that call.

**Wiring.** `filter_query_context_for_library` gains a `Purchase` scope,
`library_purchases(library).annotated_for_filtering(library)`;
`filter_queryset_for_library` returns the same for `Purchase`;
`_FILTER_LIST_URL` maps `PurchaseFilter` to `list_purchases`;
`FILTER_MODE_MODELS["purchases"]` (`common/components/custom_elements.py`)
and `MODE_PARSERS["purchases"]` name it. The builder route refuses
`legacypurchase`. The legacy model's reverse accessors go
(`related_name="+"` on `games`, `related_game` and `platform`, no
database change), so the comparison operand sources and every reverse
walk lose them; each legacy reader left walks forward. The class itself
stays until P5c.

**Relations moved.**

- `GameFilter.purchase_filter` and `purchase_count` go through
  `player_games__entries__purchases`.
- `GameFilter.purchase_price_total` sums valuations. A valuation is an
  alias on the scoped purchase, which no join path reaches, so
  `AggregateSpec` gains `correlated`, the path from the related row back
  to the parent, beside the forward `accessor` the drift guard walks.
  With it, `aggregate_to_q` compiles the reducer as a correlated subquery
  over the context's scoped queryset, narrowed by `base_scope` and the
  criterion's scope, grouped on that path, `output_field` the source's.
  `__post_init__` refuses `correlated` on a count. PostgreSQL sums a
  correlated scalar subquery (checked: grouped `sum((select v from t2
  where t2.id = t1.id))` answers per group), and Django renders the
  shape (`SUM((SELECT ...))`).
- `PlatformFilter.purchase_filter` relates forward:
  `related_lookup="entry__release__platform__id"`.
- `LibraryEntryFilter` gains `purchase_filter` and `edition_kind`
  (`release__edition__kind`), which the backlog links state.

Quick facets (`purchases`): kind, price state, amount, purchased,
`is_refunded` ("Refunded"), access, platform, created, name.

## Saved presets

One migration rewrites every preset once. It walks every filter at any
depth and rewrites the value under each `purchase_filter` key, the
`scope` of a `purchase_count` or `purchase_price_total` criterion, and
a `purchases` preset's root and sort. The key `purchase_filter` names a
purchase relation on every filter, so the walk needs no mode.

| Old | New |
|---|---|
| `type` INCLUDES | an `OR` member per word: `game` → kind `game` and `game_filter.kind` not `dlc`; `dlc` → kind `game` and `game_filter.kind` `dlc`; a pass → its kind |
| `ownership_type` INCLUDES | an `OR` member per word: an `entry_filter` with the conversion table's access and format; `re` names `rented` and `subscription`; `du` adds kind `upgrade`, and `di` kind not `upgrade` |
| `infinite` | `game_filter.excluded_from_unfinished` |
| `converted_price`, `price`, `price_currency` | `valuation`, `amount`, `currency` |
| `date_purchased`, `date_refunded`, `is_refunded` | `purchased`, `refunded`, `is_refunded` |
| `games` INCLUDES | `game` |
| `platform`, `name`, `created_at`, `search` | unchanged |

Unexpressible, and listed with their reason while the preset stays
unchanged (so it loads refused, as an unknown key does today): another
modifier on `type`, `ownership_type` or `games`; `num_purchases`,
`needs_price_update`, `converted_currency`, `updated_at`,
`platform_filter`; a stored `None` date; a `field_comparisons` operand
through `purchases` or `addon_purchases`. Sort `type` → `kind`, `price`
→ `amount`; `infinite` leaves the sort. Backward is a no-op. The
deployment holds no purchase preset.

## Readers moved

- **Purchases list**: rows are `library_purchases(library).annotated_for_filtering(library)`.
  Columns: Name (the game, or `product · game`), Kind, Amount (`Free`,
  `Unknown`, else the amount, the valuation beside a foreign one),
  Purchased, Refunded, Finished, Created. No Actions column and no row
  menu; P5b adds both. A stored column choice naming a gone key reads as
  the default. Sorts: `name` (game display order, then product name),
  `kind`, `amount` (the valuation, then the amount, nulls last),
  `purchased` and `refunded` (lower bound, then upper), `finished`,
  `created`. A run path runs from the run to the row:
  `PURCHASE_RUNS = "player_game__entries__purchases"`, and
  `ENTRY_RUNS = "player_game__entries"` for the copy figures;
  `completion_exists` and `completion_day` take the path, as
  `ranked_completions` does.
- **Library page summary**: count, refunded count and total spent read
  the statistics' own readers, all-time.
- **Navbar** `purchase_available`, the platform API's
  `last_purchase_use`, and the Purchases count in the game and platform
  removal previews read `library_purchases` (a platform's through the
  copy's Release).
- **Game detail** loses its legacy Purchases section (and its link to
  the legacy list); P5b puts each copy's purchases under its row. The
  Library page's Total spent links to `PurchaseFilter`.
- `view_purchase` and the legacy write routes stay on the legacy rows
  until P5b and P5c replace them; no list links to them.
- `verify_purchase_conversion`'s backlog line reads `legacy_figures`
  before the pass and `compute_stats` after.

## Statistics

`compute_stats` reads `library_purchases`, `library_entries` and the
current valuations; no sum reads a float. A purchased or acquired day is
in a year by containment, both bounds inside it. A completion keeps
today's overlap (`completed_in_scope`, `completed__between`).

**Purchases** (`StatsSource.PURCHASES`), any kind, by purchased day:

- `all_purchased_this_year_count`; the refunded count and percent (a
  refund act stated).
- `total_spent`: the current valuations of the unrefunded ones, in the
  published currency. `total_spent_unpriced` (new key): the unrefunded
  ones without a current valuation, unknown amount or no rate alike.
  `spent_per_game`: the total over the valued ones.

**Copies** (`StatsSource.ENTRIES`, new): live entries on a `full`
Edition. Held is `access_end_recorded_at` null.

- Unfinished: Owned, held, acquired in scope; the game at no done
  status, no completion in scope, not Abandoned, not
  `excluded_from_unfinished`. Percent over Owned held copies acquired in
  scope.
- Dropped: Owned, acquired in scope; the game at no done status, no
  completion in scope; Abandoned, or the copy ended with way `refunded`;
  not `excluded_from_dropped`. Percent over Owned copies acquired in
  scope.
- Backlog decrease: Owned copies whose game is finished; for a year,
  acquired before it, the game at a done status with a completion in
  it; all-time, the game at a done status or with any completion.
- Finished: for a year, a completion in it; all-time, a done status or
  any completion. Finished-released adds the game's `year_released`.
  Bought-and-finished: acquired in scope, not ended by refund, a
  completion in scope. `total_year_games`: copies whose game was played
  in scope, released that year for a year. All any access, as legacy
  counted a rental's finish.

A pass or an upgrade rides its base copy and so holds no backlog place,
unless it had none and the pass recorded its own (`own_copy_fallback`).
A DLC copy counts through its own Game, which holds its own status: a
converted DLC game starts with default facts and counts as unfinished
until the person states otherwise.

`total_year_games` and `this_year_finished_this_year_count` move from
`BOTH` and `PURCHASES` to `ENTRIES`; `PLAYED_KEYS` in `tests/test_stats.py`
follows. `total_spent_unpriced` and `total_spent_unvalued` join
`PURCHASES` and get a rule in both parity shapes.

**#1157's readers** (`games/reads/library_figures.py`): copies by access
and by format, count and share, and spend by access, per scope. No
screen reads them.

**The page.** A Purchases card: Total, Refunded, Spendings, "N with no
known price" linking to unrefunded purchases at price state unknown,
and, only where it is not 0, "N not valued yet" linking to unrefunded
ones with an amount and no valuation. A
Backlog card: Unfinished, Dropped, Backlog decrease, each linking to the
Library tab. The "Unfinished" table lists copies with a Paid column (the
copy's unrefunded purchases' valuations, `-` for none); the finished
tables list copies by their game.

## Links

Each `stats_links.py` builder states its figure's predicate: purchases
over `PurchaseFilter`, copies over `LibraryEntryFilter`, each copy
builder stating `edition_kind` `full` itself, since the Library tab's
base holds every Edition. The parity test
runs each through the destination list's base and compares the count
with the figure, every builder and scope.

## Parity gate

`make verify-purchase-statistics ARGS="--user NAME --snapshot PATH"` is
read-only. It computes `StatsData` for each snapshot scope, judges every
key by `games/stats_parity.py`'s second shape, and exits non-zero on an
unattributed difference.

**Snapshot format 2.** Beside each value, a scope holds `rows`: the
legacy keys behind each purchase and copy figure and behind each
denominator (unrefunded, all in scope, valued). `verify_purchase_conversion
--snapshot` writes it; the gate refuses format 1. The legacy figures move
from `compute_stats` into `purchase_reconciliation.legacy_figures(model,
library, year)`, which takes the legacy model, so P5c can pass the
historical one at `0031`'s state: it states the alive rule itself,
filters through `games__id__in=` key subqueries, never a live model's
queryset, and reaches runs through `games__player_games__playthroughs`.
A test runs it against the migration state's model.

**Mapping.** A converted row maps to `source_metadata.legacy_purchases[0]`
of its creation event; each conversion event names one legacy row. Each
legacy key that leaves or joins a figure carries a reason, read from
what the pass wrote and from the row's state now:

| Reason | Read from |
|---|---|
| a non-owned row at 0 is a copy and no purchase | an entry for the key, no purchase |
| a bundle became one row per game | several rows for the key |
| not Owned | the copy's access |
| a prerelease copy | the copy's Edition kind |
| an add-on counts through its own game | `review` holds `addon_game` |
| an exclusion moved | `review` holds `mixed_infinite` |
| a pass or upgrade rides the base copy | the purchase's kind |
| a pass or upgrade recorded its own copy | `review` holds `own_copy_fallback` |
| a price nobody knows | the amount is null |
| no valuation | an amount and no current valuation |
| recorded since the conversion | no conversion metadata |

Each key admits the reasons its figure can produce. `total_spent` equals
the legacy sum over the keys valued on both sides, to the cent, while
the valuations are the seeded ones; a key on one side only is a listed
reason. Ratios (`spent_per_game`, the percents) are judged by
recomputing them from the judged numerator and denominator row sets. A
key absent from the snapshot (`total_spent_unpriced`,
`total_spent_unvalued`) is new and judged by its own reader alone.

## Verification

- Focused tests per filter field, preset case, statistic and link; the
  link parity test over every builder and scope; `legacy_figures`
  against the historical model.
- Pinned lists that move: purchase facets
  (`tests/test_quick_filter_bar.py`), builder model keys
  (`tests/test_filter_builder_page.py`, `test_filter_widgets.py`,
  `test_html_validity.py`), the filter-tree contract
  (`ts/elements/filter-tree/fixtures.json`), `PLAYED_KEYS`,
  `test_stats_parity.py`'s rule set, `PURCHASE_SORTS`, `ALL_FILTERS`
  (`tests/test_filters.py`), `FILTER_FOR_MODEL` and the three
  `legacypurchase` contract cases, `_NESTED_BUILDERS`
  (`tests/test_stats_links.py`), `tests/test_game_detail_links.py`.
  Read-side tests that seed `LegacyPurchase` rows for a list, link or
  figure seed through `RecordPurchase` and `record_entry` instead; so do
  the e2e list-chrome tests (`test_responsive_table_e2e.py`,
  `test_pinned_column_e2e.py`, `test_table_width_e2e.py`,
  `test_truncated_text_e2e.py`, `test_filter_builder_e2e.py`). The e2e
  row actions on the Purchases list (`e2e/test_purchase_e2e.py`) leave
  with the Actions column; Split leaves for good with the bundle, Refund
  returns in P5b.
- `make bench` gains a purchases workload: the list page, the
  statistics, and `purchase_price_total`, inside the 20 ms budget.
- On the 2026-10-01 dump: snapshot at `0030`, migrate, gate; the output
  goes into the PR. `make render-pages` before and after, every
  differing file attributed. Full `make check`.

## Follow-up issues to file

None yet.
