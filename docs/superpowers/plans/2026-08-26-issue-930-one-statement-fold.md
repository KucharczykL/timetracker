# A fold of one statement per event — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current-state fold's six statements per event with one
`INSERT ... ON CONFLICT (id) DO UPDATE`, keeping idempotency and every error the
fold raises today.

**Architecture:** `Projector` gains one method, `project(model, identity,
**columns)`, which resolves the model through the family's target and writes the
whole row with `bulk_create(update_conflicts=True, unique_fields=["pk"])`.
`PlayerGames._created` becomes one call to it and `update_or_create` leaves the
codebase. Nothing else changes: no migration, no schema change, no new module.
The remaining work is measurement — re-record `docs/event-benchmarks.md` from a
real run, and cost what a batched replay would add.

**Spec:** `docs/superpowers/specs/2026-08-26-issue-930-one-statement-fold-design.md`
— read it before Task 1. It carries the *why*, including the two probes that
measured the statement on the live and the shadow path; this plan carries the
*what* and the order.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pytest + pytest-django.

## Global Constraints

- **Python 3.14 only.** PEP 758's bare `except A, B:` applies **without** a
  binding; a clause needing the error is `except (A, B) as error:`.
- **Drive everything through `make`.** Never `uv run pytest` directly. Focused
  runs: `make test ARGS="tests/test_event_projectors.py -k helper -x"`.
- **`PYTEST_WORKERS=0` when debugging a failure**; parallel output interleaves.
- **Iterate on `make check-fast`; gate on the full `make check`** before the PR.
- **Complete words in identifiers** — `identity`, `columns`, `projected`, never
  `id_`, `cols`, or `p`.
- **No issue references in code comments.** They belong in the spec and the PR.
- **`games/events/projection.py` holds no runtime ORM import.** `ProjectionModel`
  is imported under `TYPE_CHECKING` only. #914 bought that property.
- **No migration, no schema change, no data change.** If the work grows one,
  something has gone wrong.
- **Do not edit specs under `docs/superpowers/specs/` other than this issue's.**
  #670's spec records what was true when it was written, including "four of the
  fold's six statements are savepoints". It is a dated record, not documentation.

---

## File structure

**Modify `games/events/projection.py`** — add `project()` to `Projector`, plus
`import uuid` and a `TYPE_CHECKING` import of `ProjectionModel`. The method is
the only new public surface in this work.

**Modify `games/projectors/playergame.py`** — `_created` calls `self.project(...)`.
The file loses `update_or_create` and its own `self.target.model(...)` line.

**Modify `games/events/benchmark.py`** — one docstring in `StatementCounter`
asserts the fold has six statements, four of them savepoints. It stops being
true.

**Modify `tests/test_event_projectors.py`** — the helper's own tests: it resolves
through the target, it costs one statement, and a returning identity rewrites one
row. The module owns its registries; nothing here may reach `DEFAULT_REGISTRY`
except where a test says so.

**Modify `tests/test_playergame_projection.py`** — the real family's behaviour:
the fold costs one statement, and a second identity for a tracked game is
refused rather than silently dropped.

**Modify `tests/test_event_benchmark.py`** — the slope test that names this issue
moves from 6.0 to 1.0.

**Modify `docs/event-benchmarks.md`** — re-recorded from a real run, plus the
costing of a batched replay.

**Nothing else is touched.** No model, no migration, no view, no template.

---

## Task 0: Put the spec and the plan on a branch — done

The spec and this plan were committed on local `main`, ahead of `origin/main`.
They were moved onto a branch before any code:

```bash
git switch -c claude/issue-930-one-statement-fold
git branch -f main origin/main
```

- [x] **Step 1:** Four commits confirmed ahead — three for the spec, one for this
      plan.
- [x] **Step 2:** Branch created at HEAD, `main` reset to `origin/main`
      (`279dd1ac`).
- [x] **Step 3:** Verified with `git status -sb` and `git log --oneline -1 main`.

Every later task commits on this branch. Nothing lands on `main` except through
the pull request in Task 5.

---

## Task 1: The helper

**Files:**
- Modify: `games/events/projection.py`
- Test: `tests/test_event_projectors.py`

**Interfaces produced:**

```python
class Projector(ABC):
    def project[M: ProjectionModel](
        self, model: type[M], identity: uuid.UUID, **columns: Any
    ) -> None: ...
```

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to
      `tests/test_event_projectors.py`, after the `TargetedWriter` block that
      ends at line 377. `Device` stands in for a projection table exactly as
      `TargetedWriter` does, and needs the same `# type: ignore[type-var]`.

```python
project_registry = ProjectorRegistry()


class ProjectingWriter(Projector, registry=project_registry):
    """Writes its whole row through the helper."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        #: Device stands in for a projection table.
        self.project(  # type: ignore[type-var]
            Device,
            event.aggregate_id,
            library_id=event.library_id,
            name=f"projected {event.sequence}",
            type=Device.UNKNOWN,
        )

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


@pytest.mark.django_db
def test_the_helper_writes_through_the_target_its_family_holds(owned_library):
    target = RecordingTarget()

    project_registry.for_target(target).apply(make_event(library_id=owned_library.pk))

    assert target.asked == ["Device"]
    assert Device.objects.filter(name="projected 1").count() == 1


@pytest.mark.django_db
def test_the_helper_writes_one_row_through_one_statement(owned_library):
    """The five statements #930 removes were a lock-and-look."""
    with CaptureQueriesContext(connection) as queries:
        project_registry.apply(make_event(library_id=owned_library.pk))

    assert len(queries) == 1
    assert queries[0]["sql"].startswith("INSERT INTO")
    assert "ON CONFLICT" in queries[0]["sql"]


@pytest.mark.django_db
def test_the_helper_rewrites_the_row_an_identity_already_has(owned_library):
    """A re-fold is an upsert, not a second row."""
    identity = uuid.uuid7()

    for sequence in (1, 2):
        project_registry.apply(
            make_event(
                library_id=owned_library.pk,
                aggregate_id=identity,
                sequence=sequence,
            )
        )

    assert Device.objects.count() == 1
    assert Device.objects.get(pk=identity).name == "projected 2"


@pytest.mark.django_db
def test_the_helper_keeps_the_columns_it_was_not_given(owned_library):
    """DO UPDATE writes the named columns and no others."""
    identity = uuid.uuid7()
    project_registry.apply(
        make_event(library_id=owned_library.pk, aggregate_id=identity)
    )
    created_at = Device.objects.get(pk=identity).created_at

    project_registry.apply(
        make_event(library_id=owned_library.pk, aggregate_id=identity, sequence=2)
    )

    assert Device.objects.get(pk=identity).created_at == created_at
```

- [ ] **Step 2: Run them and watch them fail**

```
make test ARGS="tests/test_event_projectors.py -k helper -x" PYTEST_WORKERS=0
```

Expected: collection succeeds and every one fails with
`AttributeError: 'ProjectingWriter' object has no attribute 'project'`.

- [ ] **Step 3: Add the method.** In `games/events/projection.py`, add `import
      uuid` to the standard-library imports, add `TYPE_CHECKING` to the `typing`
      import, and add the guarded model import below the existing imports:

```python
if TYPE_CHECKING:
    from games.models import ProjectionModel
```

Then add the method to `Projector`, directly under `__init__`:

```python
    def project[M: ProjectionModel](
        self, model: type[M], identity: uuid.UUID, **columns: Any
    ) -> None:
        """Write one whole row, keyed on the event's identity.

        One statement: `INSERT ... ON CONFLICT (pk) DO UPDATE`. A re-fold
        rewrites the row rather than reading for it first, so idempotency
        costs the key's index rather than a `SELECT ... FOR UPDATE` and two
        savepoints on every event.

        Pass every column of the row except the key and any generated column.
        `DO UPDATE` writes only the columns it names, so a partial call is
        right against a row that exists and inserts nulls and defaults against
        one that does not.
        """
        #: Never the imported model: a rebuild redirects.
        projected = self.target.model(model)
        row = projected(**columns)
        row.pk = identity
        projected.objects.bulk_create(
            [row],
            update_conflicts=True,
            update_fields=list(columns),
            unique_fields=["pk"],
        )
```

- [ ] **Step 4: Run them and watch them pass**

```
make test ARGS="tests/test_event_projectors.py -k helper -x" PYTEST_WORKERS=0
```

- [ ] **Step 5: Run the module and the type checker**

```
make test ARGS="tests/test_event_projectors.py"
make typecheck
make lint
```

- [ ] **Step 6: Commit**

```bash
git add games/events/projection.py tests/test_event_projectors.py
git commit -m "Give a family one statement to write a row with"
```

**Gotchas:**

- `CaptureQueriesContext` and `connection` are already imported at the top of
  `tests/test_event_projectors.py`. `uuid`, `pytest`, `Device`, `RecordedEvent`,
  `ClassVar`, and `HandlerMap` are too. Add no imports.
- Plain `@pytest.mark.django_db` is right here. `transaction=True` is needed only
  by tests that call `dispatch`, because `run_in_transaction` refuses to nest.
- **One statement means one.** `bulk_create` opens `atomic(savepoint=False)`, so
  it emits no `SAVEPOINT` inside pytest-django's wrapping transaction. If the
  count is 3, someone wrapped the write in a nested `atomic()` with savepoints.
- `unique_fields=["pk"]`, not `["id"]`. Django maps `pk` to the model's primary
  key, so a projection whose key has another name needs no exception.
- `Model(pk=...)` is not a valid constructor argument. The identity goes on the
  instance after construction.

---

## Task 2: The family, and the numbers that name it

**Files:**
- Modify: `games/projectors/playergame.py`
- Modify: `games/events/benchmark.py:93-105` (the `StatementCounter` docstring)
- Test: `tests/test_playergame_projection.py`
- Test: `tests/test_event_benchmark.py:341-359`

**Interfaces consumed:** `Projector.project` from Task 1.

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to
      `tests/test_playergame_projection.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_folding_the_creation_event_costs_one_statement(
    owned_user, owned_library, tracked_game
):
    """The number #930 exists to reduce, at its source."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    event = RecordedEvent.from_row(LibraryEvent.objects.get(aggregate_id=identity))
    #: Measure the insert, which is what a replay folds.
    PlayerGame.objects.all().delete()

    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        DEFAULT_REGISTRY.apply(event)

    assert [query["sql"].split(maxsplit=1)[0] for query in queries] == ["INSERT"]
    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_second_identity_for_a_tracked_game_is_refused(
    owned_user, owned_library, tracked_game
):
    """The upsert keys on the identity, so the pair still collides.

    An `IntegrityError` fallback to an update by primary key would have found
    no row, changed nothing, and folded the event into silence.
    """
    append_created(owned_library, owned_user, tracked_game, identity=uuid.uuid7())

    with pytest.raises(IntegrityError):
        append_created(
            owned_library,
            owned_user,
            tracked_game,
            identity=uuid.uuid7(),
            key="again",
        )

    assert PlayerGame.objects.count() == 1
```

Add to that file's imports: `from django.db import connection`, `from
django.test.utils import CaptureQueriesContext`, `from games.events.envelope
import RecordedEvent`, `from games.events.projection import DEFAULT_REGISTRY`,
and `LibraryEvent` to the `games.models` import. `IntegrityError`,
`transaction`, and `uuid` are already imported.

- [ ] **Step 2: Run them**

```
make test ARGS="tests/test_playergame_projection.py -x" PYTEST_WORKERS=0
```

Expected: `test_folding_the_creation_event_costs_one_statement` fails with a
six-element list beginning `SAVEPOINT` — the expansion this work removes. The
refusal test passes already: it records behaviour that must survive the change,
so a green result there is the point of writing it now.

- [ ] **Step 3: Switch the family.** `games/projectors/playergame.py`, whole
      handler:

```python
    def _created(self, event: RecordedEvent) -> None:
        self.project(
            PlayerGame,
            event.aggregate_id,
            #: From the event, never a command's context.
            library_id=event.library_id,
            game_id=uuid.UUID(event.payload["game"]["id"]),
            tracked_at=event.recorded_at,
        )
```

The `#: Never the imported model: a rebuild redirects.` comment moves into
`project()` in Task 1; do not leave a copy here.

- [ ] **Step 4: Run them again**

```
make test ARGS="tests/test_playergame_projection.py" PYTEST_WORKERS=0
```

Expected: all green, including the two rebuild-parity tests already in the file.

- [ ] **Step 5: Move the slope test.** In `tests/test_event_benchmark.py`, rename
      `test_folding_one_event_costs_six_statements` and rewrite its docstring and
      its assertion:

```python
@pytest.mark.django_db
def test_folding_one_event_costs_one_statement(django_user_model):
    """The fold is an upsert: no lock, no look, no savepoint.

    A rebuild also pays a fixed cost -- the temp tables, the reference
    anti-joins, the diff, the swap, the drop -- measured at 17 statements.
    The average at ten events is therefore 2.7, not 1. The slope between two
    sizes is the per-event number, and it is exact.
    """
    totals: dict[int, int] = {}
    for events in (10, 30):
        user = django_user_model.objects.create_user(username=f"fold-{events}")
        seed_library(user.library, actor=user, events=events, spares=0)
        _report, fold = run_rebuild_scenario(
            user.library, mode=RebuildMode.REBUILD, count_fold=True
        )
        assert fold is not None
        totals[events] = fold.statements
    assert (totals[30] - totals[10]) / 20 == pytest.approx(1.0, abs=0.01)
```

- [ ] **Step 6: Correct the counter's docstring.** `games/events/benchmark.py`,
      inside `StatementCounter`, replace the sentence beginning "The total
      matters as much as the per-table breakdown, because four of the fold's six
      statements are savepoints and name no table at all." with:

```
    Counting statements rather than diffing COUNT(*) is what makes an update
    visible: a family that rewrites one row an event amplifies by one, and a
    before-and-after count reports zero. The total matters as much as the
    per-table breakdown, because a statement that names no table -- a
    savepoint, a lock, a transaction control -- is absent from the breakdown
    and present in the cost.
```

- [ ] **Step 7: Run the benchmark tests**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

Expected: all green. `test_the_fold_counts_the_shadow_table_as_its_projection`
still asserts 10 statements for 10 events and needs no change — one statement per
event was always one *write* per event.

- [ ] **Step 8: Run the whole event suite and the checkers**

```
make test ARGS="tests/test_event_projectors.py tests/test_event_benchmark.py tests/test_playergame_projection.py tests/test_projection_rebuild.py tests/test_event_replay.py tests/test_playergame_command.py"
make typecheck
make lint
```

- [ ] **Step 9: Commit**

```bash
git add games/projectors/playergame.py games/events/benchmark.py \
        tests/test_playergame_projection.py tests/test_event_benchmark.py
git commit -m "Fold a tracked game in one statement"
```

**Gotchas:**

- `append_created` in `tests/test_playergame_projection.py` already opens
  `transaction.atomic()` and takes a `key=` for the idempotency record. Two
  appends in one test need two different keys or the second is deduplicated
  rather than folded.
- The refusal test asserts on `IntegrityError`, not on a retry. `is_retryable`
  answers a unique violation with the constraint name and retries only
  `LIBRARY_EVENT_SEQUENCE_CONSTRAINT`, so this one fails on its first attempt.
- Do **not** relax `test_one_dispatch_writes_one_projection_row_through_one_statement`.
  It asserts one row through one statement today and after: the counter
  attributes a statement to a table only when it writes, and the five removed
  statements write nothing.

---

## Task 3: Re-record the benchmark

**Files:**
- Modify: `docs/event-benchmarks.md`

**Steps:**

- [ ] **Step 1: Confirm the machine.** The document's machine block describes the
      box the numbers belong to. Run
      `make bench ARGS="--seed 2000 --iterations 25"` (about 4 seconds) and check
      the environment line it prints against the block. If they differ, stop:
      re-recording on another machine invalidates every number in the file, and
      that is a decision for Lukáš, not a step.

- [ ] **Step 2: Take the gated run** (about 3 minutes, plus teardown)

```
make bench ARGS="--gate"
```

Keep the whole output. It replaces the recorded-run block verbatim.

- [ ] **Step 3: Take the uninstrumented run**

```
make bench ARGS="--gate --no-count-fold"
```

- [ ] **Step 4: Rewrite the document** with what the two runs printed:
      - the recorded-run block, verbatim, with its date;
      - the rebuild verdict section, which currently reads "Passed, by 23
        milliseconds in 60 seconds" and names #930 as "the standing lead on the
        cheaper fold". Say what the lead produced, in the same register: the
        measured margin, and whether one family now leaves room for a second;
      - the cost-per-event table: "Statements per folded event" 6.00 → the
        measured slope, "Statements per command" 14 → the measured total, and
        the sentence deriving `6 × events + 13` → the measured slope and
        intercept;
      - the parity section stays as it is if the diff is still empty. If it is
        not, the run failed and this task stops.

- [ ] **Step 5: Verify no stale six survives**

```
grep -rn "six\|6\.0\|14 statement" docs/event-benchmarks.md
```

Every hit must be either a re-measured number or absent.

- [ ] **Step 6: Commit**

```bash
git add docs/event-benchmarks.md
git commit -m "Record what one statement an event costs"
```

**Gotchas:**

- `make bench` creates and removes a scratch user and about 400,000 rows. It is
  not part of `make check` and must not become part of it.
- The seed rate and the teardown time move between runs and carry no budget.
  Paste them as measured; do not tune the prose to match the old ones.

---

## Task 4: Cost a batched replay

**Files:**
- Modify: `docs/event-benchmarks.md`

The spec commits to a measured ceiling rather than an estimate, and to naming
`ProjectionTarget` as the seam a batched replay would use.

**Steps:**

- [ ] **Step 1: Measure the floor.** A chunked insert of the same row count into
      the same table, with no events and no fold, is what a perfectly batched
      replay could not beat. Create `tests/test_zz_costing_930.py`, run it, keep
      the output, and **delete the file** — it is a measurement, not a test.

```python
"""Throwaway costing for #930. Delete after reading."""

import uuid
from time import monotonic

import pytest
from django.utils import timezone

from games.events.rebuild import shadow_tables
from games.events.targets import ShadowTarget
from games.models import PlayerGame

ROWS = 100_410
CHUNK = 500


@pytest.mark.django_db(transaction=True)
def test_costing(owned_library):
    tracked_at = timezone.now()
    twin = ShadowTarget().model(PlayerGame)
    #: LIKE copies the unique index, so each game differs.
    #: It copies no foreign key, so no catalog row is needed.
    rows = [
        twin(
            id=uuid.uuid7(),
            library_id=owned_library.pk,
            game_id=uuid.uuid7(),
            tracked_at=tracked_at,
        )
        for _ in range(ROWS)
    ]

    with shadow_tables([PlayerGame]):
        started = monotonic()
        twin.objects.bulk_create(rows, batch_size=CHUNK)
        print(f"\nCHUNKED FLOOR: {monotonic() - started:.2f}s for {ROWS} rows")
```

Run it with `make test ARGS="tests/test_zz_costing_930.py -s" PYTEST_WORKERS=0`.
Building the list is itself Python time and is outside the timed block on
purpose: the floor being measured is the database's, not the list comprehension's.

- [ ] **Step 2: Delete the measurement file**

```bash
rm tests/test_zz_costing_930.py
```

- [ ] **Step 3: Write the costing section** into `docs/event-benchmarks.md`,
      after the cost-per-event table. It says four things and nothing else:
      - the replay time now, from Task 3;
      - the chunked floor from Step 1, and that the gap between them is per-event
        Python — `RecordedEvent.from_row`, the registry dispatch, one SQL
        compilation per `bulk_create` — plus one round trip an event;
      - that batching does not need handlers to return rows: `ProjectionTarget`
        already owns where a family writes, so a buffering target leaves every
        handler as written;
      - the two conditions that bound it — the journal and statistics families
        read current-state rows written earlier in the same transaction, so such
        a target flushes before a read, and phase 3's diff reads the shadow
        tables, so the last flush precedes it.

If Task 3 measured a rebuild that still consumes most of the 60 seconds, this
section stops being a supporting note and becomes the result. Say so in it, in
those terms: five statements an event went away and the headroom the second
family needs did not arrive. The work still lands; the follow-up opens now
rather than later, with the measurement that argues for it.

- [ ] **Step 4: Draft the follow-up issue body** in the PR description, not in a
      file. **Ask Lukáš before running `gh issue create`** — opening an issue is
      outward-facing and is his call. The body carries the two measurements and
      the seam, so the issue opens with evidence rather than "the largest win".

- [ ] **Step 5: Commit**

```bash
git add docs/event-benchmarks.md
git commit -m "Cost the replay a batch would buy"
```

---

## Task 5: The gate, and the pull request

**Files:** none.

- [ ] **Step 1: Confirm nothing throwaway survives**

```bash
git status --porcelain          # expect: empty
ls tests/test_zz_*              # expect: no such file
```

- [ ] **Step 2: Run the full gate.** Not `check-fast`; the whole thing, `e2e/`
      included. About 6.5 minutes.

```
make check
```

- [ ] **Step 3: Push and open the pull request**

```bash
git push -u origin claude/issue-930-one-statement-fold
```

The description carries: the statement count before and after, the two
re-recorded rebuild numbers, the correctness argument against the
`IntegrityError` fallback, and the follow-up issue body from Task 4, Step 4.
Close with `Closes #930`.

---

## Task 6: The docs sweep

Expect Lukáš to ask for this after the branch is green. It has three parts, and
it is documentation only — **do not run a full `make check` for it**.

- [ ] **Step 1:** Delete this plan document. The spec stays.

```bash
git rm docs/superpowers/plans/2026-08-26-issue-930-one-statement-fold.md
```

- [ ] **Step 2:** Rewrite
      `docs/superpowers/specs/2026-08-26-issue-930-one-statement-fold-design.md`
      timeless, 200–500 words, in ASD-STE100: short declarative sentences, one
      idea per sentence, no narrative of the work and no options that were not
      taken. `docs/event-references.md` is the register to match.

- [ ] **Step 3:** Trim every comment and docstring this branch added to seven
      words. `project()`'s docstring is the one to plead for: the whole-row rule
      prevents a quiet null, and a plausible edit removes it. Plead it at the
      end, with the seven-word summary kept as its first line.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "Sweep the docs after the cheaper fold"
```

---

## Definition of done

- The fold executes one statement an event, asserted by a named test at the
  helper, at the family, and at the benchmark's slope.
- A re-fold still writes one row; a second identity for a tracked game is still
  refused.
- `make check` is green, `e2e/` included.
- `docs/event-benchmarks.md` records a real run of the changed code, and costs
  what a batched replay would add.
- The 60-second rebuild budget is where it was. Changing it was never in scope.
