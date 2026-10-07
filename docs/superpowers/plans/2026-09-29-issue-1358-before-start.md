# Before start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `outside_playthrough_dates` into `before_playthrough_start` and `after_playthrough_completion`, count only the first on the Library page, and say what it means and how to fix it.

**Architecture:** One one-sided handler in `common/criteria.py` (with `unless`) backs two `BoolCriterion` fields on `PlayerSessionFilter`, both excluding `PRERELEASE_PLAY`. `games/reads/session_organization.py` states the counted filter once; `PlaytimeReviewPanel` renders its card, the explanation paragraph and the narrowed empty state.

**Tech Stack:** Django 6 ORM (`Q`/`F`), pytest + pytest-django, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-09-29-issue-1358-before-start-design.md`

## Global Constraints

- Drive everything through `make`. Iterate with `make test-fast ARGS="<paths> -x"` and `make test-e2e ARGS="<path> -x"`. The gate is a full `make check`, wrapped in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Complete-word identifiers. `type BoundSide = Literal["below", "above"]`.
- Comments state intent only; no issue references.
- `make format`, `make lint-fix` and `make vale` run before every commit.
- The old key is refused, not renamed through `renamed_fields`. No migration.
- Line references are for main at `9dd3863c` (2026-10-07). Re-grep if they've moved.

---

### Task 1: The handler and the two fields

**Files:**
- Modify: `common/criteria.py:3244-3264` (`outside_interval_handler` → `beyond_bound_handler`)
- Modify: `games/filters.py:68` (import), `:561-562` (dataclass fields), `:595-604` (`fields` entries)
- Modify: `common/components/quick_filter.py:164`
- Test: `tests/test_filters.py:6362-6590`, `tests/test_session_release.py:852-877`, `tests/test_quick_filter_bar.py:490-524, 630`

**Interfaces:**
- Produces: `beyond_bound_handler(day_field: ORMLookup, bound_field: ORMLookup, side: BoundSide, *, unless: Q | None = None) -> FieldHandler`. True is `day < bound` (or `>`) combined as `& ~unless`; False is the plain `~` of that.
- Produces: `PlayerSessionFilter.before_playthrough_start` (label `Before start`, bound `playthrough__started_lower`, side `below`) and `.after_playthrough_completion` (label `After completion`, bound `playthrough__completed_upper`, side `above`). Both pass `unless=PRERELEASE_PLAY`.
- Produces: two `QuickFacet`s where the old one stood, Before start first.

- [ ] **Step 1: Update `tests/test_filters.py`.**
  - Add an open-start run to `dated_population`, built with the open-start endpoint (`TemporalEndpoint.open()`, `timetracker/temporal.py:84`). Its session is never flagged.
  - Split `OUTSIDE_CASES` (`:6457`) into `BEFORE_START_CASES = {before_a_stated_start, before_a_lone_start, before_an_imprecise_start}` and `AFTER_COMPLETION_CASES = {after_a_stated_completion, after_a_lone_completion}`.
  - Parametrize the class over `(field, cases)`, with `_answered` taking the field name. Pin three things per field:
    - True answers exactly its cases.
    - False answers the rest.
    - A run stating no bound on that side answers False. For Before start: `on_a_run_stating_neither`, `in_the_bucket`, `after_a_lone_completion`. For After completion: `on_a_run_stating_neither`, `in_the_bucket`, `after_a_lone_start`.
  - `TestTheDatesQuestionStatedTheLongWay` (`:6555`): one single field-comparison equivalence per field.
  - Add: `PlayerSessionFilter.from_json('{"outside_playthrough_dates": {"value": true}}')` raises `FilterError`.
- [ ] **Step 2: Update `tests/test_session_release.py:852-877`.** Cover both fields. A demo-Release session answers False on each. `on_the_game` and `unstated` answer True for Before start. The count line is Task 2.
- [ ] **Step 3: Update the quick-bar tests.**
  - `RunFacetsTest` asserts `>Before start<` and `>After completion<`.
  - The editable test runs over both keys.
  - `FacetOrderTest.ORDERS["sessions"]` gets both keys where the old one stood.
- [ ] **Step 4: Run and see them fail.** `make test-fast ARGS="tests/test_filters.py tests/test_session_release.py tests/test_quick_filter_bar.py -x"`
- [ ] **Step 5: Implement.** Keep the docstring's point about the `IS NOT NULL` guard and `unless`.
- [ ] **Step 6: Run them green,** same command as Step 4.
- [ ] **Step 7: Commit.** `feat(sessions): split outside dates into before start and after completion`

### Task 2: The count, the card, the paragraph, the empty state

**Files:**
- Modify: `games/reads/session_organization.py` (whole module)
- Modify: `games/views/session_reclassification.py:47` (import), `:175-235` (`PlaytimeReviewPanel`, `_nothing_to_review`, `_review_prose`)
- Test: `tests/test_session_organization.py`, `tests/test_session_reclassification_views.py:280-330`, `tests/test_session_release.py:877`

**Interfaces:**
- Consumes: `PlayerSessionFilter.before_playthrough_start` (Task 1).
- Produces: `before_start_filter() -> PlayerSessionFilter` and `OrganizationCounts(bucket: int, before_start: int)`. Counting stays over `shown_sessions(library)`.

- [ ] **Step 1: Update `tests/test_session_organization.py`.**
  - The population gives `OrganizationCounts(bucket=1, before_start=1)`. The after-completion row is not counted, and the bucket row counts only under `bucket`.
  - The zero tests use the new field.
  - The link parity runs over `bucket_sessions_filter` and `before_start_filter`.
  - Add a setting-parity test. Count the population, plus one session on a prerelease Release, once with `SHOW_PRERELEASE_PLAY` set to show and once with it set to hide; `before_start` is equal both times. Reuse the setter #1361's tests use (`git grep -n SHOW_PRERELEASE_PLAY tests`).
- [ ] **Step 2: Update `tests/test_session_release.py:877`** to `.before_start == 2`.
- [ ] **Step 3: Update the panel tests.**
  - The cards read `"Before start": "1"`, and that card's href carries `sort=playthrough`.
  - Add: an after-completion-only population draws no card and shows `Nothing to review`.
  - Add: the paragraph (`"dated before the start of their playthrough"`) renders exactly when the Before start card does.
  - Invert `test_the_paragraphs_give_way_when_nothing_waits_for_review`. With only the bucket card, neither `Nothing to review` nor `hours or longer` appears.
- [ ] **Step 4: Run and see them fail.** `make test-fast ARGS="tests/test_session_organization.py tests/test_session_reclassification_views.py tests/test_session_release.py -x"`
- [ ] **Step 5: Implement.**
  - The card href is `filter_url(before_start_filter(), sort="playthrough")`.
  - Order: grid, then the review paragraphs where `waiting`, then the Before start paragraph where `counts.before_start`.
  - `_nothing_to_review()` appears only on the existing no-cards early return; `_review_prose` stops falling back to it.
  - The paragraph text is the spec's (§ "What the section says"), word for word.
- [ ] **Step 6: Run green, then `make vale`.**
- [ ] **Step 7: Commit.** `feat(playtime): count sessions before their playthrough's start`

### Task 3: e2e and documents

**Files:**
- Modify: `e2e/test_quick_filter_e2e.py:~330-420`
- Modify: `CLAUDE.md` (the `PlayerSessionFilter` bullet naming `outside_playthrough_dates`)
- Modify: `docs/superpowers/specs/2026-09-21-issue-717-outside-run-dates-design.md` and `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md`. Add one line each: "#1358 splits this field; see `2026-09-29-issue-1358-before-start-design.md`."

- [ ] **Step 1: Update the e2e quick-bar tests.** `quick-outside_playthrough_dates-*` becomes `quick-before_playthrough_start-*`. The applied-facet test states `{"before_playthrough_start": {"value": true}}` and expects `Before start (applied)`.
  - Gotcha: the bar now holds eight facets. The priority test's counts (`2` wide, `7` at 520 px, `5` row triggers at 2000 px) and its exact id lists depend on widths. Run it, read the real split, and assert that. Don't loosen to ranges.
- [ ] **Step 2: Run.** `make test-e2e ARGS="e2e/test_quick_filter_e2e.py -x"`, with no `make dev` running.
- [ ] **Step 3: Rewrite the CLAUDE.md bullet.** It names both fields, `beyond_bound_handler`, `unless=PRERELEASE_PLAY`, and says only Before start is counted, on the Library page's card.
- [ ] **Step 4: Grep.** `git grep -n "outside_playthrough_dates\|outside_interval_handler\|outside_dates_filter\|counts.outside" -- games common ts tests e2e CLAUDE.md` should return only the `FilterError` test.
- [ ] **Step 5: Format and lint.** `make format && make lint-fix && make vale`
- [ ] **Step 6: Commit.** `test(e2e): the sessions quick bar states before start`

### Task 4: Gate and evidence

- [ ] **Step 1:** `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check > $SCRATCH/check.log 2>&1; echo $?`. Read the exit code.
- [ ] **Step 2:** `make fetch-dump && make restore-dump`. Check presets against the restored URL: `select count(*) from games_filterpreset where object_filter::text like '%outside_playthrough_dates%'`. Nonzero stops the deploy; ask the user.
- [ ] **Step 3:** Against that dump, start the dev server and screenshot the Library page's Playtime section: the Before start card, the paragraph, and the card's link grouping rows by game. Then `make drop-dump`.
