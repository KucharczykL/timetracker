# Plan: exact duration filters (#1583)

Spec: `docs/superpowers/specs/2026-10-08-issue-1583-exact-duration-filters-design.md`.
Implementation inline, TDD per task. Iterate with focused `make test ARGS=…`
under the shared lock; `make test-ts` for vitest; `make ts-check` (not bare
tsc: the worktree's `ts/generated/` is stale).

## Task 1 — compile: exact, no presence, coalesced aggregates

Files: `common/criteria.py`.

- `duration_hours_to_q`: EQUALS → `field = d`; NOT_EQUALS → `~Q(field = d)`;
  delete IS_NULL/NOT_NULL arms; ordering and BETWEEN arms unchanged. One
  helper `_hours(value) -> timedelta` raising `FilterError` on
  `(OverflowError, ValueError)`. Rewrite docstring.
- `duration_hours_handler` docstring: FloatCriterion.
- `aggregate_to_q`: after the reducer branches, when `spec.unit ==
  DURATION_HOURS`, wrap in `Coalesce(expr, Value(timedelta(0)),
  output_field=DurationField())`.
- `field_metadata` aggregate nullability: `reducer in (sum, avg) and
  spec.unit is None`.
- `FloatCriterion._coerce` → a coercer that refuses non-finite and keeps
  integral values int (extend `_coerce_number`, or a finite check inside
  `_coerce_float` that `_coerce_number` inherits — the latter also covers
  `AggregateCriterion`).

Tests (`tests/test_filters.py`), replace the #1045 ones:
- EQUALS 1 matches exactly 1 h, not 1 h 30 m nor 59 m 58 s; `≤ 1` and
  `= 1` agree at 1 h.
- EQUALS 0 on each of the five fields matches zero and no-play (games with
  no sessions; `running_only`), NOT_EQUALS 0 is the complement — rewrite
  `TestDurationPresence` as a partition test over every modifier pair.
- `< 1` on `session_average` and `session_playtime_hours` includes an
  unplayed game; `purchase_price_total` IS_NULL still matches no purchases.
- Decimal 1.5 matches a 90-minute session.
- IS_NULL/NOT_NULL on each duration field → `FilterError` at parse.
- `1e20`, `"inf"`, `"nan"` → `FilterError` (duration field and `amount`).
- `test_every_duration_field_offers_the_pair_unless_exempt` → no duration
  field offers the pair; non-duration sum still does.
- Integral float round-trips as int after parse.

## Task 2 — fields and callers

Files: `games/filters.py`, `games/views/session_reclassification.py`,
`tests/test_historical_playtime_filter.py`, `tests/test_filter_where.py`.

- Three handler fields typed `FloatCriterion | None`; drop `nullable=True`
  and its comment on `playtime_hours` and session `duration_hours`.
- `review_filter()` → `FloatCriterion`.
- `test_isnull_suffix_ignores_value` → `year_released`.
- Grep every `IntCriterion` reaching a duration field in tests; mypy finds
  the rest (`make typecheck`).

## Task 3 — widget

Files: `common/components/filters.py`, `tests/test_field_widget.py`,
`tests/test_quick_filter_bar.py`.

- Delete `DURATION_MODIFIER_LABELS`, `_hour_text`, `MAX_DURATION_HOURS`,
  `duration_bucket_hint`, the hint `<p>`. Labels always
  `NUMBER_MODIFIER_LABELS`; with `unit` set, fallback list drops the pair;
  `step = "any"` when `unit` is set.
- Tests: duration widget offers no "none", labels plain, `step="any"` for a
  handler field and an aggregate, quick-bar and builder alike; no hint
  element. Quick bar: a stored `session_average` IS_NULL is no longer
  editable; `≥ 1.5` is.
- Check other users of the deleted names (`grep -rn`).

## Task 4 — TypeScript

Files: `ts/elements/duration-bucket.ts` (+test, deleted),
`ts/elements/filter-widgets.ts` (+test), `ts/elements/filter-tree/summary.ts`
(+test), `ts/elements/filter-tree/fixtures.json`.

- Remove `refreshDurationBucketHint`, its `input` listener in
  `setupModifierToggles`, both calls in `writeNumberWidget`.
- Summary: delete `durationClause`, `DURATION_MODIFIER_PHRASES`, the import;
  test "Playtime (hrs) is 1.5".
- Fixture "game: playtime none" → `EQUALS 0` (rename description).

## Task 5 — e2e

File: `e2e/test_quick_filter_e2e.py`.

- `test_playtime_none_finds_the_unplayed_game` → pick "is", type 0, apply,
  unplayed game listed and a played one not.
- Delete `test_duration_hint_follows_typing`; add: type 1.5 on the
  Sessions Duration facet, apply, URL carries `1.5` and the 90-minute row
  shows.

## Task 6 — docs

- Delete the #1045 spec.
- CLAUDE.md filter section: aggregate-nullability sentence gains the
  duration carve-out; #1045 paragraph rewritten to the exact rule.
- `docs/configuration.md`: stale `duration_total_hours` facet name.

## Gotchas

- `~Q` on the coalesced annotation: no NULL, so no `IS NOT NULL` surprise;
  test NOT_EQUALS includes the unplayed game explicitly.
- Contract test `tests/test_filter_tree_contract.py` needs `make test-ts`
  first to regenerate `fixtures.canonical.json`.
- A list with a now-invalid `?filter=` renders unfiltered; e2e must not
  assert on an IS_NULL URL.
