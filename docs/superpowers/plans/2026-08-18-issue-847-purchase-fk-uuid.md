# ID-09: `Purchase.related_game` → UUID — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint `Purchase.related_game` at `Game.uuid` as a real `uuid_v7`-typed foreign key, reversibly, with the sample fixture still loading — and pin the deliberately deferred `Purchase.games` through table so Wave E cannot move it unannounced.

**Architecture:** A five-operation expand/contract migration (add holding column → backfill + reconcile → drop → rename → retype into the real FK), copied from `0011_session_fk_uuid.py`, whose `backfill`/`restore`/`reconcile` helpers are already generic over `(table_name, column, target_table)`. Four application seams follow: a form initial shim, an audit projection, an anonymizer id translation, and a fixture regeneration.

**Tech Stack:** Django 6, PostgreSQL 18, pytest + pytest-django + pytest-xdist, `uv`, `make`.

**Read before starting:** [the design spec](../specs/2026-08-18-issue-847-purchase-fk-uuid-design.md). It carries the reasoning this plan only executes — in particular *why* the M2M is deferred and why that is not a shortcut.

## Global Constraints

- **Python 3.14 is mandatory.** A `SyntaxError` in an `except A, B:` line means the wrong interpreter, not broken code.
- **Drive everything through `make`.** Never `direnv exec .`, never raw `uv run`/`pytest`/`pnpm`.
- Iterate with `make check-fast`; **the gate is the full `make check`, including `e2e/`.** Never gate on a hand-picked subset.
- Focused runs: `make test ARGS="tests/test_purchase_fk_uuid.py -k migration -x"`. `PYTEST_WORKERS=0` when debugging a failure — parallel output interleaves.
- **Never write to a `GeneratedField`** (`price_per_game` on `Purchase`).
- Comments explain obscure code and intent only — no issue or PR references, no history narration.
- Name variables with complete words.
- Criterion values and search-endpoint option values stay **integer**. Nothing in this slice flips a value to a UUID.
- `Purchase.games` (M2M) is **out of scope**. If a step tempts you to touch `games__…`, `Purchase.games.through`, or `all_game_ids`' element type, stop and re-read the spec's scope section.

## File Structure

| Path | Responsibility | Task |
| --- | --- | --- |
| `games/models.py:313-321` | `related_game` gains `to_field="uuid"`; `games` gains the deferral comment | 1 |
| `games/migrations/0012_purchase_related_game_uuid.py` | **new** — the five-operation expand/contract | 1 |
| `tests/test_purchase_fk_uuid.py` | **new** — migration, ORM, integrity, form, tripwire | 1–4 |
| `games/forms.py:699` | `seed_related_initial` gains `"related_game"` | 3 |
| `games/management/commands/audit_library_ownership.py:196` | attname projection → relation lookup | 3 |
| `games/management/commands/anonymize_sample.py:194-197,247` | pk→uuid map for `related_game` | 4 |
| `games/management/commands/load_sample_data.py:74` | `reference_field="uuid"` | 5 |
| `games/fixtures/sample.yaml.gz` | 40 `related_game` values → uuid strings | 5 |
| `tests/test_library_commands.py:321` | `related_game: 999` → `ABSENT_GAME_UUID` | 5 |
| `tests/test_anonymize_sample.py:162` | assert the emitted value is a real game uuid | 4 |

---

### Task 1: The migration and the model

**Files:**
- Modify: `games/models.py:313-321`
- Create: `games/migrations/0012_purchase_related_game_uuid.py`
- Create: `tests/test_purchase_fk_uuid.py`

**Interfaces:**
- Consumes: `timetracker.uuidv7.UUIDv7Field`; `0011_session_fk_uuid`'s module-level `require_match(path, actual, expected)`, `backfill(cursor, table_name, column, target_table)`, `restore(...)`, `reconcile(cursor, table_name, column, target_table, label, *, nullable) -> (row_count, distinct_targets, null_count)`.
- Produces: migration node `("games", "0012_purchase_related_game_uuid")`; `Purchase.related_game_id` is now a `UUID`.

- [ ] **Step 1: Write the failing migration tests**

Create `tests/test_purchase_fk_uuid.py`. Copy the harness block from `tests/test_session_fk_uuid.py:1-115` verbatim — the `fk_uuid_harness` fixture (with its leaf-node restore, which exists so a down-migration does not strand this xdist worker's shared database behind head), `migrate_to_fk_uuid()`, `column_type()`, `foreign_key_target()` — changing only:

```python
BEFORE_FK_UUID = ("games", "0011_session_fk_uuid")
WITH_FK_UUID = ("games", "0012_purchase_related_game_uuid")
pytestmark = pytest.mark.django_db(transaction=True)
```

Write a `seed_historic_world(apps, *, username)` modelled on the session file's, creating through the **historic** `apps` registry: a user + `UserLibrary` + `PurchaseConversionState`, three `Game` rows, and four `Purchase` rows — two of type `Purchase.GAME` with `related_game=None`, two of type `dlc` pointing at different games. Historic `Purchase` rows need `price_currency` set (the model's `save()` requires it, but `bulk_create`/historic writes bypass `save()`; set it anyway so a later ORM read is realistic) and `date_purchased`.

Two tests:

```python
def test_forward_migration_repoints_the_related_game_relation(fk_uuid_harness):
    seed_historic_world(fk_uuid_harness, username="migrator")
    before = dict(
        fk_uuid_harness.get_model("games", "Purchase").objects.values_list(
            "pk", "related_game__name"
        )
    )

    new_apps = migrate_to_fk_uuid()

    after = dict(
        new_apps.get_model("games", "Purchase").objects.values_list(
            "pk", "related_game__name"
        )
    )
    assert after == before
    assert sum(1 for name in after.values() if name is None) == 2
    assert column_type("games_purchase", "related_game_id") == "uuid_v7"
    assert foreign_key_target("games_purchase", "related_game_id") == (
        "games_game",
        "uuid",
    )


def test_reverse_migration_restores_the_original_integer_ids(fk_uuid_harness):
    seed_historic_world(fk_uuid_harness, username="migrator")
    before = dict(
        fk_uuid_harness.get_model("games", "Purchase").objects.values_list(
            "pk", "related_game_id"
        )
    )

    migrate_to_fk_uuid()
    MigrationExecutor(connection).migrate([BEFORE_FK_UUID])
    old_apps = MigrationExecutor(connection).loader.project_state([BEFORE_FK_UUID]).apps

    after = dict(
        old_apps.get_model("games", "Purchase").objects.values_list(
            "pk", "related_game_id"
        )
    )
    assert after == before
    assert column_type("games_purchase", "related_game_id") == "bigint"
```

Comparing by `related_game__name` rather than by id is the point: it is the only comparison that stays meaningful across the type change.

- [ ] **Step 2: Run them to verify they fail**

```bash
make test ARGS="tests/test_purchase_fk_uuid.py -x -p no:randomly" PYTEST_WORKERS=0
```

Expected: `NodeNotFoundError` / `KeyError` on `("games", "0012_purchase_related_game_uuid")` — the migration does not exist.

- [ ] **Step 3: Change the model**

`games/models.py`, `Purchase.related_game` gains one line:

```python
    related_game = models.ForeignKey(
        Game,
        to_field="uuid",
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
        related_name="addon_purchases",
        verbose_name="Base game",
    )
```

And the deferral comment above `games` (`:280`). Keep it about the code, not the history:

```python
    # An auto-created many-to-many table always references the target's primary
    # key: ManyToManyField takes no to_field, and Django builds the
    # intermediary's foreign keys as plain ForeignKeys. So this link still
    # resolves through Game.id while every other Game relation resolves through
    # Game.uuid; it converts when Game.uuid becomes the primary key.
    games = models.ManyToManyField(Game, related_name="purchases")
```

- [ ] **Step 4: Write the migration**

`games/migrations/0012_purchase_related_game_uuid.py`. Copy `require_match`, `backfill`, `restore` and `reconcile` from `0011_session_fk_uuid.py` unchanged — they are already generic. (`0010`'s are *not*; they are platform-specific. Copy from `0011`.) Then:

```python
def fill_uuid_from_integer(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        backfill(cursor, "games_purchase", "related_game", "games_game")
        rows, related_games, nulls = reconcile(
            cursor,
            "games_purchase",
            "related_game",
            "games_game",
            "Purchase.related_game",
            nullable=True,
        )
    print(
        "FK identity rewritten "
        f"purchase_rows={rows} purchase_related_games={related_games} "
        f"purchase_related_game_nulls={nulls} unmatched=0"
    )


def fill_integer_from_uuid(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        restore(cursor, "games_purchase", "related_game", "games_game")
```

Five operations, in this order — **no leading `AlterField`**: ID-06's exists only to relax a `NOT NULL`, and this column is already nullable, so adding one would imply a constraint that does not exist.

1. `AddField` `purchase.related_game_uuid` = `UUIDv7Field(null=True, default=None, db_default=None, editable=False)`. The explicit `None`s suppress the field's own defaults so the column is added empty.
2. `RunPython(fill_uuid_from_integer, fill_integer_from_uuid)`.
3. `RunSQL("SET CONSTRAINTS ALL IMMEDIATE", reverse_sql=migrations.RunSQL.noop)` — every FK in this schema is `DEFERRABLE INITIALLY DEFERRED`; without this the `ALTER TABLE`s below fail with *"cannot ALTER TABLE because it has pending trigger events"*.
4. `RemoveField` `related_game`, then `RenameField` `related_game_uuid` → `related_game`.
5. `AlterField` `related_game` → the final `ForeignKey(Game, to_field="uuid", …)` — this one operation renames the column to `related_game_id`, creates the FK constraint and creates the index.

`dependencies = [("games", "0011_session_fk_uuid")]`.

- [ ] **Step 5: Run the migration tests**

```bash
make test ARGS="tests/test_purchase_fk_uuid.py -x -p no:randomly" PYTEST_WORKERS=0
```

Expected: PASS. If you see `operator does not exist: uuid_v7 = bigint`, a lookup somewhere still spells the attname — but at this stage it means the migration itself is wrong, since no application code has changed yet.

- [ ] **Step 6: Confirm no migration drift**

```bash
make check-migrations
```

Expected: clean. `makemigrations` would otherwise want to emit a single `AlterField`, which is unrunnable — PostgreSQL has no `integer`→`uuid` cast. The drift guard compares final state only, so a correct hand-written file leaves nothing to detect.

- [ ] **Step 7: Commit**

```bash
git add games/models.py games/migrations/0012_purchase_related_game_uuid.py tests/test_purchase_fk_uuid.py
git commit -m "feat: resolve the purchase base-game link through UUID identity"
```

---

### Task 2: ORM behaviour and the deferral tripwire

**Files:**
- Modify: `tests/test_purchase_fk_uuid.py`

**Interfaces:**
- Consumes: Task 1's migration; `tests/conftest.py`'s `owned_user` / `owned_library` fixtures.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the ORM and integrity tests**

Append to `tests/test_purchase_fk_uuid.py`. Define the shared fixtures first — Tasks 2 and 3 both use them, so they belong at module level:

```python
def _purchase(library, **overrides) -> Purchase:
    fields = {
        "library": library,
        "date_purchased": timezone.now().date(),
        "price": 10.0,
        "price_currency": "USD",
        "ownership_type": Purchase.DIGITAL,
        "type": Purchase.GAME,
    }
    return Purchase.objects.create(**{**fields, **overrides})


@pytest.fixture
def base_game(owned_library):
    return Game.objects.create(library=owned_library, name="Base")


@pytest.fixture
def other_game(owned_library):
    return Game.objects.create(library=owned_library, name="Other")


@pytest.fixture
def dlc_purchase(owned_library, base_game):
    return _purchase(
        owned_library,
        type=Purchase.DLC,
        name="Expansion",
        related_game=base_game,
    )
```

A `Purchase` whose `type` is not `GAME` **must** carry both `related_game` and `name`, or `save()` raises `ValidationError` — that is the model's own rule (`games/models.py:384`), not a form rule.

```python
def test_related_game_attname_reads_back_as_the_games_uuid(base_game, dlc_purchase):
    assert dlc_purchase.related_game_id == base_game.uuid


def test_purchase_filters_by_related_instance_and_by_integer_id(
    base_game, dlc_purchase
):
    assert Purchase.objects.filter(related_game=base_game).count() == 1
    assert Purchase.objects.filter(related_game__id=base_game.id).count() == 1


def test_addon_purchases_reverse_accessor_reaches_the_purchase(base_game, dlc_purchase):
    assert list(base_game.addon_purchases.all()) == [dlc_purchase]


def test_deleting_the_base_game_clears_the_link_without_deleting_the_purchase(
    base_game, dlc_purchase
):
    base_game.delete()
    dlc_purchase.refresh_from_db()
    assert dlc_purchase.related_game_id is None
    assert Purchase.objects.filter(pk=dlc_purchase.pk).exists()
```

`SET_NULL`, not cascade — that last test is the one that would catch a copy-paste of `Session.game`'s `CASCADE`.

The database-integrity test **must** use `bulk_create`: `Purchase.save()` calls `clean()`, which dereferences `self.related_game` through `_validate_related_library` and would raise in Python before PostgreSQL ever sees the row. ID-07 and ID-08 both hit this trap.

```python
def test_database_rejects_a_purchase_naming_a_game_uuid_no_game_owns(owned_library):
    orphan = Purchase(
        library=owned_library,
        date_purchased=timezone.now().date(),
        price_currency="USD",
        type=Purchase.DLC,
        name="Orphan",
    )
    orphan.related_game_id = uuid.uuid4()
    with pytest.raises(IntegrityError), transaction.atomic():
        Purchase.objects.bulk_create([orphan])
```

- [ ] **Step 2: Write the deferral tripwire**

This is the artifact that makes the M2M deferral a contract instead of a comment. Pin **both** through-table columns — pinning only `game_id` leaves ID-13 with no warning when it promotes `Purchase.uuid`.

```python
def test_the_purchase_games_through_table_is_still_integer_keyed():
    """The many-to-many link is deliberately left on integer ids.

    Django cannot point an auto-created intermediary at a non-primary-key
    field, so this table converts when Game.uuid and Purchase.uuid become the
    primary keys. Rewrite this test then; do not delete it now.
    """
    assert column_type("games_purchase_games", "game_id") == "bigint"
    assert column_type("games_purchase_games", "purchase_id") == "bigint"
    assert foreign_key_target("games_purchase_games", "game_id") == (
        "games_game",
        "id",
    )
    assert foreign_key_target("games_purchase_games", "purchase_id") == (
        "games_purchase",
        "id",
    )


def test_the_purchase_games_pair_is_still_unique(owned_library, base_game):
    purchase = _purchase(owned_library)
    purchase.games.add(base_game)
    through = Purchase.games.through
    with pytest.raises(IntegrityError), transaction.atomic():
        through.objects.create(purchase_id=purchase.pk, game_id=base_game.pk)
```

The uniqueness assertion must go through the through model directly: `purchase.games.add(base_game)` a second time is silently filtered by `_get_missing_target_ids` and would prove nothing.

- [ ] **Step 3: Run them**

```bash
make test ARGS="tests/test_purchase_fk_uuid.py -x" PYTEST_WORKERS=0
```

Expected: PASS, all of them, with no source changes — Task 1 already did the work these cover.

- [ ] **Step 4: Commit**

```bash
git add tests/test_purchase_fk_uuid.py
git commit -m "test: pin the base-game relation and the deferred many-to-many table"
```

---

### Task 3: The form shim and the audit projection

**Files:**
- Modify: `games/forms.py:699`
- Modify: `games/management/commands/audit_library_ownership.py:196`
- Modify: `tests/test_purchase_fk_uuid.py`

**Interfaces:**
- Consumes: `seed_related_initial(form, *field_names)` (`games/forms.py:180`), which already skips a field whose initial is a model instance.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing form test**

Without the shim, `model_to_dict` hands the widget a `UUID` while `_game_options` resolves integers through a `pk__in`, so the Base-game combobox renders empty on the edit page.

```python
def test_purchaseform_preselects_the_base_game_by_integer_id(
    owned_user, owned_library, base_game, dlc_purchase
):
    form = PurchaseForm(
        instance=dlc_purchase,
        library=owned_library,
        user=owned_user,
        presentation=PRESENTATION,
    )
    assert form["related_game"].value() == base_game.id


def test_purchaseform_posting_an_integer_id_saves_the_right_base_game(
    owned_user, owned_library, base_game, other_game, dlc_purchase
):
    form = PurchaseForm(
        {
            "games": [other_game.id],
            "date_purchased": "2026-01-01",
            "price": "1",
            "price_currency": "USD",
            "ownership_type": Purchase.DIGITAL,
            "type": Purchase.DLC,
            "related_game": str(base_game.id),
            "name": "Expansion",
        },
        instance=dlc_purchase,
        library=owned_library,
        user=owned_user,
        presentation=PRESENTATION,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.related_game_id == base_game.uuid
```

`PRESENTATION` is the module constant copied from `tests/test_session_fk_uuid.py:22-24`.

This is the **only** coverage of the shim. `e2e/test_widgets_e2e.py`'s five `related_game` cases (`:158`, `:271`, `:311`, `:460`, `:521`) all drive the *add* page, where the form is unbound and `seed_related_initial` short-circuits at `games/forms.py:195`.

- [ ] **Step 2: Run it to verify it fails**

```bash
make test ARGS="tests/test_purchase_fk_uuid.py -k purchaseform -x" PYTEST_WORKERS=0
```

Expected: FAIL — `form["related_game"].value()` is a `UUID`, not the integer pk.

- [ ] **Step 3: Add the shim**

`games/forms.py:699`, one argument:

```python
        seed_related_initial(self, "platform", "related_game")
```

Do **not** add `"games"`. For a `ManyToManyField`, `model_to_dict` returns model *instances*, which `ModelMultipleChoiceField.prepare_value` already maps back to integer pks — the M2M is self-consistent and seeding it would be a no-op at best.

- [ ] **Step 4: Run it to verify it passes**

```bash
make test ARGS="tests/test_purchase_fk_uuid.py -k purchaseform -x" PYTEST_WORKERS=0
```

Expected: PASS.

- [ ] **Step 5: Fix the audit projection**

`games/management/commands/audit_library_ownership.py:196`:

```python
            .values_list("pk", "related_game__id")
```

`related_game__id` yields the target's **integer** pk, which is what the through-table line at `:208` already prints — the point of the rewrite is that the report cannot start printing two kinds of id at once. ID-07 and ID-08 moved the other four projections for the same reason.

- [ ] **Step 6: Run the audit command's tests**

```bash
make test ARGS="tests/test_library_commands.py -k ownership" PYTEST_WORKERS=0
```

Expected: PASS unchanged. `tests/test_library_commands.py:539` asserts the `"Purchase.related_game"` violation line; the ids in it stay integer.

- [ ] **Step 7: Commit**

```bash
git add games/forms.py games/management/commands/audit_library_ownership.py tests/test_purchase_fk_uuid.py
git commit -m "fix: seed the purchase base-game field and audit it by relation"
```

---

### Task 4: The anonymizer

**Files:**
- Modify: `games/management/commands/anonymize_sample.py:194-197,247`
- Modify: `tests/test_anonymize_sample.py:162`

**Interfaces:**
- Consumes: `all_game_ids` (`anonymize_sample.py:140`), a list of integer `Game` pks.
- Produces: `games/fixtures/sample.yaml.gz` regeneration is Task 5's, not this one's — this task fixes the command that would generate it.

- [ ] **Step 1: Strengthen the existing assertion**

`tests/test_anonymize_sample.py:162` currently only asserts the emitted value is not `None`. Make it prove the translation:

```python
            if fields["type"] != Purchase.GAME:
                self.assertIn(
                    str(fields["related_game"]),
                    {str(item["fields"]["uuid"]) for item in by_model["games.game"]},
                    "related_game must name a game uuid carried by the same dump",
                )
```

- [ ] **Step 2: Run it to verify it fails**

```bash
make test ARGS="tests/test_anonymize_sample.py -x" PYTEST_WORKERS=0
```

Expected: FAIL. Two tests should go red — the strengthened `test_output_invariants` and `test_output_reloads_via_loaddata` (`:174`), which is the one that catches this even without the new assertion: `_build_dataset` creates a DLC purchase with `related_game=base_game` (`:46-55`), and an untranslated integer into a `uuid_v7` column fails on `bulk_update`.

- [ ] **Step 3: Translate the id**

`anonymize_sample.py`. The comprehension at `:194-197` already runs the query that carries both values — widen its loop rather than adding a second query:

```python
games_by_pk = {
    game.pk: game
    for game in Game.objects.filter(pk__in=all_game_ids).only("pk", "uuid")
}
game_offsets_by_uuid = {game.uuid: game_offsets[pk] for pk, game in games_by_pk.items()}
```

Then `:247`:

```python
                purchase.related_game_id = games_by_pk[random.choice(all_game_ids)].uuid
```

Keep sampling `all_game_ids` and translate the result. `all_game_ids` must stay integer regardless: the through-row build at `:251` (`Through(purchase_id=…, game_id=…)`) still needs Game pks, per the deferral.

- [ ] **Step 4: Run the anonymizer tests**

```bash
make test ARGS="tests/test_anonymize_sample.py" PYTEST_WORKERS=0
```

Expected: PASS, including the determinism test — `random.choice` consumes the RNG identically, so the byte-for-byte output per `--seed` is unchanged apart from the translated values.

- [ ] **Step 5: Commit**

```bash
git add games/management/commands/anonymize_sample.py tests/test_anonymize_sample.py
git commit -m "fix: emit the base-game link as a uuid when anonymizing"
```

---

### Task 5: The committed fixture and its loader

**Files:**
- Modify: `games/management/commands/load_sample_data.py:74`
- Modify: `games/fixtures/sample.yaml.gz`
- Modify: `tests/test_library_commands.py:321`

**Interfaces:**
- Consumes: `FixtureRelationship(field, target_model, many, required, reference_field="pk")`.
- Produces: a fixture whose `games.purchase.related_game` values are uuid strings.

- [ ] **Step 1: Declare the reference field**

`games/management/commands/load_sample_data.py:74`:

```python
(
    FixtureRelationship(
        "related_game", "games.game", False, False, reference_field="uuid"
    ),
)
```

Leave the `games` entry on `reference_field="pk"` — its list still carries Game pks.

The validator derives its reference index generically from this field; the comment at `:178` names this exact move as the case it was built for, so nothing else in the loader changes.

- [ ] **Step 2: Move the sentinel test case**

`tests/test_library_commands.py:321` — the `related_game` parameter case now has to name a *uuid* the fixture does not carry, or it stops testing the rejection path and starts failing on a type error:

```python
(
    (
        "games.purchase",
        {"library": "__target_library__", "related_game": ABSENT_GAME_UUID},
        "Game",
    ),
)
```

Leave the sibling `{"games": [999]}` case at `:316` on an integer — it still covers the pk reference path, and it is the regression guard for the deferral.

- [ ] **Step 3: Run the loader tests to verify they fail**

```bash
make test ARGS="tests/test_library_commands.py -x" PYTEST_WORKERS=0
```

Expected: FAIL in `test_committed_sample_load_owns_private_rows_and_reuses_shared_platform` (`:197`) — the committed blob still carries integer `related_game` values, which no longer deserialize. **This is the gate.** It loads the real committed fixture under `@pytest.mark.django_db(transaction=True)`, so a botched regeneration is a hard `make check` failure rather than a dev-only annoyance.

- [ ] **Step 4: Regenerate the fixture**

A database round trip does not work here: loading the old blob needs pre-cutover code while the migration needs post-cutover code. Use a throwaway, **uncommitted** transform in the scratchpad:

```python
import gzip
import yaml

path = "games/fixtures/sample.yaml.gz"
records = yaml.safe_load(gzip.open(path, "rt"))
uuid_by_pk = {
    record["pk"]: record["fields"]["uuid"]
    for record in records
    if record["model"] == "games.game"
}
rewritten = 0
for record in records:
    if record["model"] != "games.purchase":
        continue
    related_game = record["fields"]["related_game"]
    if related_game is None:
        continue
    record["fields"]["related_game"] = str(uuid_by_pk[related_game])
    rewritten += 1
print("rewritten", rewritten)
payload = yaml.safe_dump(records, sort_keys=True, default_flow_style=False).encode()
open(path, "wb").write(gzip.compress(payload, compresslevel=9, mtime=0))
```

`mtime=0` and no embedded filename are what keep the blob a stable git object — this mirrors `anonymize_sample._write_fixture` exactly. Run it with `make shell` or through a `make`-driven script; do not reach for a raw `uv run`.

- [ ] **Step 5: Verify the regeneration**

Record this in the PR body. Expected values, all confirmed against the pre-change blob:

| Check | Expected |
| --- | --- |
| `rewritten` printed by the transform | 40 |
| per-model record counts | 851 game, 2718 session, 795 purchase, 203 playevent, 25 platform, 14 device, 75 exchangerate |
| `related_game` nulls | 755 |
| total entries across all `games:` lists | 4505 (**unchanged** — the M2M is untouched) |
| fields differing from the old blob | only the 40 `related_game` values |
| each new value | resolves to exactly one `games.game` `uuid` in the same blob |

- [ ] **Step 6: Run the loader tests to verify they pass**

```bash
make test ARGS="tests/test_library_commands.py" PYTEST_WORKERS=0
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add games/management/commands/load_sample_data.py games/fixtures/sample.yaml.gz tests/test_library_commands.py
git commit -m "fix: reference the sample fixture's base game by uuid"
```

The fixture and the migration are a single unit for rollback purposes: `manage.py migrate games 0011` restores the integer column, and reverting it requires reverting this blob too.

---

### Task 6: Full gate

**Files:** none — this task only runs and, if needed, repairs.

- [ ] **Step 1: Run the full gate**

```bash
make check
```

Expected: green. This is lint + format-check + mypy + ts-check + icon drift + migration drift + vitest + the **entire** pytest suite including `e2e/`. Never substitute a subset.

- [ ] **Step 2: If something is red, read it against these**

- `operator does not exist: uuid_v7 = bigint` — a lookup still spells `related_game_id` as an attname. The spec's sweep says there is exactly one (the audit projection, Task 3); a second means the sweep missed a site, so grep before patching.
- A `UUID` reaching `_game_options`' `pk__in` — the form shim is missing or was given the wrong field name.
- `DeserializationError` or a foreign-key violation loading the sample fixture — the regeneration or the `reference_field` declaration.
- Do **not** run `make test-e2e` while `make dev` is running: its watchers rewrite the served assets underneath the browser and produce mass phantom failures.

- [ ] **Step 3: Do not fix a red `make check` by narrowing the run**

If a failure looks unrelated to this change, confirm it fails on `origin/main` too before setting it aside, and say so explicitly in the PR.

---

### Task 7: Propagate to the sibling issues

The spec's handoffs are only real once they are on GitHub. The design work is already committed (`ec67c9ff`); this task carries it outward.

- [ ] **Step 1: Comment on #646 (ID-11)**

It inherits the largest share. Cover: the `games_purchase_games.game_id` expand/contract (add UUID holding column → `UPDATE … FROM games_game` → drop → rename → restore the FK **and** the `(purchase, game)` unique index that `DROP COLUMN` cascades away); that the migration *state* needs no operation because an auto-created through derives its foreign keys from the target's pk; that `to_field="uuid"` must be deleted from every FK naming `Game.uuid` or `Platform.uuid`, since it becomes `fields.E312` the moment the field is renamed; the `seed_related_initial` arguments; `audit_library_ownership`'s `related_game__id`/`platform__id`; `PurchaseFilter._games_to_q`'s `int(...)` coercion; and `GameOption.value: int` (`games/api.py:129-132`), which is the response schema of all three search endpoints and raises a pydantic `ValidationError` on a `UUID` — the promotion 500s the endpoint rather than flipping it for free.

- [ ] **Step 2: Comment on #849 (ID-13)**

The mirror-image conversion of `games_purchase_games.purchase_id`, with the same unique-index cascade. Note that ID-09's tripwire test pins this column and will fail loudly when ID-13 moves it.

- [ ] **Step 3: Comment on #645 (ID-10)**

Two columns are still integers when its audit runs, both on `games_purchase_games`, and neither is a gap: `game_id` is anomalous (deferred here — the only `Game` reference that did not move in Wave C), `purchase_id` is normal until ID-13. `auth.User` is not a converted model, so `UserLibrary.user` and `UserPreferences.user` stay integer throughout.

- [ ] **Step 4: Comment on #847**

The scope reduction and its reason, linking the design spec.

- [ ] **Step 5: Open the PR**

Body carries: the reconciliation evidence line printed by the migration, the fixture verification table from Task 5 Step 5, and a statement that the full `make check` is green.

---

## Notes for the implementer

- **The deferral is a decision, not an omission.** Four Django facts back it, each verified against the installed 6.0.7: `ManyToManyField` takes no `to_field`; `create_many_to_many_intermediary_model` builds plain `ForeignKey`s; `Serializer.handle_m2m_field` bails on a non-auto-created through, so `dumpdata` drops the `games` key entirely; and `deserialize_m2m_values` converts through the target's pk, so the fixture's lists cannot carry uuids. If a reviewer asks "why not just do the M2M too", that is the answer.
- **`Purchase` has no `class Meta` at all.** ID-07's cascade trap — `DROP COLUMN` silently taking a unique index with it while Django's migration state still lists it — has nothing to take down and restore on this model. It *does* apply to the through table, which is why Task 2 asserts the unique pair is still enforced.
- `Purchase.price_per_game` is a `GeneratedField`. Never assign it.
