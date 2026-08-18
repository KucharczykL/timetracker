# ID-07: Platform foreign-key UUID rewrite — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint every foreign key targeting `Platform` — `Game.platform` and
`Purchase.platform` — at `Platform.uuid`, with no user-visible behavior change.

**Architecture:** Five tasks land in strict order. Tasks 1–3 are behavior-preserving
preparation that is green against the *current* integer schema, so each commits on its
own. Task 4 is the atomic cutover — models, migration, API, fixture and loader in one
commit, because splitting it leaves `make check` red. Task 5 propagates the boundary
change to the wave plan and sibling issues.

**Tech Stack:** Django 6 / Python 3.14 / PostgreSQL 18, pytest + pytest-django,
`make` for everything.

**Design spec:** [2026-08-18-issue-845-platform-fk-uuid-design.md](../specs/2026-08-18-issue-845-platform-fk-uuid-design.md).
Read it before starting. This plan names *what* to change; the spec says *why*, and
several decisions here look arbitrary without it.

## Global Constraints

- Every command goes through `make`. Never `direnv exec .`, never raw `uv run` /
  `pnpm` / `pytest`. If a target does not exist, add one.
- Iterate with `make check-fast`; **gate on the full `make check`** (includes `e2e/`)
  before pushing. Never gate on a hand-picked subset.
- `make check` must be green at **every commit on this branch**, not just the tip.
  This is what forces Task 4's scope.
- `make makemigrations` — the repo's target already passes `--noinput`. Never invoke
  the autodetector interactively; a `UUIDv7Field` add plus a nullable→NOT NULL alter
  prompts and hangs.
- Criterion values and `/api/platforms/search` option values stay **integer**
  `Platform.pk`s throughout. Nothing in this issue emits a UUID to the client.
- Never write to a `GeneratedField` (`duration_calculated`, `duration_total`,
  `price_per_game`, `days_to_finish`).
- Comments explain intent, never issue or PR numbers.
- Rebase onto `origin/main` before starting.

---

### Task 1: Nullability follows the whole lookup path

Standalone correctness fix in the filter metadata layer. Must land first: Task 2's
lookup rewrite turns `make check` red without it.

**Files:**
- Modify: `common/criteria.py` — `_resolve_model_field` (`:2411`), `field_metadata`
  (`nullable` at `:2572`)
- Test: `tests/test_filters.py`, `tests/test_field_widget.py`

**Interfaces:**
- Produces: `_lookup_is_nullable(model: type[models.Model] | None, lookup: ORMLookup) -> bool`
  — True when any traversed relation hop is nullable, or the terminal field is.
  Returns `False` for `model is None` and for an unresolvable lookup (aggregates and
  handler-mapped fields reach it).
- `_resolve_model_field` keeps its exact current signature and return value. Do not
  change what it resolves to. Its five existing assertions
  (`tests/test_filters.py:5138,5142,5146,5153,5155`) must pass untouched.

- [ ] **Step 1: Write the failing tests**

In `tests/test_filters.py`, direct unit cases for `_lookup_is_nullable(Game, …)`:
`"year_released"` → True (nullable plain column); `"name"` → False; `"platform_id"`
→ True (FK attname, unchanged behavior); `"platform__id"` → True (**the new case** —
nullable hop, non-nullable terminal); `"platform__group"` → True (same); and on
`PlayEventFilter`'s model, `"game__id"` → False (non-nullable hop). Plus
`_lookup_is_nullable(None, "x")` → False and `_lookup_is_nullable(Game, "nope")` → False.

Extend `test_nullable_reads_fk_attname` (`:5105`) to also assert
`self._by_name(GameFilter)["platform_group"]["nullable"] is True` and
`self._by_name(PurchaseFilter)["platform"]["nullable"] is True`.

Keep `test_dynamic_fk_and_m2m_have_no_choices`'s `purchase_fields["games"]["nullable"]
is False` (`:5101`) — it is the guard against implementing this as "everything is
nullable".

- [ ] **Step 2: Run them and confirm the right ones fail**

```bash
make test ARGS="tests/test_filters.py -k nullable -p no:randomly" PYTEST_WORKERS=0
```

Expected: the `platform__id` / `platform__group` cases FAIL (`_lookup_is_nullable`
undefined, then False), everything else passes.

- [ ] **Step 3: Implement**

Extract the segment walk currently inside `_resolve_model_field` into one private
generator yielding each resolved segment field and whether it was traversed as a
relation hop. `_resolve_model_field` consumes it and returns the terminal field
exactly as today; `_lookup_is_nullable` consumes it and ORs `.null` over the relation
hops plus the terminal field. **One walk, two consumers** — do not write a second
walker, it will drift.

In `field_metadata`, replace `nullable = bool(getattr(model_field, "null", False))`
with the call. Note it is evaluated for aggregate/handler fields too, where
`model_field` is None — hence the guards.

- [ ] **Step 4: Verify, including the sentinel**

```bash
make test ARGS="tests/test_filters.py tests/test_field_widget.py -p no:randomly" PYTEST_WORKERS=0
```

`tests/test_field_widget.py:106-114` must stay green. Then `make check-fast`.

- [ ] **Step 5: Commit**

`fix: derive filter nullability from the whole lookup path` — body should say that a
path through a nullable relation can yield NULL regardless of the terminal column, and
that the ORM already behaves this way.

---

### Task 2: Rewrite the six platform filter lookups

`platform__id` is a valid lookup against the *current* integer FK too — it is one join
deeper and returns the same rows. So this lands and stays green before any schema
change.

**Files:**
- Modify: `games/filters.py:148, 216, 374, 440, 634, 644` (lookups) and `:102, :338`
  (the `# platform_id (int FK)` declaration comments)
- Test: `tests/test_filters.py:5128`, `tests/test_filter_execution.py`,
  `tests/test_stats_links.py:170`

- [ ] **Step 1: Write the failing/updated tests**

`tests/test_filters.py:5128`: `GameFilter.fields["platform"].lookup == "platform__id"`.

`tests/test_filter_execution.py`: for **both** `GameFilter` and `PurchaseFilter` —
INCLUDES with integer values selects the right rows; EXCLUDES selects the right rows
**and still matches platformless rows** (the `_not_in_q` isnull arm); `IS_NULL` and
`NOT_NULL` select the platformless/platformed sets. Then the `platform_filter`
relation in both directions: `GameFilter(platform_filter=PlatformFilter(...))` and
`PlatformFilter(game_filter=…)` / `PlatformFilter(purchase_filter=…)`, each under
ANY/NONE/ALL.

`tests/test_stats_links.py:170`: `game__platform_id=platform.id` →
`game__platform=platform`. (It breaks under Task 4 either way; fixing it here keeps
Task 4's diff to non-test files.)

- [ ] **Step 2: Run and watch the lookup assertion fail**

```bash
make test ARGS="tests/test_filters.py::test_explicit_filterfield_label_wins -p no:randomly" PYTEST_WORKERS=0
```

- [ ] **Step 3: Rewrite the six sites**

All `platform_id` → `platform__id`. The two in `PlatformFilter._extra_q` (`:634`,
`:644`) are separate `relation_to_q` calls, one per referencing model — change both.
Correct the `:102`/`:338` comments to describe the criterion value type rather than
the column.

Leave `platform_group`'s `platform__group` alone. Leave every `parent_field="game_id"`
/ `related_lookup="game_id"` alone — those belong to ID-08.

- [ ] **Step 4: Verify**

```bash
make test ARGS="tests/test_filters.py tests/test_filter_execution.py tests/test_filter_bars.py tests/test_stats_links.py -p no:randomly" PYTEST_WORKERS=0
```

Then `make check-fast`.

- [ ] **Step 5: Commit**

`refactor: reach Platform's id through the relation in platform filters`

---

### Task 3: Form initial-value helper and integer-preserving read paths

All behavior-neutral against the current schema.

**Files:**
- Modify: `games/forms.py` — new `seed_related_initial`, called from `GameForm.__init__`
  (`:800-809`), `PurchaseForm.__init__` (`:658-670`), and replacing `PlayEventForm`'s
  open-coded lines (`:880-887`); `game_option_data` (`:185`)
- Modify: `games/management/commands/audit_library_ownership.py:169-187`
- Test: `tests/test_forms.py` (or nearest existing form test module)

**Interfaces:**
- Produces: `seed_related_initial(form: forms.ModelForm, *field_names: str) -> None`.
  For each name, when `form.instance.pk` is set, assigns
  `form.initial[name] = getattr(form.instance, name)` — the related **instance**, which
  `ModelChoiceField.prepare_value` resolves back to its pk. ID-08 calls this with
  `("game", "device")`.

- [ ] **Step 1: Write the failing tests**

A bound `GameForm(instance=game, library=library)` and a bound
`PurchaseForm(instance=purchase, …)` each render the platform combobox preselected
with the platform's **integer** id; a game/purchase with `platform=None` renders no
selection (not the string `"None"`). Assert on the rendered widget value, not on
`form.initial`, so the test still means something after Task 4.

Also assert `game_option_data(game)["platform"]` is `str(platform.pk)` for a
platformed game and `""` for a platformless one.

- [ ] **Step 2: Run — the empty/preselect cases should pass today**

```bash
make test ARGS="tests/test_forms.py -k platform -p no:randomly" PYTEST_WORKERS=0
```

These characterize current behavior, so they pass now and are the regression net for
Task 4. That is the point: write them here, where a failure means *you* broke
something, not the migration.

- [ ] **Step 3: Implement**

Add `seed_related_initial` with a docstring saying it is transitional (Wave E deletes
it) and *why* it exists: `model_to_dict` reads the FK attname, which is a UUID for
moved relations, while SearchSelect options are integer ids.

Call it with `"platform"` from `GameForm.__init__` and `PurchaseForm.__init__`.
Migrate `PlayEventForm`'s two lines onto it, keeping the explanatory comment.

`game_option_data`: `str(game.platform_id)` → `str(game.platform.id) if game.platform
else ""`. The docstring's "Callers must `select_related('platform')`" is now
correctness, not performance — both callers (`games/forms.py:200`, `games/api.py:146`)
already comply; verify before changing.

`audit_library_ownership`: both `.values_list("pk", "platform_id")` become
`.values_list("pk", "platform__id")`, so the two adjacent violation lines keep
reporting the same kind of id.

`PlatformForm` needs nothing.

- [ ] **Step 4: Verify**

```bash
make test ARGS="tests/test_forms.py tests/test_library_commands.py -p no:randomly" PYTEST_WORKERS=0
```

Then `make check-fast`.

- [ ] **Step 5: Commit**

`refactor: seed SearchSelect-backed form fields from the related instance`

---

### Task 4: The cutover — models, migration, API, fixture, loader

**One commit.** Splitting it leaves `make check` red: the moment the FK moves, the
committed fixture stops deserializing and `/api/platforms/search` raises
`operator does not exist: uuid_v7 = bigint`. Work through the steps, commit once at
the end.

**Files:**
- Modify: `games/models.py:68-70` (`Game.platform`), `:277-279` (`Purchase.platform`)
- Create: `games/migrations/0010_platform_fk_uuid.py`
- Modify: `games/api.py:243, 250`
- Modify: `games/fixtures/sample.yaml.gz` (regenerated blob)
- Modify: `games/management/commands/load_sample_data.py` —
  `FIXTURE_RELATIONSHIPS` (`:66, :68`), the `FixtureRelationship` docstring (`:48-62`),
  `_load_platforms` (`:266-292`), `_prepare_private_records` (`:309-327`)
- Create: `tests/test_platform_fk_uuid.py`
- Modify: `tests/test_library_commands.py`
- Scratch (uncommitted): the fixture transform script

- [ ] **Step 1: Write the migration test first**

`tests/test_platform_fk_uuid.py`, mirroring `tests/test_library_cutover_migration.py`'s
`MigrationExecutor` usage. At `0009`: create several platforms, plus games and
purchases across them **including rows with `platform=None` in both models**. Migrate
to `0010`. Assert every row still points at the same platform (compare by platform
*name*, not id), every previously-NULL row is still NULL, and no previously-non-NULL
row became NULL.

Reading the failure of this test is how you decide whether the final `AlterField`
renames-and-constrains in one operation. ID-06 found that it does and its
`SeparateDatabaseAndState` fallback was unnecessary — but confirm, don't assume.

- [ ] **Step 2: Add the remaining schema tests**

Same file: reverse migration back to `0009` restores exact integers **and** NULLs;
column type is `uuid_v7` via `information_schema`; an FK constraint exists on both
tables; inserting a row with a UUID no platform owns is rejected at the database level.

**And the constraint tests** — new coverage that does not exist today, which is exactly
why the migration could silently drop these: after migrating to `0010`, both
`Game.Meta.unique_together` and `unique_library_platformless_game_name_year` exist in
`pg_constraint` **and are enforced** — a duplicate `(library, name, platform,
year_released)` raises `IntegrityError`, and so does a second platformless game with
the same `(library, name, year_released)`.

- [ ] **Step 3: Change the two model fields**

Add `to_field="uuid"` to `Game.platform` and `Purchase.platform`, keeping
`on_delete=SET_NULL, null=True, blank=True, default=None` on both.

- [ ] **Step 4: Hand-write `0010_platform_fk_uuid.py`**

Depends on `0009_playhistory_game_uuid_fk`. Copy `0009`'s `require_match` helper and
its evidence-line convention. Per model, five operations:

1. `AddField platform_uuid` — `UUIDv7Field(null=True, default=None, db_default=None,
   editable=False)`. The explicit `None`s suppress the field's own defaults so the
   column arrives empty.
2. `RunPython(fill_uuid_from_integer, fill_integer_from_uuid)` — `UPDATE … FROM
   games_platform … WHERE platform.id = child.platform_id`, and the mirror join through
   `platform.uuid` in reverse. NULL rows match no join row and are left untouched in
   both directions; that is what makes this reversible without ID-06's NOT NULL step.
3. `RemoveField platform`
4. `RenameField platform_uuid → platform`
5. `AlterField platform` → the final FK.

**`Game` gets four more operations wrapped around that block**, and they are not
optional: `AlterUniqueTogether(name="game", unique_together=set())` and
`RemoveConstraint(model_name="game", name="unique_library_platformless_game_name_year")`
**before** step 3, and the mirrored `AddConstraint` + `AlterUniqueTogether` **after**
step 5. `RemoveField` compiles to a bare `DROP COLUMN`; PostgreSQL cascades both
guarantees away while Django's state still lists them, so the drift guard sees nothing
and the suite stays green with the platformless-duplicate guard gone. The
`unique_together` also names the `platform` field, so it must be empty across the
window where that field does not exist.

`Purchase` needs none of this — no `Meta` constraint touches its `platform`.

One `RunSQL("SET CONSTRAINTS ALL IMMEDIATE", reverse_sql=RunSQL.noop)` after the
backfill and before the schema alterations, as `0009` does.

Reconciliation inside the `RunPython`, raising `RuntimeError` via `require_match`:
NULL-set identity in **both** directions (zero rows with old-NULL/new-non-NULL, zero
with old-non-NULL/new-NULL — as anti-joins, not count comparisons); a non-NULL
anti-join against `games_platform`; and unchanged distinct referenced-platform count
per model. Print one line:

```
FK identity rewritten game_rows=<n> game_platforms=<n> game_nulls=<n> purchase_rows=<m> purchase_platforms=<m> purchase_nulls=<m> unmatched=0
```

- [ ] **Step 5: Run the migration tests**

```bash
make test ARGS="tests/test_platform_fk_uuid.py -p no:randomly" PYTEST_WORKERS=0
```

Then confirm no drift: `make makemigrations` produces nothing.

- [ ] **Step 6: Fix the API recency subqueries**

`games/api.py:243` and `:250`: `filter(platform=OuterRef("pk"))` →
`filter(platform=OuterRef("uuid"))`, in both the `Game` and `Purchase` subqueries.
`filter(platform=…)` *is* the FK column, so leaving either raises
`operator does not exist: uuid_v7 = bigint` on the endpoint that feeds both platform
facets and both forms. `/api/platforms/groups` (`:275-282`) is genuinely unaffected.

Verify with `make test ARGS="tests/test_api.py tests/test_library_api_isolation.py"`.

- [ ] **Step 7: Regenerate the fixture**

Throwaway script in the scratchpad — **do not commit it**. A database round trip is
impossible: loading the old fixture needs pre-cutover code, the migration needs
post-cutover code.

1. Walk `games.platform` records ordered by `(created_at, pk)`, minting each `uuid`
   with `timetracker.uuidv7.uuid7_at(created_at, sequence=…)`, resetting the sequence
   per millisecond. **All 25 records share `created_at` of `2020-01-01T00:00:00Z`** —
   without the per-millisecond sequence you get 25 identical uuids and a fixture that
   cannot load.
2. Rewrite every `games.game.platform` and `games.purchase.platform` to that platform's
   UUID string; leave `null` as `null`.
3. Re-emit exactly as `anonymize_sample._write_fixture` does:
   `yaml.safe_dump(sort_keys=True, default_flow_style=False)`, then
   `gzip.compress(compresslevel=9, mtime=0)`.

Verify and record in the PR body: per-model counts unchanged (851 game, 2718 session,
795 purchase, 203 playevent, 25 platform, 14 device, 75 exchangerate); NULL counts
preserved exactly (30 games, 7 purchases); no field on any record differs except the
added `platform.uuid` and the two rewritten references; every non-NULL reference
resolves to exactly one `platform.uuid`.

- [ ] **Step 8: Update the loader**

`FIXTURE_RELATIONSHIPS`: `reference_field="uuid"` on `games.game.platform` and
`games.purchase.platform`. Update the `FixtureRelationship` docstring, which currently
enumerates the moved relations by name.

`_load_platforms` returns `{str(fixture_uuid): str(real_uuid)}`;
`_prepare_private_records` rewrites both models' `platform` through it. Two traps:

- **Values must be `str`, not `uuid.UUID`.** The prepared records go through
  `yaml.safe_dump(loadable, sort_keys=False)` (`:120`) before deserialization, and a
  `UUID` object raises `RepresenterError`. The command already stringifies at `:318`
  for this reason.
- **Read the fixture uuid with `fields.get("uuid")`, never `fields["uuid"]`.** A
  platform record without a uuid is legal — `_validate_records` indexes with `.get()`
  (`:218`) and only errors at the referencing record — and
  `tests/test_library_commands.py:405-419` defines exactly such a record. Skip mapping
  those.

The remap is load-bearing: a created `Platform` mints its own uuid
(`UUIDv7Field.__init__` sets the default), and the reuse path matches an existing row
on `(library, name, group)`. **The real uuid is never the fixture's, on either path.**

- [ ] **Step 9: Add the loader tests**

In `tests/test_library_commands.py`: **new** parametrized dangling-reference cases for
`games.game.platform` and `games.purchase.platform` naming a UUID no platform record
carries — additions, not edits; the existing list (`:299-317`) has no platform case and
`load_sample_data.py:324`'s error has no coverage at all today. Plus the case that
catches a missing or wrong remap: after loading against a database that already holds
a matching shared platform, the loaded game points at the **reused** platform, not a
duplicate.

Confirm `test_committed_sample_load_owns_private_rows_and_reuses_shared_platform`
(`:197`) passes against the new blob.

- [ ] **Step 10: Full gate, then commit**

```bash
make check
```

Must be green including `e2e/`. Commit everything from steps 3–9 together.

`feat: resolve platform links through Platform's UUID identity`

---

### Task 5: Propagate the boundary change

**Files:**
- Modify: `docs/superpowers/specs/2026-08-17-uuid-identity-cutover-wave-plan.md`
- GitHub: comments on #845, #846, #847

- [ ] **Step 1: Amend the wave plan**

Wave C table: ID-07 owns `Game.platform` **and** `Purchase.platform`; ID-09's row drops
`Purchase.platform`, leaving `Purchase.games` + `related_game`. ID-07's `blocked-by`
stays `#640` alone.

The "learned in ID-06" checklist gains two items: **(5)** nullable relations use the
five-operation shape, reconcile on NULL-set identity rather than a zero NULL count, and
need no per-slice nullability work now that the metadata fix has landed once; **(6)**
check the owning model's `Meta.unique_together` and `constraints` for the dropped
column — PostgreSQL cascades them away and the state-based drift guard cannot see it.

- [ ] **Step 2: Comment on the issues**

#845: the boundary now covers both Platform FKs, and why.
#847: `Purchase.platform` moved out; remaining scope is `Purchase.games` +
`related_game`, and an M2M through table has no model field to relax, so its migration
shape is ID-09's to design.
#846: `Session.device` is nullable → five-op shape; `Session.game` is NOT NULL → ID-06's
six-op shape; `seed_related_initial` already exists for its two fields; the nullability
metadata work is already done; and `games/signals.py:113` is still its to own.

- [ ] **Step 3: Commit and open the PR**

`docs: record that ID-07 owns every Platform foreign key`

PR body carries the fixture verification numbers from Task 4 Step 7 and the migration's
printed reconciliation line.

---

## Notes for the implementer

- **The single most likely way to ship this broken** is missing one lookup that spells
  the FK column. It fails as `operator does not exist: uuid_v7 = bigint`. If you see
  that string, you missed a site — grep for `platform_id` before assuming otherwise.
- **`anonymize_sample` needs no change, deliberately.** The generic Wave C checklist
  says each moved relation needs a matching UUID-keyed offset map; that item is
  specific to `Game` relations. The command's maps (`:187-196`) are keyed by game and
  looked up through `session.game_id` / `event.game_id`, and purchase offsets are drawn
  independently (`:236`). Nothing there is keyed by platform. Do not add a map.
- **A UI assertion is not a database assertion.** If an e2e test reads the ORM after a
  write, wait on server-rendered output first.
- Filter criterion values stay integers. If you find yourself emitting a UUID to a
  template, a form, or JSON, stop — that flip belongs to a later wave.
- Tasks 1–3 are individually revertible. Task 4 is not; revert it together with the
  fixture blob.
