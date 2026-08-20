# CAT-02 (#888): legacy Game writes stay in the catalog hierarchy

Status: awaiting approval 2026-08-20. Parent phase: #600. Depends on #649.
This design is governed by the
[timetracker overhaul charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
and the
[catalog foundation delivery wave](2026-08-20-catalog-wave-design.md).

## Outcome and boundary

CAT-02 makes the existing Add/Edit Game flow a supported writer for the
additive Game–Edition–Release hierarchy introduced by #649. A durable catalog
service saves a private Game and its explicitly selected default Edition and
Release in one transaction. A thin compatibility adapter translates the
legacy form's integer years and Platform into canonical temporal/catalog values
while preserving the current fields, actions, validation, and redirects.

Every successful create produces one default Edition and one default Release.
Every successful edit reuses those same identities. The durable service is the
supported manual/custom catalog writer after legacy columns disappear; only
the adapter that mirrors the current form fields is temporary.

The following remain out of scope:

- backfilling Games that existed before this writer; #650 owns that migration
  and reconciliation;
- moving status, mastered, sort-name overrides, playtime, Sessions, Purchases,
  or other player facts out of Game;
- changing current reads, form controls, URLs, redirects, APIs, filters,
  statistics, templates, TypeScript, or CSS;
- exposing Edition/Release management or allowing the current form to choose
  among multiple Editions or Releases;
- shared-record mutation, IGDB search/import, automatic matching or merging,
  external references, tombstones, redirects, or a Catalogue page; and
- intercepting unsupported direct ORM writes, fixtures, migrations, or signal-
  driven updates to non-catalog legacy fields.

## Chosen default-graph contract

#649 deliberately introduced UUID identities without claiming that UUID order
or child count selects a default. CAT-02 closes that contract explicitly:

- `Edition.is_default` is a non-editable Boolean with default `False`.
- `Release.is_default` is a non-editable Boolean with default `False`.
- PostgreSQL partial unique constraints permit at most one default Edition per
  Game and at most one default Release per Edition.
- The catalog service supplies the complementary existence guarantee: after a
  successful service write, the Game has exactly one default Edition and that
  Edition has exactly one default Release.

The fields default to `False` so ordinary creation of additional identities
does not accidentally claim default status or break #649's multiplicity
contract. If a Game has non-default children but no default graph, the service
creates a new explicit default graph; it never guesses that an unmarked UUID is
the intended default. Existing default identities are locked and reused.

Migration `0019_catalog_write_defaults` only adds the two flags and two partial
constraints. The catalog-wave integration branch has no production hierarchy
rows before #650, so this migration performs no data backfill and assigns no
meaning to pre-existing test/development children. #650 will use the same
explicit default contract when it backfills historical Games.

## Durable catalog writer

Create `games/catalog_writes.py` with two public types:

```python
@dataclass(frozen=True, slots=True)
class PrivateGameGraph:
    game: Game
    edition: Edition
    release: Release


def save_private_game(
    *,
    game: Game,
    original_release_date: TemporalValue | None,
    release_date: TemporalValue | None,
    platform: Platform | None,
) -> PrivateGameGraph: ...
```

`game` may be a new unsaved private Game or an existing private Game. This
keeps the durable service focused on the catalog facts while allowing a
temporary caller to populate legacy fields on the same model instance before
the transaction starts. A future manual/custom writer can construct the Game
with only the fields still present at that time and use the same service.

`save_private_game` owns the entire transaction. It:

1. rejects a missing private owner and rejects a Platform that is neither
   shared nor owned by the Game's library;
2. locks the existing Game row when updating, then sets the canonical Game
   original-release value and saves the supplied Game instance;
3. locks and resolves the explicitly default Edition, creating it if absent;
4. locks and resolves that Edition's explicitly default Release, creating it
   if absent;
5. sets the Release's exact supplied Platform (including `None`) and canonical
   release date (including `None`); and
6. returns all three persisted rows.

The Game row is the serialization lock for a graph. Service callers therefore
cannot race into two default children; the database constraints remain the
last guard against writes that bypass the service. An unchanged call performs
ordinary updates but creates no identities. No lookup uses name, year,
Platform, UUID ordering, or “first child” semantics.

The service accepts canonical `TemporalValue | None`, not legacy integers. It
does not know that the current form has `year_released` or
`original_year_released`, and it does not infer a Platform from any other row.
`None` means unknown date or explicitly unspecified Platform.

## Temporary legacy compatibility adapter

Create `games/catalog_compat.py` with one public function:

```python
def save_legacy_game_form(form: GameForm) -> Game: ...
```

The adapter calls `form.save(commit=False)` and passes that unsaved/updated
Game to `save_private_game`. It translates each non-NULL integer year with
`TemporalValue.from_year`; a cleared year passes `None`. It passes the form's
Platform exactly, including `None`.

Because `form.save(commit=False)` performs no database write and
`save_private_game` owns the atomic block, the Game's current legacy fields and
the canonical graph commit or roll back together. The adapter contains all
knowledge of the temporary mapping:

| Legacy form/Game value | Canonical write |
| --- | --- |
| `name` | `Game.name` on the supplied Game |
| `original_year_released` | `Game.original_release_date`, year precision or unknown |
| `year_released` | default `Release.release_date`, year precision or unknown |
| `platform` | default `Release.platform`, exact value or explicitly unspecified |
| `sort_name`, `status`, `mastered`, `wikidata` | current Game compatibility fields only |

The add and edit views replace only `form.save()` with
`save_legacy_game_form(form)`. Their validation order, response bodies,
submit-button branches, origin handling, and redirect targets do not change.
No `GameForm.save` override or model signal is added: the compatibility
boundary remains visible at the two supported form call sites and cannot
silently affect fixtures, migrations, status/playtime signals, or tests that
deliberately construct passive catalog rows.

## Validation and failure behavior

The current ModelForm remains responsible for current uniqueness and visible
Platform choices. The service independently enforces its durable private-
catalog boundary so non-form callers cannot attach another library's private
Platform. Model/database validation errors propagate through the existing
application behavior; CAT-02 adds no new error page or retry policy.

Any exception after the transaction starts rolls back all of these together:
the Game insert/update, canonical original-release value, default child
creation, Release date/Platform update, and every compatibility field applied
to the Game instance. Tests force a child-write failure on both create and edit
and inspect fresh database state, rather than trusting `atomic` by inspection.

The service does not repair multiple defaults because the database forbids
that state after `0019`. It does not adopt unmarked children because doing so
would invent semantics. A missing default child is normal and is created; an
existing one is reused.

## Testing and verification

Focused service/model tests prove:

- creation persists one private Game, one default Edition, and one default
  Release with UUIDv7 identities and exact parent relationships;
- partial constraints reject a second default while non-default multiplicity
  remains valid;
- the service ignores unmarked children and creates an explicit default graph;
- edits preserve default Edition/Release UUIDs while changing name, canonical
  original year, release year, and Platform;
- clearing either year or Platform writes SQL NULL/unknown to both canonical
  and compatibility state;
- an unchanged second write preserves counts and identities;
- a foreign private Platform is rejected without mutation; and
- forced Release failures roll back both new and existing Game writes.

Focused view/adapter tests POST through the real add/edit URLs and prove legacy
and canonical values agree. Redirect cases cover the normal fallback, carried
origin, Submit & Create Purchase, and Submit & Create Session paths without
changing their expected targets. Existing form-isolation and broad regression
tests remain authoritative for rendering and invalid submissions.

Verification runs focused tests, `make check-migrations`, `git diff --check`,
and finally `make check` with the Makefile's default parallel worker
configuration. No normal verification command sets `PYTEST_WORKERS=0`.

## Alternatives considered

**Infer the default from the only/oldest child.** Rejected because #649 allows
multiple children and explicitly says UUID identity alone is not a default.
This would become ambiguous as soon as multi-edition data exists.

**Make every new Edition/Release default by field default.** Rejected because
ordinary non-service creation of a second identity would violate the partial
constraint and silently redefine #649's model API. Defaults are semantic and
must be explicit.

**Put default foreign keys on Game and Edition.** Rejected because the circular
relations require nullable staged writes and ordinary foreign keys cannot prove
that the selected Release belongs to the selected Edition. Partial constraints
on child rows match the service lookup directly and keep the migration small.

**Override `Game.save`, add signals, or override `GameForm.save`.** Rejected
because model-wide hooks would affect status/playtime signals, fixtures,
migrations, and deliberate direct ORM setup. A form override would hide a
temporary compatibility policy inside a general form API. Two explicit view
call sites are easier to remove at the final read/write cleanup.

**Let the compatibility adapter own child ORM writes.** Rejected because it
would make temporary legacy code the only supported writer and leave no durable
manual/custom catalog service after compatibility columns are removed.

## Complexity forecast and re-slice gate

Forecast: two closely coupled runtime subsystems (Django application/service
code and PostgreSQL schema), eight implementation/test files, and 550–900
non-generated changed lines:

- `games/models.py`;
- `games/migrations/0019_catalog_write_defaults.py`;
- `games/catalog_writes.py`;
- `games/catalog_compat.py`;
- `games/views/game.py`;
- `tests/test_catalog_writes.py`;
- `tests/test_catalog_write_views.py`; and
- `tests/test_catalog_hierarchy_migration.py`.

No generated frontend output is expected. The work remains below all mandated
re-slice thresholds: it does not cross three independent runtime subsystems,
40 files, or 2,000 non-generated changed lines. If implementation exceeds any
threshold or requires a third runtime subsystem, work returns to this design
gate before expanding scope.
