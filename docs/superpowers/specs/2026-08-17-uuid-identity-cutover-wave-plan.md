# UUID identity cutover: wave and PR-boundary plan (ID-01–ID-16)

Status: applied to GitHub 2026-08-17. This document governs how the
"Remaining UUID identity cutover" group in phase #600 is sliced into
reviewable PRs. The original ten placeholder issues (ID-01–ID-10, one line
each, no design behind them) were re-sliced based on actual code coupling
and restructured on GitHub to a flat sequential ID-01–ID-16 numbering — no
"wave" grouping exists in the issue tracker itself; "wave" here is this
document's internal explanatory grouping only.

## Final ID-XX → issue number map

| ID | Issue | Outcome |
| --- | --- | --- |
| ID-01 | #639 (done) | UUIDv7 identity conventions and utilities |
| ID-02 | #640 | Catalog identities: `Game`, `Platform` |
| ID-03 | #641 | Session and play-history identities: `Session`, `PlayEvent`, `GameStatusChange` |
| ID-04 | #642 | Purchase and ownership identity: `Purchase` |
| ID-05 | #643 | Library configuration identities: `Device`, `FilterPreset` |
| ID-06 | #644 | Rewrite `PlayEvent.game`, `GameStatusChange.game` FKs to UUID |
| ID-07 | #845 | Rewrite `Game.platform` FK to UUID |
| ID-08 | #846 | Rewrite `Session.game`, `Session.device` FKs to UUID |
| ID-09 | #847 | Rewrite `Purchase.games` M2M, `Purchase.related_game`, `Purchase.platform` to UUID |
| ID-10 | #645 | Verify the integer-to-UUID reconciliation map |
| ID-11 | #646 | Remove legacy integer identities: catalog (`Game`, `Platform`) |
| ID-12 | #848 | Remove legacy integer identities: Session/play-history |
| ID-13 | #849 | Remove legacy integer identity: `Purchase` |
| ID-14 | #850 | Remove legacy integer identities: `Device`, `FilterPreset` |
| ID-15 | #647 | Canonical slug+UUID URLs |
| ID-16 | #648 | Remove integer routes without permanent aliases |

`blocked-by` links between these issues on GitHub encode the dependency
edges described per wave below.

## Why re-slice at all

`#639` is real and merged. `#640`–`#648` are eight one-line placeholder
issues sharing an identical boilerplate body — no design exists behind any
of them yet. Treating each as exactly one PR would produce either:

- one humongous PR for `#644` (rewrite every foreign key and M2M to UUID),
  touching Session, PlayEvent, GameStatusChange, Purchase's three relations,
  Game.platform, Device, plus every filter/API/template/test that reads
  those columns, all in one diff; or
- if split reflexively, PRs that don't align with actual coupling and cause
  rework when a later slice discovers the earlier one drew the line in the
  wrong place.

The waves below are sized by **actual app-surface coupling** (how many
filters, API endpoints, templates, and tests a relation touches), not by
table count or by the original issue numbering.

## Model inventory

Every model that still owns an integer primary key needing conversion:

| Model | Bucket |
| --- | --- |
| `Game`, `Platform` | Catalog |
| `Session`, `PlayEvent`, `GameStatusChange` | Session / play-history |
| `Purchase` | Purchase / ownership |
| `Device`, `FilterPreset` | Library configuration |

`UserLibraryPreferences` and `PurchaseConversionState` already use
`UserLibrary`'s UUID as a shared primary key (`library = OneToOneField(...,
primary_key=True)`) and need no conversion of their own.

## Wave A — identity foundation (done)

ID-01, #639, merged as PR #833. No further action.

## Wave B — additive UUID columns (4 PRs, confirmed as-is)

`#640`–`#643` stay four separate, purely additive PRs — each adds one
non-primary-key `uuid` column per model, backfills it from `created_at` with
strict ordering, and touches nothing else. This is confirmed as the right
granularity: they don't touch each other's code, `#641`–`#643` just apply the
recipe `#640` establishes (`uuid7_at` helper, five-operation migration shape,
reconciliation-line convention), and each is independently revertible.

| Issue | Models | Depends on |
| --- | --- | --- |
| `#640` | `Game`, `Platform` | `#639` — design approved, see [catalog identity design](2026-08-17-issue-640-catalog-uuid-identity-design.md) |
| `#641` | `Session`, `PlayEvent`, `GameStatusChange` | `#639` (not `#640` — independent) |
| `#642` | `Purchase` | `#639` |
| `#643` | `Device`, `FilterPreset` | `#639` |

`#641`–`#643` can be designed and implemented in any order or in parallel;
none of them depend on `#640` landing first, only on the pattern it
establishes being copyable. Each needs its own short design spec following
`#640`'s shape before implementation (same planning-gate requirement).

## Wave C — FK/M2M rewrite, split by relation-weight (ID-06–ID-09, 4 issues, was 1)

The original `#644` "Rewrite foreign keys and many-to-many links to UUIDs" is
re-scoped from one issue into four (ID-06/#644, ID-07/#845, ID-08/#846,
ID-09/#847 on GitHub), ordered cheapest-and-most-validating first:

| ID | Issue | Relations | Why this grouping |
| --- | --- | --- | --- |
| ID-06 | #644 | `PlayEvent.game`, `GameStatusChange.game` | Lowest surface: both are single Game-FKs, mostly read-only/audit, neither has its own quick-filter bar mode of its own weight. Bundled to validate the FK-rewrite pattern cheaply before the bigger slices. |
| ID-07 | #845 | `Game.platform` | Catalog-internal; moderate surface (platform quick-filter facet on Game, platform badge/link rendering). Deferred from `#640` specifically so it lands here once ID-10's reconciliation discipline exists. |
| ID-08 | #846 | `Session.game`, `Session.device` | Heaviest of the "single entity" slices: session quick-filter facets (game, device, started, ended, duration), the `PATCH /api/session/{id}/device` endpoint, session list/detail templates, sorting. |
| ID-09 | #847 | `Purchase.games` (M2M), `Purchase.related_game`, `Purchase.platform` | Heaviest slice overall: multi-game bundle/split logic, DLC/addon `related_game` relationship, purchase forms' multi-game SearchSelect, stats aggregation through the M2M. Landed last, after the pattern is proven three times over. |

`blocked-by` on GitHub: ID-06 ← #640,#641; ID-07 ← #640; ID-08 ← #640,#641,#643;
ID-09 ← #640,#642. No slice depends on another's schema, only on the shared
FK-rewrite pattern the first slice establishes (add UUID-typed FK column
pointing at the target's `uuid` field, backfill via the parent's
already-populated `uuid` column, swap every read/write path for that
relation to the new column, drop the old integer FK column — a per-relation
expand/contract, mirroring Wave B's per-model expand/contract). Recommended
run order ID-06 → ID-07 → ID-08 → ID-09, though only the FK-rewrite pattern
(not schema) needs to exist first.

**Saved-filter content is explicitly out of scope for Wave C.** Filter
criteria on `platform`/`device`/`game` fields store raw integer PKs inside
`FilterPreset.find_filter`/`object_filter` JSON; once a relation's FK column
type flips to UUID, any *existing* saved preset referencing that entity by
old integer value would go stale. This repository's only real deployment
currently has zero saved `FilterPreset` rows, so no remap/migration tooling
is built for this. This is a deliberate, recorded gap, not an oversight — if
a hosted multi-user deployment with real saved presets exists by the time
Wave C starts, this section must be revisited before ID-06 proceeds.

## Wave D — reconciliation verification (ID-10/#645, 1 issue, unchanged)

ID-10 stays one lightweight, standalone PR: an audit pass confirming the
integer→UUID map is complete and consistent across every model converted in
Waves B and C, run as a gate before Wave E. No schema change. `blocked-by`
ID-06, ID-07, ID-08, ID-09 (all of Wave C).

## Wave E — remove legacy integers, promote UUID to PK (ID-11–ID-14, 4 issues, was 1)

The original `#646` "Remove legacy integer identities" is re-scoped from one
issue into four (ID-11/#646, ID-12/#848, ID-13/#849, ID-14/#850 on GitHub),
mirroring Wave B's grouping for review-size symmetry: catalog (`Game`+
`Platform`), Session/play-history (`Session`+`PlayEvent`+`GameStatusChange`),
Purchase, library configuration (`Device`+`FilterPreset`). Each PR, per model
group: drops the integer `id` and every now-unused integer FK column Wave C
replaced, renames `uuid` to `id`, promotes it to primary key, and drops any
transitional `to_field` pointers Wave C's FK columns needed while `uuid`
wasn't yet the primary key. Lower risk than Wave C per PR — by this point
nothing references the integer columns — but kept split for reviewability
and to keep `games/sorting.py`'s `F("pk").asc()` tiebreak change auditable
per model group rather than in one sweep. All four are `blocked-by` ID-10.

## Wave F — canonical slug+UUID URLs (ID-15/#647, 1 issue, scope TBD in its own design)

ID-15 stays one issue, `blocked-by` ID-11 (catalog UUID becomes the real PK).
Its own design spec must resolve which entities actually get a
slug-plus-UUID canonical URL (the charter's example is `Game`;
`Platform`/`Session`/`Purchase`/`Device` may only need a bare-UUID URL or no
change at all) — not decided here.

## Wave G — remove integer routes (ID-16/#648, 1 issue, time-gated not code-gated)

ID-16 stays one issue, `blocked-by` ID-15, deliberately landed later than the
others in this plan: it should wait for a bake-in period after ID-15
(confirm no internal link still builds an integer URL, no
external/bookmarked traffic still depends on one) rather than merging
back-to-back with it.

## Summary: PR count

Was 8 placeholder issues (`#640`–`#648`, excluding done `#639`). Is now 15
issues across 7 waves (ID-02–ID-16): 4 (Wave B) + 4 (Wave C) + 1 (Wave D) + 4
(Wave E) + 1 (Wave F) + 1 (Wave G). More issues than the original count, but
each is sized to touch one coherent slice of app surface — no PR here
approaches the "every filter, API, template, and test in the app" blast
radius the original `#644` or `#646` would have had as single issues. This
was applied directly to GitHub on 2026-08-17 (see the ID map above);
`docs/superpowers/specs/` and the issue tracker should stay in sync going
forward — if a wave's design changes its issue boundary, update both.

## Status of each wave's design work

- Wave A: done.
- Wave B: `#640` design approved (this session). `#641`/`#642`/`#643` need
  their own short specs before implementation — expected to be small since
  they copy `#640`'s pattern.
- Waves C–G: not yet designed. This document fixes their PR boundaries and
  ordering; each PR still needs its own issue-level design spec before
  implementation, per the planning-gate acceptance criterion every one of
  these issues already carries.
