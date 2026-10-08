# Duration filters: none apart from under an hour — Implementation Plan

> Inline execution: one session, task by task, with a commit per task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every duration filter can ask for "no duration" exactly. The hour
bucket that `= h` compiles to is visible in the UI, and the presence pair on
the two session aggregates includes games with no sessions.

**Architecture:** `duration_hours_to_q` stays the one compile point. Its
presence pair is redefined as zero-or-NULL against more than zero. Two
handler fields expose the pair through the existing `FilterField.nullable`.
`FieldMeta` gets an optional `unit`, which the Python number widget and the
TS summary and widget read for duration-only labels and the bucket hint.

**Tech Stack:** Django 6 / PostgreSQL 18, `common/criteria.py` filter
framework, Python components, TypeScript custom elements (vitest),
Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-08-issue-1045-duration-zero-design.md`
(read D1–D6 and U1–U3 before starting).

## Global Constraints

- Drive everything through `make`: `make test ARGS="tests/test_filters.py -k
  <name> -x"`, `make test-ts TS_ARGS="ts/elements/<file>.test.ts"`,
  `make test-e2e ARGS="-k <name>"`. Never raw `pytest`, `uv run` or `pnpm`.
- Wrap every pytest target in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make …`.
- Run `make ts` after editing any `.ts`, before an e2e run.
- Run `make gen-element-types` after changing `FieldMeta`, so that
  `ts/generated/filter-metadata.ts` picks up `unit`.
- Wire format unchanged: `EQUALS h` stays `[h, h+1)`, and NOT_EQUALS stays
  its complement. No data migration.
- Exact copy (U1–U3): `"is 0 (none)"`, `"is more than 0"`,
  `"{a} h up to {b} h"`, `"outside {a} h up to {b} h"`, `"Playtime (hrs)"`,
  `"Duration (hrs)"`, `"Session average (hrs)"`, `"Session playtime (hrs)"`.
- Full words in identifiers. Name compound types. Comments ≤7 words unless a
  reason is pleaded. Run `make vale` on the changed files.
- Gate: full `make check` (e2e included) under the lock before pushing.

## File map

| file | responsibility in this change |
|---|---|
| `common/criteria.py` | presence pair (D2); `unit` mark on handler, `FilterField.unit`, `FieldMeta.unit` (D1); delete `bool_nonzero_duration_handler` and its comments (D5) |
| `games/filters.py` | `nullable=True` on two fields (D3); "(hrs)" labels (U3) |
| `common/components/filters.py` | duration modifier labels and server-rendered bucket hint in `NumberFilter` (U1, U2); `field_widget` passes `unit` |
| `ts/elements/duration-bucket.ts` (new) | `durationBucketHint(modifier, value)`, the one TS home of the hint text |
| `ts/elements/filter-widgets.ts` | hint refresh on modifier pick, on input and on hydration |
| `ts/elements/filter-tree/summary.ts` | duration phrases for the presence pair and the bucket range |
| `ts/elements/filter-tree/fixtures.json` | contract case `playtime_hours IS_NULL` |
| tests | `tests/test_filters.py`, `tests/test_field_widget.py`, `tests/test_quick_filter_bar.py`, `ts/elements/duration-bucket.test.ts` (new), `ts/elements/filter-widgets.test.ts`, `ts/elements/filter-tree/summary.test.ts`, `e2e/test_quick_filter_e2e.py` |

## Shared names (every task uses these exactly)

- Python: `DURATION_HOURS: DurationUnit = "duration_hours"` (constant
  beside `type DurationUnit` at `common/criteria.py:1358`).
- Python: `FilterField.unit -> DurationUnit | None` (property beside
  `interval`, `common/criteria.py:1056-1059`). It reads
  `getattr(self.handler, "unit", None)`.
- Python: `FieldMeta.unit: NotRequired[DurationUnit]`.
- Python: `duration_bucket_hint(modifier: ModifierToken, value: str) -> str`
  in `common/components/filters.py`. It returns `""` when there is no hint.
- Python: `DURATION_MODIFIER_LABELS: dict[ModifierToken, str]`, which is
  `NUMBER_MODIFIER_LABELS` with `IS_NULL`/`NOT_NULL` replaced.
- Python: `NumberFilter(..., unit: DurationUnit | None = None)`.
- DOM: the hint element carries `data-duration-bucket-hint`. The widget root
  carries `data-unit="duration_hours"` when the field states a unit.
- TS: `durationBucketHint(modifier: string, value: string): string` exported
  from `ts/elements/duration-bucket.ts`.
- TS: `DURATION_MODIFIER_PHRASES: Partial<Record<ModifierToken, string>>` in
  `summary.ts`.

---

### Task 1: The presence pair means none against some (D2)

**Files:**
- Modify: `common/criteria.py:3124-3183` (`duration_hours_to_q` and its
  docstring)
- Test: `tests/test_filters.py` (`TestFilterFieldHandlers`, `:4660-4711`;
  `TestScopedAggregate…` `:5935-5962`; new class `TestDurationPresence`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `duration_hours_to_q(..., Modifier.IS_NULL, f)` returns
  `Q(f=timedelta(0)) | Q(f__isnull=True)`; `NOT_NULL` returns
  `Q(f__gt=timedelta(0))`.

- [ ] **Step 1: Write the failing compile tests.** In `TestFilterFieldHandlers`,
  add `test_duration_presence_is_zero_or_absent`: the handler for
  `effective_duration` given `IntCriterion(modifier=IS_NULL)` equals the
  zero-or-isnull Q, and given `NOT_NULL` it equals the `__gt` Q. Keep
  `test_duration_hours_equals_bucket` unchanged, as the D4 pin.
- [ ] **Step 2: Write the failing partition test.** New class
  `TestDurationPresence` (`@pytest.mark.django_db`, `untracked_games`).
  Fixture world, built with `timed_row`/`tracked_run` (`tests/session_rows.py`)
  and `record_row` (`tests/historical_playtime_rows.py`):
  *unplayed* (no row), *half_hour* (Timed 30 min), *running_only* (Timed, no
  end), *two_hours* (Timed 2 h), *hist_only* (a 20-minute record, no
  session), plus a 3-hour record on *two_hours*. Parametrise over
  `(filter class, field, queryset, expected none set)`:
  - `GameFilter.playtime_hours` → {unplayed, running_only}
  - `GameFilter.session_playtime_hours` → {unplayed, running_only, hist_only}
  - `GameFilter.session_average` → {unplayed, running_only, hist_only}
  - `PlayerSessionFilter.duration_hours` → {the running session}
  - `HistoricalPlaytimeFilter.duration_hours` → {} (no record)

  Assert three things per case: `IS_NULL` returns the expected set,
  `NOT_NULL` returns the rest of the scope, and the two are disjoint. Run
  queries through `execute_filter` with `filter_query_context_for_library`.
  Games are read from `Game.objects.tracked_by(library)`, sessions from
  `PlayerSession.objects.filter(library=…)`, records from
  `library_records(library)`.
- [ ] **Step 3: Add the bucket regression pin.** In the same class:
  `EQUALS 0` on each field returns the `[0, 1 h)` set (the repro sets in the
  spec, F1). `NOT_EQUALS 0` on `session_playtime_hours` leaves out both
  unplayed and hist_only. Name it
  `test_not_equals_zero_drops_games_without_sessions` and have its docstring
  point to follow-up 3.
- [ ] **Step 4: Run and see them fail.**
  `make test ARGS="tests/test_filters.py -k 'DurationPresence or duration_presence' -x"`.
  Expected: the aggregate cases fail (unplayed and hist_only are in neither
  set), and the Q-equality test fails.
- [ ] **Step 5: Implement.** In `duration_hours_to_q`, replace the two
  presence branches. Rewrite the docstring: "EQUALS matches the hour bucket
  [h, h+1). IS_NULL is no duration (zero, or NULL over no rows); NOT_NULL is
  more than zero." Keep the raise on unknown modifiers.
- [ ] **Step 6: Flip the pinned scoped test.** Rename
  `test_scoped_sum_is_null_when_no_row_matches_the_scope` to
  `test_scoped_sum_over_no_rows_is_none_not_zero`. Assert that `IS_NULL`
  returns {desktop_only}, `EQUALS 0` still returns the empty set, and
  `EQUALS 2` still returns {mixed}. Rewrite its docstring to state D2.
- [ ] **Step 7: Run the focused tests, then the whole file.**
  `make test ARGS="tests/test_filters.py tests/test_relation_algebra.py -x"`.
  Expected: PASS. The existing `test_playtime_hours_is_null_matches_an_unplayed_game`
  (`:1252`) still passes.
- [ ] **Step 8: Commit** `filters: duration none includes no rows (#1045)`.

**Gotcha:** use `__gt=timedelta(0)`, not `~Q(=0)`. A negated equality on a
NULL aggregate is unknown and drops the row again.

---

### Task 2: Two handler fields offer the pair; delete the dead handler (D3, D5, D6)

**Files:**
- Modify: `games/filters.py:368` (`playtime_hours`), `:628-631` (session
  `duration_hours`)
- Modify: `common/criteria.py` — delete `bool_nonzero_duration_handler`
  (`:3269-3281`); reword the comments at `:1014-1017`, `:1027-1032` and
  `:3184-3187` so they no longer name a "bool presence/zero" case
- Test: `tests/test_filters.py` (`:71` import, `:4702-4711`, `:5160-5164`),
  `tests/test_quick_filter_bar.py`, `tests/test_field_widget.py:134-140`

**Interfaces:**
- Consumes: Task 1's presence semantics.
- Produces: `field_metadata(GameFilter)["playtime_hours"]["modifiers"]` and
  the session `duration_hours` modifiers end with `IS_NULL`, `NOT_NULL`. The
  record field does not.

- [ ] **Step 1: Write the failing metadata tests.** Replace
  `test_handler_field_defaults_not_nullable` with two tests:
  `test_a_handler_field_defaults_not_nullable`, on
  `HistoricalPlaytimeFilter.duration_hours` (`nullable` False, no presence
  pair), and `test_duration_fields_where_none_occurs_state_the_pair`, which
  checks `playtime_hours` and session `duration_hours` (`nullable` True, pair
  last in `modifiers`).
- [ ] **Step 2: Write the failing quick-bar tests.** In
  `tests/test_quick_filter_bar.py`, next to
  `test_an_averaged_facet_in_a_presence_mode_is_editable` (`:214`), add
  `is_quick_editable` cases admitting `{"playtime_hours": {"modifier":
  "IS_NULL"}}` (GameFilter) and `{"duration_hours": {"modifier": "NOT_NULL"}}`
  (PlayerSessionFilter). Add a negative case: the record filter's
  `duration_hours` with `IS_NULL` is not editable.
- [ ] **Step 3: Add a DB proof to the widget test comment.** At
  `tests/test_field_widget.py:134-140`, keep the comment ("never played")
  and make it true by reference: point it to `TestDurationPresence`.
- [ ] **Step 4: Run and see them fail.**
  `make test ARGS="tests/test_filters.py tests/test_quick_filter_bar.py -k 'nullable or pair or editable' -x"`.
- [ ] **Step 5: Implement.** `FilterField(handler=duration_hours_handler("playtime"),
  nullable=True)` and the same on session `duration_hours`. Leave the record
  field at the default. A one-line comment on each: `#: Zero is "none"; see
  duration_hours_to_q.`
- [ ] **Step 6: Delete the dead handler.** Remove the factory, its test, and
  its import in `tests/test_filters.py:71`. Reword the three comments.
- [ ] **Step 7: Run.**
  `make test ARGS="tests/test_filters.py tests/test_quick_filter_bar.py tests/test_field_widget.py tests/test_filter_where.py -x"`.
  Expected: PASS.
- [ ] **Step 8: Commit** `filters: playtime and session duration offer none (#1045)`.

**Gotcha:** `FilterField.__post_init__` refuses `nullable` without a handler
(`common/criteria.py:1087-1092`). Both fields have one, so this is fine.

---

### Task 3: `FieldMeta.unit` and the "(hrs)" labels (D1, U3)

**Files:**
- Modify: `common/criteria.py` — `DURATION_HOURS` constant near `:1358`; mark
  in `duration_hours_handler` (`:3204-3215`), the same way
  `temporal_interval_handler` sets `interval_bounds` (`:3356`);
  `FilterField.unit` property next to `interval` (`:1056-1059`);
  `FieldMeta.unit: NotRequired[DurationUnit]` (`:2732-2770`); set it in
  `field_metadata` (`:3058-3075`) from `field_spec.unit` or `spec.unit`
- Modify: `games/filters.py` — `label="Playtime (hrs)"` on `playtime_hours`;
  `label="Duration (hrs)"` on both `duration_hours` fields (`:628-631`,
  `:1009-1012`); `GameFilter.labels` (`:397`) gains
  `"session_average": "Session average (hrs)"` and
  `"session_playtime_hours": "Session playtime (hrs)"`
- Regenerate: `make gen-element-types`
- Test: `tests/test_filters.py` (metadata class near `:5150`),
  `tests/test_ts_codegen.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: `meta.get("unit") == "duration_hours"` on exactly the five
  fields. TS `FieldMeta` has `unit?: "duration_hours"`.

- [ ] **Step 1: Write the failing tests.**
  `test_duration_fields_state_their_unit`: walk `field_metadata` over every
  filter class in `games.filters` (the same set the drift guards use), and
  collect `(class, name)` where `unit` is present. It must equal exactly the
  five fields. `test_duration_fields_read_in_hours`: the labels are the four
  U3 strings. In `tests/test_ts_codegen.py`, assert that the generated
  module renders `unit?:` (optional) on `FieldMeta`.
- [ ] **Step 2: Run and see them fail.**
  `make test ARGS="tests/test_filters.py tests/test_ts_codegen.py -k 'unit or hours' -x"`.
- [ ] **Step 3: Implement.** Add the key only when a unit exists. Do not
  write `unit=""`, because absence is the contract. The handler mark is two
  lines plus the `# type: ignore[attr-defined]` that the `interval_bounds`
  precedent uses.
- [ ] **Step 4: Regenerate and type-check.** `make gen-element-types`, then
  `make ts-check`. Expected: clean. The hand-built `FieldMeta` objects in
  `filter-group.test.ts`, `summary.test.ts`, `operations.test.ts` and
  `filter-tree/test-support.ts` compile unchanged, because the key is
  optional.
- [ ] **Step 5: Run.**
  `make test ARGS="tests/test_filters.py tests/test_ts_codegen.py tests/test_quick_filter_bar.py -x"`.
- [ ] **Step 6: Commit** `filters: duration fields state their unit (#1045)`.

**Gotcha:** `_FIELD_METADATA_CACHE` memoises per class. Tests that patch
labels must not mutate the cached dicts.

---

### Task 4: Duration labels and the bucket hint in the Python widget (U1, U2)

**Files:**
- Modify: `common/components/filters.py` — `DURATION_MODIFIER_LABELS` and
  `duration_bucket_hint` beside `NUMBER_MODIFIER_LABELS` (`:908-919`);
  `NumberFilter` (`:922-997`) takes `unit`; `field_widget`'s number branch
  (`:410-421`) passes `unit=meta.get("unit")`
- Test: `tests/test_field_widget.py`

**Interfaces:**
- Consumes: `FieldMeta.unit` (Task 3).
- Produces: a duration widget root carries `data-unit="duration_hours"` and
  holds one `<p data-duration-bucket-hint>` (`hidden` when the text is
  empty). Hint rules are below; TS (Task 5) must match them exactly.

Hint rules (`value` is the raw input text):

| modifier | value | text |
|---|---|---|
| `EQUALS` | `0` | `0 h up to 1 h` |
| `EQUALS` | `0.5` | `0.5 h up to 1.5 h` |
| `NOT_EQUALS` | `1` | `outside 1 h up to 2 h` |
| `EQUALS` | `` (empty) or not a number | `` |
| any other | any | `` |

Numbers print without a trailing `.0` (`1`, not `1.0`). The upper bound is
`value + 1`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_field_widget.py`:
  - `test_duration_presence_labels`: `field_widget(GameFilter,
    "playtime_hours", presentation=…)` shows the options `is 0 (none)` and `is
    more than 0`, and not `is null`.
  - `test_other_numbers_keep_null_labels`: `purchase_price_total` (a
    nullable sum, not a duration) keeps `is null`/`is not null` and renders
    no `data-duration-bucket-hint`.
  - `test_bucket_hint_renders_server_side`: a widget fed `{"modifier":
    "EQUALS", "value": 0}` holds `0 h up to 1 h`. One fed `GREATER_THAN`
    holds an empty, `hidden` hint.
  - `test_duration_bucket_hint_table`: parametrised over the table above,
    calling `duration_bucket_hint` directly.

  Use whatever `presentation` fixture the existing tests in this file pass.
- [ ] **Step 2: Run and see them fail.**
  `make test ARGS="tests/test_field_widget.py -k 'duration or bucket or null_labels' -x"`.
- [ ] **Step 3: Implement.** Pick the label dict by `unit`. Render the hint
  under the inputs row, inside the widget root. Give it its own text classes
  (`text-type-caption text-body-subtle` or the nearest existing caption
  token: grep `text-type-` in `filters.py`). Do not style it from
  `input.css`.
- [ ] **Step 4: Run.**
  `make test ARGS="tests/test_field_widget.py tests/test_quick_filter_bar.py tests/test_rendered_pages.py -x"`.
- [ ] **Step 5: Commit** `filters: duration widgets name zero and the hour (#1045)`.

**Gotcha:** `tests/html_answers.py` checks every HTML answer. The hint is a
plain `<p>`, not a floating panel, so it needs no `popover`.

---

### Task 5: The hint follows typing in TS (U2)

**Files:**
- Create: `ts/elements/duration-bucket.ts`,
  `ts/elements/duration-bucket.test.ts`
- Modify: `ts/elements/filter-widgets.ts` — `toggleNumberFilterInput`
  (`:235-242`) also refreshes the hint; `setupModifierToggles` (`:245-258`)
  adds an `input` listener for number inputs inside a
  `[data-unit="duration_hours"]` widget; `writeNumberWidget` (`~:294-305`)
  refreshes after hydration
- Test: `ts/elements/filter-widgets.test.ts`

**Interfaces:**
- Consumes: the DOM contract from Task 4 (`data-unit`,
  `data-duration-bucket-hint`).
- Produces: `durationBucketHint(modifier, value)` and
  `refreshDurationBucketHint(widget: HTMLElement): void` (exported from
  `filter-widgets.ts`).

- [ ] **Step 1: Write the failing unit test.** `duration-bucket.test.ts`
  runs the Task 4 table, the same five rows with the same strings. The
  docstring names the Python twin, `duration_bucket_hint`.
- [ ] **Step 2: Write the failing DOM tests.** In `filter-widgets.test.ts`,
  next to the existing `setupModifierToggles` tests (`:142-160`), build a
  number widget with `data-unit="duration_hours"` and a hint element:
  - typing `0` with modifier EQUALS shows `0 h up to 1 h`, unhidden;
  - picking `GREATER_THAN` empties and hides the hint;
  - `writeLeafWidget(cell, "number", {modifier: "NOT_EQUALS", value: 1})`
    shows `outside 1 h up to 2 h`;
  - a widget without `data-unit` gets no listener effect (no throw, no text).
- [ ] **Step 3: Run and see them fail.**
  `make test-ts TS_ARGS="ts/elements/duration-bucket.test.ts ts/elements/filter-widgets.test.ts"`.
- [ ] **Step 4: Implement.** Keep the formatting rule in one function. Use
  `String(Number(value))` for the trailing-zero rule, and return `""` when
  `value.trim() === ""` or `Number.isNaN(Number(value))`. Toggle `hidden`
  from the text.
- [ ] **Step 5: Run.** The same `make test-ts` line, then `make ts-check`.
- [ ] **Step 6: Commit** `filters: bucket hint follows the typed hour (#1045)`.

**Gotcha:** hydration writes silently, with no events (see the comment at
`filter-widgets.ts:262-269`), so the writer must call the refresh directly.

---

### Task 6: The builder summary speaks duration (U1, U2)

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts` (`MODIFIER_PHRASES`
  `:50-68`; `renderCriterionClause` `:246-…`)
- Modify: `ts/elements/filter-tree/fixtures.json` (one contract case)
- Test: `ts/elements/filter-tree/summary.test.ts`,
  `tests/test_filter_tree_contract.py` (unchanged; it reads the regenerated
  `fixtures.canonical.json`, `:32`)

**Interfaces:**
- Consumes: `FieldMeta.unit` (Task 3), `durationBucketHint` (Task 5).
- Produces: summary text such as `Playtime (hrs) is 0 (none)`,
  `Playtime (hrs) is more than 0`, `Duration (hrs) is 0 h up to 1 h`,
  `Duration (hrs) is not 0 h up to 1 h`.

- [ ] **Step 1: Write the failing tests.** In `summary.test.ts`, add a model
  whose field has `unit: "duration_hours"`. Assert the four sentences above,
  and that a number field without `unit` still reads `is empty` and `is 3`.
  Keep `MODIFIER_PHRASES` complete. `tests/test_summary_modifier_contract.py`
  checks its keys, and `DURATION_MODIFIER_PHRASES` is a partial override,
  not a second map that contract must know about.
- [ ] **Step 2: Add the contract case.** In `fixtures.json`, add "game:
  playtime none" with `{"playtime_hours": {"modifier": "IS_NULL"}}` on model
  `game`.
- [ ] **Step 3: Run and see them fail.**
  `make test-ts TS_ARGS="ts/elements/filter-tree/summary.test.ts"`.
- [ ] **Step 4: Implement.** For EQUALS/NOT_EQUALS on a duration, phrase the
  value as the range. Reuse the range part of `durationBucketHint`: export a
  `durationBucketRange(value): string` from `duration-bucket.ts` that
  returns `"0 h up to 1 h"`, and build `durationBucketHint` on it, so that
  "outside" stays a widget word and the summary says "is not".
- [ ] **Step 5: Run.** `make test-ts`, then
  `make test ARGS="tests/test_filter_tree_contract.py tests/test_summary_modifier_contract.py -x"`.
  Expected: PASS. If the contract test skipped, re-run `make test-ts` first.
  It writes the canonical artifact.
- [ ] **Step 6: Commit** `filters: summary names zero and the hour (#1045)`.

**Gotcha:** if Step 4 adds `durationBucketRange`, Task 5's
`durationBucketHint` must use it. Update Task 5's file in this commit rather
than keeping two formatters.

---

### Task 7: E2E through the quick bar

**Files:**
- Test: `e2e/test_quick_filter_e2e.py` (beside the duration tests at
  `:104-119`)

**Interfaces:**
- Consumes: everything above. Helpers: `open_facet`, `pick_choice`,
  `authenticated_page`, the session/game builders already used in this
  file.

- [ ] **Step 1: Write the test.**
  `test_playtime_none_finds_the_unplayed_game`: seed one unplayed game and
  one game with a 30-minute session. Open the "Playtime (hrs)" facet,
  `pick_choice(panel, "quick-playtime_hours-modifier", "IS_NULL")`, and
  Apply. Assert that the URL `filter` JSON equals
  `{"playtime_hours": {"modifier": "IS_NULL"}}`, that the list shows the
  unplayed game and not the 30-minute one, and that on reopen the facet
  holds `IS_NULL` and shows "is 0 (none)".
- [ ] **Step 2: Write the hint test.**
  `test_duration_hint_follows_typing`: on the sessions list, open "Duration
  (hrs)", keep "is", type `0`, and expect `0 h up to 1 h` to be visible in
  `[data-duration-bucket-hint]`.
- [ ] **Step 3: Run.** `make ts`, then
  `flock … make test-e2e ARGS="-k 'playtime_none or duration_hint'"`.
- [ ] **Step 4: Commit** `e2e: duration none and bucket hint (#1045)`.

**Gotcha:** wait for the server-rendered list after Apply before reading
rows (CLAUDE.md "UI assertion is not database assertion").

---

### Task 8: Docs and the gate

**Files:**
- Modify: `CLAUDE.md`, the Filter system section (`:1124-1131`): one
  sentence saying a duration field's presence pair is zero-or-absent against
  more than zero, and `EQUALS h` is the hour `[h, h+1)`, shown under the
  input.
- Modify: the spec, trimmed to the timeless contract (docs sweep).

- [ ] **Step 1:** Edit both. Run `make vale`.
- [ ] **Step 2:** `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
  Expected: green, e2e included.
- [ ] **Step 3: Commit** `docs: duration none and hour bucket (#1045)`.
- [ ] **Step 4:** File the spec's five follow-up issues (with
  `owner/repo#N` cross-references) and correct #1045's restatement (five
  fields; the dead handler is gone).

## Self-review

- Spec coverage: D1→T3, D2→T1, D3→T2, D4→T1 step 3, D5→T2, D6→T1 step 6 and
  T2 steps 1 and 3, U1→T4/T6, U2→T4/T5/T6, U3→T3, test plan 1–12→T1–T7.
- One formatter per language for the hint (`duration_bucket_hint`,
  `durationBucketRange`/`durationBucketHint`), and a shared table pins the
  two against each other.
- Names are consistent across tasks: `DURATION_HOURS`, `FilterField.unit`,
  `FieldMeta.unit`, `data-unit`, `data-duration-bucket-hint`,
  `refreshDurationBucketHint`.
