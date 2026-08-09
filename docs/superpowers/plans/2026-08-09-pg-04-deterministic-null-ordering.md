# PG-04: Deterministic NULL ordering across lists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make every sort served by games.sorting.apply_sort() put NULL values last in either direction and resolve otherwise equal rows by primary key.

**Architecture:** Keep public sort keys and SortSpec unchanged. Translate each resolved sort field to a Django F() ascending/descending order expression with nulls_last=True, then append ascending pk after requested terms. Annotation creation remains before ordering; the audit confirms manual user-facing orderings need no change.

**Tech Stack:** Python 3.14, Django ORM, pytest, SQLite test database, Make targets.

## Global Constraints

- Related issue: https://github.com/KucharczykL/timetracker/issues/606
- Preserve existing sort keys, default sorts, header state, filters, presets, API response shapes, and ownership boundaries.
- Use explicit NULLS LAST for every apply_sort() term in both directions.
- Append ascending pk internally only; never expose it in URLs or SortResult.terms.
- Do not add a migration, PostgreSQL runtime, schema change, data operation, backfill, or rollback operation.
- Run tests through make; completion requires make check.

---

## File structure

- Modify: games/sorting.py — make ORM ordering explicit and stable.
- Modify: tests/test_sorting.py — cover nullable direct fields, nullable aggregate annotations, and equal sort values.
- Inspect only: games/api.py, games/views/game.py, games/views/session.py, games/views/stats_data.py — audit manual user-facing ordering without scope expansion.

### Task 1: Define the shared sort contract with tests

**Files:**

- Modify: tests/test_sorting.py:96-145
- Modify: games/sorting.py:6-10,170-186

**Interfaces:**

- Consumes: apply_sort(queryset, find, sort_map, default_sort) -> SortResult, GAME_SORTS, and FindFilter.sort.
- Produces: a SortResult whose queryset sorts every requested/default expression with NULLS LAST and then ascending pk; terms remains the parsed public terms.

- [ ] **Step 1: Add the failing nullable direct-field and tiebreaker tests**

In TestApplySortGames, add a test that creates games with year_released values None, 1990, and 2000. Call apply_sort() with year and -year and assert [early, late, unknown] and [late, early, unknown] respectively.

Add a separate test that creates first and second with the same Game.Status.UNPLAYED. Sort a deliberately unordered pk__in queryset by status; assert [first, second] and assert result.terms == [SortTerm("status", False)].

Use this exact structure:

~~~
def test_nullable_direct_sort_keeps_null_last_in_both_directions(self, db):
    platform = Platform.objects.create(name="P", icon="p")
    unknown = Game.objects.create(name="Unknown", platform=platform)
    early = Game.objects.create(name="Early", platform=platform, year_released=1990)
    late = Game.objects.create(name="Late", platform=platform, year_released=2000)

    ascending = apply_sort(Game.objects.all(), _find("year"), GAME_SORTS, GAME_DEFAULT_SORT)
    descending = apply_sort(Game.objects.all(), _find("-year"), GAME_SORTS, GAME_DEFAULT_SORT)

    assert list(ascending.queryset) == [early, late, unknown]
    assert list(descending.queryset) == [late, early, unknown]
~~~

- [ ] **Step 2: Run the direct-field tests before implementation**

Run:

~~~powershell
make test ARGS="tests/test_sorting.py::TestApplySortGames::test_nullable_direct_sort_keeps_null_last_in_both_directions tests/test_sorting.py::TestApplySortGames::test_equal_sort_values_use_primary_key_tiebreaker -v"
~~~

Expected: the descending NULL-last assertion fails on SQLite under the current implicit signed-string ordering. The tie test documents the required secondary ordering.

- [ ] **Step 3: Add the failing nullable aggregate test**

Import date alongside datetime. Create unfinished, early, and late games; create PlayEvents for early ending on 2024-01-01 and late ending on 2024-01-02. Sort with finished and -finished, which exercises GAME_SORTS["finished"] and its Max(playevents__ended) annotation.

~~~
def test_nullable_aggregate_sort_keeps_null_last_in_both_directions(self, db):
    platform = Platform.objects.create(name="P", icon="p")
    unfinished = Game.objects.create(name="Unfinished", platform=platform)
    early = Game.objects.create(name="Early", platform=platform)
    late = Game.objects.create(name="Late", platform=platform)
    PlayEvent.objects.create(
        game=early, started=date(2024, 1, 1), ended=date(2024, 1, 1)
    )
    PlayEvent.objects.create(
        game=late, started=date(2024, 1, 1), ended=date(2024, 1, 2)
    )

    ascending = apply_sort(Game.objects.all(), _find("finished"), GAME_SORTS, GAME_DEFAULT_SORT)
    descending = apply_sort(Game.objects.all(), _find("-finished"), GAME_SORTS, GAME_DEFAULT_SORT)

    assert list(ascending.queryset) == [early, late, unfinished]
    assert list(descending.queryset) == [late, early, unfinished]
~~~

- [ ] **Step 4: Run the aggregate test before implementation**

Run:

~~~powershell
make test ARGS="tests/test_sorting.py::TestApplySortGames::test_nullable_aggregate_sort_keeps_null_last_in_both_directions -v"
~~~

Expected: the descending assertion fails because the current SQLite ordering places the NULL aggregate first.

### Task 2: Implement explicit shared ordering

**Files:**

- Modify: games/sorting.py:6-10,170-186
- Test: tests/test_sorting.py:96-145

**Interfaces:**

- Consumes: Task 1 tests and existing SortSpec.expression/annotate contract.
- Produces: apply_sort() that accepts all current SortSpec fields and annotations without changing its public signature.

- [ ] **Step 1: Import F and replace signed strings with OrderBy expressions**

Change the django.db.models import to include F. In apply_sort(), replace list[OrderField] and the signed-string append with:

~~~
    annotations: Annotations = {}
    order_by = []
    for term in terms:
        spec = sort_map[term.key]
        if spec.annotate:
            annotations.update(spec.annotate)
        expression = F(spec.expression)
        order_by.append(
            expression.desc(nulls_last=True)
            if term.descending
            else expression.asc(nulls_last=True)
        )
    order_by.append(F("pk").asc())
~~~

Retain the existing annotation application and return:

~~~
    if annotations:
        queryset = queryset.annotate(**annotations)
    return SortResult(queryset.order_by(*order_by), terms, unknown)
~~~

- [ ] **Step 2: Run the focused shared sort suite**

Run:

~~~powershell
make test ARGS="tests/test_sorting.py::TestApplySortGames -v"
~~~

Expected: PASS, including the direct nullable, aggregate nullable, tie, default-sort, and no-duplicate-row cases.

- [ ] **Step 3: Audit remaining manual user-facing ordering sites**

Run:

~~~powershell
rg -n "\.order_by\(" games/api.py games/views/game.py games/views/session.py games/views/stats_data.py
~~~

Confirm:

- search_devices() and search_platforms() already use F(...).desc(nulls_last=True) for nullable last-used values.
- Search selectors and form-choice-style queries use non-null name or sort_name values.
- Game detail purchases and sessions use non-null date_purchased and timestamp_start.
- Statistics queries are filter-constrained to their displayed temporal/aggregate value or use non-null scalar values; none is a shared paginated list ordering owned by this issue.

If the audit contradicts any finding, stop implementation and update the approved design before changing a manual query.

- [ ] **Step 4: Run all sorting coverage and commit**

Run:

~~~powershell
make test ARGS="tests/test_sorting.py -v"
git add games/sorting.py tests/test_sorting.py
git commit -m "fix: make list null ordering deterministic"
~~~

Expected: all sorting tests pass. The commit contains only shared ordering behavior and tests.

### Task 3: Verify the full change

**Files:**

- Inspect: games/sorting.py
- Inspect: tests/test_sorting.py

**Interfaces:**

- Consumes: Task 2 commit.
- Produces: verified issue-ready branch with no schema/data changes and a PR body that closes the related issue.

- [ ] **Step 1: Review scope and ordering semantics**

Run:

~~~powershell
git diff HEAD~1 -- games/sorting.py tests/test_sorting.py
git diff --check HEAD~1
~~~

Verify every requested/default term uses asc/desc(nulls_last=True), pk is appended once, and SortResult.terms, sort maps, URLs, views, migrations, and data remain unchanged.

- [ ] **Step 2: Run the repository gate**

Run:

~~~powershell
make check
~~~

Expected: exit code 0 for the project-required Python, frontend, formatting, and static checks.

- [ ] **Step 3: Confirm the final branch and pull-request close link**

Run:

~~~powershell
git status --short
git log -1 --oneline
~~~

Expected: clean worktree and the Task 2 implementation commit at HEAD. The pull request body must link https://github.com/KucharczykL/timetracker/issues/606 and include the exact GitHub closing keyword Closes #606.

## Spec coverage review

- Task 1 proves explicit NULL-last behavior for direct nullable fields and nullable aggregates, in both directions.
- Task 1 proves stable primary-key ordering for equal sort values.
- Task 2 keeps public sorts, headers, filters, presets, APIs, and ownership unchanged by modifying only the common ORM translation.
- Task 2's audit protects manual user-facing orderings from unreviewed scope expansion.
- The plan contains no migration/data operation because the approved design changes ordering only.
- Task 3 requires make check before issue handoff.

