# Sessions outside their playthrough's dates implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new `PlayerSessionFilter` fields — the run's kind, and whether a
session's day falls outside the dates its run states — both quick facets, and
the Library page's Playtime section counting three populations as linked cards.

**Architecture:** No model, no migration, no event, no stored state. One
handler factory in `common/criteria.py`, two field entries in
`games/filters.py`, two quick facets, one read module that states each filter
once so a count and its link compile one predicate, and one rewritten panel on
the Library page.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django,
Playwright for the browser test.

**Spec:** [docs/superpowers/specs/2026-09-21-issue-717-outside-run-dates-design.md](../specs/2026-09-21-issue-717-outside-run-dates-design.md)

## Global constraints

- Python 3.14 only; `except A, B:` bare form is correct (PEP 758).
- Everything through `make`. Never `uv run pytest`, never wrap in
  `direnv exec .`. Focused runs:
  `make test ARGS="tests/test_filters.py -k outside -x"`.
- The gate before the PR is a full `make check`, e2e included. `make check-fast`
  is for iterating only. Read its exit code, never grep its output.
- `make format` then `make lint-fix` before every commit — `format` leaves
  import order alone and only `lint-fix` fixes `I001`.
- Unabbreviated identifiers (`session` not `s`, `criterion` not `c`).
- Name compound types: `TypedDict` / `NamedTuple` / `type` alias rather than a
  repeated structural annotation.
- Comments explain intent only; no issue or PR references except forward
  `TODO`s. Docstrings terse, house style.
- `make vale` runs inside `make check` and now reads **the files this checkout
  changed**. `fold`, `seam`, `heal`, `delete`, `archive`, `tombstone` and
  **`leg`** are refused in prose and comments; design records under
  `docs/superpowers/` are no longer exempt, so a record this plan amends must
  answer for every refused word it holds. Say `clause` for one branch of a
  predicate, `step` for one part of a run.
- Never write to a `GeneratedField`: `effective_day`, `effective_duration`,
  `sort_instant`, `started_lower`, `completed_upper`.
- Read playtime only through `games/reads/playtime.py`. This issue adds no
  playtime figure, so nothing here should reach for one.
- Rebase onto `origin/main` before the first edit.

## What the code already does

Read these before Task 1; each is load-bearing and none is obvious.

- `common/criteria.py:3116` `bool_running_handler` — the shape both new
  handlers follow: one `Q`, returned or negated on the criterion's value.
- `common/criteria.py:3151` `temporal_interval_handler`, and
  `_bound_at_most` / `_bound_at_least` below it — the null-tolerant bound
  comparison against a **literal**. The new factory compares against a
  **column**, so it does not reuse them.
- `games/reads/player_sessions.py:26` `library_sessions` — the read scope, four
  removal marks and three library columns. It **keeps** imported-history
  sessions, unlike `library_runs`. Both counts read it.
- `games/bulk_reclassification.py:54` `reviewable_sessions` — the review's base:
  duration-only, at or over `REVIEW_THRESHOLD_HOURS`, `kind=ORDINARY`. Its
  docstring says no filter field states a run; Task 9 restates that.
- `games/views/session_reclassification.py:133` `review_filter` and `:151`
  `review_url` — the precedent for a Python-built filter in a link.
- `games/filters.py:1050` `filter_query_context_for_library` — what a read
  passes so a relation clause resolves under the right library.
- `common/components/library_kit.py:68` `StatisticCard` — `label`, `value`,
  `href`, and the link's accessible name, which defaults to `f"{value} {label}"`.
  The browser test in Task 8 depends on that string.

## Gotchas found before the plan was written

1. **Do not hand-write the false branch of the dates filter.** A comparison
   against a nullable column is NULL where the column is, so `NOT (a OR b)`
   looks like it would drop every undated run from both answers. Django adds an
   `IS NOT NULL` guard to a negated lookup whose right side is a column
   (`django/db/models/sql/query.py:1648`), so the plain negation is correct and
   holds those rows. Task 1 pins that with a test rather than trusting it.
2. **`playthrough_kind` needs no `search_url`.** `platform_group` states one
   because platform groups are a dynamic value list; `PlaythroughKind` is a
   static enum on the model, so `field_metadata` fills the choices itself, as
   it does for `timing_mode`. Its `nullable` is False, because
   `PlayerSession.playthrough` is non-null.
3. **No registry to update.** The filter completeness tests
   (`tests/test_filters.py:5204`, `tests/test_quick_filter_bar.py:501`,
   `tests/test_filter_paths.py:117`) all derive from `dataclasses.fields`, so a
   new field needs only its dataclass attribute and its `fields` entry.
   `renamed_fields` is for renames; no preset migration is needed;
   `ts/generated/filter-metadata.ts` codegens types, not field names.
4. **`PlayerSession.comparison_through` needs nothing.** It names multi-segment
   paths; `playthrough__started_lower` is one to-one hop, which
   `_comparison_operand_info` already admits, and `_comparison_relations`
   already offers every concrete foreign key.
5. **Three tests and one browser test name the button Task 7 removes.** They
   are listed in Task 7 and Task 8; do not discover them at gate time.

---

## Task 1: The dates filter

**Files:**
- Modify: `common/criteria.py` — new factory beside `temporal_interval_handler`
- Modify: `games/filters.py` — `PlayerSessionFilter` attribute and `fields` entry
- Test: `tests/test_filters.py`

**Interfaces:**
- Produces: `outside_interval_handler(day_field: ORMLookup, lower_field: ORMLookup, upper_field: ORMLookup) -> FieldHandler`
  in `common/criteria.py`, exported through the same path `bool_running_handler`
  uses; and `PlayerSessionFilter.outside_playthrough_dates: BoolCriterion | None`,
  whose `fields` entry is
  `FilterField(handler=outside_interval_handler("effective_day", "playthrough__started_lower", "playthrough__completed_upper"), label="Outside dates")`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_filters.py`, beside the existing `is_running` cases. One run per
case, sessions built with the module's existing helpers. Assert over
`library_sessions(library).filter(filter.to_q(context))` row sets, not SQL:

| case | run states | session day | `value=True` | `value=False` |
|---|---|---|---|---|
| before a stated start | 2022-02-01 → 2022-04-01 | 2021-12-30 | matches | no |
| after a stated completion | 2022-02-01 → 2022-04-01 | 2024-07-01 | matches | no |
| inside the interval | 2022-02-01 → 2022-04-01 | 2022-03-02 | no | matches |
| start alone, day before it | start 2022-03-01 | 2021-01-05 | matches | no |
| start alone, day after it | start 2022-03-01 | 2026-01-05 | no | matches |
| completion alone, day after | completion 2022-04-01 | 2022-06-01 | matches | no |
| **run states neither** | — | any | no | **matches** |
| bucket row | bucket states neither | any | no | matches |
| imprecise start (`2022`) | lower 2022-01-01, upper 2022-12-31 | 2022-06-01 | no | matches |
| imprecise start (`2022`) | as above | 2021-06-01 | matches | no |

The undated row under `value=False` is the gotcha above; name the test so a
later reader knows it guards the ORM's guard, for example
`test_a_run_stating_no_date_answers_no_rather_than_nothing`.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_filters.py -k outside -x"` — expect
`TypeError: PlayerSessionFilter() got an unexpected keyword argument`.

- [ ] **Step 3: Write the factory**

`outside_interval_handler` builds one `Q`: day strictly below the lower bound,
or strictly above the upper. Return it for `value`, negate it otherwise — the
`bool_running_handler` shape, one expression and its negation. The docstring
says why the negation is safe and names the ORM's guard; that is the one
comment this task needs.

- [ ] **Step 4: Wire the field**

Dataclass attribute with a one-line `#:` comment saying what it reads, and the
`fields` entry from the Interfaces block. Keep it beside `is_running`, which is
its sibling in shape.

- [ ] **Step 5: Green, format, commit**

`make test ARGS="tests/test_filters.py -k outside"`, then `make format`,
`make lint-fix`, then commit as `feat: the sessions a run's dates do not cover`.

---

## Task 2: The run's kind

**Files:**
- Modify: `games/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Produces: `PlayerSessionFilter.playthrough_kind: ChoiceCriterion | None`, entry
  `FilterField("playthrough__kind", label="Playthrough")`.

- [ ] **Step 1: Write the failing tests**

- `INCLUDES ["imported_history"]` answers the bucket's sessions and no others.
- `EXCLUDES ["imported_history"]` answers the ordinary ones.
- `field_metadata(PlayerSessionFilter)` entry for the field states
  `kind == "set"`, `nullable is False`, an empty `search_url`, and both
  `PlaythroughKind` values in `choices`.
- `to_json` / `from_json` round trip.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_filters.py -k playthrough_kind -x"`.

- [ ] **Step 3: Add the attribute and the entry**

No handler. The lookup crosses one to-one hop, which `_resolve_model_field`
resolves, so the widget reads the model's own choices.

- [ ] **Step 4: Green, format, commit**

Commit as `feat: the session filter states its run's kind`.

---

## Task 3: Both as quick facets

**Files:**
- Modify: `common/components/quick_filter.py` — `QUICK_FACETS["sessions"]`
- Test: `tests/test_quick_filter_bar.py`

- [ ] **Step 1: Write the failing tests**

- The sessions bar renders a facet trigger for each new field, labelled
  `Playthrough` and `Outside dates`.
- A filter naming `playthrough_kind` alone is quick-editable, and its rendered
  bar does **not** contain `Advanced filter active`.
- The same for `outside_playthrough_dates`.
- The bar's own serialized output for each round-trips back to editable, which
  is the property `is_quick_editable`'s docstring pins.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_quick_filter_bar.py -k playthrough -x"`.

- [ ] **Step 3: Add the two facets**

`QuickFacet("playthrough_kind", "Playthrough")` and
`QuickFacet("outside_playthrough_dates", "Outside dates")`, after `timing_mode`
so the row's order reads session facts first, then the run's.

- [ ] **Step 4: Green, format, commit**

Commit as `feat: the session bar asks both run questions`.

---

## Task 4: Pin the long way round

**Files:**
- Test: `tests/test_filters.py` only. No source change.

- [ ] **Step 1: Write the test**

Build the same question as two `FieldComparisonCriterion` values — `effective_day`
`LESS_THAN` `playthrough__started_lower`, and `effective_day` `GREATER_THAN`
`playthrough__completed_upper` — one per `OR` branch of a `PlayerSessionFilter`,
and assert the row set equals the one `outside_playthrough_dates=True` answers
over the same fixtures. Assert also that `comparable_columns(PlayerSession)`
offers both operands, so the test fails loudly if a later change closes the hop.

- [ ] **Step 2: Run it**

`make test ARGS="tests/test_filters.py -k long_way -x"`. It should pass on
first run: this task states an existing capability rather than adding one. If
it fails, stop — the spec's claim is wrong and the shorthand's semantics need
re-deciding before Task 5.

- [ ] **Step 3: Commit**

Commit as `test: the dates question, stated the long way`.

---

## Task 5: The counts

**Files:**
- Create: `games/reads/session_organization.py`
- Test: `tests/test_session_organization.py`

**Interfaces:**
- Produces:
  - `bucket_sessions_filter() -> PlayerSessionFilter`
  - `outside_dates_filter() -> PlayerSessionFilter`
  - `OrganizationCounts(NamedTuple)` with `bucket: int` and `outside: int`
  - `organization_counts(library: UserLibrary) -> OrganizationCounts`

- [ ] **Step 1: Write the failing tests**

- Each count answers the rows its own filter answers, over a fixture holding a
  bucket session, two sessions outside their run's dates, and one inside.
- Neither count sees another library's rows.
- A library with none answers `OrganizationCounts(0, 0)`.
- `filter_url(bucket_sessions_filter())` and `filter_url(outside_dates_filter())`
  both resolve to the session list and parse back to the same filter.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_session_organization.py -x"`.

- [ ] **Step 3: Write the module**

Each builder states its `PlayerSessionFilter` once. `organization_counts` counts
`library_sessions(library).filter(criteria.to_q(filter_query_context_for_library(library)))`
per builder. The module's docstring says why the builders are public: the
Library page passes the same objects to `filter_url`, so the number and the
link compile one predicate.

- [ ] **Step 4: Green, format, commit**

Commit as `feat: the two counts the organizer starts from`.

---

## Task 6: The review link states the kind

**Files:**
- Modify: `games/views/session_reclassification.py:133` `review_filter`
- Test: `tests/test_session_reclassification_views.py:279`

- [ ] **Step 1: Change the pinned test first**

`test_the_review_filter_parses_and_stays_quick_editable` asserts
`set(parsed) == {"timing_mode", "duration_hours"}`. Make it expect
`playthrough_kind` as well, and add an assertion that the link's filter answers
exactly the rows `reviewable_sessions(library)` answers, over a fixture holding
one reviewable bucket-dwelling session and one ordinary one. That second
assertion is the point of the task.

- [ ] **Step 2: Run it and watch it fail**

`make test ARGS="tests/test_session_reclassification_views.py -k review_filter -x"`.

- [ ] **Step 3: Add the clause**

`playthrough_kind=ChoiceCriterion(value=[PlaythroughKind.ORDINARY.value], modifier=Modifier.INCLUDES)`
beside the two the builder already states.

- [ ] **Step 4: Green, format, commit**

Commit as `fix: the review link names the rows the review offers`.

---

## Task 7: Three cards on the Library page

**Files:**
- Modify: `games/views/session_reclassification.py:163` `PlaytimeReviewPanel`
- Test: `tests/test_session_reclassification_views.py`

**Interfaces:**
- Consumes: `organization_counts` from Task 5, `review_url` and
  `reviewable_sessions` as they are.
- Produces: no new public name; the panel keeps its signature
  `PlaytimeReviewPanel(library: UserLibrary) -> Node`.

- [ ] **Step 1: Write the failing tests**

- All three counts non-zero: the page holds three `StatisticCard`s labelled
  `To review`, `Imported history` and `Outside dates`, each linking to the
  session list, and the review's two paragraphs.
- The bucket count zero: no `Imported history` card, the other two present.
- The review count zero, the others not: no `To review` card, and the
  paragraphs give way to `Nothing to review`.
- All three zero: no grid, and `Nothing to review` alone — this keeps
  `test_the_library_says_so_when_nothing_waits` (`:264`) true.
- `See these sessions` appears nowhere on the page.

Update the two existing tests that assert the button:
`test_the_library_offers_the_review` (`:193`) now asserts the `To review` card
and the count sentence; `test_the_session_list_carries_no_review_row` (`:272`)
asserts the card's label is absent from the session list instead.

- [ ] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_session_reclassification_views.py -x"`.

- [ ] **Step 3: Rewrite the panel**

`StatisticGrid` of the non-zero cards first, then the review's paragraphs when
its count is not zero, then nothing else. The `ControlButton` goes. Card values
are the counts; each `href` is `review_url()` or `filter_url(...)` over Task 5's
builders.

- [ ] **Step 4: Green, format, commit**

Commit as `feat: the Playtime section counts three populations`.

---

## Task 8: The browser test follows the card

**Files:**
- Modify: `e2e/test_session_reclassification_e2e.py:38`

- [ ] **Step 1: Change the selector**

The flow opens the Library page and presses
`get_by_role("link", name="See these sessions")`. The card's link has no text of
its own; `StatisticCard` gives it `aria_label=f"{value} {label}"`, so the press
becomes `get_by_role("link", name=re.compile(r"\d+ To review"))`. The rest of
the flow is unchanged.

- [ ] **Step 2: Run it**

`make test-e2e ARGS="-k reclassification"`. Never run this while `make dev` is
up: its watchers rewrite the served assets and the suite fails everywhere at
once.

- [ ] **Step 3: Commit**

Commit as `test: the review flow starts at the card`.

---

## Task 9: The records this change makes stale

**Files:**
- Modify: `games/bulk_reclassification.py:56-65` — docstring and the `#:` comment
- Modify: `CLAUDE.md` — the `PlayerSessionFilter` paragraph, which lists the
  filter's words
- Modify: `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md`
  — the `#717` entry under "Delivery order", the "The question the sole-run rule
  never asked" section, and the "What was applied" note

- [ ] **Step 1: Restate the two comments**

`reviewable_sessions` says the bucket "is told apart by its run's kind, which
`PlayerSessionFilter` does not carry". It carries it now. What stays true is
the second sentence: the act's scope is its own base narrowed by a statement's
filter, so the field widens nothing.

- [ ] **Step 2: Restate CLAUDE.md**

Add both fields to the `PlayerSessionFilter` word list in the same clipped
register the paragraph already uses.

- [ ] **Step 3: Amend the wave record**

Say that the field judges each endpoint a run states rather than requiring
both, that a second field states the run's kind, and that the section counts
three cards. **The record is no longer exempt from the vocabulary rules**, so
`make vale` will report every refused word the file holds once you touch it —
the selectable-tables record holds three uses of `leg`. Fix them in this
commit; `clause` and `step` are the replacements.

- [ ] **Step 4: Lint and commit**

`make vale` — it reads only what this checkout changed, so the three files
above. Commit as `docs: the two run questions the session filter states`.

---

## Task 10: Measure the real population

**Files:** none. This task produces two numbers and one amendment.

- [ ] **Step 1: Restore a dump**

`make fetch-dump` then `make restore-dump`, which prints its `DATABASE_URL`.
Needs `PROD_SSH_HOST` and `PROD_DB_CONTAINER` in `.env`. Run `make migrate`
against the restored copy before reading it.

- [ ] **Step 2: Count both rules**

Against that copy, through `make shell ARGS='-c "..."'`:

- this issue's rule: `outside_dates_filter()` over `library_sessions`;
- the wave record's narrower rule: the same, restricted to runs whose
  `start_recorded_at` and `completion_recorded_at` are both stated;
- the bucket count;
- for context, how many of the flagged sessions sit on a game's sole run,
  which is the population the record's 113 actually counted.

- [ ] **Step 3: Record them**

Write all four numbers into the spec's Verification section, and correct the
wave record's figure where it moved. If this rule answers far more than 113,
say so plainly in both records rather than quietly replacing the number.

- [ ] **Step 4: Drop the scratch database**

`make drop-dump`.

- [ ] **Step 5: Commit**

Commit as `docs: what the dates question answers on real data`.

---

## Task 11: The gate

- [ ] **Step 1: Rebase**

`git fetch origin && git rebase origin/main`.

- [ ] **Step 2: Format and lint**

`make format` then `make lint-fix`. Both, in that order.

- [ ] **Step 3: Full gate**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check
```

Read the exit code. `make check-fast` does not close this task: only the full
run covers `e2e/`, and Task 8 changed a browser test.

- [ ] **Step 4: Open the PR**

Body states what the two fields answer, the three cards, the two numbers Task
10 measured, and the two follow-ups the spec names (#1249, #1250).
