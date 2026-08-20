# CAT-04 (#651): shared/private catalog isolation

Status: approved 2026-08-20. Parent phase: #600. Depends on #650. This design
is governed by the
[catalog foundation delivery wave](2026-08-20-catalog-wave-design.md).

## Outcome and boundary

CAT-04 makes a NULL `Game.library` the explicit representation of a shared
catalog Game. Existing Games stay private and retain their owners, UUIDs,
compatibility fields, Edition/Release hierarchy, and incoming relationships.
Shared Games are visible only through explicit catalog queries and the existing
catalog search endpoint. Every current player-history read and mutation remains
private-only until PlayerGame is introduced.

The following remain out of scope:

- creating or importing shared catalog records;
- PlayerGame, private overrides, matching, reconciliation, or merging;
- IGDB and other external references;
- redirects, tombstones, archive rules, or deletion semantics for referenced
  shared records;
- user editing of shared Games; and
- moving status, mastered state, playtime, Sessions, Purchases, PlayEvents,
  status history, `sort_name`, or compatibility fields off Game.

## Ownership representation and migration

Migration `0021` alters only `Game.library` to `null=True`, `blank=True`, and
`default=None`, preserving its existing `CASCADE` behavior and `games` reverse
name for private owners. It contains no data migration: every existing
non-NULL owner remains exact and no Game, Edition, Release, UUID, legacy value,
or relationship is rewritten or merged. The new state permits a shared
Game–Edition–Release graph to be created with `Game.library_id IS NULL`.

The existing uniqueness contracts stay deliberately private. PostgreSQL's NULL
semantics mean the existing `(library, name, platform, year_released)` and
platformless conditional constraints continue rejecting duplicate private rows
within one owner while they do not introduce shared-name uniqueness. Shared and
private Games may have equal names, normalized-equal names, years, or Platforms.
There is no name normalization, shadow prohibition, or name-based resolution.

## Explicit query contracts

`Game.objects.for_library(library)` keeps its current exact-owner meaning and
therefore excludes both shared Games and foreign private Games.
`Game.objects.visible_to(library)` returns Games whose owner is NULL or the
given library. The distinction is intentional and call sites must opt into the
broader catalog contract.

Edition and Release derive both contracts through their owning Game:

- `Edition.objects.for_library(library)` filters `game__library=library`;
- `Edition.objects.visible_to(library)` filters Games shared with or owned by
  that library;
- `Release.objects.for_library(library)` filters
  `edition__game__library=library`; and
- `Release.objects.visible_to(library)` filters Releases whose owning Game is
  shared with or owned by that library.

All existing lists, details, forms, filters, statistics, Session and Purchase
flows, option resolvers, and write authorization continue using `for_library`.
They therefore remain private-only without a broad call-site rewrite.

## Search contract

`GET /api/games/search` is the only current surface broadened to
`Game.objects.visible_to(library)`. It keeps the existing response shape and
catalog-safe option fields: Game UUID, display label, and Platform option data.
It does not add status, mastered, playtime, Sessions, Purchases, PlayEvents,
status history, timestamps, owner identity, or any new compatibility field.

An empty query may return shared plus requesting-library private Games. For a
matching query, `name` remains searchable on both visible kinds, while
`sort_name` is searchable only when `Game.library` equals the requesting
library. Thus one library cannot discover another library's private rows, and
a private presentation override never becomes a shared-catalog search term.
Ordering and limit behavior remain unchanged.

## Mutation and graph-validation contract

Every current mutation continues resolving Games through
`Game.objects.for_library(library)`. Shared and foreign-private UUIDs therefore
return 404 for status updates, PlayEvent creation, add/edit/delete flows, Game
details, and other existing player-history paths. Shared records are not
editable through current forms or services.

`save_private_game` enforces three invariants inside its existing atomic
transaction before changing the graph:

1. a Game supplied for creation must have a non-NULL owner;
2. an existing persisted Game must remain owned by the same library recorded in
   the database, so callers cannot transfer it by mutating `game.library`; and
3. the selected Platform must be shared or owned by that same private library.

The service locks and reads the persisted Game before accepting changes. A
shared Game, foreign Platform, or attempted owner transfer raises
`ValidationError`, and no Game compatibility field, Edition, or Release is
changed.

Release validates Platform ownership through
`release.edition.game.library_id`. A private graph may use a shared Platform,
the same library's private Platform, or no Platform. A shared graph may use
only a shared Platform or no Platform. A foreign private Platform is rejected
before save in every graph kind. Edition and Release carry no independent
owner column.

## Testing and verification

Focused model/query tests use two libraries and shared/private graphs to prove
shared visibility, foreign-private exclusion, hierarchy-derived Edition and
Release visibility, same-name coexistence, and unchanged private uniqueness.
Validation/service tests prove foreign Platforms, shared-Game writes, and
owner transfers fail atomically without changing existing compatibility or
catalog graph state.

API tests prove both users discover shared catalog rows, neither discovers the
other's private rows, shared `sort_name` does not match, private owner
`sort_name` does match, response objects contain only the established option
keys, and shared/foreign status and PlayEvent mutations return 404 without
changing data. Migration tests prove exact preservation of existing private
graphs, nullable field state, shared-graph creation, and absence of data merge
or rewrite.

Verification runs the focused catalog, writer, API-isolation, and migration
files; `make check-migrations`; `git diff --check`; and the complete
`make check` gate with the Makefile's unchanged default `PYTEST_WORKERS`.

## Alternatives considered

**Broaden `for_library` to include shared rows.** Rejected because hundreds of
current private player-state call sites rely on exact ownership. Changing its
meaning would expose shared rows to forms, filters, histories, and mutations.

**Add a PlayerGame or private override in this issue.** Rejected because those
are later wave consumers. This slice establishes catalog visibility without
moving player data or inventing a partial transition model.

**Add shared normalized-name uniqueness or forbid private shadows.** Rejected
because identity is UUID-based and the wave explicitly preserves equal-name
rows. Names cannot safely establish catalog equivalence.

**Make every current read shared-aware.** Rejected because current pages show
player history and mutation affordances. Only the catalog-safe search response
has a valid shared consumer before PlayerGame.

## Complexity forecast and re-slice gate

Forecast: two runtime subsystems (Django model/service contracts and the Game
search API), approximately eight implementation/test files, and fewer than
1,000 non-generated changed lines. Expected files are `games/models.py`,
`games/catalog_writes.py`, `games/api.py`, migration `0021`, and focused tests
under `tests/`. The temporary design and plan are committed before runtime
work and removed only after all gates pass, preserving the planning commit in
branch history. Return to the design gate if the implementation needs a third
independent runtime subsystem, more than 40 files, or 2,000 non-generated
changed lines.
