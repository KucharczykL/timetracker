# PG-07 Review Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve PR #812's review findings by making the portability guard discover generated columns, aligning PG-07 documentation with the supported database states, and correcting the Phase 1 and follow-up issue metadata.

**Architecture:** Keep the migration baseline and runtime behavior untouched. Refactor only the static migration-test helper so its forbidden generated-column set comes from loaded migration operations, then synchronize the repository specification, PR description, and issue bodies around the approved dependency order and deployment precondition.

**Tech Stack:** Python 3.14, Django 6.0 migrations, pytest, GNU Make, GitHub CLI.

## Global Constraints

- Do not alter any migration operation, model, runtime database configuration, or application behavior.
- The remaining order is `#613 → #614 → #610 → #611 → #612 → #615 → #811 → #616 → #617…` after PG-07.
- Supported migration states are a fresh database with none of the 36 predecessors applied and the sole production database at `a62da2c` with all 36 applied.
- A partially applied 0001-0036 history is unsupported after the originals are deleted and must be documented explicitly.
- Keep the Makefile's default `PYTEST_WORKERS`; do not force serial execution for the full gate.
- Preserve unrelated local changes and unrelated GitHub issue/PR body content.

---

## File structure

- Modify `tests/test_migration_portability.py`: derive generated-field names from migration operations and test discovery with unknown synthetic names.
- Modify `docs/superpowers/specs/2026-08-10-pg-07-postgresql-migration-baseline-design.md`: state the exact supported upgrade states and partial-history limitation.
- Modify `docs/superpowers/plans/2026-08-10-pg-07-postgresql-migration-baseline.md`: make its upgrade instructions use the same precondition.
- Modify `docs/superpowers/specs/2026-08-10-pg-07-review-followups-design.md`: mark the reviewed written specification approved.
- Edit GitHub issue #599: record the remaining-phase order adjustment.
- Edit GitHub issue #600: encode the approved dependency order.
- Edit GitHub issue #809: replace every stale `0001_initial.py` reference with the actual squashed filename.
- Edit GitHub PR #812: qualify the zero-action upgrade statement with the two supported migration states.

---

### Task 1: Make generated-column discovery dynamic

**Files:**
- Modify: `tests/test_migration_portability.py:1-105`
- Test: `tests/test_migration_portability.py`

**Interfaces:**
- Consumes: `games_migrations() -> list[tuple[str, Migration]]` and `referenced_column_names(expression) -> set[str]`.
- Produces: `generated_fields(migration)` yielding `(operation, field_name, field)` and `generated_column_references(migration_items) -> list[tuple[str, str, list[str]]]`.

- [ ] **Step 1: Write the synthetic failing regression test**

Add `from django.db import migrations, models`, then add this test immediately before `test_no_generated_column_reads_another_generated_column`:

```python
def test_generated_column_guard_discovers_new_names():
    synthetic = migrations.Migration("0001_synthetic", "games")
    synthetic.operations = [
        migrations.CreateModel(
            name="Synthetic",
            fields=[
                ("seed", models.IntegerField()),
                (
                    "computed_source",
                    models.GeneratedField(
                        expression=models.Value(1),
                        output_field=models.IntegerField(),
                        db_persist=True,
                    ),
                ),
                (
                    "computed_total",
                    models.GeneratedField(
                        expression=models.F("computed_source"),
                        output_field=models.IntegerField(),
                        db_persist=True,
                    ),
                ),
            ],
        )
    ]

    assert generated_column_references([("0001_synthetic", synthetic)]) == [
        ("0001_synthetic", "computed_total", ["computed_source"])
    ]
```

- [ ] **Step 2: Run the regression test to verify the red state**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_migration_portability.py::test_generated_column_guard_discovers_new_names -q
```

Expected: FAIL with `NameError: name 'generated_column_references' is not defined`.

- [ ] **Step 3: Refactor the migration walker and implement dynamic discovery**

Delete `GENERATED_COLUMNS`. Change `generated_fields()` and add the helper below:

```python
def generated_fields(migration):
    """Yield (operation, field name, field) for every GeneratedField declared."""
    for operation in migration.operations:
        field = getattr(operation, "field", None)
        if isinstance(field, GeneratedField):
            yield operation, operation.name, field
        for field_name, field in getattr(operation, "fields", None) or []:
            if isinstance(field, GeneratedField):
                yield operation, field_name, field


def generated_column_references(migration_items):
    generated_names = {
        field_name
        for _, migration in migration_items
        for _, field_name, _ in generated_fields(migration)
    }
    offenders = []
    for migration_name, migration in migration_items:
        for _, field_name, field in generated_fields(migration):
            read = referenced_column_names(field.expression) & (
                generated_names - {field_name}
            )
            if read:
                offenders.append((migration_name, field_name, sorted(read)))
    return offenders
```

Replace `test_no_generated_column_reads_another_generated_column()` with:

```python
def test_no_generated_column_reads_another_generated_column():
    offenders = generated_column_references(games_migrations())
    assert offenders == [], (
        f"PostgreSQL forbids a generated column reading another; found {offenders}"
    )
```

Update `test_no_raw_sql_in_generated_columns()` to unpack `for _, _, field in generated_fields(migration)`.

- [ ] **Step 4: Correct the stale documented blind spot**

Replace the module docstring's blind-spot paragraph with:

```text
Known blind spot, covered instead by the PostgreSQL build itself: RunSQL nested
inside SeparateDatabaseAndState.
```

Keep the explicit `Q` traversal in `referenced_column_names()` unchanged.

- [ ] **Step 5: Run the focused portability suite**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_migration_portability.py -q
```

Expected: 7 tests pass.

- [ ] **Step 6: Commit the test change**

```bash
git add tests/test_migration_portability.py
git commit -m "test: discover generated columns in migrations"
```

---

### Task 2: Align the repository documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-pg-07-postgresql-migration-baseline-design.md:65-69,151-161`
- Modify: `docs/superpowers/plans/2026-08-10-pg-07-postgresql-migration-baseline.md:125-130,193-199`
- Modify: `docs/superpowers/specs/2026-08-10-pg-07-review-followups-design.md:5`

**Interfaces:**
- Consumes: the confirmed production state at commit `a62da2c` and Django's all-or-none squash replacement behavior.
- Produces: one consistent migration-lifecycle contract for repository readers and the PR body.

- [ ] **Step 1: Mark the follow-up design approved**

Change its status line to:

```markdown
**Status:** Approved
```

- [ ] **Step 2: State the supported database states in the PG-07 design**

In “Baseline construction” and “Reversibility,” replace unconditional existing-install wording with this contract:

```text
The deleted-history deployment supports the two database states that exist for
this project: a fresh database with none of the replaced migrations recorded,
and the sole production database at main commit a62da2c with all 36 recorded.
Django substitutes the baseline in both states. A partially applied 0001-0036
history is unsupported after the originals are deleted because Django can use a
replacement only when all or none of its targets are applied.
```

Retain the verified 36-to-37 recorder-row explanation for the production state.

- [ ] **Step 3: Qualify the implementation plan's upgrade claims**

Update the Task 2 contract and the `replaces` explanation so they say the sole production database has all 36 keys recorded. Add one sentence that partial histories are unsupported and do not say “any existing installation.” Do not change the baseline filename, operation list, or verification commands.

- [ ] **Step 4: Check documentation consistency**

Run:

```bash
rg -n "any existing installation|partially applied|a62da2c|0001_initial.py" \
  docs/superpowers/specs/2026-08-10-pg-07-postgresql-migration-baseline-design.md \
  docs/superpowers/plans/2026-08-10-pg-07-postgresql-migration-baseline.md \
  docs/superpowers/specs/2026-08-10-pg-07-review-followups-design.md
```

Expected: no unconditional “any existing installation” claim; the supported-state and partial-history wording appears in the PG-07 documentation; `0001_initial.py` appears only when naming a replaced historical migration or explaining the self-cycle.

- [ ] **Step 5: Commit the documentation alignment**

```bash
git add \
  docs/superpowers/specs/2026-08-10-pg-07-postgresql-migration-baseline-design.md \
  docs/superpowers/plans/2026-08-10-pg-07-postgresql-migration-baseline.md \
  docs/superpowers/specs/2026-08-10-pg-07-review-followups-design.md
git commit -m "docs: align PG-07 deployment assumptions"
```

---

### Task 3: Correct GitHub planning and PR metadata

**Files:**
- External edit: GitHub issue #599
- External edit: GitHub issue #600
- External edit: GitHub issue #809
- External edit: GitHub PR #812

**Interfaces:**
- Consumes: current authenticated issue and PR bodies; the approved ordering and supported-state contract.
- Produces: dependency-ordered trackers and a PR description consistent with the committed documentation.

- [ ] **Step 1: Re-read all four current bodies before mutation**

Run:

```bash
gh issue view 599 --repo KucharczykL/timetracker --json body,updatedAt
gh issue view 600 --repo KucharczykL/timetracker --json body,updatedAt
gh issue view 809 --repo KucharczykL/timetracker --json body,updatedAt
gh pr view 812 --repo KucharczykL/timetracker --json body,updatedAt
```

Expected: capture the latest bodies and preserve content outside the exact sections below.

- [ ] **Step 2: Reorder Phase 1 issue #600**

Keep #603-#609 under PostgreSQL compatibility. Then encode these sections in order:

```markdown
### PostgreSQL connection and developer server

- [ ] #613
- [ ] #614

### PostgreSQL regex compatibility

(the next 3 go together)
- [ ] #610
- [ ] #611
- [ ] #612

### PostgreSQL test topology and runtime

- [ ] #615
- [ ] #811
- [ ] #616
- [ ] #617
- [ ] #618
- [ ] #619
- [ ] #620
```

Leave SQLite transfer, ownership, UUID, catalog, and phase-gate sections unchanged.

- [ ] **Step 3: Record the ordering decision in issue #599**

Append this subsection to “Plan adjustments,” before “Completion”:

```markdown
### 2026-08-10 — PostgreSQL runtime bootstrap moved ahead of regex work

The issue boundaries remain separate, but the remaining Phase 1 order changes
after PG-07. PG-11 (#613) and PG-12 (#614) now precede PG-08 through PG-10 so
the regex implementation and timeout behavior can execute against the developer
PostgreSQL server instead of being accepted from SQLite-only evidence.

PG-13 (#615) remains after the regex cluster: moving the full pytest-xdist
topology first would make its gate depend on the known regex incompatibilities
that #610 through #612 own. #811 follows PG-13 immediately, so PG-01 through
PG-06 are re-verified as soon as the permanent topology exists, before PG-14
moves CI to PostgreSQL.

The resulting order is #613, #614, #610, #611, #612, #615, #811, #616, then
#617 onward. This changes sequencing, not issue granularity or ownership.
```

- [ ] **Step 4: Correct issue #809's baseline filename**

Replace all three claims that the regenerated baseline is `games/migrations/0001_initial.py` or `0001_initial` with `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py` or its matching basename. Preserve its cutover timing and “delete the `replaces` list and nothing else” boundary.

- [ ] **Step 5: Qualify PR #812's upgrade section**

Rename `## Upgrade impact: none` to `## Upgrade impact for supported states: none`. Replace “an installation with them recorded” with “the sole production installation at main commit `a62da2c`, with all 36 recorded.” Add:

```markdown
A fresh database has none of the replaced keys applied, so Django selects the
baseline normally. A partially applied 0001–0036 history is not supported after
the originals are deleted: Django can select a squashed replacement only when
all or none of its targets are applied. No such database exists in this project.
```

Keep the verified upgrade transcript and the 36-to-37 explanation unchanged.

- [ ] **Step 6: Read back and verify the external edits**

Run the four Step 1 commands again. Verify exactly:

- #600 orders `#613, #614, #610, #611, #612, #615, #811, #616`.
- #599 contains the new runtime-bootstrap adjustment.
- #809 contains no assertion that the live baseline file is `0001_initial.py`.
- PR #812 names both supported states and the partial-history limitation.

---

### Task 4: Run the complete verification gate

**Files:**
- Verify: all changed repository files

**Interfaces:**
- Consumes: Tasks 1-3 completed and committed where applicable.
- Produces: fresh evidence that the PR remains mergeable after the follow-ups.

- [ ] **Step 1: Run migration drift and patch hygiene checks**

```bash
direnv exec . make check-migrations
git diff --check origin/main...HEAD
```

Expected: `No changes detected`, no whitespace errors.

- [ ] **Step 2: Run the full project gate**

```bash
direnv exec . make check
```

Expected: lint, formatting, typing, generated assets, migration drift, TypeScript tests, and all Python/E2E tests pass with the Makefile's default worker count.

- [ ] **Step 3: Verify final repository state**

```bash
git status --short --branch
git log --oneline -5
```

Expected: no uncommitted changes; recent commits include the review-follow-up design, dynamic portability guard, and deployment-assumption documentation.

- [ ] **Step 4: Report the addressed findings**

Report the exact issue order, corrected #809 filename, supported migration states, dynamic regression-test result, full-gate totals, and the fact that the four GitHub bodies were read back after editing.
