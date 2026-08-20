# CAT-05 (#652): provider-neutral external references

Status: awaiting approval 2026-08-20. Parent phase: #600. Depends on #650 and
#651. This design is governed by the
[timetracker overhaul charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
and the
[catalog foundation delivery wave](2026-08-20-catalog-wave-design.md).

## Outcome and boundary

CAT-05 introduces a provider-neutral `ExternalReference` identity map. A
canonical `(provider, entity_kind, provider_key)` tuple resolves to exactly one
existing Game, Edition, Release, or Platform UUID. The schema and lookup
service are independent of Wikidata, while the first provider policy and data
migration cover Wikidata only.

Every nonblank legacy `Game.wikidata` value is trimmed, uppercased, validated,
and copied to one Game-kind Wikidata reference whose target is the same Game
UUID. Blank and whitespace-only values become the canonical empty string and
create no reference. The current Game form, list display, and legacy field stay
in place. CAT-02's existing private catalog writer keeps that field and the new
reference synchronized until the later catalog compatibility cleanup.

The following remain out of scope:

- IGDB authentication, API or dump clients, source records, refresh/staleness,
  images, attribution, or import workflows;
- helper routes, redirects, matching, merging, or private-to-shared
  reconciliation;
- catalog tombstones, archive behavior, or changes to current deletion flows;
- dedicated external-reference forms, APIs, admin surfaces, or bulk commands;
- moving or removing `Game.wikidata`, or changing its visible form/list label;
  and
- adding policies for providers that have no current producer. IGDB and store
  provider policies arrive with their owning integration issues.

## Model and target-integrity contract

`ExternalReference` is a conventional catalog model with a UUIDv7 primary key,
canonical `provider` (50 characters), `entity_kind` (20 characters), and
`provider_key` (255 characters), plus four nullable target foreign keys:
`game`, `edition`, `release`, and `platform`. Each target uses `CASCADE`, because
a hard-deleted catalog row must
not leave an identifier that resolves to no row. CAT-05 does not otherwise
change deletion behavior; #653 owns future archive/tombstone semantics.

The entity kinds are the stable lowercase values `game`, `edition`, `release`,
and `platform`. A database `CheckConstraint` contains four explicit branches.
Each branch requires the declared entity kind's corresponding foreign key to
be non-NULL and the other three target columns to be NULL. The constraint both
requires exactly one target and makes the target's table agree with
`entity_kind`; each foreign key then proves that the UUID exists. Model
validation enforces the same rule before ordinary ORM saves.

A database `UniqueConstraint` covers `(provider, entity_kind, provider_key)`.
The model stores only canonical provider/key values, so case or surrounding
whitespace cannot create a second logical tuple. The initial schema accepts
only the canonical provider `wikidata`, and its database check requires the
canonical key pattern `Q[1-9][0-9]*`. Extending the provider registry later
requires an explicit model/migration change that adds that provider's policy;
unknown providers do not silently receive a generic normalization rule.

The model's reverse names are `external_references` on each target model. A
read-only `target_uuid` property returns the one non-NULL target UUID and
raises `ValidationError` if an unsaved/corrupt in-memory object violates the
target contract. It does not perform a polymorphic model fetch.

## Provider policy and service interfaces

New module `games/external_references.py` owns provider normalization and the
typed persistence/lookup boundary. Its public interfaces are:

```python
CatalogTarget = Game | Edition | Release | Platform

def normalize_provider(provider: str) -> str: ...

def normalize_provider_key(*, provider: str, provider_key: str) -> tuple[str, str]: ...

def save_external_reference(
    *, provider: str, provider_key: str, target: CatalogTarget
) -> ExternalReference: ...

def resolve_external_reference(
    *, provider: str, entity_kind: str, provider_key: str
) -> UUID | None: ...

def sync_game_wikidata(*, game: Game) -> ExternalReference | None: ...
```

`normalize_provider` strips and casefolds the provider name, then rejects any
provider not in the explicit policy registry. The Wikidata policy strips and
uppercases the key, then requires a full match of `Q[1-9][0-9]*`. A nonblank
malformed key raises field-addressable `ValidationError`; reference creation
also rejects a blank key. `GameForm.clean_wikidata()` applies the same Wikidata
policy to a nonblank legacy value, canonicalizes whitespace-only input to
`""`, and rejects a tuple already owned by another Game. This keeps validation
on the existing visible field while the database unique constraint remains the
concurrency backstop.

`save_external_reference` derives the entity kind and target field from the
concrete target model; callers cannot supply a contradictory kind. Inside an
atomic transaction it locks any existing normalized tuple. An absent tuple is
created. An existing tuple for the same target is returned idempotently. An
existing tuple mapped to another UUID raises `ValidationError`; the service
never silently reassigns external identity.

`resolve_external_reference` normalizes the provider and key, validates the
entity kind, and selects the one corresponding target UUID column from the
unique tuple. It returns `None` when no row exists. It never falls back across
entity kinds or providers, and it never resolves by Game name or another
catalog attribute.

`sync_game_wikidata` is the temporary compatibility operation. For a canonical
nonblank legacy value it removes any other Game-kind Wikidata reference owned
by that same Game and saves/retains the exact requested tuple. For a blank
legacy value it removes all Game-kind Wikidata references for that Game and
returns `None`. A tuple already owned by another Game fails before reassignment.
All deletes and creates occur inside the caller's transaction, so a collision
restores the prior synchronized state on rollback.

## Thin legacy-adapter synchronization

`save_private_game` remains the durable Game–Edition–Release writer and does
not acquire temporary compatibility behavior. The thin
`save_legacy_game_form` adapter adds an outer `transaction.atomic` boundary,
calls the existing writer, then calls `sync_game_wikidata(game=game)` before
returning. The writer's nested atomic block and the reference synchronization
therefore commit or roll back together.

Creating or editing through the current Game form therefore has these exact
effects:

- `" q123 "` persists and displays as `"Q123"` and maps to the same Game UUID;
- an unchanged key reuses the reference UUID;
- changing `Q123` to `Q456` removes the old mapping and creates the new one;
- clearing the field removes the Game's Wikidata reference; and
- a malformed or already-owned key is attached to the existing form field and
  leaves the Game, default Edition/Release, legacy value, and existing
  reference unchanged rather than producing a partial write.

The Game form fields, label, templates, list column, and display source remain
unchanged. No current read surface is switched to the reference table in this
issue; only the provider-neutral lookup service is a new consumer contract.

## Migration, preflight, and exact reconciliation

Atomic migration `0022_external_references` creates the table and constraints,
then runs the historical-model backfill. PostgreSQL applies the migration in
one transaction. A failed preflight or post-write reconciliation therefore
rolls back both data changes and schema creation.

The forward function first snapshots every Game UUID and all pre-existing Game
fields. For each legacy `wikidata` value it computes the expected canonical
value in memory: trim, uppercase, and treat the empty result as blank. Before
updating any Game or inserting any reference, it collects every malformed
nonblank value and every canonical key owned by more than one Game. Malformed
objects use code `malformed_wikidata`; duplicate groups use code
`duplicate_normalized_wikidata` with the canonical key and sorted Game UUIDs.
All source mismatches are emitted deterministically, then one `RuntimeError`
aborts before data writes. This retains the issue's fail-closed assertion even
though the recorded 2026-08-20 production preflight found zero conflicts.

After successful preflight, the migration bulk-updates only legacy values that
differ from their canonical spelling and creates exactly the missing
Game-kind Wikidata references in batches. It does not call live model or
service code. A second in-transaction ensure pass must insert zero rows and
must retain the same ordered reference UUID/tuple/target set.

Post-write reconciliation proves all of the following before success:

- the Game UUID set is unchanged and every Game field other than the permitted
  canonicalized `wikidata` value is exact;
- every expected nonblank legacy value has exactly one
  `(wikidata, game, canonical_key)` reference to that same Game UUID;
- every blank legacy Game has zero Game-kind Wikidata references;
- no extra Game-kind Wikidata reference exists;
- all created references have one valid target and their Game UUIDs exist (also
  enforced by the schema);
- the second ensure pass inserted zero rows and changed no reference identity;
  and
- Edition, Release, Platform, and their existing relationships are untouched.

The migration prints one compact, sorted machine line:

```text
EXTERNAL_REFERENCE_RECONCILIATION_JSON={"mismatches":[],"schema_version":1,"summary":{"games":<n>,"inserted_references":<n>,"legacy_blank":<n>,"legacy_nonblank":<n>,"mismatches":0,"normalized_legacy_values":<n>,"wikidata_edition_references":0,"wikidata_game_references":<n>,"wikidata_platform_references":0,"wikidata_release_references":0,"wikidata_references":<n>}}
```

and one exact human summary in this key order:

```text
CAT external reference reconciliation: games=<n> legacy_nonblank=<n> legacy_blank=<n> normalized_legacy_values=<n> inserted_references=<n> wikidata_references=<n> wikidata_game_references=<n> wikidata_edition_references=<n> wikidata_release_references=<n> wikidata_platform_references=<n> mismatches=<n>
```

Each mismatch also receives one line beginning
`CAT external reference mismatch: code=<code>` with sorted key/value details.
Mismatch objects sort by code, provider key, Game UUID, target kind, expected,
and actual. The JSON summary counts the final table state; on preflight failure
all reference counts and inserted count are zero. The final exception is:

```text
CAT external reference reconciliation failed with <n> mismatch(es).
```

## Transaction, reverse migration, and deployment rollback

The schema, data backfill, legacy canonicalization, reconciliation, and failure
raise remain inside migration `0022`'s default atomic transaction. Focused tests
force both preflight and post-write failures and inspect migration state and
data afterward; they do not merely assume PostgreSQL rolled back.

The reverse function runs before Django would drop the new table. It refuses
with a clear `RuntimeError` whenever any `ExternalReference` exists, because
dropping populated provider-neutral identity is destructive and cannot restore
the original legacy spelling. It permits schema reversal only on a truly empty
reference table, primarily for empty-database migration tests.

Before the catalog wave reaches production, rollback is branch deletion. After
deployment, supported rollback is to keep web/workers offline, restore the
ordinary verified pre-deployment PostgreSQL custom-format backup into a clean
database, point the prior application image at that database, verify the prior
migration leaf and recorded Game/Wikidata counts, and only then restart the
processes. A reverse migration is not accepted as a substitute for the verified
backup and prior image. The wave-level integration gate rehearses this exact
migration and restore against the current protected production copy before
merge to `main`.

## Testing and verification

Focused model/service tests prove provider/key canonicalization, rejection of
blank/malformed/unknown providers, all four target kinds, UUIDv7 identities,
database uniqueness, database target-kind checks, foreign-key existence,
idempotent same-target writes, conflict refusal, deterministic lookup, no
cross-kind fallback, and target-delete cascade.

Migration tests cover mixed canonical/noncanonical/blank Wikidata values,
exact same-Game UUID mapping, preserved catalog hierarchy/relationships, exact
machine/human output, malformed and duplicate all-at-once preflight failure,
post-write mismatch rollback, empty databases, direct repeated forward
idempotency, populated reverse refusal, and empty reverse success.

Catalog-writer and view tests cover create, unchanged edit, key replacement,
clearing, malformed form input, duplicate-key conflict, and rollback after a
later graph/reference failure. They assert the current Wikidata field remains
visible and displays the canonical value.

Verification runs the focused external-reference migration/service/writer/view
suites, the existing catalog hierarchy and shared/private suites,
`makemigrations --check`, `git diff --check`, and the complete `make check`
gate with the Makefile's unchanged default `PYTEST_WORKERS`.

## Alternatives considered

**One generic `target_uuid` column.** Rejected because a UUID alone cannot
prove the target exists or belongs to the declared entity kind. Application
validation would be bypassable and deletion could leave an orphan mapping.

**Django `GenericForeignKey`.** Rejected because it provides no database
foreign key, permits targets outside the catalog contract, and couples the
portable provider tuple to Django content-type identities.

**Four separate external-reference models.** Rejected because it duplicates
provider policy and lookup behavior, and cannot express one provider/kind/key
namespace with one unique contract.

**Keep only `Game.wikidata` and add helper functions.** Rejected because it
cannot support Edition, Release, or Platform targets and would require each
future provider to add another dedicated field.

**Add IGDB/store policies now.** Rejected because no current producer or linked
specification defines their key semantics. Provider-neutral structure does not
require speculative provider behavior.

## Complexity forecast and re-slice gate

Forecast: two runtime subsystems (external-reference model/service and the
existing thin Game-form compatibility path), approximately nine
implementation/test files, and 1,200–1,800 non-generated changed lines.
Expected files are `games/models.py`, `games/external_references.py`, migration
`0022`, `games/forms.py`, `games/catalog_compat.py`, and focused tests under
`tests/`. Existing views need no structural change because form validation and
the current adapter preserve their contract.

The temporary design and plan are committed before tests or runtime code and
removed only after implementation and all gates pass, preserving the planning
commit in branch history. Return to the design gate before expanding scope if
implementation needs a third independent runtime subsystem, more than 40
files, or 2,000 non-generated changed lines.
