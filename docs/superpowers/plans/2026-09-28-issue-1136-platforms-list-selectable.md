# Platforms list selectable (#1136) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bulk Remove on the Platforms list with a working batch Undo, a row ⋯ menu (Edit, Remove), and no Actions column.

**Architecture:** Platform stays conventional. The removal stamp names its batch (`removed_in_batch`). `BulkAction` states where its Undo reads rows: from events (every existing act) or from that stamp (`platform.remove`).

**Tech Stack:** Django 6, PostgreSQL 18, pytest + Playwright, the bulk runner in `games/bulk_actions.py` / `games/views/bulk.py`.

**Spec:** [2026-09-28-issue-1136-platforms-list-selectable-design.md](../specs/2026-09-28-issue-1136-platforms-list-selectable-design.md)

## Global Constraints

- Drive everything through `make`; wrap pytest targets in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Iterate with `make test ARGS="tests/<file> -x"` / `make check-fast`; the gate is full `make check`, run once at the end.
- `make format`, `make lint-fix` (import order), `make vale` before each commit.
- Complete words in identifiers; name compound and primitive-role types; comments 7 words, no issue refs.
- Nothing destroys a row: `remove()`/`restore()` only.
- Bulk tests that POST through the runner need `@pytest.mark.django_db(transaction=True)`.
- Step 0: `git fetch && git rebase origin/main`.

---

### Task 1: The column and `remove(batch=)`

**Files:**
- Modify: `games/models.py` (`Platform`: `removed_in_batch = models.UUIDField(null=True, blank=True, default=None, editable=False)`)
- Create: `games/migrations/0017_platform_removed_in_batch.py` (`make makemigrations ARGS="games --name platform_removed_in_batch"`)
- Modify: `games/removal.py`
- Test: `tests/test_removal.py` (or the file that already tests `remove`/`restore`; grep first)

**Interfaces:**
- Produces: `remove(instance: Model, *, batch: uuid.UUID | None = None) -> None`; `restore(instance)` unchanged; `BATCH_COLUMN = "removed_in_batch"` in `games/removal.py`; `names_its_batch(model: type[Model]) -> bool`.

`_stamp` gains a `columns` mapping written in the same `rows.update(...)`. `remove` passes `{BATCH_COLUMN: batch}` whenever the model has the column (NULL outside a batch), and raises `TypeError` when `batch is not None` and the model lacks it. `restore` writes no batch column.

Tests:
- remove with a batch writes both columns; a later `remove(row)` without one writes NULL;
- `restore` keeps the column;
- `remove(game, batch=...)` raises `TypeError`;
- the platform's external references still leave and come back (`_AFTER_STAMP` still runs).

- [ ] Failing tests → implement → `make test ARGS="tests/test_removal.py -x"` → commit `feat: a platform's removal names its batch (#1136)`.

### Task 2: `undo_rows` on `BulkAction`

**Files:**
- Modify: `games/bulk_actions.py`, `games/views/bulk.py` (`_act_of`, `undo_bulk_action` at ~:858)
- Modify (mechanical, `inverse_aggregate=…, inverse_model=…` → `undo_rows=EventRows(…, …)`): `games/bulk_removal.py` ×5, `bulk_edit.py`, `bulk_game_edit.py`, `bulk_reclassification.py`, `bulk_finish.py`, `bulk_playthrough_acts.py` ×2
- Modify tests: `tests/test_bulk_actions.py` (:102–192, :446, :640–666; rewrite `test_every_act_names_the_model_its_inverse_reads`), `test_bulk_runner.py:1152`, `test_bulk_removal.py:464`, `test_bulk_game_removal.py:172`, `test_bulk_device_removal.py:50`

**Interfaces:**
- Produces, in `games/bulk_actions.py`:

```python
@dataclass(frozen=True, slots=True)
class EventRows:
    aggregate: AggregateType
    model: type[Model]

    def rows(
        self, library: UserLibrary, batch: uuid.UUID
    ) -> list[uuid.UUID]: ...  # batch_aggregate_ids


@dataclass(frozen=True, slots=True)
class StampedRows:
    model: type[Model]

    def rows(self, library: UserLibrary, batch: uuid.UUID) -> list[uuid.UUID]: ...

    # model.objects.filter(library=library, removed_in_batch=batch).order_by("pk")


type UndoRows = EventRows | StampedRows
```

- `BulkAction.undo_rows: UndoRows` replaces both fields. `__post_init__` runs today's two checks on `EventRows`, and refuses a `StampedRows` whose model fails `names_its_batch`.
- `_act_of(library, batch)`: events first, as today. With no events, it takes the first `StampedRows` act in `BULK_ACTIONS` whose `rows(...)` is non-empty, and raises `Http404("No such batch.")` otherwise.
- `undo_bulk_action` reads `declared.undo_rows.rows(user.library, correlation_id)`.

Gotcha: `games/reads/events.py` must not import `bulk_actions` (cycle). `EventRows.rows` imports `batch_aggregate_ids` at module top in `bulk_actions.py`, which already imports from `games.events`.

Tests (in `tests/test_bulk_actions.py`):
- an `EventRows` with an aggregate no event speaks about is refused, and so is a model/aggregate mismatch (both existing tests, re-spelled);
- a `StampedRows(Game)` is refused;
- `_act_of` finds a stamped act: declare a throwaway act only in the test, or rely on Task 4's act by writing this test there;
- `_act_of` answers 404 for an unknown batch.

- [ ] Rewrite tests → implement → `make test ARGS="tests/test_bulk_actions.py tests/test_bulk_runner.py -x"` → `make check-fast` (every bulk suite still green) → commit `refactor: an act states where its Undo reads rows (#1136)`.

### Task 3: Platform writes and the restore refusal

**Files:**
- Create: `games/writes/platform.py`
- Modify: `games/views/platform.py` (`restore_platform` uses `restore_platform_by_hand`)
- Test: `tests/test_platform_writes.py`

**Interfaces:**
- Produces:

```python
PLATFORM_TAKEN: str  # "{name} cannot come back: another platform named {name} is in your library now. Rename or remove that one first."
def remove_platform_in_batch(platform: Platform, *, batch: uuid.UUID) -> RowOutcome
def restore_platform_from_batch(platform: Platform, *, batch: uuid.UUID) -> RowOutcome
def restore_platform_by_hand(platform: Platform) -> None  # raises CommandFailed(…, CONFLICT_STATUS)
```

Each function runs `transaction.atomic()` (a savepoint when nested), re-reads the row with `select_for_update()`, and decides:
- remove: live with `removed_in_batch == batch` → `UNCHANGED`; live → `remove(row, batch=batch)`, `MOVED`; removed → `UNCHANGED`;
- restore from batch: live → `UNCHANGED`; removed with another batch → `UNCHANGED`; removed with this batch → collision check, then `restore(row)`, `MOVED`.

The collision check: a live `Platform` other than this one, whose `Lower(Trim(name))`/`Lower(Trim(group))` equal this row's (`name_key` in `games/models.py`), and whose library is either this row's library or NULL. Wrap `restore(row)` in `except IntegrityError` → the same `CommandFailed`. The runner catches `CommandFailed` per row (`games/views/bulk.py` ~:529), so neither case ends the batch.

`RowOutcome` imports from `games.bulk_actions`. If that closes an import cycle, return a bool and convert in Task 4's wrappers.

Tests:
- each state-table row above;
- a collision with a private platform and with a shared one;
- an `IntegrityError` is answered 409 (patch `restore` to raise one);
- external references come back;
- the per-row route: a collision answers the refusal on the page, not a 500 (POST to `games:restore_platform`, assert 302 + error message).

- [ ] Failing tests → implement → `make test ARGS="tests/test_platform_writes.py -x"` → commit `feat: platform writes a batch can undo (#1136)`.

### Task 4: The act, its preview, and the one-row counts

**Files:**
- Create: `games/reads/platform_departures.py`
- Modify: `games/bulk_removal.py` (the Platforms section beside Devices), `games/views/platform.py` (`remove_platform` details)
- Test: `tests/test_bulk_platform_removal.py` (model on `tests/test_bulk_device_removal.py`: `bulk_posts.act_url/posted/selection`)

**Interfaces:**
- Consumes: Task 2 `StampedRows`, Task 3 writes.
- Produces:

```python
# games/reads/platform_departures.py
class PlatformDepartures(NamedTuple): games: int; releases: int; purchases: int
def with_departures(platforms: QuerySet[Platform], library: UserLibrary) -> QuerySet[Platform]
def departures_of(platform: Platform) -> PlatformDepartures
# games/bulk_removal.py
PLATFORM_GONE = "One of the platforms is no longer available, so it was left as it is."
REMOVE_PLATFORM: BulkAction[Platform]
```

Counts use `counted()` from `games/reads/game_departures.py`:
- games: `Game.objects.for_library(library).filter(platform=OuterRef("pk"))`;
- releases: `Release.objects.for_library(library).filter(platform=OuterRef("pk"))` (`related_name="+"`, so go through the manager);
- purchases: `Purchase.objects.for_library(library).filter(platform=OuterRef("pk"))`.

Scope: `narrowed(Platform.objects.for_library(library), library, filter_json, parse_platform_filter)`. Resolve: the device pattern, ordered `("name", "id")`, with `lost(..., PLATFORM_GONE)`. The run/inverse wrappers take `choice`/`undoes`/`idempotency_key`/`correlation_id` keyword-only (the `__post_init__` check); `idempotency_key` is unused, because the stamp is the record. The inverse reads the row through `_removed_row(Platform.objects.all(), actor, key, "platform")`.

Preview: Platform, Group, Games, Releases, Purchases, the counts aligned right. The per-row `remove_platform` details read `departures_of` over `with_departures(...)`, so both pages print the same numbers.

Tests:
- the act is declared, with `StampedRows(Platform)`;
- scope excludes shared and removed rows;
- a missing key is lost with `PLATFORM_GONE`;
- the preview counts skip removed games, releases and purchases;
- end to end: POST remove of two rows, then POST the Undo, and both are live;
- a chunk posted twice gives lost;
- a chunk re-posted after a hand restore leaves the row live;
- the Undo after a hand restore counts "already so";
- a later per-row remove takes the row off the earlier Undo;
- `_act_of` finds `platform.remove`, and answers 404 when every row names a later batch.

- [ ] Failing tests → implement → `make test ARGS="tests/test_bulk_platform_removal.py -x"` → commit `feat: remove platforms in bulk (#1136)`.

### Task 5: Row menu, the view, e2e, render-pages

**Files:**
- Create: `games/views/platform_menu.py`, `e2e/test_bulk_platform_removal_e2e.py`
- Modify: `games/views/platform.py` (`PLATFORM_COLUMNS` loses Actions; `list_platforms` as `list_devices` at `games/views/device.py:95-126`)
- Test: `tests/test_platform_views.py` if present, else the menu tests go into `tests/test_bulk_platform_removal.py`

**Interfaces:**
- Produces: `platform_row_menu(platform: Platform, origin: OriginUrl | None) -> Node`, the copy of `device_row_menu` with label `f"{name} ({group}) actions"`, or `f"{name} actions"` when the group is blank, and `id=f"platform-menu-{pk}"`.

View: materialise `page_platforms = list(platforms)`. Rows are `make_row(*cells, key=str(platform.pk), menu=platform_row_menu(platform, origin))`. Add `"menu_slot": True`, and `"selection": {"filter": filter_json, "csrf_token": get_token(request), "actions": tray_actions(REMOVE_PLATFORM.name, origin=origin)}`. Drop `ButtonGroup` and any other import left unused.

Before editing, save the "before" pages from the rebased `main` checkout:
`make render-pages ARGS="--user <dev user> --out .cache/render-before"`. After Task 5, run it again into `.cache/render-after` and `diff -r`. Every differing file should come from the Platforms list; attribute them in the PR body.

e2e: copy the device test. Two private platforms, select both, Remove, heading "Remove 2 platforms", confirm, empty table, press Undo on the toast, two rows back.

Tests:
- the menu label, with and without a group;
- the Platforms page renders no "Actions" header and carries `data-selection` markup (`tests/test_rendered_pages.py` style);
- `tests/test_column_priority_contract.py` still passes (the table leaves it, as the Devices table did).

- [ ] Failing tests → implement → `make test ARGS="tests/test_bulk_platform_removal.py tests/test_rendered_pages.py -x"` → `make test-e2e ARGS="-k platform"` → commit `feat: the Platforms list is selectable (#1136)`.

### Task 6: Docs and the gate

**Files:**
- Modify: `CLAUDE.md` (bulk-runner paragraph: one sentence after #1135's naming `platform.remove`, `StampedRows`, `removed_in_batch`, contract link), `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md` (cross-wave handoff: Platforms delivered), the `REMOVABLE_MODELS` paragraph if it describes the stamp columns.

- [ ] `make vale`, `make format`, `make lint-fix`, then the full `flock … make check` once, reading its exit code rather than grepping → commit `docs: #1136 in CLAUDE.md and the wave doc`.
- [ ] Docs sweep before the PR: delete this plan and trim the spec to its timeless form.

## Gotchas

- The runner looks keys up again for every chunk through `Platform.objects.for_library`, which calls `.alive()`. So a replayed forward chunk never reaches the write with a removed row.
- `Platform.save()` calls `clean()`; the writes never save, only `remove()`/`restore()`, which use `update()`.
- `_act_of` loops over `BULK_ACTIONS`; the table is filled at import through the tail of `games/bulk_actions.py`.
- Never run e2e while `make dev` is up.
