# CAT-05 Provider-Neutral External References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-neutral, target-safe external-reference map with deterministic outbound links; migrate legacy Game Wikidata identities exactly; and keep the current Game form/field synchronized and clickable through its thin compatibility path.

**Architecture:** Store one canonical provider/kind/key tuple with one of four database-enforced catalog foreign-key targets. Centralize normalization, trusted provider URL templates, deterministic lookup/link generation, and idempotent/conflict-safe persistence in a focused service, then call its Wikidata synchronizer from an outer transaction in the existing thin Game-form adapter. Create and backfill the schema in one fail-closed atomic migration and render the current canonical Wikidata value as a policy-built link.

**Tech Stack:** Python 3.14, Django 6 ORM/migrations, PostgreSQL 17, pytest-django, pytest-xdist, Make.

**Spec:** `docs/superpowers/specs/2026-08-20-issue-652-external-references-design.md`

## Global Constraints

- Treat issue #652, the overhaul charter, and the catalog foundation wave as authoritative.
- The canonical tuple is `(provider, entity_kind, provider_key)` and resolves to one existing Game, Edition, Release, or Platform UUID.
- `provider` names the external namespace; `provider_key` is that provider's identifier rather than a URL; `entity_kind` declares whether it identifies an internal Game, Edition, Release, or Platform.
- Store exactly one typed catalog foreign-key target and enforce declared-kind/target agreement in PostgreSQL and model validation.
- Normalize provider names by explicit policy. For Wikidata, trim and uppercase the key and require `Q[1-9][0-9]*`.
- Each provider policy owns one trusted HTTPS URL template. It may use `{entity_kind}` and must use `{provider_key}`; Wikidata uses `https://www.wikidata.org/wiki/{provider_key}`. Build links only after kind validation, canonicalization, and path-segment encoding.
- Store neither repeated complete URLs nor editable per-row templates. `ExternalReference.external_url` and the provider URL builder are the consumer contract.
- Unknown providers and blank/malformed reference keys fail closed; add no speculative IGDB/store policies.
- Preserve Game UUIDs, catalog hierarchy UUIDs/relationships, all non-Wikidata fields, and equal-name rows. Never merge or infer identity.
- Duplicate or malformed normalized nonblank legacy values must all be reported and abort before data writes.
- Whitespace-only legacy Wikidata becomes `""` and creates no reference; every valid nonblank value maps to exactly one Game reference with the same Game UUID.
- Keep the current Game Wikidata form/list field and label. Canonicalize through `GameForm.clean_wikidata()`, synchronize through the existing thin adapter, and render a nonblank list value as a link whose text remains the canonical key; do not switch reads to the reference table or add compatibility behavior to the durable catalog writer.
- A tuple already mapped to another target is never silently reassigned.
- Keep schema/data migration atomic. Refuse reverse migration when any reference exists; production rollback is verified database restore plus the prior image.
- Add no auth/client/cache/source-record/refresh/helper-route/import/matching/tombstone/redirect behavior.
- Run normal verification with the Makefile's unchanged default `PYTEST_WORKERS`; do not set it to `0`.
- Stop and return to the design gate if actual scope crosses three independent runtime subsystems, 40 files, or 2,000 non-generated changed lines.

## File structure

- Modify `games/models.py`: add the target-safe `ExternalReference` model/constraints.
- Create `games/external_references.py`: provider registry with trusted URL templates, normalization, URL building, idempotent persistence, deterministic UUID lookup, and temporary Game Wikidata synchronization.
- Create `games/migrations/0022_external_references.py`: schema, fail-closed legacy preflight/backfill, exact reconciliation, idempotency proof, and reverse guard.
- Modify `games/forms.py`: canonicalize and validate the existing Wikidata field.
- Modify `games/catalog_compat.py`: synchronize Wikidata with an outer transaction around the existing writer.
- Modify `games/views/game.py`: render a canonical nonblank Wikidata value as a policy-built link while keeping the legacy display source.
- Create `tests/test_external_references.py`: model, constraint, provider policy, persistence, lookup, and deletion contracts.
- Create `tests/test_external_reference_migration.py`: migration mapping, reconciliation, rollback, idempotency, and reverse behavior.
- Create `tests/test_catalog_compat.py`: adapter-level synchronization and graph/reference rollback.
- Modify `tests/test_catalog_write_views.py`: current form/display behavior, canonicalization, exact link destination, blank rendering, and validation.
- Remove this plan and its paired design only after all implementation and verification gates pass; preserve their planning commit in branch history.

## Planning gate checkpoint

Commit this plan and paired design before changing tests or runtime code. Stop
and obtain explicit user approval. Do not begin Task 1 on the same turn that
presents the planning artifacts.

---

### Task 1: Define provider policies and target-safe model contracts

**Files:**
- Create: `tests/test_external_references.py`
- Create later: `games/external_references.py`
- Modify later: `games/models.py`
- Create later: `games/migrations/0022_external_references.py`

**Interfaces:**
- Produces `ExternalReference.Provider.WIKIDATA == "wikidata"`.
- Produces entity kinds `game`, `edition`, `release`, and `platform`.
- Produces `normalize_provider(provider: str) -> str` and `normalize_provider_key(*, provider: str, provider_key: str) -> tuple[str, str]`.
- Produces `external_reference_url(*, provider: str, entity_kind: str, provider_key: str) -> str` using the provider policy's trusted URL template.
- Produces `ExternalReference.target_uuid: UUID`, `ExternalReference.external_url: str`, and four nullable target foreign keys with reverse name `external_references`.

- [ ] **Step 1: Write provider normalization tests**

Add parametrized tests proving `" WikiData "` plus `" q123 "` normalize to
`("wikidata", "Q123")`; `Q1` and large positive Q-numbers pass; `""`,
whitespace, `Q0`, `Q01`, negative, suffixed, embedded-whitespace, and non-Q
keys raise `ValidationError`; and an unknown provider raises
`ValidationError` rather than using a generic policy. Assert
`external_reference_url(provider=" WikiData ", entity_kind="game",
provider_key=" q123 ") ==
"https://www.wikidata.org/wiki/Q123"` and that malformed/unknown input never
produces a URL.

- [ ] **Step 2: Run normalization tests to verify RED**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_external_references.py -k normalization -q
```

Expected: collection/import failure because `games.external_references` and
`ExternalReference` do not exist.

- [ ] **Step 3: Implement the minimal explicit provider registry**

Create `games/external_references.py` with a compiled full-match Wikidata regex,
a frozen `ProviderPolicy` containing `normalize_key` and `url_template`, and
these exact signatures:

```python
@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    normalize_key: Callable[[str], str]
    url_template: str


def _normalize_wikidata_key(provider_key: str) -> str:
    key = provider_key.strip().upper()
    if not WIKIDATA_KEY_PATTERN.fullmatch(key):
        raise ValidationError(
            {"provider_key": "Enter a Wikidata entity ID such as Q123."}
        )
    return key


PROVIDER_POLICIES = {
    "wikidata": ProviderPolicy(
        normalize_key=_normalize_wikidata_key,
        url_template="https://www.wikidata.org/wiki/{provider_key}",
    ),
}


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().casefold()
    if normalized not in PROVIDER_POLICIES:
        raise ValidationError({"provider": "Unsupported external-reference provider."})
    return normalized


def normalize_provider_key(
    *, provider: str, provider_key: str
) -> tuple[str, str]:
    provider = normalize_provider(provider)
    return provider, PROVIDER_POLICIES[provider].normalize_key(provider_key)


def external_reference_url(
    *, provider: str, entity_kind: str, provider_key: str
) -> str:
    if entity_kind not in {"game", "edition", "release", "platform"}:
        raise ValidationError({"entity_kind": "Unsupported catalog entity kind."})
    provider, key = normalize_provider_key(
        provider=provider, provider_key=provider_key
    )
    policy = PROVIDER_POLICIES[provider]
    return policy.url_template.format(
        entity_kind=quote(entity_kind, safe=""),
        provider_key=quote(key, safe=""),
    )
```

Register Wikidata with the exact trusted template
`https://www.wikidata.org/wiki/{provider_key}`. Do not read a URL template from
form input or an `ExternalReference` row.

Keep imports of concrete catalog models inside persistence functions or behind
`TYPE_CHECKING`, so `games.models` can import the normalization helper without
a module cycle.

- [ ] **Step 4: Write model and database-integrity tests**

For each of Game, Edition, Release, and Platform, create one reference and
assert a UUIDv7 primary key, the canonical tuple, exactly one non-NULL target,
the expected entity kind, `target_uuid`, exact `external_url`, and reverse
manager. Add tests that:

- attempt the same provider/kind/key twice and receive `IntegrityError`;
- construct a mismatched kind/target and receive `ValidationError` on save;
- bypass model validation with `QuerySet.update` to prove PostgreSQL's check
  rejects a mismatched or multiple-target row;
- prove the database rejects a noncanonical/malformed Wikidata key; and
- delete each target and prove its reference cascades without affecting other
  target rows.

- [ ] **Step 5: Run model tests to verify RED**

Run the full new file. Expected failures identify the absent model/table and
constraints, not fixture ownership errors.

- [ ] **Step 6: Implement the model state and schema operation**

Add `ExternalReference` after `Release` in `games/models.py` with UUIDv7 `id`,
`provider = CharField(max_length=50)`,
`entity_kind = CharField(max_length=20)`,
`provider_key = CharField(max_length=255)`, and nullable
`game`/`edition`/`release`/`platform` foreign keys. Add:

- `UniqueConstraint(fields=("provider", "entity_kind", "provider_key"),
  name="unique_external_reference_provider_kind_key")`;
- one four-branch `CheckConstraint` named
  `external_reference_kind_matches_target`;
- canonical-provider and canonical-Wikidata-key database checks named
  `external_reference_supported_provider` and
  `external_reference_canonical_provider_key`;
- `clean()` that normalizes the tuple and raises field-addressable errors for
  target mismatch; and
- `external_url` that delegates to `external_reference_url`; and
- `save()` that calls `clean()` before `super().save()`.

Start `games/migrations/0022_external_references.py` with the matching
`CreateModel` state and constraints, depending on `0021_alter_game_library`.
Do not add `RunPython` yet.

- [ ] **Step 7: Run focused model tests to GREEN**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_external_references.py -q
```

Expected: provider/model/constraint tests pass.

- [ ] **Step 8: Commit the independently testable schema contract**

```bash
git add games/models.py games/external_references.py games/migrations/0022_external_references.py tests/test_external_references.py
git commit -m "feat: add target-safe external references"
```

---

### Task 2: Add deterministic persistence and lookup services

**Files:**
- Modify: `tests/test_external_references.py`
- Modify later: `games/external_references.py`

**Interfaces:**
- Produces `CatalogTarget = Game | Edition | Release | Platform` for typing.
- Produces `save_external_reference(*, provider: str, provider_key: str, target: CatalogTarget) -> ExternalReference`.
- Produces `resolve_external_reference(*, provider: str, entity_kind: str, provider_key: str) -> UUID | None`.
- Produces `sync_game_wikidata(*, game: Game) -> ExternalReference | None`.

- [ ] **Step 1: Write persistence and lookup tests**

Add tests proving all four target types derive their kind/field without caller
input; a repeated canonical-equivalent save returns the same reference UUID;
a tuple mapped to a second same-kind target raises `ValidationError` and keeps
the first mapping; unsupported target classes fail; lookups normalize provider
and key, return the exact target UUID or `None`, never cross entity kinds, and
reject invalid kinds/providers/keys.

- [ ] **Step 2: Write synchronization tests**

Create a Game with one Wikidata reference and prove `sync_game_wikidata`:

- retains its reference UUID when the canonical key is unchanged;
- replaces the old mapping when the legacy key changes;
- deletes Game-kind Wikidata mappings and returns `None` when blank;
- does not delete Edition/Release/Platform references; and
- raises on a key owned by another Game, leaving both Games' prior mappings
  unchanged after the transaction exits.

- [ ] **Step 3: Run service tests to verify RED**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_external_references.py -k 'save_external or resolve_external or sync_game' -q
```

Expected: import/attribute failures for the absent service functions.

- [ ] **Step 4: Implement target metadata and conflict-safe save**

Inside functions, import Game/Edition/Release/Platform/ExternalReference and map
each exact model class to `(entity_kind, target_field)`. Normalize first, then
run `save_external_reference` inside `transaction.atomic`: lock the normalized
tuple with `select_for_update`, create it with only the derived target field
when absent, and resolve an absent-row uniqueness race through a nested
savepoint plus locked refetch. Return the row for the exact same target, and raise
`ValidationError({"provider_key": "This external reference already maps to another catalog target."})`
for a different target. Do not use `update_or_create`, because reassignment is
forbidden.

- [ ] **Step 5: Implement deterministic UUID lookup**

Validate `entity_kind` against the four exact values, map it to one FK ID field,
then use `.filter(provider=..., entity_kind=..., provider_key=...).values_list(target_id_field, flat=True).first()`.
Uniqueness makes zero/one deterministic; do not query or return another target
kind and do not fetch the target model.

- [ ] **Step 6: Implement Game Wikidata synchronization**

Under `transaction.atomic`, lock the Game's existing Game-kind Wikidata
references. For blank `game.wikidata`, delete only those rows. For nonblank,
normalize and assign the canonical legacy value, retain only the exact tuple,
then call `save_external_reference`. Ensure a later conflict rolls back any
earlier deletion.

- [ ] **Step 7: Run the full focused service file to GREEN**

Run `tests/test_external_references.py` and confirm every model/service test
passes.

- [ ] **Step 8: Commit the service slice**

```bash
git add games/external_references.py tests/test_external_references.py
git commit -m "feat: resolve canonical external references"
```

---

### Task 3: Migrate Wikidata identities with exact reconciliation

**Files:**
- Create: `tests/test_external_reference_migration.py`
- Modify later: `games/migrations/0022_external_references.py`

**Interfaces:**
- Produces `backfill_external_references(apps, schema_editor)` in migration `0022`.
- Produces machine prefix `EXTERNAL_REFERENCE_RECONCILIATION_JSON=` and human prefix `CAT external reference reconciliation:`.
- Produces populated reverse refusal before `DeleteModel` and empty-table reverse allowance.

- [ ] **Step 1: Build the migration harness and mixed source world**

Use `MigrationExecutor` with `BEFORE_EXTERNAL_REFERENCES = ("games",
"0021_alter_game_library")` and `WITH_EXTERNAL_REFERENCES = ("games",
"0022_external_references")`. Seed two libraries, shared/private Platforms,
three Games with canonical `Q123`, padded lowercase ` q456 `, and whitespace
Wikidata, plus default/non-default Editions/Releases and representative Session,
PlayEvent, status-history, Purchase related-Game, and Purchase–Game links.
Snapshot every Game field and all catalog/incoming relationship UUIDs.

- [ ] **Step 2: Write the exact happy-path mapping test**

After forward migration, assert Game UUIDs and every non-Wikidata field/related
UUID are exact; legacy values are `Q123`, `Q456`, and `""`; exactly two
references target the corresponding Game UUIDs; no reference targets another
kind; and lookup tuples ordered by provider/kind/key/target are literal.

Capture stdout, parse the one machine-prefix line, and compare the complete
payload with literal counts from the fixture. Compare the complete human line
in the design's exact key order. Assert `schema_version == 1`, empty mismatches,
`legacy_nonblank == wikidata_game_references == wikidata_references == 2`,
`legacy_blank == 1`, `normalized_legacy_values == 2`, and
`inserted_references == 2`.

- [ ] **Step 3: Run the happy-path test to verify RED**

Run the single test. Expected: migration succeeds at schema creation but lacks
references/reconciliation until the RunPython operation is added.

- [ ] **Step 4: Implement deterministic snapshots and preflight**

In migration `0022`, define `BATCH_SIZE = 1000`, exact summary keys/prefixes,
JSON/human scalar conversion, and a Game snapshot ordered by UUID. Normalize
legacy strings in memory without importing live code. Collect all
`malformed_wikidata` objects and group canonical keys to collect one
`duplicate_normalized_wikidata` object per duplicate key with sorted Game UUIDs.
Sort all mismatches; emit the full report; and raise the exact documented
`RuntimeError` before `bulk_update` or `bulk_create` when any exist.

- [ ] **Step 5: Implement batched ensure and exact result checks**

Bulk-update only Games whose Wikidata spelling changes. Use the exact preserved
field tuple `library_id`, `name`, `sort_name`, `original_year_released`,
`year_released`, `original_release_date`, `platform_id`, `status`, `mastered`,
`playtime`, `created_at`, and `updated_at`; generated temporal projections are
checked through the canonical `original_release_date` source. Read existing
Wikidata/Game references into a tuple map, create only absent expected tuples
with UUIDv7 IDs supplied by the migration state, and reject an existing tuple
with the wrong Game target. Run the ensure helper twice and capture ordered
reference identity/tuple/target rows after each pass.

Reconciliation must append all missing/extra Games, changed preserved fields,
legacy/reference count mismatches, wrong target UUIDs, blank-Game references,
extra Game references, target-kind violations, and non-idempotent second-pass
changes. Emit all mismatches before raising. Do not call live models or
`games.external_references`.

- [ ] **Step 6: Wire atomic forward and reverse functions**

Append `migrations.RunPython(backfill_external_references,
reverse_external_references)` after `CreateModel`. Keep the default atomic
migration. `reverse_external_references` checks the frozen model and raises
`RuntimeError("Cannot reverse external references while reference rows exist.")`
when populated; it returns without mutation only when the table is empty.

- [ ] **Step 7: Run the happy path to GREEN**

Run the single mapping test and inspect the exact stdout assertions.

- [ ] **Step 8: Add all-at-once preflight and rollback coverage**

Seed padded `q7` and canonical `Q7` on different Games plus malformed `Q0` and
`not-an-id`. Assert the machine mismatch array contains two malformed objects
and one duplicate group in deterministic order, all exact human lines appear,
and the final exception reports three mismatches. Rebuild the executor and
prove the leaf remains `0021`, every legacy spelling is unchanged, and the
external-reference table does not exist. This explicitly proves abort before
data writes and transaction rollback.

- [ ] **Step 9: Add post-write, idempotency, empty, and reverse tests**

Monkeypatch a migration reconciliation helper to force one post-write mismatch;
assert the migration leaf/data/schema all roll back. After a successful
migration, call `backfill_external_references` directly with frozen `0022` apps
and assert zero inserts, unchanged reference UUIDs, and a second zero-mismatch
report. Pin the exact all-zero report for an empty database. Assert reverse to
`0021` refuses while references exist, then separately prove an empty database
can reverse and migrate forward again.

- [ ] **Step 10: Run migration tests and catalog regressions to GREEN**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_external_reference_migration.py tests/test_catalog_hierarchy_migration.py tests/test_shared_catalog_migration.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit the migration slice**

```bash
git add games/migrations/0022_external_references.py tests/test_external_reference_migration.py
git commit -m "feat: migrate legacy Wikidata references"
```

---

### Task 4: Synchronize the current thin Game compatibility adapter

**Files:**
- Create: `tests/test_catalog_compat.py`
- Modify: `tests/test_catalog_write_views.py`
- Modify later: `games/forms.py`
- Modify later: `games/catalog_compat.py`
- Modify later: `games/views/game.py`

**Interfaces:**
- `GameForm.clean_wikidata()` canonicalizes blank/nonblank legacy Wikidata with the shared provider policy and rejects a tuple owned by another Game.
- `save_legacy_game_form(form)` wraps `save_private_game(...)` and `sync_game_wikidata(game=game)` in one outer atomic transaction.
- `save_private_game(...)` remains the durable compatibility-free catalog writer with its current signature.
- Current Game form/list continues reading `Game.wikidata` with the same field and label; a nonblank list value becomes `Link(href=external_reference_url(...))[game.wikidata]`.

- [ ] **Step 1: Write adapter synchronization tests**

Create `tests/test_catalog_compat.py` to prove create with ` q123 ` stores
`Q123` in both legacy/reference state; an unchanged edit retains reference UUID;
changing to `Q456` replaces the mapping; clearing deletes it; a key already
owned by another Game rolls back Game/default graph/old reference state; and a
forced reference-save failure rolls back both a new Game graph and edits to an
existing graph. Add a guard that direct `save_private_game(...)` keeps its
current responsibility and does not create an external reference by itself.

- [ ] **Step 2: Write view/form compatibility tests**

Extend `tests/test_catalog_write_views.py` to POST padded lowercase Wikidata on
add/edit and assert successful redirects, canonical legacy/reference values,
and the unchanged Wikidata form field/list column. Assert the list response
contains an anchor whose text is `Q123` and whose exact escaped `href` is
`https://www.wikidata.org/wiki/Q123`; a blank value has no outbound anchor.
POST `Q0` and assert a normal field error with no Game/reference writes. Post a
duplicate key and assert a field-addressable validation response plus unchanged
persisted state, not an unhandled error.

- [ ] **Step 3: Run focused tests to verify RED**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_compat.py tests/test_catalog_write_views.py -k wikidata -q
```

Expected: missing synchronization/canonicalization assertions fail.

- [ ] **Step 4: Add legacy form validation**

In `GameForm.clean_wikidata()`, canonicalize whitespace-only Wikidata to `""`;
otherwise call
`normalize_provider_key(provider="wikidata", provider_key=value)`. Query the
canonical `(wikidata, game, key)` tuple, excluding the current Game target on
edit, and raise `forms.ValidationError` when another Game owns it. Return the
canonical key so the existing ModelForm instance stores the same spelling.

- [ ] **Step 5: Synchronize inside the thin adapter transaction**

Decorate `save_legacy_game_form` with `transaction.atomic`. After
`save_private_game(...)` returns the Game/default Edition/default Release, call
`sync_game_wikidata(game=graph.game)` before returning the Game. Keep
`save_private_game` unchanged. Form validation handles ordinary duplicates;
the service/database constraint remains the race-safe backstop and any failure
rolls the outer adapter transaction back.

- [ ] **Step 6: Render the canonical Wikidata value as a trusted link**

In `games/views/game.py`, replace only the current raw nonblank Wikidata cell
value with:

```python
Link(
    href=external_reference_url(
        provider="wikidata", entity_kind="game", provider_key=game.wikidata
    )
)[game.wikidata]
if game.wikidata
else ""
```

Keep the current `Wikidata` column heading and legacy value source. The trusted
policy emits HTTPS and the component escapes attributes/text; do not use
`Safe`, `target="_blank"`, or per-row URL data.

- [ ] **Step 7: Run focused adapter/view tests to GREEN**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_compat.py tests/test_catalog_write_views.py tests/test_external_references.py -q
```

Confirm rollback assertions reload database state outside the failed atomic
block and link assertions compare the exact canonical text and destination.

- [ ] **Step 8: Run existing catalog regression suites**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_hierarchy.py tests/test_catalog_writes.py tests/test_catalog_write_views.py tests/test_library_api_isolation.py -q
```

Expected: PASS with current forms, visibility, and private mutation behavior
unchanged; the intended display delta is the canonical Wikidata text becoming
an exact policy-built anchor.

- [ ] **Step 9: Commit the compatibility slice**

```bash
git add games/forms.py games/catalog_compat.py games/views/game.py tests/test_catalog_compat.py tests/test_catalog_write_views.py
git commit -m "feat: synchronize legacy Wikidata writes"
```

---

### Task 5: Complete verification, scope audit, cleanup, push, and PR

**Files:**
- Delete after all gates pass: `docs/superpowers/specs/2026-08-20-issue-652-external-references-design.md`
- Delete after all gates pass: `docs/superpowers/plans/2026-08-20-issue-652-external-references.md`
- Review: every file changed from `origin/codex/catalog-wave`

**Interfaces:**
- Consumes green schema/service/migration/compatibility slices.
- Produces one verified issue-only branch and PR targeting `codex/catalog-wave`.

- [ ] **Step 1: Run focused external-reference and catalog verification**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_external_references.py tests/test_external_reference_migration.py tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py tests/test_shared_catalog_migration.py tests/test_catalog_writes.py tests/test_catalog_compat.py tests/test_catalog_write_views.py tests/test_library_api_isolation.py -q
```

Expected: PASS.

- [ ] **Step 2: Verify migration state and whitespace**

Run:

```bash
direnv exec . uv run --frozen python manage.py makemigrations --check
git diff --check origin/codex/catalog-wave...HEAD
```

Expected: “No changes detected” and no diff-check output.

- [ ] **Step 3: Run the required full gate with default workers**

Run exactly:

```bash
direnv exec . make check
```

Expected: exit 0. Do not set `PYTEST_WORKERS`; retain the Makefile default.

- [ ] **Step 4: Audit issue-only scope and thresholds**

Run:

```bash
git diff --stat origin/codex/catalog-wave...HEAD
git diff --numstat origin/codex/catalog-wave...HEAD
git status --short
```

Confirm no IGDB/source/import/helper-route behavior or editable/arbitrary URL
template entered the branch;
actual scope remains below three runtime subsystems, 40 files, and 2,000
non-generated changed lines; and all new model constraints have matching
migration state. Return to approval before continuing if a threshold is crossed.

- [ ] **Step 5: Record rollback and integration-gate requirements**

In the eventual PR body, record the issue's 2026-08-20 production preflight
result (zero normalized duplicates and zero malformed nonblank values), the
exact test reconciliation summary, and the required pre-`main` production-copy
migration/restore rehearsal from the catalog wave. Do not claim that rehearsal
was run unless protected external evidence is actually available and checked.

- [ ] **Step 6: Remove planning artifacts only after all green gates**

Delete the paired design and plan with `apply_patch`, then commit their removal:

```bash
git add docs/superpowers/specs/2026-08-20-issue-652-external-references-design.md docs/superpowers/plans/2026-08-20-issue-652-external-references.md
git commit -m "chore: finalize external reference rollout"
```

The planning commit remains visible in branch history even though the final
target-tree diff contains implementation only.

- [ ] **Step 7: Run final lightweight integrity checks**

Run:

```bash
git diff --check origin/codex/catalog-wave...HEAD
git status --short --branch
```

Expected: no whitespace errors and a clean issue branch.

- [ ] **Step 8: Push and open the requested PR**

Push `codex/issue-652-external-references` and open a GitHub PR with base
`codex/catalog-wave`. The PR body must summarize the typed target-integrity
contract, canonical provider policy, fail-closed migration and exact
reconciliation, trusted URL-template/link behavior, compatibility behavior,
focused/full verification, actual scope totals, rollback requirement, and
include `Closes #652`. Do not merge it.
