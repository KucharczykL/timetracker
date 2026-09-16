# Projection library scope implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Both projector write helpers take the event and write only rows the event's library owns: `amend` filters on `(pk, library_id)`, `project` upserts on the `(id, library)` pair every projection table now carries.

**Spec:** `docs/superpowers/specs/2026-09-16-issue-1058-projection-library-scope-design.md` — read it first; every "why" lives there.

## Global constraints

- Run everything through `make`. Iterate with `make check-fast`; the gate is the full `make check`.
- Focused runs: `make test ARGS="tests/test_event_projectors.py -x"`.
- Python 3.14 only; `except A, B:` is PEP 758.
- Comments explain intent, never history; no issue or PR numbers in code comments.
- Rebase onto `origin/main` before the first edit.
- Ask the user inline vs subagents before starting; recommend inline, three tasks and one gate.

---

### Task 1: The pair constraint, its migration and its check

**Files:**
- Modify: `games/models.py` — `library_identity_constraint()` beside `ProjectionModel`; four concrete `Meta.constraints` (`PlayerGame` ~1425, `Playthrough` ~1590 has `indexes` only so gains `constraints`, `PlayerSession` ~1737, `LibraryCalendar` ~1853)
- Create: `games/migrations/0008_projection_library_identity.py` via `make makemigrations ARGS="games --name projection_library_identity"` (four `AddConstraint`)
- Modify: `games/checks.py` — `games.E012` in `_check_one`
- Modify: `tests/test_projection_model.py` — every synthetic projection gains `constraints = (library_identity_constraint(),)`; `test_an_event_derived_projection_passes` keeps `== []`
- Test: `tests/test_projection_model.py`

**Interfaces produced:**
- `library_identity_constraint() -> models.UniqueConstraint` — fields `("id", "library")`, name `unique_%(app_label)s_%(class)s_library_identity`. A fresh object per call: Django clones per model, but a shared instance across `Meta` tuples is a trap nobody needs.
- `games.E012` — "A projection model carries no unique constraint over its primary key and library." Hint names the builder. Detect by walking `model._meta.constraints` for a `UniqueConstraint` whose `fields` equal `(pk.name, "library")` in either order.

**Tests to write first:**
- `test_a_projection_without_the_library_pair_is_refused` → `["games.E012"]`
- `test_the_pair_may_name_the_key_by_its_own_name` — pk named `key`, pair `("key", "library")` → `[]`
- `test_a_check_constraint_is_not_the_pair` — `LibraryCalendar`'s shape without the pair → `["games.E012"]`
- Existing exact-list assertions unchanged after the synthetic models gain the pair.

- [ ] Write the tests, watch them fail
- [ ] Builder, four `Meta` edits, check
- [ ] `make makemigrations …`; read the file: exactly four `AddConstraint`, names `unique_games_<model>_library_identity`
- [ ] `make migrate`, `make check-fast`

**Gotchas:**
- `%(class)s` is interpolated only on concrete models (`options.py` `_format_names`), so the name in the migration is the lowercase class name.
- `LibraryCalendar` keeps its CHECK; the pair sits beside it.
- Synthetic projections in `tests/test_projection_targets.py`, `tests/test_projection_references.py`, `tests/test_playthrough_command.py` are never handed to `check_projection_models`, so they need nothing — unless Task 2's harness lands there.

---

### Task 2: The helpers take the event

**Files:**
- Modify: `games/events/projection.py` — `project`, `amend`, `ProjectionRowMissing` docstring
- Modify: `tests/test_event_projectors.py` — replace the `Device` stand-in with a synthetic projection
- Test: `tests/test_event_projectors.py`

**Interfaces produced:**
- `Projector.project[M](model: type[M], event: RecordedEvent, **columns) -> None`
  - `TypeError` if `columns` names `library` or `library_id` (message: the helper writes it from the event)
  - merges `library_id=event.library_id` before `_unfilled_columns`
  - `row.pk = event.aggregate_id`; `bulk_create(update_conflicts=True, update_fields=<handler's columns>, unique_fields=[projected._meta.pk.name, "library"])`
- `Projector.amend[M](model: type[M], event: RecordedEvent, **columns) -> None`
  - `filter(pk=event.aggregate_id, library_id=event.library_id).update(**columns)`
  - on `changed != 1`: `filter(pk=…).values_list("library_id", flat=True).first()`; `None` → today's message; a value → message naming row, event library, holding library, "the stream is wrong, not the row"
- `ProjectionRowMissing` unchanged in type and in `NOT_ANSWERED`

**The harness:** one module-level synthetic `ProjectionModel` under `isolate_apps("games")` is awkward at module scope; follow `tests/test_projection_rebuild.py` — define the model inside a fixture or a helper that calls `create_tables(...)` inside the test's transaction, with `constraints = (library_identity_constraint(),)`, two columns (`name`, `type`-like default) so the existing `PartialWriter`/`ProjectingWriter`/`AmendingWriter` cases port one-to-one. `RecordingTarget.asked` assertions change from `"Device"` to the new model name.

**Tests to write first (beside the ported ones):**
- `test_the_helper_writes_the_events_library` — no `library_id` in the call; row carries `event.library_id`
- `test_the_helper_refuses_a_library_it_is_handed` — `library_id=` in columns → `TypeError`
- `test_the_helper_still_writes_one_statement` — one `INSERT`; SQL contains `ON CONFLICT ("id", "library_id")`
- `test_a_creation_under_another_librarys_identity_is_refused` — row in `second_library`, event in `owned_library` with that id → `IntegrityError`, `sqlstate_of(error) == "23505"`, row unchanged (use `transaction.atomic()` around the call)
- `test_an_amendment_in_another_library_is_refused` — same shape → `ProjectionRowMissing`, message holds both library ids, row unchanged, two statements (`UPDATE`, `SELECT`)
- `test_an_amendment_with_no_row_is_refused` — keep; assert two statements now
- `test_an_amendment_costs_one_statement` — keep, happy path

- [ ] Port the harness, watch the old tests pass on the new model
- [ ] New tests, watch them fail
- [ ] Helpers
- [ ] `make test ARGS="tests/test_event_projectors.py"`

**Gotchas:**
- `bulk_create` refuses a pk in `update_fields`, not in `unique_fields`; `pk` is accepted as a name there.
- `library` is in `_required_columns` (FK, no default): merge before the check or every call raises.
- The `second_library` fixture exists (`test_the_handlers_cost_the_append_no_query` uses it).
- Do not reach for `LibraryCalendar` as the stand-in: its CHECK `id = library` refuses `make_event`'s random `aggregate_id`.

---

### Task 3: The handlers

**Files:**
- Modify: `games/projectors/playergame.py` (6 calls), `games/projectors/playthrough.py` (9), `games/projectors/playersession.py` (9), `games/projectors/calendar.py` (1)
- Test: `tests/test_playergame_projection.py`, `tests/test_playthrough_projection.py`, `tests/test_playersession_projection.py`, `tests/test_projection_replay_gate.py`, `tests/test_projection_rebuild.py` — all unchanged

Mechanical: `self.amend(Model, event.aggregate_id, …)` → `self.amend(Model, event, …)`; same for `project`, dropping the `library_id=event.library_id` line and its comment. `LibraryCalendars` keeps its hand-scoped `PlayerSession` update as is.

- [ ] Edit the four files
- [ ] `grep -rn "aggregate_id" games/projectors/` shows nothing
- [ ] `make check-fast`

---

### Task 4: Docs and the gate

- Modify: `CLAUDE.md` — the Conventions bullet "A reference out of a projection is registered" gains a sibling: a projector writes through `project`/`amend`, which take the event and scope the row to its library; `games.E012` refuses a projection without the pair. The `ProjectionModel` docstring in `games/models.py` names the pair.
- Modify: `docs/superpowers/specs/2026-08-26-issue-930-one-statement-handler-design.md` lines 10–17, 44, 57 — the arbiter is the `(id, library)` pair, `unique_fields` names `pk` and `library`.
- Modify: `docs/event-benchmarks.md` ~line 89 — `ON CONFLICT (id, library_id)`.
- Comment on #1058: the issue's "no schema change is needed" was wrong because `project` upserts on the pk with `library_id` in the update set; link the spec.
- [ ] `make vale`
- [ ] Full `make check` green, read from a log with its exit code
- [ ] Commit per task; PR body links the spec

---

## Follow-up issues to file

None. The two out-of-scope items in the spec (typed refusals for the swap's and the bare append's primary-key collision) are declined, not deferred: both paths are already loud and roll back.
