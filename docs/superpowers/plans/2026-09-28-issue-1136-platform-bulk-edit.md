# Platform bulk Edit over a batch ledger (#1136, part 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, chosen by the user). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the removal stamp with a `BatchChange` ledger, add `platform.edit` (group, icon), and share the Edit acts' common parts in `games/bulk_edit.py`.

**Architecture:** Conventional rows record `(earlier, stated)` per field per batch in one ledger; `undo_rows` becomes `EventRows(model) | LedgerRows(model)`. One inverse restores every recorded field for both platform acts. The session Edit is renamed, and the parts every Edit repeats move into `games/bulk_edit.py`.

**Spec:** [2026-09-28-issue-1136-platforms-list-selectable-design.md](../specs/2026-09-28-issue-1136-platforms-list-selectable-design.md) (sections "The ledger" through "The acts").

**State at start:** branch `claude/issue-1136-planning-993d4d`. Platform bulk Remove works over `Platform.removed_in_batch` + `StampedRows` (commits 4767b6fd..a0d1dd9a). The gate is green at a0d1dd9a.

## Global Constraints

- Drive everything through `make`. Wrap every pytest target in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`. Never run e2e while the `dev-make` preview server is up: stop it first (`preview_stop`).
- Iterate with `make test-fast ARGS="<files> -q"`. The gate is one full `make check` at the end; read its exit code, never a grep.
- Before each commit: `make format`, `make lint-fix`, `make typecheck`, `make vale`.
- Code style:
  - complete-word identifiers;
  - PEP 695 aliases for roles;
  - comments of at most 7 words, unless they plead a reason;
  - no issue references in code.
- `games/bulk_edit.py` (the shared module) must never import `games.bulk_actions` or any act module: the table's foot imports the acts (import cycle).
- Step 0: `git fetch && git rebase origin/main`.

---

### Task 1: The ledger replaces the stamp

**Files:**
- Modify `games/models.py`:
  - drop `Platform.removed_in_batch`;
  - add `BatchChange` with fields `id` (UUIDv7), `library` (FK CASCADE), `batch` (UUID), `act`, `model_label`, `row_id` (UUID), `field`, `earlier`, `stated` (JSONField, `encoder=DjangoJSONEncoder`) and `created_at`;
  - `UniqueConstraint(batch, model_label, row_id, field)`, `Index(library, batch)`.
- Replace `games/migrations/0017_platform_removed_in_batch.py` with `0017_batch_change.py`: delete the file, then `make makemigrations ARGS="games --name batch_change"` against a DB migrated back to 0016 (`make migrate ARGS="games 0016"` first).
- `games/removal.py`: drop `BATCH_COLUMN`, `names_its_batch`, `remove(batch=)` and the `columns` mapping of `_stamp`, returning both to their `origin/main` shape (`git diff origin/main -- games/removal.py` must end empty).
- Create `games/batch_ledger.py`:
  - `type FieldName = str`, `type ModelLabel = str`;
  - `record(library, *, batch, act, row, field, earlier, stated) -> None` uses `get_or_create` on the unique key;
  - `recorded(library, *, batch, row, field) -> bool`;
  - `batch_rows(library, batch, model) -> list[uuid.UUID]`, distinct and ordered by the first `created_at`;
  - `batch_act(library, batch) -> BulkActionName | None`, read from the first row;
  - `row_changes(library, batch, row) -> dict[FieldName, FactChange[object]]`, decoded per field through `FIELD_DECODERS: dict[FieldName, Callable[[object], object]]` (`removed_at` → `parse_datetime`, `group`/`icon` → `str`).
- `games/bulk_actions.py`: `StampedRows` → `LedgerRows(model)`, whose `rows()` is `batch_rows`. No `__post_init__` check beyond "model is conventional": refuse a `ProjectionModel` subclass.
- `games/views/bulk.py`: `_stamped_act_of` becomes `_ledger_act_of`: `batch_act` → `bulk_action(name)`. `None` from the name → the existing `UNKNOWN_ACT` path, so `_act_of` returns `BulkAction | None` in both branches. No row at all → `logger.warning` + 404.
- Tests:
  - rework `tests/test_removal.py`: delete the four batch tests;
  - `tests/test_reference_removal.py`: delete the batch test;
  - `tests/test_bulk_actions.py`: the stamp test becomes "`LedgerRows` over a projection is refused";
  - new `tests/test_batch_ledger.py`: record is idempotent, the row order, `batch_act`, a datetime round trip, and another library reads nothing.

- [ ] Tests → implement → `make test-fast ARGS="tests/test_batch_ledger.py tests/test_removal.py tests/test_bulk_actions.py -q"` → commit `refactor: a batch ledger replaces the removal stamp (#1136)`.

### Task 2: Platform writes over the ledger

**Files:** `games/writes/platform.py`, `games/bulk_removal.py` (platform section), `tests/test_platform_writes.py`, `tests/test_bulk_platform_removal.py`.

**Interfaces (produces):**
```python
REMOVE_FIELD = "removed_at"
PLATFORM_REMOVED: str  # "That platform is removed. Restore it first."


def remove_platform_in_batch(platform, *, batch, act: BulkActionName) -> Moved: ...
def edit_platform_in_batch(
    platform, statement: PlatformEditStatement, *, batch, act
) -> Moved: ...
def undo_platform_batch(platform, *, undoes: uuid.UUID, batch, act) -> Moved: ...
def restore_platform_by_hand(platform) -> None: ...  # unchanged
```

- Remove: `recorded(... field="removed_at")` → False. Removed → False. Else `remove(row)`, then `record(earlier=None, stated=row.removed_at)`.
- Edit: for `group`/`icon` stated and not `KEEP`: skip a field already recorded; skip a field whose value already equals the statement. A group change runs `_refuse_a_taken_name(row, group=new)` first; generalise that helper to take a candidate group. Then `Platform.objects.filter(pk=).update(**changed)` inside the savepoint, with the narrowed `IntegrityError` mapping, and record each field.
- Undo:
  1. read `row_changes(library, undoes, row)`;
  2. for each field, skip it when this Undo batch already recorded it; compute `restated(change, held)` (Task 3's helper);
  3. nothing to write → False;
  4. if `group`/`icon` are to be written and `row.removed_at` is not None → `CommandFailed(PLATFORM_REMOVED, CONFLICT_STATUS)`;
  5. `removed_at` restated to None → `_restore(row)`, which keeps the taken-name refusal;
  6. `group`/`icon` → the taken-name check, then `update()`;
  7. `log_overwrite` each field;
  8. `record` each field under the Undo's own `batch`, with act `f"{act}.undo"`.
- `restore_platform_from_batch` and `removed_again_sentence` are deleted; the Undo rule now restores over a later removal. Delete their tests and add "a later removal is restored by the Undo".
- `games/bulk_removal.py`: `remove_one_platform` passes `act=REMOVE_PLATFORM.name`. `restore_one_platform` calls `undo_platform_batch(..., undoes=undoes, batch=correlation_id, act=REMOVE_PLATFORM.name)`. `undo_rows=LedgerRows(Platform)`.

- [ ] Tests (every state above, the refusals, another library's batch, the Undo chunk posted twice) → implement → `make test-fast ARGS="tests/test_platform_writes.py tests/test_bulk_platform_removal.py -q"` → commit `feat: platform writes record the batch ledger (#1136)`.

### Task 3: One module for what every Edit shares

**Files:**
- `git mv games/bulk_edit.py games/bulk_session_edit.py`. Fix its importers: `games/bulk_actions.py:372` (the foot list), `games/views/session.py:48`, `tests/test_bulk_edit.py:18`, `tests/test_bulk_edit_moves.py:17`, `tests/test_bulk_tray.py:256,275`, and the doc links in the 1211 spec (line 5) and the wave doc (line 384). Rename `tests/test_bulk_edit.py` → `tests/test_bulk_session_edit.py`.
- Create `games/reads/fact_change.py` with `FactChange[T]`, moved out of `games/reads/playergame_facts.py`, which re-imports it; update its importers (`grep -rn FactChange`).
- `games/bulk_actions.py`: `RowOutcome.either(outcomes) -> RowOutcome` classmethod; the session Edit's `_either` goes.
- Create the new `games/bulk_edit.py` (imports only `games.events.dispatch`, `games.reads.fact_change`, `django`, `logging`):
  - `type Keeping = str`;
  - `keeping[RowT](rows, value, shown) -> Keeping`;
  - `STATEMENT_UNREADABLE`;
  - `decode_statement(raw, keys: frozenset[str], unreadable) -> dict[str, object]`, the JSON → object → no unknown key prologue;
  - `settled_statement[T](choice, decode, *, act_name, row_label) -> T`, which raises `RowUnreadable` for `None` or for drift;
  - `form_refusal(form) -> CommandRejected`, the first error led by its label (game's `_named`);
  - `restated[T](change, held) -> T | None`;
  - `log_overwrite[T](change, held, *, act_name, fact, row_description) -> None`.
- Move `bulk_game_edit.py` and `bulk_session_edit.py` onto these where the spec says; behaviour must stay identical. Their existing tests are the proof, and no test assertion changes.

- [ ] Move → `make test-fast ARGS="-k 'bulk' -q"` green with no test edits beyond imports → commit `refactor: the Edit acts share games/bulk_edit.py (#1136)`.

### Task 4: `platform.edit`

**Files:**
- Create `games/bulk_platform_edit.py`, `common/components/platform_icons.py` (`PLATFORM_ICONS: tuple[str, ...]`: battlenet, bethesda, eaorigin, egs, gog, itchio, microsoft, nintendo, nintendo-3ds, nintendo-switch, physical, physical-media, playstation, ps1, ps3, ps4, ps5, steam, ubisoft, xbox-gamepass, yuzu, unspecified; check each snippet before listing it) and `tests/test_bulk_platform_edit.py`.
- Modify:
  - `common/components/primitives.py`: add `datalist` (and `option` if absent) to the `_html_element` whitelist and export it;
  - `games/forms.py`: `DatalistTextInput(forms.TextInput)` renders the input with `list=<id>` plus `Datalist(id=…)[Option(value=…)…]`, and takes `suggestions`;
  - `games/bulk_actions.py`: add `bulk_platform_edit` to the foot;
  - `games/views/platform.py`: `tray_actions(EDIT_PLATFORMS.name, REMOVE_PLATFORM.name, …)`.
- `PlatformEditStatement(group: str | None | Keep, icon: str | None)`: `KEEP` keeps the group, `""` states no group, `None` keeps the icon. At least one field is stated. `encode`/`decode` go through `decode_statement`. The icon must be in `PLATFORM_ICONS`, else `STATEMENT_UNREADABLE`.
- `BulkPlatformEditForm(PrimitiveWidgetsMixin, UnsetFieldsForm)`:
  - group: `CharField(required=False, max_length=255)` with `UnsetWidget(DatalistTextInput(suggestions=…), none_label="No group")`. The suggestions are the distinct non-blank `group` values of `Platform.objects.visible_to(library)`, sorted;
  - icon: a `ChoiceField` over `("", …) + PLATFORM_ICONS` with `ChoiceSearchSelectWidget`;
  - the placeholders come from `keeping`.
- The act: `EDIT_PLATFORMS = BulkAction(name="platform.edit", label="Edit…", title=ActTitle("Edit this platform", "Edit {count} platforms"), confirm_label="Edit", subject="platform", color="blue", undo_rows=LedgerRows(Platform), scope=platform_scope, resolve=platform_resolution, run=edit_one, inverse=undo_one, preview=(Platform, Group, Icon glyph), choice=BulkChoice(offer, settle))`. Match the Games act's label and title spelling; check `EDIT` in `bulk_game_edit.py`.
- Tests:
  - the statement codec and refusals;
  - the form's keep, none and value paths;
  - the placeholders ("Keep: mixed");
  - end to end: edit two rows, the Undo restores them, the Undo restates over a later hand edit, a taken name on edit refuses that row only, the Undo of a now-removed platform is refused;
  - `PLATFORM_ICONS` each in `ICON_NODES`;
  - the tray order Edit…, Remove.

- [ ] Tests → implement → `make test-fast ARGS="tests/test_bulk_platform_edit.py tests/test_bulk_platform_removal.py -q"` → commit `feat: edit platforms' group and icon in bulk (#1136)`.

### Task 5: e2e, render-pages, docs, gate

- `e2e/test_bulk_platform_edit_e2e.py`: select two, Edit…, type a group, pick an icon, confirm; the rows show them; Undo brings the earlier values back. Also check the ⊘ path clears the group.
- Before `make test-e2e`, stop the preview server. Run `make ts` if any `.ts` changed (none expected).
- `make render-pages` at `origin/main` and at HEAD (switch detached as before, `.dumps` untouched). Only the Platforms list should differ. Attribute it in the PR body.
- Docs:
  - `CLAUDE.md`: rewrite the #1136 sentence for the ledger plus `platform.edit`; the bulk paragraph's `StampedRows` becomes `LedgerRows`; mention `games/bulk_edit.py` as the shared Edit parts and `bulk_session_edit.py`;
  - wave doc handoff line: say "ledger", not "stamp".
- Docs sweep: delete this plan, and keep the spec timeless and under 500 words where possible.
- Full `make check` once; read the exit code.
- Then run the `/pr-review-toolkit:review-pr` pass with all five reviewers again. Fix what holds, then push and open the PR.

## Gotchas

- `update()` skips `Platform.save()`/`clean()`. The taken-name helper is the only guard, and it covers private-with-private and private-with-shared.
- `restore()` must stay the path for `removed_at`, so that `_AFTER_STAMP` brings the external references back.
- The runner resolves keys again per chunk through `for_library` (live rows only). So a repeated forward chunk never reaches a removed row, and an edit of a removed row is "lost".
- A datetime in `JSONField` reads back as a string. Always decode through `FIELD_DECODERS`.
- The session Edit's sentences are asserted bare in its tests. `form_refusal` is for the Games and platform Edits only.
