# Before start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `outside_playthrough_dates` into `before_playthrough_start` and `after_playthrough_completion`, count only the first on the Library page, and say what it means and how to fix it.

**Architecture:** One one-sided handler in `common/criteria.py` backs two `BoolCriterion` fields on `PlayerSessionFilter`. `games/reads/session_organization.py` states the counted filter once, and `PlaytimeReviewPanel` renders its card, the explanation paragraph, and the narrowed empty state.

**Tech Stack:** Django 6 ORM (`Q`/`F`), pytest + pytest-django, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-09-29-issue-1358-before-start-design.md`

## Global Constraints

- Drive everything through `make`. While iterating use `make test-fast ARGS="<path> -k <expr> -x"` and `make test-e2e ARGS="-k <expr>"`. The gate is a full `make check`, wrapped in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Complete-word identifiers; primitive roles get PEP 695 aliases (`type BoundSide = Literal["below", "above"]`).
- Comments explain intent only, with no issue or PR references.
- `make format`, `make lint-fix` and `make vale` pass before every commit.
- The old key is removed, not aliased. No migration: the prod dump holds no preset naming it.

---

### Task 1: The handler and the two fields

**Files:**
- Modify: `common/criteria.py:3126-3139` (`outside_interval_handler` → `beyond_bound_handler`)
- Modify: `games/filters.py:61` (import), `:316-317` (dataclass fields), `:344-351` (`fields` entries)
- Modify: `common/components/quick_filter.py:124` (the sessions facet list)
- Test: `tests/test_filters.py:7178-7410`, `tests/test_quick_filter_bar.py:501-509, 613-621`

**Interfaces:**
- Produces: `type BoundSide = Literal["below", "above"]` and `beyond_bound_handler(day_field: ORMLookup, bound_field: ORMLookup, side: BoundSide) -> FieldHandler` in `common/criteria.py`.
- Produces: `PlayerSessionFilter.before_playthrough_start` (label `Before start`, `effective_day < playthrough__started_lower`) and `PlayerSessionFilter.after_playthrough_completion` (label `After completion`, `effective_day > playthrough__completed_upper`). Both are `BoolCriterion | None = None`.
- Produces: in `QUICK_FACETS["sessions"]`, `QuickFacet("before_playthrough_start", "Before start")` then `QuickFacet("after_playthrough_completion", "After completion")`, where the old facet stood.

- [ ] **Step 1: Rewrite the filter tests.** Keep the `dated_population` fixture. Split `OUTSIDE_CASES` into:
  - `BEFORE_START_CASES = {"before_a_stated_start", "before_a_lone_start", "before_an_imprecise_start"}`
  - `AFTER_COMPLETION_CASES = {"after_a_stated_completion", "after_a_lone_completion"}`

  Parametrize `_answered` on the field name. Replace `TestSessionsOutsideTheirRunsDates` with one class per field (or one class parametrized over `(field, cases)`), asserting three things:
  - True answers exactly its cases.
  - False answers every other row of the population.
  - For its own side, a row whose run states no bound lands in False, never True. For Before start these are `on_a_run_stating_neither`, `in_the_bucket` and `after_a_lone_completion`. For After completion they are `on_a_run_stating_neither`, `in_the_bucket` and `after_a_lone_start`.

  In `TestTheDatesQuestionStatedTheLongWay`, replace the OR test with one single-comparison equivalence per field.

  Add a test: `PlayerSessionFilter.from_json('{"outside_playthrough_dates": {"value": true}}')` raises `FilterError`.
- [ ] **Step 2: Update the quick-bar tests.** Rename `test_the_dates_question_alone_stays_editable` so it runs over both new keys. Put both keys in `FacetOrderTest.ORDERS["sessions"]` where the old one stood.
- [ ] **Step 3: Run and see them fail.** `make test-fast ARGS="tests/test_filters.py tests/test_quick_filter_bar.py -k 'Dates or Facet or editable or outside' -x"`. Expected: failures naming the unknown field.
- [ ] **Step 4: Implement.** In `beyond_bound_handler`, build `Q(**{f"{day_field}__lt" if side == "below" else f"{day_field}__gt": F(bound_field)})` and return it for True and its plain `~` for False. Keep the docstring's point about Django's `IS NOT NULL` guard on the negation. Wire both fields and both facets.
- [ ] **Step 5: Run them green,** same command as Step 3.
- [ ] **Step 6: Commit.** `feat(sessions): split outside dates into before start and after completion`

### Task 2: The count, the card, the paragraph, the empty state

**Files:**
- Modify: `games/reads/session_organization.py` (whole module, 47 lines)
- Modify: `games/views/session_reclassification.py:44-48` (imports), `:174-237` (`PlaytimeReviewPanel`, `_nothing_to_review`, `_review_prose`)
- Test: `tests/test_session_organization.py`, `tests/test_session_reclassification_views.py:260-330`

**Interfaces:**
- Consumes: `PlayerSessionFilter.before_playthrough_start` (Task 1).
- Produces: `before_start_filter() -> PlayerSessionFilter` and `OrganizationCounts(bucket: int, before_start: int)`.

- [ ] **Step 1: Rewrite the organization tests.**
  - The `population` fixture keeps its rows: one before start, one after completion, one inside, one bucketed. Assert `OrganizationCounts(bucket=1, before_start=1)`; the after-completion row is not counted.
  - The zero-count tests use the new field name.
  - Parametrize the link-parity test over `bucket_sessions_filter` and `before_start_filter`. Add one assertion: the Before start card's URL, built in the panel as `filter_url(before_start_filter(), sort="playthrough")`, carries `sort=playthrough`.
- [ ] **Step 2: Rewrite the panel tests.**
  - `test_the_panel_counts_three_populations` expects the card `"Before start": "1"`. Its `three_populations` row dated 2021-12-30 is before start.
  - Add: the after-completion population alone (a session after `2022-04-01` on a dated run) draws no card and shows `Nothing to review`.
  - Add: the Before start paragraph renders exactly when its card does. Assert on a stable phrase, for example `"dated before the start of their playthrough"`.
  - Change `test_the_paragraphs_give_way_when_nothing_waits_for_review`. With the bucket card showing and the review empty, `Nothing to review` is absent and so is `hours or longer`.
  - Add: nothing counted anywhere shows `Nothing to review` and no grid.
- [ ] **Step 3: Run and see them fail.** `make test-fast ARGS="tests/test_session_organization.py tests/test_session_reclassification_views.py -x"`
- [ ] **Step 4: Implement.**
  - Rename the builder and the count field.
  - The Before start card's href is `filter_url(before_start_filter(), sort="playthrough")`.
  - Order the panel as: grid; the review paragraphs where `waiting`; then the Before start paragraph where `counts.before_start`.
  - `_nothing_to_review()` renders only where `cards` is empty, which is the existing early return. `_review_prose` stops falling back to it.
  - Use the spec's paragraph text, § "What the section says", word for word.
- [ ] **Step 5: Run them green,** same command as Step 3.
- [ ] **Step 6: `make vale`** on the changed files (the paragraph is user-facing prose).
- [ ] **Step 7: Commit.** `feat(playtime): count sessions before their playthrough's start`

### Task 3: e2e and documents

**Files:**
- Modify: `e2e/test_quick_filter_e2e.py:~370-420`
- Modify: `CLAUDE.md:852-856` (the `PlayerSessionFilter` bullet)
- Modify: `docs/superpowers/specs/2026-09-21-issue-717-outside-run-dates-design.md` and `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md`. Add one line each: "#1358 splits this field; see `2026-09-29-issue-1358-before-start-design.md`."

- [ ] **Step 1: Rewrite the e2e facet tests.** Replace `quick-outside_playthrough_dates-*` ids with `quick-before_playthrough_start-*`. The applied-facet test states `{"before_playthrough_start": {"value": true}}` and expects the accessible name `Before start (applied)`.

  Gotcha: the priority test (`expect(row_triggers).to_have_count(5)` at 2000 px, then the exact inline and overflow id lists) depended on the old facet widths. There is now one more facet with different labels, so run it, read the real split, and state the lists it shows. Don't loosen the assertions.
- [ ] **Step 2: Run.** `make test-e2e ARGS="e2e/test_quick_filter_e2e.py -x"`. `make dev` must not be running.
- [ ] **Step 3: Rewrite the CLAUDE.md bullet.** It should name `before_playthrough_start` and `after_playthrough_completion` through `beyond_bound_handler`, and say that only the first is counted, on the Library page's Before start card.
- [ ] **Step 4: Grep.** `grep -rn "outside_playthrough_dates\|outside_interval_handler\|outside_dates_filter" games common ts tests e2e CLAUDE.md` should return nothing. Older specs keep the old names as records.
- [ ] **Step 5: Format and lint.** `make format && make lint-fix && make vale`
- [ ] **Step 6: Commit.** `test(e2e): the sessions quick bar states before start`

### Task 4: Gate

- [ ] **Step 1:** `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check > $SCRATCH/check.log 2>&1; echo $?`. Read the exit code, not a grep.
- [ ] **Step 2:** Screenshot the Library page's Playtime section against a restored dump (`make restore-dump`, then `DATABASE_URL=… make dev` in the preview). Confirm the Before start card, the paragraph, and the link's sort grouping by game.
