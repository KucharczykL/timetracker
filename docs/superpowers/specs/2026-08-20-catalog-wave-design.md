# Catalog foundation delivery wave

Date: 2026-08-20

Parent epic: [#599](https://github.com/KucharczykL/timetracker/issues/599)

## Purpose

This document replaces the placeholder CAT-01 through CAT-06 ordering with a
reviewable catalog-foundation wave. It preserves the overhaul charter's domain
direction while applying the delivery lessons recorded in #599 and the #630
postmortem: issue, pull-request, migration, and deployment boundaries solve
different problems; temporary deployment states do not need to become
production states; and every large design receives an explicit complexity
budget before implementation begins.

The current six issues identify useful concepts but do not form an executable
plan. They omit the temporal-value dependency, a supported write path that
keeps new Games inside the hierarchy, the eventual removal of compatibility
state, and exact handoffs to PlayerGame, Sessions, access, Purchases, and IGDB.
Conversely, durable tombstones and private-to-shared redirects have no consumer
in Phase 1 and should not block it.

## Product boundary

Phase 1 preserves the current Add/Edit/List/Detail Game experience. It does not
add a dedicated Catalogue page, multi-edition management, IGDB discovery, or
automatic catalog matching.

`Game` becomes the platform-independent work identity. `Edition` represents a
commercial/presentation edition of that work. `Release` represents an Edition
on an optional Platform. A legacy Game initially maps to one private Game, one
default Edition, and one default Release. Its Game UUID remains unchanged.

The hierarchy is not permission. A private Game belongs to one `UserLibrary`;
a shared Game has no Library owner. Edition and Release inherit their visibility
from Game. Player status, mastered state, playtime, Sessions, purchases, and
other private facts remain private even when a later PlayerGame points to a
shared Game.

## Data mapping

| Current Game value | Catalog destination | Rule |
| --- | --- | --- |
| `id` | `Game.id` | Preserve the UUID exactly. |
| `library` | `Game.library` | Existing rows remain private. |
| `name` | `Game.name` | Preserve exactly; never merge by name. |
| `sort_name` | temporary Game presentation value | Preserve until PlayerGame owns private overrides. |
| `original_year_released` | Game-level original-release temporal value | Preserve as year precision; blank remains unknown. |
| `year_released` | default Release temporal value | Preserve as year precision; blank remains unknown. |
| `platform` | default Release Platform | NULL becomes explicitly unspecified; never infer. |
| `wikidata` | Game `ExternalReference` | Trim, uppercase, validate, and migrate nonblank values. |
| status/mastered/playtime | legacy Game compatibility fields | Move only in the PlayerGame/Session waves. |

Every current row becomes its own provisional Game. Equal names, years, or
external IDs never cause an automatic merge. Production was checked on
2026-08-20: normalized nonblank Wikidata IDs had zero duplicates and zero
malformed values. The migration still fails closed if either invariant changes.

## Delivery and review topology

Create `codex/catalog-wave` from `main` in the current checkout. Each issue has
one bounded child branch and pull request targeting `codex/catalog-wave`. The
child PRs are review units, not production deployments. The completed wave is
verified and merged to `main` once.

Before approving an issue-level design, re-slice it if the forecast crosses
three independent runtime subsystems, more than 40 files, or 2,000
non-generated changed lines. A migration and its runtime consumer may use
separate commits or PRs where that makes review clearer; neither fact changes
the owning issue or the single final deployment.

### Phase 1 order

1. **#655 — temporal-value prerequisite.** Supply the final exact/imprecise
   value and parsed query bounds needed by Release dates. Approximate/uncertain
   qualifiers, entry UI, filtering, and broad legacy temporal migration remain
   #656–#659.
2. **#649 — additive hierarchy.** Add Edition and Release UUID identities,
   relations, date fields, and constraints without changing current reads or
   writes.
3. **New issue — catalog writer and legacy adapter.** Add the durable service
   that creates/updates private Game–Edition–Release graphs. The current Game
   form calls it through a thin adapter that also maintains legacy columns.
4. **#650 — existing-data backfill.** Create one default Edition/Release graph
   for every legacy Game and emit field/count reconciliation evidence.
5. **#651 — shared/private rules.** Add shared/private visibility, mutation,
   uniqueness, and cross-library constraints without adding shared data.
6. **#652 — external references.** Add provider-neutral references, migrate
   Wikidata, and keep the legacy field synchronized through the adapter until
   cleanup.

The final catalog service is enduring. Only legacy-column synchronization is
temporary.

### Deferred consumers

- **#653** moves after event-store foundations and before PlayerGame events
  first reference catalog UUIDs. It owns archive/tombstone rules for referenced
  conventional catalog rows. IGDB source-record staleness stays in #786.
- **#654** moves immediately before #785, after normalized shared IGDB records
  exist. It owns permanent, cycle-free private-to-shared identity redirects and
  resolution. #785 owns the explicit reconciliation command and UI.
- **New cleanup issue** follows final read cutovers. It removes legacy Game
  catalog columns and the thin adapter only after PlayerGame, Session,
  Historical Playtime, access, Purchase, filter/statistics, and IGDB consumers
  use final catalog interfaces.

## Cross-phase handoffs

- #671 creates one library-owned PlayerGame for a catalog Game and moves private
  current state without changing the catalog UUID.
- #678 switches Game-library reads to PlayerGame joined to the catalog; it owns
  private presentation overrides rather than placing them on shared Game rows.
- #690 permits an explicit Release in Session commands/events and never infers
  one from Game or Device.
- #705 includes optional recorded Release and Device dimensions on Historical
  Playtime; statistics use them only when explicitly present.
- #719/#722 make LibraryEntry access attach to Release, including multiple
  physical/digital entries for the same Release.
- #731/#732 introduce DLC, expansion, pass, and upgrade product relationships
  on the catalog identities rather than extending Phase 1 speculatively.
- #769 switches any residual read surfaces before catalog compatibility cleanup.
- #782 normalizes IGDB into the existing Game/Edition/Release/Platform and
  ExternalReference contracts; it does not create a second catalog schema.
- #785 uses #654's redirects when an explicit private-to-shared reconciliation
  is accepted. Historic events retain the original UUID.
- #786 distinguishes raw-source stale/deleted metadata from catalog tombstones.
- #788 exposes `/tracker/game/igdb/<id>/`; GET redirects an existing mapping or
  returns a not-found/import affordance and never imports implicitly.

## Migration, rollback, and reconciliation

All Phase 1 schema changes are additive on the integration branch. The final
deployment runs on PostgreSQL inside one transaction where Django permits it.
Before merge, run the migration against a current production copy and retain
the ordinary verified database backup as the rollback artifact.

The backfill reports total Games, Editions, Releases, unspecified Platforms,
known/unknown release years, and mismatches. It aborts on any missing or extra
graph, changed UUID, changed text/year/platform value, cross-library relation,
or non-idempotent default graph.

External-reference preflight trims and uppercases Wikidata keys in memory,
validates `Q[1-9][0-9]*`, and rejects duplicates before writing. Blank values
create no reference. Reconciliation proves every prior nonblank valid value has
exactly one provider-neutral reference with the same Game UUID.

Rollback before the final `main` merge is branch deletion. Rollback after
deployment is database restore plus the prior application image; reverse
migrations are not accepted as a substitute for proving the real backup.

## Verification contract

Every issue-level plan names focused tests and finishes with `make check` using
the default parallel worker configuration. The final integration gate also:

1. builds a fresh PostgreSQL database from migrations;
2. migrates and reconciles a production copy;
3. exercises Game add/edit with known and unknown Platform/year/Wikidata;
4. proves same-named Games remain distinct;
5. proves shared visibility and two-library private isolation;
6. checks current Game URLs, forms, searches, filters, saved presets, APIs,
   statistics, Session entry, and Purchase entry remain behaviorally stable;
7. starts the complete web/worker topology and repeats the catalog audit after
   a representative worker interval; and
8. records the affected-file and changed-line totals against the approved
   complexity forecast.

## GitHub update safety

Before mutation, export every affected issue's title/body/metadata to a
timestamped directory under `/tmp`. Prepare complete replacement bodies in
local files, inspect their diffs, and validate headings, task lists, links, and
code fences. Use `gh issue edit --body-file` rather than shell-quoted bodies.

Apply leaf issue edits and create new issues first. Record their assigned
numbers, then update #600–#602, and update #599 last. Read every changed issue
back and compare its title/body with the local proposed version. On a mismatch,
stop and restore that issue from the original local snapshot before continuing.

No existing issue is closed by this re-slice.
