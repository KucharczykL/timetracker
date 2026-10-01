# Every purchase read on the projections (P5a) Implementation Plan

> Inline execution in this session; TDD per behaviour.

**Goal:** Switch every purchase read (filter, presets, Purchases list,
statistics, links, small readers) to the `Purchase`/`LibraryEntry`
projections and valuations, with a row-level parity gate against the
legacy snapshot.

**Architecture:** A new `PurchaseFilter` over the projection carries a
valuation alias registered like the run condition aliases. Statistics
split into purchase figures (purchases + valuations) and copy figures
(entries on full Editions). The legacy figures move into
`purchase_reconciliation.legacy_figures`, model-parametrised, which
feeds a format-2 snapshot that a new read-only command judges against.

**Spec:** `docs/superpowers/specs/2026-10-01-issue-735-purchase-reads-design.md`

## Global constraints

- Every pytest run: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS=…`.
- Before each commit: `make format`, `make lint-fix`, `make format-check`, `make vale`, separate call, by exit code.
- No column on any table the P4 pass touches; `related_name` changes are state-only.
- Days: `calendar_today(library)` only; tests seed via `tests/calendar_days.py`.
- Seed new-shape rows with `tests/purchases.py:record_purchase` and `tests/entries.py:record_entry`/`end_entry_access`; tests that read the conversion's metadata need `untracked_games`.
- Comments ≤ 7 words; no issue numbers in comments.
- Commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: The valuation alias and the Purchase filter scope

**Files:** `games/models.py` (`PurchaseQuerySet`), `games/reads/purchases.py`,
`games/filters.py` (context + base), tests `tests/test_purchase_valuation.py`,
new `tests/test_purchase_filter.py`.

**Produces:** `PurchaseQuerySet.annotated_for_filtering(library: UserLibrary | None = None) -> PurchaseQuerySet`
registering `rate_year` and `valuation_amount` (and `valuation_currency`);
`UnscopedValuationAlias` (raised at compile without a library);
`with_valuation(purchases, library)` delegates to it;
`filter_query_context_for_library(library).queryset_for(Purchase)` and
`filter_queryset_for_library("purchase", library)` both return
`library_purchases(library).annotated_for_filtering(library)`.

Tests:
- annotating twice with the same library is a no-op; with another library raises.
- `Purchase.objects.none().annotated_for_filtering()` filters on `valuation_amount__gt=1` without error; executing an unscoped one raises `UnscopedValuationAlias`.
- existing `with_valuation` tests still pass (null without current valuation, published target currency).

Gotchas: mirror `PlaythroughQuerySet.annotated_for_filtering`/`_clone`
(`games/models.py:1699`); `with_filter_aliases` calls it without
arguments; `rate_year` must be annotated before `valuation_amount`
(OuterRef reads it).

### Task 2: `PurchaseFilter`

**Files:** `games/filters.py`, `common/components/custom_elements.py`
(`FILTER_MODE_MODELS`), `common/components/quick_filter.py`
(`QUICK_FACETS["purchases"]`), tests `tests/test_purchase_filter.py`,
`tests/test_quick_filter_bar.py`, `tests/test_filter_builder_page.py`,
`tests/test_filter_widgets.py`, `tests/test_html_validity.py`,
`tests/test_filters.py` (`ALL_FILTERS`), `tests/test_filter_presets.py`.

**Produces:** `PurchaseFilter` with the spec's fields, `parse_purchase_filter`
returning it, `MODE_PARSERS["purchases"]`, `_FILTER_LIST_URL[PurchaseFilter]`,
`PRICE_STATES` words `paid`/`free`/`unknown` and `price_state_handler`.
`LegacyPurchaseFilter` loses its `_FILTER_LIST_URL` entry and `parse_*`;
the builder route answers 404 for `legacypurchase` (`filter_for_model`
refuses it by an explicit retired set).

Tests, one per field: kind; name/note; amount incl. null; currency;
price_state each word (and a 0 amount not `unknown`); valuation
(current only, stale is null); purchased `within` a year; refunded
interval and `is_refunded`; access/format/platform through entry; game;
created_at by calendar day; search over name, game name, platform name;
entry_filter; game_filter; two-library isolation (a filter never returns
another library's purchase); `from_json` refuses a legacy key
(`ownership_type`) with `FilterError`.

Gotchas: `endpoint_filter_fields(PURCHASE_DAY, ...)` gives `interval`;
do not expose its `stated` (always true). `PURCHASE_REFUND` gives both.
Facet `is_refunded` labelled "Refunded".

### Task 3: Relations and aggregates on the other filters

**Files:** `common/criteria.py` (`AggregateSpec.correlated`,
`aggregate_to_q`), `games/filters.py` (`GameFilter.purchase_filter`,
`aggregates`, `PlatformFilter.purchase_filter`, `LibraryEntryFilter`
`purchase_filter` + `edition_kind`), `games/models.py` (legacy
`related_name="+"`), a state-only migration `0032_legacy_purchase_reverse`,
tests `tests/test_filters.py`, `tests/test_filter_cross_entity.py`,
`tests/test_relation_algebra.py`, `tests/test_aggregate_base_scope.py`,
`tests/test_playergame_nested_filter_scope.py`.

**Produces:** `AggregateSpec(..., correlated: RelationPath | None = None)`;
`GameFilter.aggregates["purchase_count"] = AggregateSpec("count", "player_games__entries__purchases", PurchaseFilter)`;
`["purchase_price_total"] = AggregateSpec("sum", "player_games__entries__purchases", PurchaseFilter, source="valuation_amount", correlated="entry__player_game__game")`.

Tests: purchase_count counts a game's purchases across two copies; a
removed purchase or copy does not count; price_total sums valuations
only (an unvalued purchase adds nothing) and honours a scope
(`kind=game`); `__post_init__` refuses `correlated` on count; the drift
guard `test_aggregate_accessor_reaches_the_scope_filter_model` passes;
PlatformFilter.purchase_filter matches through the copy's Release
platform; LibraryEntryFilter.purchase_filter and edition_kind; Game's
comparison operand sources no longer list `purchases`/`addon_purchases`.

Gotchas: grep every legacy reverse walk (`game.purchases`,
`addon_purchases`, `legacypurchase_set`, `games__purchases`, `PURCHASE_RUNS`
consumers) and turn each surviving legacy reader forward before the
`related_name` change; the migration must order after `0031` and touch
no column (schema guard). `RelationMatch.NONE` semantics stay.

### Task 4: Saved preset rewrite migration

**Files:** `games/migrations/0033_purchase_presets.py`, test
`tests/test_purchase_preset_rewrite.py` (calls the module's pure
functions, plus one migration-executor case).

**Produces:** pure `rewrite_purchase_node(node) -> Rewritten(node, unexpressible: list[str])`,
`rewrite_filter_tree(node)` walking every dict, `rewrite_sort(find_filter)`.

Tests, one per table row: type game/dlc/pass (OR members); ownership
di/ph/du/re/bo/tr/de/pi; infinite; prices; dates; is_refunded; games
INCLUDES; unchanged keys; each unexpressible case leaves the preset
unchanged and reports it; nested: a games preset's `purchase_filter`,
a sessions preset's `game_filter.purchase_filter`, an aggregate
`purchase_count.scope`, `OR` members; sort tokens keep their sign; the
rewritten JSON parses with `parse_purchase_filter`/`parse_game_filter`;
backward is a no-op; a second run changes nothing.

Gotchas: the migration cannot import `games.filters` (historical
state); keep the rewrite pure-dict. Prints `presets rewritten: n/m`
and each unexpressible key, as `0047` did.

### Task 5: Run paths take the row

**Files:** `games/reads/playthrough_completions.py`, callers in
`games/views/stats_data.py`, `games/models.py`
(`LegacyPurchaseQueryset.finished`), tests `tests/test_playthrough_completions_read.py`,
`tests/test_playthrough_completion_reads.py`.

**Produces:** `PURCHASE_RUNS = "player_game__entries__purchases"`,
`ENTRY_RUNS = "player_game__entries"`, `LEGACY_PURCHASE_RUNS` kept in
`games/backfill/purchase_reconciliation.py` for the legacy figures;
`completion_exists(library, year, path)`, `completion_day(library, year, path)`.

Tests: a purchase and a copy each report the completion of their game's
run; removed run excluded; year overlap kept.

### Task 6: The Purchases list on the projection

**Files:** `games/views/purchase.py` (list half only), `games/sorting.py`
(`PURCHASE_SORTS`), `common/components/domain.py` (new `PurchaseName`,
`PurchaseAmount`), tests `tests/test_purchase_finished_column.py`,
`tests/test_purchase_list_fanout.py`, `tests/test_sorting.py`,
`tests/test_finished_sorts.py`, `tests/test_rendered_pages.py`,
`tests/test_paths_return_200.py`, `tests/test_column_priority_contract.py`,
`tests/test_table_width_policy.py`, `tests/test_sort_header_parity.py`;
e2e `test_purchase_e2e.py` (drop row-action cases),
`test_responsive_table_e2e.py`, `test_pinned_column_e2e.py`,
`test_table_width_e2e.py`, `test_truncated_text_e2e.py`,
`test_filter_builder_e2e.py` (seed new rows).

**Produces:** `PURCHASE_COLUMNS` keys `name, kind, amount, purchased,
refunded, finished, created`; `PurchaseName(purchase)` (game link, or
`product · game`); `PurchaseAmount(purchase)` (`Free`, `Unknown`, amount
+ currency, valuation beside when currencies differ).

Tests: one row per purchase (a game with two copies lists both);
Name/Kind/Amount words; Finished column; every sort, nulls last for
amount; a stored column choice naming `price` is ignored; filter in the
URL narrows; a legacy filter key answers the refusal message; no
Actions column; render under `make render-pages`.

### Task 7: The other small readers

**Files:** `games/views/library.py`, `games/views/general.py`
(`purchase_available`), `games/api.py` (`last_purchase_use`),
`games/reads/platform_departures.py`, `games/reads/game_departures.py`,
`games/views/game.py` (drop `_purchases_section` and its call),
tests `tests/test_library_page_isolation.py`, `tests/test_game_detail_links.py`,
`tests/test_bulk_game_removal.py`, `tests/test_bulk_platform_removal.py`,
`tests/test_api.py`, `tests/test_view_authentication.py`.

Tests: Library page count/refunded/spent equal the stats all-time
figures and link to `PurchaseFilter`; navbar flag true with one
purchase; platform `last_purchase_use` through the copy's Release;
previews count purchases of the game / on the platform; Game detail
renders no Purchases section and no legacy link.

### Task 8: The statistics

**Files:** `games/views/stats_data.py`, new `games/reads/purchase_figures.py`
(purchase scope helpers) and `games/reads/copy_figures.py` (copy
scopes), new `games/reads/library_figures.py` (#1157 readers),
`games/views/stats_content.py`, tests `tests/test_stats.py`,
`tests/test_stats_finish_reads.py`, `tests/test_stats_reads_the_projection.py`,
`tests/test_stats_content_links.py`, `tests/test_user_preference_consumers.py`,
new `tests/test_purchase_figures.py`, `tests/test_copy_figures.py`,
`tests/test_library_figures.py`.

**Produces:** `StatsData` gains `total_spent_unpriced: int`,
`total_spent_unvalued: int`; list keys hold querysets of `Purchase`
(purchase lists) or `LibraryEntry` (copy lists, annotated `date_finished`,
`paid` for the Unfinished table). `StatsSource.ENTRIES`;
`STATS_SOURCE_GROUPS` regrouped per spec. Helpers:
`purchases_in_scope(library, year)`, `owned_copies(library, year)`,
`held(entries)`, `copies_on_full_editions(library)`.

Tests per figure, each with a year and all-time case: counts by
containment (a day spanning two years counts in neither year, only
all-time); refunded; total spent sums current valuations of unrefunded
only; unpriced and unvalued counts; spent per game over valued; backlog
unfinished (Owned, held, full; a rented copy, a sold copy, a demo-edition
copy, an excluded game, an Abandoned game, a finished game each left
out); dropped (Abandoned, refund-ended; excluded_from_dropped);
backlog decrease per scope; finished lists any access; finished-released
by `year_released`; bought-and-finished excludes refund-ended;
total_year_games; a pass purchase holds no backlog place; the
`own_copy_fallback` copy counts; a DLC copy counts through its own game.
Page: two cards, "Unfinished" table with Paid, "N with no known price",
"N not valued yet" only when nonzero.
`library_figures`: by access, by format, count and share; spend by access.

### Task 9: Links and their parity

**Files:** `games/views/stats_links.py`, tests `tests/test_stats_links.py`,
`tests/test_stats_finished_links.py`, `tests/test_filter_url.py`.

**Produces:** builders `purchases_total`, `purchases_refunded`,
`purchases_unpriced`, `purchases_unvalued` (PurchaseFilter);
`copies_unfinished`, `copies_dropped`, `copies_backlog_decrease`,
`copies_finished`, `copies_finished_released`,
`copies_bought_and_finished` (LibraryEntryFilter, each stating
`edition_kind=full`). Old `purchases_*` names for copy figures go.

Tests: the parity test (`_count` through `filter_queryset_for_library`)
for every builder × {a year, all-time} over a seeded library holding each
edge case of Task 8; `_NESTED_BUILDERS` retyped; stats page links decode.

### Task 10: Legacy figures, snapshot format 2, and the gate

**Files:** `games/backfill/purchase_reconciliation.py` (`legacy_figures`,
`SNAPSHOT_FORMAT = 2`, `rows`), `games/management/commands/verify_purchase_conversion.py`
(`_backlog`), new `games/management/commands/verify_purchase_statistics.py`,
`games/stats_parity.py` (purchase shape), `Makefile`
(`verify-purchase-statistics`), CLAUDE.md command row, tests
`tests/test_verify_purchase_conversion.py`, `tests/test_stats_parity.py`,
new `tests/test_purchase_stats_parity.py`, new
`tests/test_verify_purchase_statistics.py`.

**Produces:** `legacy_figures(model, library, year) -> LegacyFigures(values: dict[StatsKey, object], rows: dict[RowsKey, frozenset[LegacyId]])`;
`legacy_statistics` writes format 2 (purchase keys from `legacy_figures`,
the rest from `compute_stats`); `ConversionMap` (legacy key → new rows,
read from creation events' `source_metadata.legacy_purchases[0]`);
`Reason` enum (the spec's eleven); `judge_purchase_scope(before, after,
rows, mapping) -> tuple[FigureChange, ...]`.

Tests: `legacy_figures` equals the old `compute_stats` purchase keys on a
seeded legacy library (live model) and runs on the model from
`MigrationExecutor(...).loader.project_state(("games", "0031_purchase_conversion")).apps`;
format 1 refused; each reason attributes its case (one test per reason,
built by running the pass on a small legacy library); an unexplained
row fails; `total_spent` equal to the cent passes and one cent off
fails; percents recomputed; new keys judged alone; the command exits
non-zero on any unattributed change and prints each.

Gotchas: `legacy_figures` must not pass a live-model queryset into a
historical lookup (`games__id__in=` over `values("pk")`); reach runs
via `games__player_games__playthroughs`; keep it working after the Task 3
`related_name` change.

### Task 11: Bench, rehearsal, render-pages, docs

**Files:** `games/management/commands/benchmark_events.py` (purchases
workload: list page query, stats purchase/copy figures,
`purchase_price_total`), CLAUDE.md (filter, stats, command rows), the
spec.

Steps: `make bench` within 20 ms; restore the 2026-10-01 dump, migrate
to `0030`, write the format-2 snapshot, migrate, run the gate, paste
output; `make render-pages` on that database at P4's head and here,
attribute every diff; drop the scratch DB (`unset DATABASE_URL`).

## Self-review

Spec sections → tasks: filter (1, 2), relations (3), presets (4), list
(5, 6), readers moved (7), statistics + page (8), links (9), gate (10),
verification (11). Type names consistent: `annotated_for_filtering`,
`UnscopedValuationAlias`, `ENTRY_RUNS`, `legacy_figures`.
