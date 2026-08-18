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
| ID-07 | #845 | Rewrite `Game.platform` and `Purchase.platform` FKs to UUID |
| ID-08 | #846 | Rewrite `Session.game`, `Session.device` FKs to UUID |
| ID-09 | #847 | Rewrite `Purchase.games` M2M and `Purchase.related_game` to UUID |
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
| ID-07 | #845 | `Game.platform`, `Purchase.platform` | **Every** foreign key pointing at `Platform` — re-scoped during its design (2026-08-18) to slice by target model rather than by owning model. Moderate surface (platform quick-filter facet on two modes, the platform search endpoint's recency subqueries, platform badge/link rendering). |
| ID-08 | #846 | `Session.game`, `Session.device`, `UserLibraryPreferences.default_device` | Heaviest of the "single entity" slices: session quick-filter facets (game, device, started, ended, duration), the `PATCH /api/session/{id}/device` endpoint, session list/detail templates, sorting. Took the fourth `Device` foreign key during its design (2026-08-18) so **every** foreign key pointing at `Device` moves together — see its [design spec](2026-08-18-issue-846-session-fk-uuid-design.md). |
| ID-09 | #847 | `Purchase.related_game` (**only** — see below) | Expected to be the heaviest slice overall, on account of the `Purchase.games` M2M. Its design (2026-08-18) established that Django cannot move an M2M to a non-pk target without an explicit through model, and **deferred the M2M's through column to ID-11**, leaving one nullable FK — see its [design spec](2026-08-18-issue-847-purchase-fk-uuid-design.md). |

ID-07's rejected alternatives — including why filter nullability was fixed at
the source rather than accepted as a temporary loss — are kept as a
[decision record](2026-08-18-issue-845-platform-fk-uuid-design.md); its
mechanics are folded into the checklist below rather than duplicated there.

**Why ID-09 does not move `Purchase.games`.** Established by probe against the
installed Django 6.0.7, during ID-09's design; the full argument is in its
[design spec](2026-08-18-issue-847-purchase-fk-uuid-design.md). `ManyToManyField`
accepts no `to_field`, and `create_many_to_many_intermediary_model` builds the
auto-created through's foreign keys as plain `ForeignKey(to_model)` — an
auto-created through always references the target's **primary key**. Pointing
`Purchase.games` at `Game.uuid` therefore requires an explicit through model,
and that is not a column retype:

- `Serializer.handle_m2m_field` bails on a non-auto-created through, so
  `dumpdata` emits purchase records with **no `games` key**. The committed
  fixture would carry ~4505 `games.purchasegame` records in place of 795 `games:`
  lists, roughly doubling it, and `load_sample_data` /
  `PORTABLE_LIBRARY_MODELS` / `DUMP_LABELS` would have to learn a model that
  exists only to carry the transition.
- The existing shape cannot survive either: `loaddata` of `games: [<int pk>]`
  fails with a foreign-key violation, and `games: [<uuid>]` with
  `DeserializationError`, because `deserialize_m2m_values` converts through the
  **target's pk** field in both directions.

Deferring costs no application code, now or later: every site touching the M2M
speaks "Game primary key" (`_games_to_q`'s `games__in=`/`games=`, both
`games__id` `relation_to_q` lookups, `m2m_changed`'s `pk_set`,
`anonymize_sample`'s direct `Through(...)` build, `audit_library_ownership`'s
projection, the fixture's `games:` lists, `sorting.py`'s reverse-join
annotations), and each follows automatically once that pk *is* the UUID. What
ID-11 inherits is one database-level conversion inside the migration that is
already rewriting `Game.id` — and ID-13 owes the same table the mirror-image
conversion of `purchase_id` regardless, so Wave E pays for it once instead of
twice. ID-09 pins both columns with a test so neither slice can miss it.

**The integer→UUID flip of filter and search-endpoint values dissolves into
Wave E.** ID-09 was nominated to own it; its design established that there is
nothing to own. Wave C's lookups are all `<name>__id`, which resolve UUIDs the
moment the pk is one, so a dedicated flip issue would have to move every lookup
to `<name>__uuid` and back. The genuine residual is three *type annotations*,
which belong to the promoting slices: `GameOption.value: int`
(`games/api.py:129-132`, the response schema of all three search endpoints — a
`UUID` against it raises a pydantic `ValidationError`, so the promotion 500s the
endpoint rather than flipping it for free), `SearchSelectOption["value"]`
(`common/components/search_select.py:77`), and the three option resolvers in
`games/forms.py:216-241`. Because `Game`/`Platform` promote in ID-11 while
`Device` waits for ID-14, the shared schema must tolerate both types across that
window.

**Why ID-07 took `Purchase.platform` from ID-09.** The two platform foreign
keys are structurally identical (nullable `SET_NULL` to `Platform`), so
grouping by owning model rather than by target manufactured three transitional
artifacts and no benefit: `load_sample_data`'s remap would have carried two
identities at once for a full wave (one relation naming a `uuid`, the other a
`pk`, against the same target model), `games/filters.py` would have moved two
of six platform lookups and left four, and `GameForm.platform` would have
needed the `ModelForm` initial shim while `PurchaseForm.platform` — same field
name, same widget, same target — must not have had it. The two adjacent,
identical `OuterRef` subqueries in `/api/platforms/search` settled it: under
the split, one would have had to change and the other stay.

Two facts about the remaining slices, established after ID-06 landed and worth
knowing before estimating any of them:

- **`UserLibraryPreferences.default_device` (`games/models.py:781`) belongs to
  ID-08**, which claimed it during its design (2026-08-18) on the same
  slice-by-target-model reasoning that moved `Purchase.platform` into ID-07. It
  is a fourth `Device` foreign key, nullable, with no filter or fixture surface,
  so taking it cost one more nullable relation in ID-08's migration and left
  ID-14 a pure contraction rather than a foreign-key rewrite with its own
  reconciliation.
- **Every remaining Wave C relation except `Session.game` and `Purchase.games`
  is `null=True, on_delete=SET_NULL`.** ID-06 proved the six-operation shape
  only on `NOT NULL` columns: its step 1 exists to relax a NOT NULL that a
  nullable relation does not have, and its reconciliation asserts a zero NULL
  count where the real invariant is "the NULL set is unchanged, and the
  non-NULL rows anti-join clean". ID-07 settled this — see item 5 below.

`blocked-by` on GitHub: ID-06 ← #640,#641; ID-07 ← #640 (unchanged by the
re-scope: both platform relations point at `Platform.uuid`, and nothing in the
slice reads `Purchase.uuid`); ID-08 ← #640,#641,#643; ID-09 ← #640,#642. No slice depends on another's schema, only on the shared
FK-rewrite pattern the first slice establishes (add UUID-typed FK column
pointing at the target's `uuid` field, backfill via the parent's
already-populated `uuid` column, swap every read/write path for that
relation to the new column, drop the old integer FK column — a per-relation
expand/contract, mirroring Wave B's per-model expand/contract). Recommended
run order ID-06 → ID-07 → ID-08 → ID-09, though only the FK-rewrite pattern
(not schema) needs to exist first.

### What "swap every read/write path" actually means (learned in ID-06)

ID-06 shipped as the
[play-history FK design](2026-08-18-issue-644-playhistory-fk-uuid-design.md),
which is the worked example every later Wave C slice should read before
estimating its own size. The relation itself was two lines of model code; the
surrounding work was four seams this plan had not named. **Each of them recurs
in ID-07, ID-08 and ID-09** — treat this as the slice checklist:

0. **Correlated subqueries are a lookup direction of their own.** Before
   trusting any "confirmed unaffected" list, grep the app for `OuterRef` *and*
   read what each one correlates. ID-07 found `/api/platforms/search`'s recency
   subqueries filtering on the foreign-key column; ID-08 found
   `games/views/game.py:109`, where the games list annotates `filtered_playtime`
   from `Session.objects.filter(game=OuterRef("pk"))` — unconditional, so
   leaving it would have broken every render of the page, not just a filtered
   one. Both designs had listed the file as unaffected, and in both cases an
   adversarial review before implementation is what caught it. `OuterRef("pk")`
   becomes `OuterRef("uuid")`.
1. **Every lookup that spells the foreign-key column.** `games/filters.py`
   holds three kinds, and ID-06 needed all three for one relation:
   `FilterField("<name>_id")` on the owning filter, `relation_to_q(...,
   related_lookup="<name>_id")` on the parent's cross-entity filter, and
   `relation_to_q(..., parent_field="<name>_id")` on the child's. Missing one
   surfaces as `operator does not exist: uuid_v7 = bigint`. Rewrite them to
   `<name>__id` so criterion values stay integer — **do not flip filter values
   to UUIDs mid-wave**: `/api/games/search` and its siblings feed the facets of
   every mode at once, so a single relation cannot change the option value type
   without breaking the modes still on integer FKs. The values flip once, after
   the last Wave C slice.
2. **`ModelForm` initial values.** `model_to_dict` reads the FK *attname*, so a
   bound instance hands the widget a UUID while a `SearchSelect`'s options are
   integer ids. Seed `self.initial[field]` with the related *instance*;
   `ModelChoiceField.prepare_value` resolves it back to the pk. A field derived
   from the model (plain `<select>`) is self-consistent and needs nothing. The
   helper is `seed_related_initial` in `games/forms.py`. **Check what the view
   already puts in `initial` before adding a call**: `BaseModelForm` merges the
   caller's `initial` over `model_to_dict`, so seeding unconditionally silently
   overwrites a deliberate default — ID-08 hit this on `edit_session`, which
   offers the library's default device to a session that has none. The helper
   now skips a field whose initial is already a model instance, which
   `model_to_dict` never produces.
3. **`games/fixtures/sample.yaml.gz`.** Django serializes a foreign key as the
   target's `to_field` value, so the committed fixture stops deserializing the
   moment a relation moves — and
   `tests/test_library_commands.py::test_committed_sample_load_owns_private_rows_and_reuses_shared_platform`
   loads that exact blob, so it is a `make check` failure. The fixture must
   carry the target's `uuid` and reference it. Regenerate with a throwaway
   transform (ID-06's design records the recipe); a database round trip does
   not work, because loading the old fixture needs pre-cutover code while the
   migration needs post-cutover code.
4. **`load_sample_data` and `anonymize_sample`.** The loader's
   `FIXTURE_RELATIONSHIPS` (now a `FixtureRelationship` NamedTuple) declares
   which field of the target a reference names — a new relation adds
   `reference_field="uuid"` there. If the loader *remaps* that target (it does,
   for `Platform`, matching an existing shared row on `(library, name, group)`
   and otherwise creating one), the remap must translate to the **real** row's
   `uuid`: it is never the fixture's, on either path. Its values must be `str`,
   because prepared records are re-serialized with `yaml.safe_dump`, which
   cannot represent a `UUID`. The anonymizer keys its per-game date-offset map
   by integer pk and looks it up through the child's FK attname, so each moved
   ***`Game`*** relation needs the matching UUID-keyed map — ID-07 needed no
   anonymizer change at all, because nothing there is keyed by platform. Read
   the command rather than applying this item by rote.
5. **A nullable relation is a different migration, and different metadata.**
   Established by ID-07, which moved the first two:
   - **Five operations, not six.** ID-06's leading `AlterField` exists only to
     relax a `NOT NULL`; on an already-nullable column it is a no-op that
     implies a constraint that does not exist. Of what remains, only
     `Session.game` is `NOT NULL`.
   - **Reconciliation asserts NULL-set identity**, as two zero-row anti-joins
     (nothing gained NULL, nothing lost it) rather than a count comparison,
     which passes if one row gains NULL while another loses it. Both backfill
     directions are `UPDATE … FROM` joins, so NULL rows are simply not touched
     — reversibility needs no special case.
   - **The filter-metadata nullability fix is already done** (`common/criteria.py`,
     `_lookup_is_nullable`). Rewriting a lookup to `<name>__id` moves the
     resolved field from the nullable FK to the target's `NOT NULL` pk, which
     silently dropped the facet's presence modifiers. Nullability is now a
     property of the whole lookup path, OR-ed across relation hops, so ID-08
     and ID-09 need no per-relation nullability work.
6. **Check the owning model's `Meta.unique_together` and `constraints`.**
   `RemoveField` compiles to a bare `DROP COLUMN`, and PostgreSQL cascades away
   every index over that column — while Django's migration *state* still lists
   them, so `make check-migrations` reports no drift and the suite stays green
   with the guarantee gone. ID-07 had to take down and restore both of `Game`'s
   (`unique_together`, which also has to be empty across the window where the
   field does not exist, and the partial platformless-name `UniqueConstraint`).
   Assert them present *and enforced* afterwards; before ID-07 no test asserted
   either. Note when writing that test that a NULL never collides in a unique
   index, so a row needs non-NULL values in every constrained column to trip it.

Also settled by ID-06 and reusable verbatim: the reversible migration shape
(optionally relax NOT NULL → add holding column → backfill and reconcile → drop
integer column → rename → retype into the real FK), with the
`SET CONSTRAINTS ALL IMMEDIATE` guard between the backfill and the schema
alterations. Django's final `AlterField` does rename the column and create the
FK constraint in one operation — confirmed twice now, in ID-06 and ID-07; the
`SeparateDatabaseAndState` fallback the design describes has not been needed.

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

Two columns are still integers when ID-10 runs, both on `games_purchase_games`,
and neither is a gap: `game_id` is the M2M column ID-09 deferred (anomalous — the
only `Game` reference that did not move in Wave C), and `purchase_id` is normal,
because `Purchase.uuid` is not promoted until ID-13. `auth.User` is not a
converted model, so `UserLibrary.user` and `UserPreferences.user` stay integer
throughout.

## Wave E — remove legacy integers, promote UUID to PK (ID-11–ID-14, 4 issues, was 1)

The original `#646` "Remove legacy integer identities" is re-scoped from one
issue into four (ID-11/#646, ID-12/#848, ID-13/#849, ID-14/#850 on GitHub),
mirroring Wave B's grouping for review-size symmetry: catalog (`Game`+
`Platform`), Session/play-history (`Session`+`PlayEvent`+`GameStatusChange`),
Purchase, library configuration (`Device`+`FilterPreset`). Each PR, per model
group: drops the integer `id`, renames `uuid` to `id`, promotes it to primary
key, and drops any transitional `to_field` pointers Wave C's FK columns needed
while `uuid` wasn't yet the primary key. (Amended 2026-08-18 by
[the ID-06 design](2026-08-18-issue-644-playhistory-fk-uuid-design.md): the
old integer FK columns are dropped by Wave C itself, in the same migration
that adds the UUID column, because a retained `NOT NULL` integer FK column
would keep a live write-path obligation for two more waves. Wave E has no FK
columns left to drop — only the integer `id` and the `to_field` pointers.) Lower risk than Wave C per PR — by this point
nothing references the integer columns — but kept split for reviewability
and to keep `games/sorting.py`'s `F("pk").asc()` tiebreak change auditable
per model group rather than in one sweep. All four are `blocked-by` ID-10.

**ID-11 and ID-13 are no longer pure contractions** (amended 2026-08-18 by
[the ID-09 design](2026-08-18-issue-847-purchase-fk-uuid-design.md)). Each owns
one expand/contract on `games_purchase_games` — ID-11 on `game_id`, ID-13 on
`purchase_id` — as a UUID holding column, an `UPDATE … FROM` join, a drop, a
rename, and a restore of the FK plus the `(purchase, game)` unique index that
`DROP COLUMN` cascades away (checklist item 6, which applies to the through
table because its `unique_together` spans both dropped columns). Django's
migration *state* needs no operation: an auto-created through derives its
foreign keys from the target's pk at state-render time.

ID-11 additionally owns everything keyed to `Game` and `Platform` ceasing to be
integers, which is the larger half of that slice: deleting `to_field="uuid"`
from every FK naming `Game.uuid` or `Platform.uuid` (mandatory — `to_field`
becomes `fields.E312` the moment the field is renamed), the corresponding
`seed_related_initial` arguments in `PurchaseForm`/`SessionForm`/`GameForm`,
`audit_library_ownership`'s `related_game__id`/`platform__id` lookups,
`PurchaseFilter._games_to_q`'s `int(...)` coercion, and the `Game`/`Platform`
half of the option-value annotation widening described in Wave C above.

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
