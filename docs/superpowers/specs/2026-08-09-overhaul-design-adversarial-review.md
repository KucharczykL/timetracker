# Adversarial review: overhaul design and Player's Journal design

Date: 2026-08-09
Reviews:
- [2026-08-09-timetracker-overhaul-design.md](2026-08-09-timetracker-overhaul-design.md)
- [2026-08-09-player-journal-design.md](2026-08-09-player-journal-design.md)

This review is deliberately hostile. It assumes the documents are wrong until
the code says otherwise, and it prioritises findings that would cost real
rework if discovered during implementation instead of now. Findings are grounded
in the current tree (`games/models.py`, `common/criteria.py`,
`timetracker/settings_registry.py`, `games/views/stats_data.py`) rather than in
the documents' own claims about the current tree.

Sections: **A. Blockers** (the design as written cannot be executed),
**B. Structural objections** (it can be executed, but the shape is wrong),
**C. Contradictions between the two documents**, **D. Missing surfaces**,
**E. What is right**, **F. Recommended restructuring**.

---

## A. Blockers

These are not "audit items". They are known, specific, load-bearing failures in
Phase 0 and Phase 1, and the design currently hides all of them behind one
sentence: *"The work audits every migration, GeneratedField, RawSQL expression,
duration, timestamp/timezone, JSON field, conditional uniqueness rule,
case-insensitive query, sequence, and deletion behavior."* An audit list is not a
plan when the answers are already knowable and three of them are "this cannot be
ported, the model must change first."

### A1. `duration_total` cannot exist on PostgreSQL as written

`games/models.py:322` defines a generated column whose expression references
another generated column:

```python
duration_calculated = GeneratedField(expression=Coalesce(F("timestamp_end") - F("timestamp_start"), 0), ...)
duration_total     = GeneratedField(expression=F("duration_calculated") + F("duration_manual"), ...)
```

PostgreSQL rejects this outright — a generation expression may not reference
another generated column. There is no flag, no workaround at the DDL level; the
column must become a plain column maintained in application code, a view, or be
deleted.

This matters far beyond a migration detail, because the design's phase ordering
depends on it not mattering. Phase 1 is *"Port the current schema/application/
test suite to PostgreSQL"* and the replacement of the additive
`duration_manual + duration_calculated` model with explicit timing modes is
Phase 6. That ordering is impossible: the Session duration model has to be
reshaped **in Phase 1**, five phases before the design says it will be. Either
Phase 1 ships a stopgap (drop `duration_total`, compute in Python, update ~68
references) which is throwaway work, or Session timing modes get pulled forward
into the database migration, which contaminates the "port, don't redesign"
property that makes Phase 1 low-risk.

Name this in the document and pick one. It is the single most consequential
sequencing fact in the plan.

### A2. `price_per_game` divides by zero — every Purchase INSERT fails

`games/models.py:193`:

```python
price_per_game = GeneratedField(
    expression=Coalesce(F("converted_price"), F("price"), 0) / F("num_purchases"), ...)
```

`num_purchases` defaults to `0` and is only set afterwards by the `m2m_changed`
signal (`games/signals.py:72-76`), so a Purchase row exists with
`num_purchases = 0` for the duration of every create. SQLite returns `NULL` for
`x / 0`. PostgreSQL raises `division by zero` (SQLSTATE 22012) and aborts the
statement.

Consequences the design does not cover:

- Creating a Purchase fails on PostgreSQL from the first request after cutover.
- The transfer tool cannot insert any existing row that has `num_purchases = 0`,
  and *"omits/recalculates database-generated values where appropriate"* does not
  help — the failure is in the generation expression evaluated during INSERT, not
  in the value being copied.

The expression needs a `NULLIF(num_purchases, 0)` guard (or the column has to
stop being generated) before any data moves. Again: Phase 1 work, currently
invisible.

### A3. `days_to_finish` is raw SQLite SQL with different semantics elsewhere

`games/models.py:444` embeds `date()` and `julianday()` in a `RawSQL`
expression. Both are SQLite-only. The portable rewrite is not mechanical:
`julianday(a) - julianday(b)` yields a float, while `ended - started` on two
PostgreSQL `date` columns yields an integer, and the `output_field` is
`IntegerField` — meaning the current column has been silently truncating a float
this whole time. Whether the migrated values match the old ones for every row is
a parity question the transfer's reconciliation report has to answer explicitly.

### A4. `ORDER BY` results change for every nullable sort column

SQLite sorts `NULL` first in `ASC` and last in `DESC`. PostgreSQL does the exact
opposite by default (`NULLS LAST` in `ASC`, `NULLS FIRST` in `DESC`). The tree is
full of ordering over nullable columns — `games/views/stats_data.py:229` and
`:340` order by `games__playevents__ended` (nullable), `game.py:637` by
`-timestamp_start`, stats by `-date_finished`, plus every user-selected `sort=`
key that resolves to a nullable field.

So: list pages, stats tables, and the sort editor all reorder after migration,
and any test asserting row order flips. This is cheap to fix (`F(...).asc(nulls_last=True)`
or an explicit `Meta.ordering` policy) and expensive to discover during a cutover.
It is not in the audit list.

Adjacent and also absent: **collation**. `ORDER BY name` under SQLite's `BINARY`
collation is not the same as under PostgreSQL's `en_US.UTF-8`. The design must
pin the database's collation (`C.UTF-8` preserves current behaviour; a locale
collation changes visible game-list ordering) and say so in the deployment
contract, because operators creating their own database will otherwise pick
whatever their image defaults to.

### A5. `__regex` changes dialect, and the ReDoS analysis becomes wrong

`common/criteria.py:464` compiles `MATCHES_REGEX` / `NOT_MATCHES_REGEX` to a
`__regex` lookup. Django implements that lookup on SQLite by registering a Python
`re.search` function; on PostgreSQL it becomes the `~` operator with POSIX ARE
syntax. These are different languages. Lookaheads, `(?i)`, `\b`, and non-greedy
semantics do not transfer identically, so a saved `FilterPreset` containing a
regex will either change meaning silently or start raising a database error at
query time.

The design's FilterPreset story (*"Supported fields and enum values are rewritten
explicitly"*) covers field renames and enum churn. It does not cover
**criterion values whose interpretation is database-defined**. Regex presets need
their own validation pass during the PostgreSQL migration, not during the domain
migration.

Second-order: the deliberate ReDoS guard documented at `common/criteria.py:226`
is justified entirely by *"SQLite runs `re.search` per row, with no timeout"*.
After migration that comment is false, the threat model moves into the database,
and PostgreSQL — which does backtrack, and which has no `statement_timeout`
configured in this project — inherits it. The guard's heuristic length/quantifier
checks were explicitly chosen as partial protection over a runtime bound; moving
to PostgreSQL makes `statement_timeout` available as the real fix. The design
should claim that win rather than leave a stale comment and an unexamined
worker-hang path.

### A6. The developer and CI bootstrap story is a regression, and it is unaddressed

*"Local development and `make check` run against PostgreSQL as well"* is one
sentence spending the most valuable property this repository has. `CLAUDE.md`
devotes several hundred words to the fact that **`make check` runs anywhere with
no Nix shell** — `ensure-python` provisions 3.14, `ensure-node` verifies what
`pnpm exec` will actually run, e2e discovers a system Chrome on Windows and macOS
without a `playwright install` download. The current maintainer verifies on
Windows with no Nix, no direnv, and no WSL. Adding "and also a running PostgreSQL
of a pinned major version" to that contract is the largest practical change in
the whole design and it gets no `ensure-postgres` target, no container-vs-local
decision, no story for `make check` on a laptop with no Docker.

Two concrete consequences that need answers in the document:

- `tests/test_live_server_db_concurrency.py` exists specifically to guard the
  on-disk SQLite test database (issue #476: shared-cache table locking against
  `live_server`'s threads). Its entire rationale evaporates, so it is deleted —
  but the *problem* it guards does not evaporate, it changes shape. The suite
  runs at up to 16 xdist workers, each e2e test serving requests on multiple
  `live_server` threads, each thread taking a connection. That is a
  `max_connections` and per-worker-database question that nobody has asked yet,
  and getting it wrong reproduces exactly the intermittent-failure class #476
  fixed.
- pytest-django creates one test database per xdist worker. Against SQLite that is
  16 files; against PostgreSQL it is 16 `CREATE DATABASE` calls per run, and
  template/`--reuse-db` behaviour becomes load-bearing for suite runtime. The
  design's cost model for `make check` should state the expected wall time.

---

## B. Structural objections

### B1. PostgreSQL is asserted, never argued — and it is the most expensive item

Principle 9 states *"PostgreSQL is the sole runtime database"* as an axiom. The
only technical justifications offered anywhere are (a) *"Event stream sequencing
later uses PostgreSQL row locking and a unique stream/sequence constraint inside
the same transaction as projections"* and (b) optional JSONB / full-text search.

Neither survives scrutiny as a *requirement*:

- A unique `(stream_id, sequence)` constraint inside a transaction is ordinary
  SQL and works on SQLite. This project already runs SQLite in `IMMEDIATE`
  transaction mode precisely so that a writer takes its write lock up front
  rather than failing on upgrade (`timetracker/settings.py:154-159`) — which is
  the serialisation property an append-only event store wants. For a
  single-writer-per-library workload, SQLite's whole-database write lock is not
  a bottleneck; it is a free global sequencer.
- JSONB and full-text search are Phase 14+ conveniences, not Phase 0 needs.

Against that, the costs are: a bespoke transfer command with a reconciliation
report, a dry-run mode, a rollback artifact policy, a squashed migration
baseline, a Compose rewrite with a second volume, documented backup/restore
procedures, a new CI service, a new local-dev prerequisite, and a Phase 13
sub-issue to delete the transfer tool afterwards. For an application whose
deployment target is explicitly *"a personal self-host"*, this raises the floor
from "one container and a file you can copy" to "two containers, two volumes, and
a `pg_dump` runbook".

That may still be the right call — hosted multi-user operation (follow-up 10) is
a genuine argument, as is not maintaining two backends' worth of generated-column
behaviour. But the document must **make** the argument, with the specific
scenario SQLite fails, because everything else in the plan is sequenced behind
it. As written, a reader cannot distinguish a requirement from a preference.

If the argument turns out to be "hosted multi-user later", then the honest
structure is: keep SQLite for the self-host path through the domain overhaul, and
introduce PostgreSQL as the *hosted* deployment's backend in the phase that
actually needs it. That deletes Phase 0 from the critical path of every other
phase.

### B2. Two full-database identity rewrites where one would do

Phase 1 transfers SQLite→PostgreSQL *preserving integer primary keys*. Phase 3
then rewrites every primary key, foreign key and M2M reference to UUIDv7 through
a temporary mapping table that is verified and then deleted. That is two
row-by-row rewrites of the entire database, two verification passes, two rollback
stories, and two windows in which a bug corrupts references.

The stated reason for keeping integers in Phase 1 — *"preserves the current
integer identities only long enough to copy the existing schema faithfully"* — is
weak, because the transfer is *already* a row-by-row rewrite into an empty target
with a reconciliation report. Minting UUIDv7 during that same pass and reporting
old-id → new-id in the reconciliation output is strictly less work than doing it
twice, and it removes the temporary mapping table, its verification, and its
cleanup step entirely.

The counter-argument (Phase 1 stays mechanical and therefore reviewable) is real
but is already lost to A1/A2: Phase 1 cannot be mechanical anyway.

### B3. The plan forbids the decision that staging exists to enable

The document says twice that the first Session slice *"is not a gate for
reconsidering event sourcing"* and *"Event sourcing is the committed
destination; the early Session slice reduces delivery risk rather than deciding
whether the remaining migration happens."*

This is an anti-review clause. The purpose of a narrow first vertical slice is to
produce information; pre-committing to ignore that information converts the slice
into ceremony. If the slice reveals that a command + event + projector + replay
test for what is currently a `ModelForm` save multiplies the cost of ordinary CRUD
by 4-5×, that is exactly the moment to reconsider scope — for instance by keeping
event sourcing for Sessions/Playthroughs/Purchases and leaving Devices,
Platforms, and PlayerGame preferences as plain models (which the design already
half-does).

Recommend replacing both sentences with explicit, falsifiable exit criteria for
the slice: acceptable lines-of-code multiple for a CRUD operation, acceptable
projection rebuild time at a stated row count, acceptable added latency per write.
State that failing them triggers a scope review, not a rollback of the idea.

### B4. Deleting multi-game bundles contradicts a recent, documented, deliberate design

`CLAUDE.md` documents the current model with unusual specificity: *"A multi-game
Purchase is an **unsplittable** bundle (one price, whole-purchase refund — e.g. a
Humble Bundle). Independently-refundable multi-item orders (e.g. a Steam cart) are
modeled as **separate single-game purchases**, not one bundle"* — and a `Split`
action already exists for the case where a bundle was the wrong model. The
distinction is not accidental; it is the stated reason no through-model is needed
for per-game refunds.

The overhaul deletes it in three sentences, calling it *"an accepted one-time
simplification for the handful of existing bundles"*, and does not say what
happens to whole-bundle refund semantics afterwards: if a Humble Bundle becomes
five Purchases with the price divided evenly, a refund of that bundle is now five
refunds of fabricated amounts — which violates the design's own principle 1
("never invent precision") applied to money rather than time.

Either the `CLAUDE.md` rationale is wrong (say so, and say why the refund case
does not matter), or the simplification is wrong. Also: *"the handful"* is a
checkable number. Put the actual count from the production library in the
document; a design that turns on "there are only a few" should show the few.

### B5. "Remove superseded fields" is one line covering ~450 call sites

Phase 13 reads *"Remove superseded fields and compatibility write paths only
after parity checks are green."* Reference counts across `games/`, `common/`,
`tests/`, `e2e/`, and `ts/`:

| Symbol | References |
| --- | --- |
| `PlayEvent` | ~196 |
| `duration_total` | ~68 |
| `duration_manual` | ~61 |
| `related_game` | ~63 |
| `num_purchases` | ~35 |
| `price_per_game` | ~15 |

That is a phase, not a step, and its true cost is not the renames — it is that
**every one of those fields is also a filter facet, a preset key, a stats
annotation, and in some cases a TypeScript fixture**. See D1.

### B6. Uneven altitude

The IGDB rate limiter gets a paragraph specifying lease expiry semantics under a
simulated worker crash. The event store — the actual foundation — gets no
statement of what happens on a sequence collision, no retry policy, no rebuild
time budget, and no statement of whether projection rebuild is online or takes
the app down. A reviewer's attention should be drawn to risk in proportion to it;
right now the most speculative workstream is the most precisely specified.

---

## C. Contradictions between the two documents

### C1. Pre-migration status history disappears from the Player's Journal

This is the most user-visible consequence in either document, and neither states
it.

Chain of stated rules:
1. `GameStatusChange` is an audit log with an exact `timestamp`, ordered
   `-timestamp` (`games/models.py:491`). That timestamp is a *recording* time.
2. The overhaul: *"every status transition—including undated transitions—are
   preserved as migration-sourced history"*.
3. The overhaul: *"Only facts whose effective temporal value has day precision
   enter this global daily timeline; `recorded_at` is never substituted for an
   unknown or imprecise effective date."*
4. The Journal doc: *"No fact falls back from unknown `effective_time` to
   `recorded_at`."*

Applied literally, every historical status change becomes an unknown-date fact
and is relegated to per-game Approximate history. For an existing user, the
Player's Journal after migration shows **no status history at all** before the
cutover date — on a feature whose headline example is *"a day on which five games
are marked Abandoned"*.

The resolution is almost certainly that `GameStatusChange.timestamp` *is* a
legitimate day-precision effective date, because the application recorded the
change at the moment the user made it. But that is a decision, it needs to be
written down, and the same question applies to `PlayEvent.started`/`ended`
(dates, so day precision — fine) versus `PlayEvent` rows with neither date (truly
unknown — correctly relegated). Say which legacy facts inherit day precision from
their recording time and why that is not a violation of principle 1.

### C2. Migration must mint correlation IDs, and neither document says it does

The Journal's duplicate-suppression rule is unambiguous: *"Correlation
identity—not same game/day coincidence—is the only basis for collapsing facts."*
The migration turns each `PlayEvent` into a Playthrough with start/completion
facts, and separately preserves `GameStatusChange` rows including the transition
to Finished/Completed.

Those two migrated facts describe one user action but will have no shared
correlation ID unless the migration explicitly assigns one. Result: every
pre-migration completed game renders **twice** in its Journal day — once as
`PlaythroughCompleted`, once as `GameStatus(Completed)` — which is precisely the
outcome the correlation rule exists to prevent, occurring on 100% of historical
data and 0% of new data.

Add to the migration spec: migrated `PlayEvent` completion and its matching
`GameStatusChange` share a correlation ID; state the matching rule (same game,
status change timestamp within the PlayEvent's interval?) and what happens when
matching is ambiguous. This is the same class of problem the design already
handles well for Session→Playthrough assignment ("Imported history—needs
sorting"); it just was not applied here.

### C3. The four-line narrative budget is not implementable as specified

The Journal doc specifies a *"shared four rendered-line budget"* where
*"Complete notes remain complete when they fit; only true overflow is clipped"*
and *"The `See all N notes` link appears only when the budget clips content."*

"Rendered lines" is a function of viewport width, font metrics, and zoom. The
server cannot know it. The repository's only truncation primitive,
`TruncatedText` (`common/components/primitives.py:655`), is **single-line width
clipping with a CSS fade** — it does not solve this and does not generalise to a
budget shared across sibling blocks.

So there are exactly two implementations, and they contradict different parts of
the doc:

- **CSS/JS measurement** (`-webkit-line-clamp` over a wrapper, or a custom element
  measuring `scrollHeight`). Handles the "shared budget across N notes" case only
  with a wrapper element and a JS pass; conditional rendering of `See all N notes`
  then becomes client-side, contradicting *"The view builds typed journal data
  before rendering"* and making verification item 5 (*"the exact visibility and
  target of `See all N notes`"*) an e2e-only assertion at fixed viewport sizes.
- **Server-side character/word budget** approximating four lines. Deterministic
  and unit-testable, but then *"complete notes remain complete when they fit"* is
  false at narrow widths and over-clipped at wide ones.

Pick one and rewrite both the IA section and verification item 5 to match. My
recommendation is the server-side budget (deterministic, testable, no new client
element, degrades honestly), with the doc dropping the word "rendered".

### C4. The Journal's central query has no design

*"It shows seven populated days per page by default"* — where a "populated day" is
a day with content in **any of five heterogeneous read models**: Sessions,
PlayerGame status facts, Playthrough lifecycle facts, Historical Playtime facts,
and Purchases. Paginating by *populated day* means the query must first determine
which distinct dates have content across all five sources, scoped to the library
and converted to the request-local timezone, then take seven, then fetch each
source for that window.

Neither document says whether there is a materialised `JournalDay` projection or
an ad-hoc five-way UNION per request. That is the single biggest performance and
complexity decision in the feature and it is absent, while the document does
specify the pagination default (7) and the approximate-history default (25) —
that is, it specifies the tuning constants of an undesigned query.

The overhaul's own framing (*"Projectors → Journal"* in the write-path diagram)
implies a materialised Journal projection, but the Journal doc says *"Synchronous
event projectors maintain the status/lifecycle/purchase facts needed for Journal
queries, while current Session and Historical Playtime projections provide their
summaries and notes"* — i.e. no Journal projection, a join across the others.
Those two statements should be reconciled and one of them made explicit.

### C5. Per-library preference vs. the existing three-scope settings registry

The Journal doc: *"Add a per-library setting, **Show purchases in Player's
Journal**, default `True`."* The overhaul: *"Library-behavior preferences such as
default Device, default currency, and Journal purchase visibility move to
PlayerLibrary."*

The repository has a settings registry with exactly three scopes
(`timetracker/settings_registry.py:95`): `USER`, `SITE`, `INFRA`. That enum drives
the settings pages (`games/settings_forms.py`), the settings API
(`games/api.py:706`, `:754`, `:769`, `:789`), form derivation, and the resolver's
layering. Adding a `LIBRARY` scope means changing the resolver's layer order, both
settings pages, the API's scope filters, the form registry derivation, and the
admin settings page — none of which either document mentions.

Worth also stating the cost/benefit honestly: with a strict one-library-per-user
rule and no library chooser, `LIBRARY` and `USER` scope are **indistinguishable to
the user**. The split buys exactly one thing — a restored library carrying its
domain defaults without overwriting the receiving account's theme. That is a real
benefit, but it is a fourth scope in a registry-driven settings system for one
restore scenario, and the document should say so rather than presenting it as an
obvious cleanup of a *"mixed `UserPreferences` row"*.

### C6. Minor: `Purchase.date_purchased` vs. precision-aware purchase dates

The Journal doc says purchases appear on `Purchase.date_purchased` (the current
concrete field) two paragraphs before its own read-model table says *"effective
purchase date, only at day precision"*. Harmless in isolation, but it is a marker
that the reconciliation pass was textual rather than complete — worth a second
pass over the Journal doc for other surviving references to current field names.

---

## D. Missing surfaces

### D1. The filter system does not appear in either document

Neither document contains the words *filter bar*, *quick filter*,
*QUICK_FACETS*, or *filter-tree*; the word *criterion* appears exactly once,
inside the `FilterPreset` paragraph. This is despite the design renaming or
removing nearly every filterable field on every filterable model. The affected
surface:

- `common/criteria.py` (2,976 lines) — typed criteria bound to field names and
  lookups, including the `__regex` dialect issue in A5.
- `games/filters.py` (856 lines) — `GameFilter`/`SessionFilter`/`PurchaseFilter`.
- `common/components/quick_filter.py` — `QUICK_FACETS` per mode, and
  `is_quick_editable`, whose degrade behaviour changes as facets change shape.
- `ts/elements/filter-tree/` — the TypeScript serializer, its `fixtures.json`,
  and the **cross-language contract test** (`tests/test_filter_tree_contract.py`)
  that asserts the TS output is `to_q()`-equivalent to the Python filter.

Every field rename in this design is therefore simultaneously a criterion change,
a facet change, a preset schema migration, a TS fixture update, and a contract
test update. The `FilterPreset` schema-version registry the design does specify is
the smallest part of that. Add a section, or the phase-13 estimate is off by a
large factor.

Specific new questions the filter system raises that the design does not answer:
how does a criterion express a *precision-aware temporal value*? Is "played in the
2000s" filterable? Does a decade-precision fact match a `BETWEEN 2000-01-01 and
2009-12-31` date criterion — and if it does, has the design just invented the
precision it forbids elsewhere?

### D2. No statistics classification table

The design states the rule — Historical Playtime records *"never contribute to
Session count, average/longest Session, streaks, device-per-day charts, or
invented calendar sessions"* — and gives one worked example of a total. But
`games/views/stats_data.py` (349 lines) plus `stats_links.py` (with its
parity-tested link builders) contain dozens of statistics, each of which now needs
an explicit classification: does this stat accept estimated duration, and at what
temporal granularity?

That classification is design work, not implementation detail, because it
determines whether `stats_links.py`'s parity property (*"each builder's queryset
count equals the stat it links from"*) still holds — a stat that includes
estimated time cannot link to a session-list filter that reproduces it.

### D3. No performance or size budget anywhere

Absent numbers, in rough order of how much they matter:

- Event count and projection rebuild wall time at a realistic library size, and
  whether rebuild is online.
- Journal page query cost (see C4).
- IGDB dump mirror storage — full IGDB endpoint dumps are large, and *"dump
  mirror mode (optional)... intended for hosted or larger installations"* is the
  only sizing guidance given.
- Image cache size and eviction, given *"Images are cached because IGDB documents
  that replaced images remain available only temporarily"* — a cache with no
  eviction policy is a disk-fill bug with a schedule.

### D4. Concurrency and failure policy for the event store

*"Events and their synchronous projection updates commit in the same PostgreSQL
transaction"* plus a unique stream/sequence constraint gives optimistic
concurrency control. Undefined: the retry policy on collision, the retry budget,
what the UI shows when the budget is exhausted, and whether an idempotency-key
replay returns the original result or an error. For a single-user app collisions
will be rare — which is exactly why the path will be untested when it fires.

### D5. Soft-deleted records are invisible for the entire overhaul

Deletion becomes event-preserving and projection-hiding from the first Session
slice (Phase 6), but *"Trash and recovery UI"* is follow-up issue 4. Between those
points, a user who deletes a Session has no way to see or restore it, where today
deletion is at least honest about being permanent. State the interim: is restore
available via an operator command, via the admin, or not at all? "Not at all" is a
defensible answer; silence is not.

### D6. Ordering within a day is undefined

`day_part` *"controls display and within-day ordering only"*. Undefined: how two
facts with the same `day_part` order relative to each other, and how a `day_part`
fact orders against an exact-timestamp Session on the same day. Undefined ordering
means unstable pagination, which is the one bug class that makes a timeline feel
broken. Specify a total order (suggestion: exact timestamp → `day_part` bucket →
`recorded_at` → event UUIDv7, which is itself time-ordered and therefore a free
stable tiebreaker).

### D7. Erasure is a stated non-goal without its consequence

*"permanent event-text redaction"* is listed as a non-goal while follow-up 10 is
hosted multi-user operation with registration and account lifecycle. Those two
are in tension: a hosted user asking for their free-text notes to be erased can
only be served by full library purge. That may be an acceptable answer — say it
explicitly ("erasure is served by library purge; partial redaction is not
supported") rather than leaving a bare non-goal for someone to discover under
time pressure.

---

## E. What is right

Stated plainly, because the rest of this document is not:

- **The `recorded_at` / `effective_time` split, and the refusal to fabricate
  precision, is the strongest idea in either document** and is carried
  consistently through statistics, the Journal, migration, and IGDB release
  dates. Most trackers get this wrong by construction; committing to it early is
  correct even though it costs a temporal-value primitive and a second Journal
  section.
- **Historical Playtime Records instead of fake Sessions**, and the rule that
  they never contribute to session counts, averages, or streaks, is the right
  shape for the actual problem (sparse pre-tracking history).
- **Treating a Steam cumulative counter as an observation to be reconciled, not a
  duration to be added**, is the specific detail that prevents the classic
  double-count bug on re-sync. Good catch, well stated.
- **Correlation IDs producing one Journal entry and a complete Audit History** is
  the right way to let a rich event model present a simple narrative.
- **Explicit, declinable companion changes** ("Also mark Game Completed", checked
  by default) is a good invariant and is applied consistently.
- **Principle 7** — every deferred idea is a named follow-up or an explicit
  non-goal — is followed, and the follow-up register is genuinely useful. Keep it.
- The **"Imported history—needs sorting"** playthrough plus a real Organize
  Sessions UI, rather than a guessed assignment, is the right trade and correctly
  refuses to defer the cleanup tool to a follow-up.

---

## F. Recommended restructuring

1. **Split into three documents.** (a) Storage and runtime migration, (b) player
   history domain model, (c) catalog and IGDB. They have independent value,
   independent risk, and different reviewers. Today an IGDB rate-limiter paragraph
   sits behind a PostgreSQL decision in the same approval.

2. **Add a "Why not SQLite" section to (a), with the specific failing
   scenario** — or move PostgreSQL out of Phase 0 to the phase that actually
   requires it. This is the highest-value single change to the plan. If the real
   driver is hosted multi-user, say that, and keep the self-host path on SQLite
   through the domain overhaul.

3. **Fix A1–A5 by name in the Phase 0/1 scope.** Replace the generic audit
   sentence with: `duration_total` cannot be a generated column (decide: plain
   column or pull Session timing modes forward), `price_per_game` needs a
   zero guard, `days_to_finish` needs a portable expression with a parity check,
   nullable-column ordering needs an explicit `NULLS` policy, collation must be
   pinned in the deployment contract, and regex presets need validation.

4. **Merge the integer→UUID cutover into the transfer** (B2). One rewrite, one
   verification, one rollback artifact, no temporary mapping table, no Phase 3
   cleanup.

5. **Give the first Session slice real exit criteria and re-permit a scope
   decision** (B3). Numbers, not "not a gate".

6. **Add the missing sections:** filter system and TS contract impact (D1),
   statistics classification table (D2), Journal query strategy and whether a
   `JournalDay` projection exists (C4), performance budgets (D3), settings-registry
   scope change (C5).

7. **Resolve the three Journal-level decisions** before implementation planning:
   legacy status-change precision (C1), migration correlation IDs (C2), and the
   narrative budget mechanism (C3). All three are cheap now and expensive after
   the projection is built.

8. **Add the developer bootstrap contract to (a)** (A6): how `make check` runs on
   a Windows laptop with no Docker, what `ensure-postgres` does, expected suite
   wall time under xdist, and what replaces
   `tests/test_live_server_db_concurrency.py`.
