# Adversarial review, round 2: overhaul design and Player's Journal design

Date: 2026-08-09
Reviews:
- [2026-08-09-timetracker-overhaul-design.md](2026-08-09-timetracker-overhaul-design.md)
- [2026-08-09-player-journal-design.md](2026-08-09-player-journal-design.md)
Prior round: [2026-08-09-overhaul-design-adversarial-review.md](2026-08-09-overhaul-design-adversarial-review.md)

The first round's findings were genuinely absorbed: the Phase-1 blockers are
named scope, the event store has retry/idempotency/rebuild semantics and
numeric budgets, the Journal has materialized day/fact projections, legacy
correlation rules exist, and the narrative budget is deterministic. This round
therefore hunts a different class of defect: contradictions *introduced or
exposed by the fixes*, commitments whose enabling detail is missing, and
migration rules that a reconciliation report cannot actually pass as written.
Findings are grounded in the current tree (`games/models.py`,
`games/views/stats_data.py`, `common/components/primitives.py`) and in the
documents' own text.

Sections: **A. Contradictions and unexecutable rules**, **B. Underspecified
load-bearing commitments**, **C. Residue and stale text**, **D. Accepted costs
to state explicitly**, **E. What the revision got right**, **F. Priority
order**.

---

## A. Contradictions and unexecutable rules

### A1. The delivery order contradicts the vertical slice's stated purpose

The event-sourcing section: *"The first production vertical slice is
intentionally narrow: create, correct, delete, and restore Sessions; … It
proves transactionality, idempotency, replay, parity, and the budgets above
**before later domains move**."*

The delivery strategy: step 7 — *"Introduce event-sourced PlayerGame and
mandatory default Playthroughs; backfill their baseline events and convert
each existing PlayEvent into a playthrough, including explicit legacy
effective-time and correlation rules"* — **precedes** step 8, the Session
slice.

So the domain with the hairiest migration in the entire plan (PlayEvent
conversion, legacy effective-time classification, correlation minting,
ambiguity reporting) moves onto commands/events/projections *before* the slice
that exists to prove the command/event/projection tooling. The dependency
motivating the order is real — Session events must reference final Playthrough
identities — but it makes the slice's "proves the machinery first" claim
false: by the time the slice runs, the machinery has already carried its most
complex passenger.

Pick one and write it down:

- **(a)** Step 7 introduces PlayerGame/Playthrough as *conventional* models
  with final UUIDs (identity only, no events). Session events reference those
  identities; PlayerGame/Playthrough cut over to events later, inside step 13,
  after the slice validates the tooling. This preserves the slice's purpose at
  the cost of a second PlayerGame cutover.
- **(b)** Accept the current order and rewrite the vertical-slice paragraph
  honestly: PlayerGame status/playthrough lifecycle is the *first* evented
  domain, the Session slice is the first domain with the full
  create/correct/delete/restore surface, and the budgets gate expansion
  *beyond* those two. Then the backfill in step 7 needs its own parity/replay
  gate, because nothing before it has proven replay works.

As written, the two passages cannot both be true.

### A2. "Stream" is the most load-bearing undefined term in the document

The event section specifies stream mechanics precisely — *"Each stream has a
lockable head row containing its current sequence"*, a unique
`(stream_id, sequence)` constraint, three retries with jitter — but never says
**what a stream is**. Per library? Per aggregate (one PlayerGame, one
Session)? Per domain type per library? Every downstream property depends on
this choice:

- **Contention.** One stream per library serializes every command in a
  library behind one head row — probably fine for one player, but it makes
  the three-retry collision policy nearly dead code and makes bulk operations
  (a 200-session Organize move) a long single-row lock. Per-aggregate streams
  mean a compound command (companion changes are the *normal* case in this
  design) locks **multiple** head rows in one transaction — which requires a
  stated lock-ordering discipline, or two concurrent compound commands
  deadlock, and the retry policy must then handle deadlock errors, not just
  sequence collisions.
- **Idempotency semantics.** *"A command … validates the expected sequence"* —
  a multi-stream command has multiple expected sequences. Which one does the
  idempotency record capture?
- **Replay determinism.** *"A complete library rebuild"* replays events from
  many streams. Cross-stream total order is undefined; per-stream sequences
  do not order events across streams. Replay needs a defined merge order
  (presumably `recorded_at` then event UUIDv7, which the Journal already uses
  for ties) — unstated, and without it two rebuilds of the same library can
  legally disagree wherever projectors are order-sensitive across streams.

This needs its own subsection: stream granularity, the lock-acquisition order
for multi-stream commands, which failure kinds are retried, and replay's total
order across streams.

### A3. Duration-only Sessions have no `timestamp_start`, but the Journal maps Sessions by it

The Journal read-model table:

> `Session projection | configured display-timezone date of exact
> timestamp_start | session summary and non-empty note`

Timing mode 2 (Duration-only): *"known calendar date plus entered duration;
**no invented start time**."* Those cannot both hold. A duration-only Session
has no exact `timestamp_start` to convert; its Journal day must be its
effective calendar date directly, with no timezone conversion, ordered in the
day-part buckets rather than by local instant (the overhaul's within-day
ordering already handles the second half — the table just predates the timing
modes).

This is not cosmetic: the current model *requires* `timestamp_start`
(`games/models.py:298`, non-null), so the migration will mint duration-only
Sessions whose Journal placement is formally undefined the moment cutover
lands. Add a duration-only row to the table (day = effective calendar date;
ordering = day-part bucket), and while touching it, state whether a *running*
timed Session appears in the Journal and with what summary duration.

### A4. The purchase-visibility preference breaks populated-day pagination as specified

Pagination rule: *"A page first selects seven populated `JournalDayProjection`
keys, newest first, then loads all facts for those days."* Day-row rule: *"A
day row exists only while at least one visible fact references it."* Empty-day
rule: *"A day with no visible entries is not rendered."* Preference rule:
*"When the setting is disabled, only Player's Journal purchase entries are
hidden."*

Now take a day whose only facts are purchases, with the preference off.
"Visible" in the day-row rule cannot mean preference-visible — the preference
is a per-library toggle, and flipping it cannot rewrite projection rows (the
doc correctly says it changes no data). So the day projection still holds a
row for that day, day selection returns it as one of the seven keys, and the
page renders an empty day — violating the empty-day rule — or silently shows
fewer than seven populated days.

The fix is small but must be designed: `JournalDayProjection` needs a per-kind
dimension (a purchase-fact count and a non-purchase-fact count is sufficient
today) so day selection can be preference-aware without querying the fact
table. State it. Adjacent gap, same section: Game Journal day selection cannot
use the library-wide day projection at all — say explicitly that per-game
populated days derive from `JournalFactProjection` filtered by Game.

### A5. Even-split bundle migration and the decimal parity check are mutually exclusive without a remainder rule

Three stated rules collide: bundles migrate to one Purchase per game *"with
the price divided evenly"*; monetary values are exact decimals; and migration
runs *"with pre/post-migration totals checked in every currency."*
`10.00 / 3` has no exact even decimal split — the three parts sum to `9.99`
and the parity check fails, for every bundle whose price is not divisible by
its game count.

Specify the remainder rule (largest-remainder, or leftover cents assigned to
the first game in a stated order) so the reconciliation report can assert
exact totals equality. The same question applies to the seeded
`PurchaseValuation` converted amounts, which are also split and also
parity-checked.

### A6. As written, games with zero PlayEvents send every Session to "needs sorting"

*"A legacy Session is assigned automatically only when its date belongs
unambiguously to one PlayEvent's exact date interval. Ambiguous Sessions are
preserved in a system-created **Imported history—needs sorting**
playthrough."*

A Game with no PlayEvents has no intervals, so under a strict reading **none**
of its Sessions can be assigned, and all of them land in the needs-sorting
bucket — for what is plausibly the most common case in a casual library
(sessions tracked, started/finished never marked). That would bury users in
migration review work exactly where zero ambiguity exists: a zero-PlayEvent
game has exactly one playthrough (the mandatory default), and every Session
unambiguously belongs to it.

State the intended rules: zero PlayEvents → all Sessions to the default
playthrough; one PlayEvent → Sessions outside the interval are the ambiguous
case (or belong to the single playthrough — decide); two or more → the
interval rule as written. Related and unstated: when PlayEvents become
playthroughs, does the first one *become* "Playthrough 1" or coexist with an
empty auto-created default, and what numbering do migrated playthroughs get?
`Playthrough N` display requires a stable answer.

---

## B. Underspecified load-bearing commitments

### B1. `C.UTF-8` is unprovisionable on the promised platform matrix unless the PostgreSQL major version is pinned ≥ 17

The deployment contract pins *"the tested `C.UTF-8` collation"* and refuses
anything else at startup. `ensure-postgres` promises Docker-free provisioned
dev clusters on Windows and macOS. But `C.UTF-8` as a libc locale does not
exist on Windows; the platform-independent builtin collation provider
(`pg_c_utf8`) arrived in **PostgreSQL 17**. On any earlier version, the
Windows dev cluster the Makefile just provisioned cannot create the mandated
collation, and the startup check refuses the very environment the document
promises.

The document never names a major version anywhere — *"CI provisions the same
major version explicitly"* explicitly, but which? Pin PostgreSQL ≥ 17 and the
builtin collation provider in the deployment contract, and define
"a compatible local installation" in the `ensure-postgres` fallback chain to
include the collation provider, not just a version floor.

### B2. Compiling a regex on PostgreSQL is the wrong preflight gate

*"Every saved regex criterion is compiled against PostgreSQL during preflight;
patterns outside the supported portable subset retain their JSON but are
disabled."* Compilation success does not establish semantic equivalence, and
the dangerous class is precisely the patterns that **compile in both dialects
with different meanings**: Python's `\b` (word boundary) is a backspace escape
in POSIX ARE, so `foo\bbar` sails through a compile check and silently matches
a control character; mid-pattern `(?i)` is legal for Python and not for ARE's
start-anchored embedded options; ARE's non-greedy quantifiers exist but with
whole-expression greediness rules Python does not share.

The actual protective mechanism is the *"supported portable subset"* — which
is never defined. Define it, and make the preflight a **whitelist parser** of
that subset (reject by default), with compile-on-PostgreSQL only as a
secondary sanity check. Otherwise the section's promise — no silent dialect
change — is not kept by its own mechanism.

### B3. The Historical Playtime contribution table references a dimension the record does not have, and cross-game linking is unresolved

Two defects in one table row and one field list:

1. Stats table: *"Device/platform playtime | … | only with an explicit
   recorded Release/device dimension; never inferred."* The Historical
   Playtime Record's field list — duration, provenance, effective temporal
   value, playthroughs, note, source reference — contains **no Release or
   device dimension**. Either add the optional dimension to the record's
   definition or delete the table branch; today it permits a contribution
   that cannot exist.
2. The record links *"one or more Playthroughs."* Playthroughs belong to
   PlayerGames; nothing restricts the linked playthroughs to one game. The
   worked example ("two playthroughs … 100 hours total") is single-game, but
   if "I played these three games about 200 hours total" is representable,
   the table's *"per-Game totals: yes, visibly estimated"* is unexecutable —
   allocating across games invents precision, which principle 1 forbids.
   Constrain the record to playthroughs of one PlayerGame (recommended), or
   define multi-game records as contributing to all-time totals only and
   excluded from per-Game totals.

### B4. The `infinite` migration changes statistical semantics and has no stated sequencing

Today `infinite` is per-Purchase and excludes purchases from the
unfinished/dropped backlog counts (`games/views/stats_data.py:184,194` —
purchase-count statistics). The overhaul migrates it *"to this preference for
every affected Game … preserving their current statistical meaning."* It does
not quite preserve it: a Game with one infinite and one normal purchase
currently keeps the normal purchase in the backlog count; a Game-level
exclusion removes both. Probably the better semantics — but then say the
meaning *changes* for mixed-purchase games rather than claiming preservation,
and note that the backlog statistics themselves change denominator.

Sequencing is also unstated: the preference lives on PlayerGame (step 7), the
Purchase field survives until purchase migration (step 12) and field removal
(step 18). Which step copies the flag, and in the interval is `Purchase.infinite`
frozen, dual-written, or already ignored by stats? The purchases quick facet
and its saved presets follow whichever answer is chosen.

### B5. The zero-elapsed-plus-manual Session has no classification

The migration classifies by evidence: elapsed + manual → Corrected;
manual-only → Duration-only; elapsed-only → Timed. The current add-manual-
session pattern produces `timestamp_start == timestamp_end` with a non-zero
`duration_manual`: elapsed is *zero but present*. Corrected (final = manual,
keeps an exact instant) and Duration-only (degrades to a calendar day) give
different Journal placement and different within-day ordering. Pick a rule —
suggested: zero elapsed ⇒ Duration-only, date taken from the local date of
`timestamp_start`, original timestamps retained as migration evidence — and
add the case to the cutover preflight's test fixtures.

### B6. The transfer never states its required source schema version

The transfer maps source columns to the final SQLite-era schema, and the
historical-migration section replaces unportable migrations with a squashed
PostgreSQL baseline. Nothing requires the *source* to be at the final SQLite
schema. An operator jumping versions (a year-old install pulled straight to
the PostgreSQL release) presents a source missing recent columns; the outcome
is a column error at best and a silently partial copy at worst. Add a
precondition: the transfer verifies the source's `django_migrations` state
equals the pinned final SQLite-release state and refuses otherwise, and the
upgrade documentation states the required two-hop path.

### B7. The compatibility cleanup cites a follow-up feature as its safety net

*"After the supported upgrade window, an explicit compatibility-cleanup issue
removes the transfer command … exported native backups remain the long-term
portable format."* Native backup/restore is **follow-up issue 5** — deferred
and unscheduled. If cleanup lands first, the sentence is false and the actual
long-term portable format is `pg_dump`. Either add the ordering dependency
(cleanup requires follow-up 5 shipped) or change the sentence to name
`pg_dump`/documented backups as the format until native backup exists.

---

## C. Residue and stale text

### C1. Journal verification item 8 predates the timezone redesign

Item 8 reads *"request timezone handling"* — but the data rules no longer use
a request timezone anywhere: days group by the **configured display timezone**
baked into the projections, and changes rebuild via shadow tables. Rewrite the
item as "configured-display-timezone grouping, and rebuild/swap on timezone
change" (which duplicates item 11's tail — merge them).

### C2. "Known bounds sort newest first" is ambiguous for ranges

Approximate history: by which bound does `2004–2006` sort against `2005` and
against `2000s`? Presumably the upper bound, descending, with precision as a
tiebreaker — one sentence, but pagination stability depends on it being
deterministic.

### C3. "A matching aggregate-history view" is a surface defined nowhere

The statistics section requires values including Historical Playtime to link
to *"a matching aggregate-history view or an explanatory breakdown."* No such
view exists in either document: is it the Game Journal's Approximate history,
a new list mode (with filter/facet implications), or a popover? Name it or
scope it to the subordinate statistics specification explicitly.

### C4. "The handful of existing bundles" is still unnumbered

Round 1 asked for the actual count of multi-game Purchases in the production
library, since the accepted simplification's justification is that the number
is small. It is one query; put the number in the document.

### C5. `See all N notes` needs a day-addressable Game Journal URL

*"Opens that game journal positioned at the selected day"* — under
seven-populated-day pagination, "positioned at" requires the link to carry a
day key and the Game Journal to resolve which page contains it. Trivial, but
it is the only deep-link contract in the feature and currently implied rather
than stated.

### C6. Retired has no companion-change affordance

Completion offers *"Also mark Game Completed."* An endless game's playthrough
never completes the main objective, so nothing ever offers Retired — the
status exists but no interaction path suggests it. One sentence in the
status/playthrough section (e.g., the status selector's follow-up action for
Retired, or a companion on ending access) keeps the companion-change principle
symmetric.

---

## D. Accepted costs to state explicitly

Not defects — consequences the documents accept implicitly and should own in
writing.

1. **Write amplification grows with each projector family.** By step 14, one
   Session command synchronously updates the event, head row, Session
   projection, playtime, Journal day/fact rows, and statistics projections in
   one transaction. The 100 ms p95 command budget was set at the slice; make
   re-measurement mandatory at each step that attaches a projector family,
   not only when someone proposes revising the number.
2. **Worker capping is the likeliest cause of blowing the 25% `make check`
   budget.** Capping xdist workers to the connection budget moves the suite
   off its measured 16-worker optimum. The foundation issue should record
   workers-used alongside both medians so the comparison compares like with
   like.
3. **A display-timezone change is no longer instant.** It pauses library
   writes briefly and triggers a shadow rebuild. The settings UI contract
   should say what the user sees during the rebuild window.

---

## E. What the revision got right

- The Phase-1 blocker list is now explicit, named scope — `NULLIF`, the
  repeated elapsed-time expression, NULLS placement, pinned collation,
  regex disable-with-repair — exactly what round 1 asked for.
- Keeping the PostgreSQL and UUID cutovers separate is now *argued*
  (distinguishing database-semantic defects from identity-map defects), and
  the argument is legitimate; the decision reads as a decision.
- The materialized `JournalDayProjection`/`JournalFactProjection` design with
  same-transaction projectors, day-keys-first pagination, and the explicit
  no-UNION rule resolves round 1's biggest Journal gap cleanly.
- Legacy correlation minting (exactly-one-unambiguous-match, everything else
  stays separate and is reported) is the right conservative rule.
- The deterministic character-budget preview with the 4×30 worked example is
  testable as specified, with no client measurement.
- The concurrency/idempotency/rebuild section now has real semantics and
  numeric gates, and the PostgreSQL rationale is stated as a product choice
  rather than smuggled in as a technical necessity.
- `PlayerLibraryPreferences` as a conventional one-to-one, explicitly *not* a
  fourth registry scope, is the right resolution of round 1's C5.

---

## F. Priority order

1. **Define streams** (A2) — granularity, multi-stream lock order, retryable
   failure kinds, cross-stream replay order. Every other event-section
   guarantee inherits this.
2. **Resolve the step-7/step-8 contradiction** (A1) — either identity-first
   playthroughs or an honest rewrite of the vertical-slice claim.
3. **Make the migration reconciliation actually passable**: split remainder
   rule (A5), zero-PlayEvent Session assignment (A6), zero-elapsed
   classification (B5), source-schema precondition (B6).
4. **Patch the Journal spec**: duration-only day rule (A3), preference-aware
   day selection with per-kind counts (A4), stale verification item (C1),
   day-addressable deep link (C5).
5. **Pin PostgreSQL ≥ 17 / builtin collation and define the regex whitelist
   subset** (B1, B2) — both are one-paragraph fixes now and cutover incidents
   later.
6. **Fix the Historical Playtime table/record mismatch and the `infinite`
   semantics + sequencing** (B3, B4).
7. Sweep the residue (B7, C2–C4, C6) and add the accepted-cost statements
   (D1–D3).
