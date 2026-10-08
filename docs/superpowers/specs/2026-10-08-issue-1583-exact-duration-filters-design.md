# Duration filters compare the stored duration exactly

Issue: KucharczykL/timetracker#1583. Decides #1581 and #1582 (both closed).
Replaces the
contract of `2026-10-08-issue-1045-duration-zero-design.md`, which this change
deletes.

## Contract

A duration filter compares the stored duration exactly, independent of the
display profile. The value is a decimal number of hours. `1.5` is 90
minutes. Every modifier compares the same number, with no rounding and no
bucket:

- `is 0` selects exactly zero, or no play. A running session counts as 0 h,
  because its `effective_duration` is 0 until it ends.
- `is 1` selects exactly one hour. A 59 m 58 s session does not match. The
  `whole_hours` profile prints a 45-minute session as "1 hour"; `is 1` does
  not match it.
- `≤ 1` selects one hour and less. `is 1` and `≤ 1` agree at the boundary.
- `is not`, `<`, `>`, `≥`, `between`, `not between` follow the same number.

No play reads as 0 h on every duration field. A game with no sessions has a
session playtime of 0 h and a session average of 0 h for filtering. So
`< 1` includes it, `is 0` includes it, `is not 0` excludes it. On the
field's own model, every `x` and its `is not x` split a scope into two
complete sets. Through a relation sub-filter (for example
`session_filter.duration_hours` under ANY) a game with no related rows
matches neither, as for every field.

Duration fields offer no presence pair. "none" is `is 0`; "any" is `> 0`.

A value outside what a `timedelta` holds is refused as `FilterError`. A
non-finite number is refused on every float field.

## Fields

| field | filter | source |
|---|---|---|
| `playtime_hours` | `GameFilter` | `playtime` alias, coalesced per half |
| `duration_hours` | `PlayerSessionFilter` | `effective_duration`, generated `Coalesce(..., 0)` |
| `duration_hours` | `HistoricalPlaytimeFilter` | `duration`, NOT NULL |
| `session_average` | `GameFilter` | `avg` aggregate, NULL over no rows |
| `session_playtime_hours` | `GameFilter` | `sum` aggregate, NULL over no rows |

The three handler fields read columns that are never NULL. The two
aggregates are the only NULL sources.

## Decisions

- **Coalesce at the aggregate.** `aggregate_to_q` wraps an aggregate whose
  spec states `unit == DURATION_HOURS` in `Coalesce(..., timedelta(0))`. The
  comparison then sees no NULL. The wrap sits after both branches, the
  join and the correlated `Subquery`, and spells it as `zero_when_null` in
  `games/reads/sums.py` does. A non-duration sum keeps NULL:
  `purchase_price_total` over no purchases is not 0 (free). No sort reads
  these aggregates.
- **Presence arms deleted.** `duration_hours_to_q` loses its `IS_NULL` and
  `NOT_NULL` arms and falls through to `FilterError`. Parse checks no
  modifier vocabulary; the refusal comes from the eager `to_q` in
  `filter_from_json`, which reaches handler fields and aggregates alike.
- **One criterion type.** The three handler fields change from
  `IntCriterion` to `FloatCriterion`. The aggregates already take a fraction
  through `_coerce_number`. `FloatCriterion` takes `_coerce_number` too, so
  after parse an integral value serializes as `1`, not `1.0`. The coercer
  also refuses a non-finite value. `amount` and `valuation` on
  `PurchaseFilter` share the change; their queries are unaffected. The
  widget prefills from the raw blob, so `"value": 1.0` prefills `1.0`.
- **Nullable from the unit.** `playtime_hours` and session `duration_hours`
  drop `nullable=True` (`HistoricalPlaytimeFilter.duration_hours` states
  none already). `field_metadata` states an aggregate nullable when
  `reducer in (sum, avg) and spec.unit is None`.
- **Labels.** `NumberFilter` uses `NUMBER_MODIFIER_LABELS` for every field.
  `DURATION_MODIFIER_LABELS` goes. When a caller passes no `modifiers`, a
  duration `unit` drops `IS_NULL` and `NOT_NULL` from the fallback list.
- **Input step.** Inside `NumberFilter`, a duration `unit` overrides the
  caller's `step` with `"any"`, so the browser accepts a decimal. The quick
  bar (`QuickFacet.step` defaults to `"1"`) and the builder templates both
  go through `NumberFilter`.
- **No hint.** `duration_bucket_hint`, `_hour_text`, `MAX_DURATION_HOURS` in
  `common/components/filters.py` go. `ts/elements/duration-bucket.ts` and its
  test go. In `ts/elements/filter-widgets.ts`, `refreshDurationBucketHint`,
  the `input` listener in `setupModifierToggles` that only refreshes it, and
  both calls in `writeNumberWidget` go. The summary drops `durationClause` and
  `DURATION_MODIFIER_PHRASES`; a duration leaf reads like any number leaf.
- **Unit stays.** `FilterField.unit`, `FieldMeta.unit` and the handler mark
  stay. The unit chooses the step and states the hours compile.
  `field_comparisons` never reads `duration_hours_to_q`; it compares two
  columns raw and is untouched.
- **Range refusal.** `duration_hours_to_q` converts each bound through one
  helper that raises `FilterError` on `OverflowError`. Today `1e20` raises
  `OverflowError`, which eager validation does not catch. The helper catches
  `(OverflowError, ValueError)`: NaN raises `ValueError`, and an
  `AggregateCriterion` built in Python skips the coercer.
- **Stored presets.** None exist in the one deployment. No migration. A
  bookmarked `?filter=` holding a duration presence modifier is a
  `FilterError`: a list renders unfiltered with a warning
  (`games/views/filtering.py`), the API answers 4xx.

## Callers

- `review_filter()` (`games/views/session_reclassification.py`) states
  `duration_hours ≥ REVIEW_THRESHOLD_HOURS` as `IntCriterion`; it becomes
  `FloatCriterion`. `reviewable_sessions()` compares `effective_duration__gte`
  raw, so link and count keep one predicate.
- Docstrings: `duration_hours_to_q` (bucket, presence) and
  `duration_hours_handler` ("IntCriterion") are rewritten.
- Tests pinning #1045 behaviour, rewritten to the new contract:
  - `tests/test_filters.py`: `test_duration_hours_equals_bucket`,
    `test_duration_presence_is_zero_or_absent`,
    `test_playtime_hours_is_null_matches_an_unplayed_game`,
    `test_every_duration_field_offers_the_pair_unless_exempt`, the
    `TestDurationPresence` class (keep its `running_only` game in the zero
    set), every `IntCriterion` on a duration field.
  - `tests/test_quick_filter_bar.py`:
    `test_an_averaged_facet_in_a_presence_mode_is_editable`,
    `test_a_duration_facet_offers_none_as_a_mode`.
  - `tests/test_field_widget.py`: `TestFieldWidgetDurationUnit`.
  - `tests/test_historical_playtime_filter.py`: `IntCriterion` on
    `duration_hours` (a mypy error once typed `FloatCriterion`).
  - `tests/test_filter_where.py`: `test_isnull_suffix_ignores_value` keeps its
    purpose on a nullable field (`year_released`).
  - `e2e/test_quick_filter_e2e.py`: `test_playtime_none_finds_the_unplayed_game`
    becomes `is 0`; `test_duration_hint_follows_typing` goes.
  - TypeScript: the hint suite in `filter-widgets.test.ts`, the duration
    phrases in `filter-tree/summary.test.ts`, `duration-bucket.test.ts`.
  - `ts/elements/filter-tree/fixtures.json`: case "game: playtime none"
    becomes `EQUALS 0`; after the change `IS_NULL` fails to parse.
- Docs: CLAUDE.md's filter section, both the aggregate-nullability sentence
  and the #1045 paragraph. `docs/configuration.md` names a stale
  `duration_total_hours` facet.

## Follow-up issues to file

None.
