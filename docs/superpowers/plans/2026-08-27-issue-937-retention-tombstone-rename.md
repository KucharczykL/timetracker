# Retention Tombstone Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename retention's `archived_at` column and its whole vocabulary to say tombstone, so the word "archive" is free for the player-facing act that #675 adds.

**Architecture:** This is a rename, not a behaviour change. No test asserts anything new, and the existing suite is the safety net. The column has never existed in a deployed database, so migration `0027` is edited in place instead of gaining a `RenameField` successor.

**Tech Stack:** Django 6.0.7, Python 3.14, PostgreSQL 18, pytest + pytest-xdist, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-27-issue-937-retention-tombstone-rename-design.md`

## Global Constraints

- **Drive everything through `make`.** Never wrap a command in `direnv exec .`, and never call `uv run` / `pytest` / `pnpm` directly. `ARGS` is for iterating, never for the gate.
- **The gate is the full `make check`** (lint + format-check + mypy + ts-check + vitest + all of `tests/` and `e2e/`). Use `make check-fast` while iterating; it is not the gate.
- **Python 3.14 is required.** A `SyntaxError` in an `except A, B:` line means the wrong interpreter, not broken code.
- **Never write to a `GeneratedField`**: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`.
- **Name variables with complete words** in any line you touch.
- **The final names**, used verbatim everywhere:
  - `Game.tombstoned_at`, `Platform.tombstoned_at`, `Device.tombstoned_at`
  - `Retirement.TOMBSTONED = "tombstoned"`
  - `tombstone_or_delete()`
  - `TombstonableQuerySet`
- `Retirement.DELETED` **keeps its name.**
- **`tests/test_projection_model.py` must not change.** Its `archived_at` is a field on an unrelated synthetic test model.
- **Do not create a new migration.** If a stray `games/migrations/0032_*.py` appears because a `make` target ran `makemigrations` midway through an edit, delete it and finish the edit.

---

## File Structure

| File | Responsibility in this change |
|------|------------------------------|
| `games/migrations/0027_archive_catalog_rows.py` | Edited in place, then renamed to `0027_tombstone_catalog_rows.py`. Three `AddField` names, four `AddConstraint` conditions. |
| `games/migrations/0028_playergame.py` | One dependency string follows the file rename. |
| `games/models.py` | Three field declarations, `TombstonableQuerySet`, `PlatformQuerySet`, `Device.objects`, four partial unique constraints, and the cross-relation lookups in `EditionQuerySet` / `ReleaseQuerySet`. |
| `games/retention.py` | The enum member and value, `tombstone_or_delete()`, the stamping update, docstrings. |
| `games/forms.py` | One string in the validation-exclusion set. |
| `games/views/retirement.py`, `games/signals.py`, `common/import_data.py`, `games/commands/playergame.py` | Import, call site, lookup, and comments. |
| `docs/event-retention.md` | Prose, headings, the `ARCHIVED` table row, and a new Naming section. |
| `CLAUDE.md` | One bullet pointing at the Naming section. |
| `tests/`, `e2e/` | Mechanical updates plus one file rename. |

Task 1 moves the column. Task 2 moves the surrounding vocabulary. Task 3 writes the documentation. Task 4 is the gate. A reviewer can accept Task 1 and reject Task 2 on its own merits, which is why they are separate.

---

### Task 1: Rename the column

**Files:**
- Modify: `games/migrations/0027_archive_catalog_rows.py` (then rename)
- Modify: `games/migrations/0028_playergame.py:12`
- Modify: `games/models.py`, `games/retention.py:132-133`, `games/forms.py:799-803`, `games/commands/playergame.py:68`
- Modify: `tests/test_retention.py`, `tests/test_archived_rows.py`, `tests/test_playergame_command.py:99`, `e2e/test_retention_confirmation_e2e.py:94`

**Interfaces:**
- Consumes: nothing from an earlier task.
- Produces: the column name `tombstoned_at` on `Game`, `Platform` and `Device`, which Task 2 and Task 3 both refer to.

- [ ] **Step 1: Confirm the starting state is green and the database is clean**

```bash
make check-fast
```

Expected: PASS. If it is red before you change anything, stop and report — the failure is not yours.

- [ ] **Step 2: Rename the column in every source and test file**

`tests/test_projection_model.py` is deliberately absent from this list. Do not add it.

```bash
sed -i 's/archived_at/tombstoned_at/g' \
  games/models.py \
  games/retention.py \
  games/forms.py \
  games/commands/playergame.py \
  games/migrations/0027_archive_catalog_rows.py \
  tests/test_retention.py \
  tests/test_archived_rows.py \
  tests/test_playergame_command.py \
  e2e/test_retention_confirmation_e2e.py
```

- [ ] **Step 3: Rename the migration file and its one dependant**

```bash
git mv games/migrations/0027_archive_catalog_rows.py \
       games/migrations/0027_tombstone_catalog_rows.py
sed -i 's/0027_archive_catalog_rows/0027_tombstone_catalog_rows/' \
  games/migrations/0028_playergame.py
```

- [ ] **Step 4: Read the migration diff and confirm it is exactly seven edits**

```bash
git diff -- games/migrations/
```

Expected: three `AddField(name="tombstoned_at")` — for `device`, `game`, `platform` — and four `condition=models.Q(("tombstoned_at__isnull", True))` occurrences, two of them inside a two-element `Q(...)` alongside `platform__isnull` or `library__isnull`. Plus the one dependency string in `0028_playergame.py`. Nothing else.

- [ ] **Step 5: Confirm the fix in `games/forms.py` still reads correctly**

The line is not an exclusion that hides the column; it puts the column *back* into constraint validation, because Django skips a conditional constraint whose condition names an excluded field. Confirm the comment above it still makes sense after the rename:

```
        # ``tombstoned_at`` is the same story, with a sharper edge.
        # Django skips a conditional constraint whose condition
        # names an excluded field. A form row is live, so it
        # contributes the NULL the condition expects.
        exclusions.discard("tombstoned_at")
```

- [ ] **Step 6: Rebuild the development database**

The local database already applied the old `0027`. It now holds a column named `archived_at` while the migration state claims `tombstoned_at`, and no command detects that. Drop it:

```bash
make reset-db
make loadplatforms
```

Expected: migrations apply cleanly through `0031`, ending with `0027_tombstone_catalog_rows`.

- [ ] **Step 7: Prove the models and the migration agree**

```bash
make check-migrations
```

Expected: exit 0 with no new migration written. A non-zero exit means a constraint condition or a field name was missed.

- [ ] **Step 8: Run the tests that exercise the column**

```bash
make test ARGS="tests/test_retention.py tests/test_archived_rows.py tests/test_library_form_isolation.py -q"
```

Expected: PASS. `tests/test_library_form_isolation.py` is the real guard for the `games/forms.py` string — it makes a live duplicate and asserts the form refuses it, which only works when the constraint condition and the exclusion set name the same column.

- [ ] **Step 9: Run the aggregate**

```bash
make check-fast
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Rename the retention column to tombstoned_at"
```

---

### Task 2: Rename the vocabulary around it

**Files:**
- Modify: `games/retention.py`, `games/models.py`, `games/views/retirement.py`, `games/signals.py:98`, `common/import_data.py:23`, `games/commands/playergame.py`
- Modify: `tests/test_retention.py`, `tests/test_reference_reconciliation.py`
- Rename: `tests/test_archived_rows.py` → `tests/test_tombstoned_rows.py`

**Interfaces:**
- Consumes: the column `tombstoned_at` from Task 1.
- Produces: `Retirement.TOMBSTONED`, `tombstone_or_delete(instance: Model) -> Retirement`, and `TombstonableQuerySet`. Task 3 names all three in prose.

- [ ] **Step 1: Rename the three identifiers everywhere they appear**

```bash
sed -i \
  -e 's/archive_or_delete/tombstone_or_delete/g' \
  -e 's/ArchivableQuerySet/TombstonableQuerySet/g' \
  -e 's/Retirement\.ARCHIVED/Retirement.TOMBSTONED/g' \
  games/retention.py \
  games/models.py \
  games/views/retirement.py \
  tests/test_retention.py \
  tests/test_reference_reconciliation.py
```

- [ ] **Step 2: Change the enum member and its value by hand**

In `games/retention.py`:

```
class Retirement(StrEnum):
    """What retiring a row meant."""

    DELETED = "deleted"
    TOMBSTONED = "tombstoned"
```

- [ ] **Step 3: Update the prose that still says archive**

Each of these is a docstring or a comment. Change them one at a time and read each in context; a blind `sed` over the word "archive" produces broken grammar.

`games/retention.py` — the function docstring:

```
def tombstone_or_delete(instance: Model) -> Retirement:
    """Delete the row, or leave a tombstone."""
```

`games/retention.py` — the comment above `_UNCASCADED_COLLATERAL`:

```
#: What a delete does that no cascade does.
#: A tombstone never fires the `pre_delete` receiver.
```

`games/retention.py` — inside `resolve_reference`:

```
    #: The plain manager. It sees tombstoned rows.
```

`games/retention.py` — the guard message in `refuse_to_delete_a_referenced_row`:

```
            "replay must still be able to resolve them. Retire it with "
            "games.retention.tombstone_or_delete, which removes it from the "
            "library and keeps the row."
```

`games/models.py` — the queryset docstring:

```
class TombstonableQuerySet(LibraryOwnedQuerySet):
    """A referenced row outlives its deletion, as a tombstone.

    `for_library` and `visible_to` are how the application asks for
    rows. A caller that must see tombstoned rows uses the plain manager.
    """
```

`games/models.py` — the comments near the constraints and the `Device` manager:

```
        #: A tombstoned name is free again.
```

```
    #: A tombstoned Platform shadows nothing.
```

```
    #: Tombstonable: `device` is a REQUIRED reference kind.
```

`games/models.py` — the `EditionQuerySet` and `ReleaseQuerySet` docstrings:

```
class EditionQuerySet(models.QuerySet):
    """A tombstone is inherited from Game.

    An Edition has no visibility of its own to lose.
    """
```

```
class ReleaseQuerySet(models.QuerySet):
    """A tombstone is inherited from Game."""
```

`games/views/retirement.py` — the `retention_message` docstring:

```
def retention_message(noun: str, label: str, count: int) -> str:
    """What the page says when a row leaves a tombstone."""
```

`games/signals.py` — inside `update_purchase_counts_on_game_delete`:

```
    """Keep purchase counts right.

    The work is in `games.retention`. A tombstone needs it too.
    """
```

`common/import_data.py`:

```
                #: Never a tombstoned Game.
                #: A deleted row stays deleted.
```

`games/commands/playergame.py` — the rejection message in `_visible_game`:

```
                f"No game {self.game_id} this library can track. A library "
                "tracks its own games and the shared catalog, and neither "
                "offers a tombstoned row."
```

- [ ] **Step 4: Rename the test file and the names inside it**

```bash
git mv tests/test_archived_rows.py tests/test_tombstoned_rows.py
sed -i \
  -e 's/^ARCHIVED = /TOMBSTONED = /' \
  -e 's/\bARCHIVED\b/TOMBSTONED/g' \
  -e 's/an_archived/a_tombstoned/g' \
  -e 's/archiving/tombstoning/g' \
  -e 's/_archived_/_tombstoned_/g' \
  -e 's/is_archived/is_tombstoned/g' \
  -e 's/\barchive(/tombstone(/g' \
  -e 's/^def archive\b/def tombstone/' \
  -e 's/An archived row/A tombstoned row/g' \
  tests/test_tombstoned_rows.py tests/test_retention.py
```

- [ ] **Step 5: Read the two test diffs and repair the grammar**

```bash
git diff -- tests/test_tombstoned_rows.py tests/test_retention.py
```

A mechanical substitution leaves wrong articles and awkward verbs. Fix each one you see. Specifically expect to hand-edit:

- `test_a_tracked_game_archives_and_keeps_its_projection_row` → `test_a_tracked_game_is_tombstoned_and_keeps_its_projection_row`
- `test_a_referenced_game_is_archived` → `test_a_referenced_game_is_tombstoned` (likewise for `_platform_` and `_device_`)
- `test_an_archived_games_name_is_free_again` → `test_a_tombstoned_games_name_is_free_again`
- The module docstring's first line, `An archived row leaves every library-scoped read …`
- The docstring at `test_the_add_game_form_accepts_a_tombstoned_duplicate`, which names the column

- [ ] **Step 6: Confirm no identifier still says archive**

```bash
grep -rn "archive_or_delete\|ArchivableQuerySet\|Retirement\.ARCHIVED" \
  games/ common/ tests/ e2e/ || echo "clean"
```

Expected: `clean`. `docs/` is deliberately not searched — `docs/event-retention.md` still names the old function until Task 3, and the specifications keep their wording permanently.

- [ ] **Step 7: Run the affected tests**

```bash
make test ARGS="tests/test_retention.py tests/test_tombstoned_rows.py tests/test_reference_reconciliation.py tests/test_playergame_command.py -q"
```

Expected: PASS. A `NameError` or a collection error here means a `sed` hit a definition but not a call site, or the reverse.

- [ ] **Step 8: Run the aggregate**

```bash
make check-fast
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Rename retention's vocabulary to say tombstone"
```

---

### Task 3: Write the documentation and the naming rule

**Files:**
- Modify: `docs/event-retention.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `tombstoned_at`, `Retirement.TOMBSTONED`, `tombstone_or_delete()` and `TombstonableQuerySet` from Tasks 1 and 2.
- Produces: `docs/event-retention.md#naming`, which the `CLAUDE.md` bullet links to.

- [ ] **Step 1: Update the two headings**

In `docs/event-retention.md`:

- `## What archiving does` → `## What a tombstone does`
- `## Where an archived row is not visible` → `## Where a tombstoned row is not visible`

- [ ] **Step 2: Update the outcome table row**

```markdown
| `TOMBSTONED` | An event names the row under a `REQUIRED` kind | The row stays, with `tombstoned_at` set. All other data goes |
```

- [ ] **Step 3: Update the remaining prose**

Every other line that says archive is listed here. Read each in place; the replacement is the natural rewording, not a word swap.

- `tombstone_or_delete(instance)`. The function gives the outcome. (line ~14)
- A tombstoned row is not a smaller delete. All the work of the delete occurs: (~21)
- … A tombstone does not delete the row, thus … (~44)
- The receiver and the tombstone path both call it. There is one implementation. (~46)
- `tombstone_or_delete` sets `tombstoned_at` with a queryset update. … (~48)
- The test nodeid at ~54 becomes `tests/test_retention.py::test_tombstoning_leaves_exactly_what_deleting_would`
- `for_library()` and `visible_to()` exclude a tombstoned row. … (~60)
- `Edition` and `Release` have no `tombstoned_at` column. … (~64)
- `tombstoned_at IS NULL`. A tombstoned row is not in the library. … (~68)
- `tombstoned_at` is not editable, thus a form always excludes it. … (~74)
- … `tombstoned_at` out of the exclusions. … (~78)
- Three readers see tombstoned rows. … (~81)
- The row can be tombstoned. … (~87)
- … a tombstoned row could pass one and fail the other (~96)
- … Thus a tombstoned row resolves. … (~108)
- delete views call `tombstone_or_delete` and do not see this exception. (~149)
- … to use `tombstone_or_delete`. … (~163)
- … delete, followed by a tombstone, is worse than each of the two outcomes. (~184)
- A Trash or recovery screen (#795). A tombstone in place, and not a stub … (~188)

- [ ] **Step 4: Add the Naming section**

Append this immediately before `## Not in this contract`:

```markdown
## Naming

One act takes one verb. The event type, the command and the projection column
all use that verb.

The column names the act in the past participle: `<act>_at`, and a name for what
the act touches can come first. It is a nullable `DateTimeField`, and null is
the live state. Thus `tombstoned_at`, `archived_at`, `voided_at`,
`access_ended_at`.

A fact about the world and a retraction of a record are two acts, thus they take
two verbs. An end of access and a refund are facts. A void and a deletion are
retractions.

`Retirement` is outside the rule. The rule governs an event, a command and a
column, and retention has none of the three: the enum reports which of two
outcomes a delete had. A hard delete leaves no row and thus no column, so
`deleted_at` on a projection always means the reversible act.

`Purchase.date_refunded` is older than the rule.
```

- [ ] **Step 5: Add the CLAUDE.md bullet**

In `CLAUDE.md`, under `## Conventions for AI assistants`, add this bullet directly after the `**Never write to GeneratedFields**` bullet:

```markdown
- **One act, one verb** — an event type, its command and its projection column
  share one verb, and the column is `<act>_at`: a nullable `DateTimeField` whose
  null is the live state. See [Naming](docs/event-retention.md#naming).
```

- [ ] **Step 6: Confirm the documentation says nothing about archive**

```bash
grep -ni "archiv" docs/event-retention.md CLAUDE.md
```

Expected: exactly one hit — the `archived_at` in the Naming section's list of examples, which is the player-facing column #675 adds and is deliberate. Any other hit is a missed reference.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Document the tombstone and the naming rule"
```

---

### Task 4: The gate

**Files:** none — this task only verifies.

**Interfaces:**
- Consumes: everything from Tasks 1 to 3.
- Produces: a green `make check` and a clean audit.

- [ ] **Step 1: Audit every remaining mention of the old word**

```bash
grep -rni "archiv" \
  games/ common/ tests/ e2e/ ts/ docs/event-retention.md CLAUDE.md Makefile \
  | grep -v "tests/test_ensure_postgres.py\|tests/test_projection_model.py\|tests/test_returns_classification.py"
```

Expected: exactly one hit — the `archived_at` in the Naming section of `docs/event-retention.md`, listed there as an example of the rule. It names the player-facing column #675 adds, so it is correct. Any other hit is a missed reference.

The three excluded files are legitimate and must not be edited:

- `tests/test_projection_model.py` — `archived_at` on an unrelated synthetic model
- `tests/test_ensure_postgres.py` — tar archives in the PostgreSQL harness, a different sense of the word
- `tests/test_returns_classification.py` — a docstring about a hypothetical future `archive_` route, which #675 goes on to create

Specification files under `docs/superpowers/specs/` are also outside the audit: a record of what the project decided is not rewritten.

- [ ] **Step 2: Confirm no column of either name survived wrongly**

```bash
make check-migrations
```

Expected: exit 0, no new migration written.

- [ ] **Step 3: Rebuild the database once more from scratch**

```bash
make reset-db
make loadplatforms
```

Expected: clean apply through `0031_playergame_excluded_from_unfinished`.

- [ ] **Step 4: Run the full gate**

```bash
make check
```

Expected: PASS. This includes `e2e/`, which `make check-fast` skips and which covers the retention confirmation page. Do not substitute a hand-picked subset.

- [ ] **Step 5: Commit anything the formatter changed**

```bash
git status --short
```

If `make check` reformatted a file, commit it:

```bash
git add -A
git commit -m "Format after the tombstone rename"
```

If nothing changed, skip this step.

---

## Notes for the executor

**Do not run `make makemigrations` to produce a rename.** The target passes `--noinput`, the non-interactive questioner answers no to every rename question, and Django emits `RemoveField` plus `AddField` instead of `RenameField`. This plan avoids the problem entirely by editing the unapplied `0027`, which is safe only because no deployment has ever run it: the one durable database stops at `0022_external_references` and `information_schema` shows no column of either name.

**A stray migration file means a `make` target ran mid-edit.** Several targets depend on `migrate`, which depends on `makemigrations`. If a `games/migrations/0032_*.py` appears, delete it and finish the edit.

**#675 merges after this.** It renames its own `PlayerGame.hidden_at` to `archived_at` by the same route, in its own unapplied `0032`.
