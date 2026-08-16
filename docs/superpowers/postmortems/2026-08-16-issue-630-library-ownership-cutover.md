# Issue 630 library-ownership cutover postmortem

Date: 2026-08-16

Issue: [#630](https://github.com/KucharczykL/timetracker/issues/630)

Implementation: [PR #837](https://github.com/KucharczykL/timetracker/pull/837)

## Executive verdict

The production migration succeeded. All recorded data, relationships, user
preferences, and the last complete converted-price cache were preserved; the
ownership audit found no cross-library links. When the first startup exposed a
legacy scheduler problem, the protected backup restored production exactly and
the corrected cutover completed safely.

The delivery process was nevertheless disproportionate to a one-user homelab
cutover. The central planning error was treating an atomic deployment as if it
also required one issue and one pull request. The resulting change was too large
for coherent human review. Extensive automated review found real defects, but it
was compensating for poor work-unit boundaries.

Manual downtime, rehearsal, and rollback-by-restore were sound decisions. The
bespoke manifest machinery, temporary conversion subsystem, breadth of operator
tooling, and review protocol collectively went beyond the smallest safe solution.

## What was delivered

#630 absorbed the intended outcomes of the former #631-#638 issues. It added the
final ownership schema and production data migration, split settings and
preferences, scoped pages/forms/APIs/filters/statistics, introduced a temporary
atomic currency-conversion bridge and browser notifications, added operator
import/delete/audit commands, converted the existing test suite, and documented
and rehearsed the production operation.

PR #837 was open for 45 hours 28 minutes of wall-clock time. Active work cannot
be recovered reliably from commit timestamps, so this document does not invent
an active-hours estimate. The PR contained 29 commits and changed 161 files:
12,068 additions and 2,231 deletions.

| Category | Files | Added | Deleted |
| --- | ---: | ---: | ---: |
| Tests | 113 | 7,552 | 1,616 |
| Runtime code | 40 | 2,495 | 501 |
| Historical migration | 1 | 1,191 | 0 |
| Documentation and plans | 4 | 805 | 110 |
| Fixtures and build files | 3 | 25 | 4 |

The headline 12k additions therefore do not represent 12k lines of enduring
application code. Tests account for 63%, while runtime code accounts for 21%.
That context matters, but it does not make a 161-file review unit reasonable.

Of the test additions, 4,611 lines were twelve new files and 2,941 lines modified
101 existing files. Migration/reconciliation and authorization-isolation
coverage were justified. Some conversion, operator-command, overlapping matrix,
and compatibility coverage existed because the approved design itself was too
broad. Test volume is not independently virtuous when reviewers cannot relate it
to a comprehensible change.

## What went well

- The production-copy rehearsal exercised the exact data migration and validated
  counts, links, preferences, currencies, totals, pages, and APIs.
- The final migration failed closed instead of guessing ownership. Production
  received one library, all expected rows, and zero cross-library links.
- The backup/manifest pair was protected and verified. Restoring it removed every
  write from the failed first attempt, demonstrating a real recovery path rather
  than a theoretical rollback story.
- Independent reviews found material authorization and concurrency defects before
  merge. The final full gate passed 3,128 Python and 769 TypeScript tests plus all
  static and migration checks.
- The production incident changed only a derived conversion cache. Source
  Purchase facts remained intact, and the restored final total matched exactly.

## What went poorly

### Deployment granularity was confused with review granularity

The original issue split contained unnecessary independently deployable
transitional states. Collapsing those states was correct. Collapsing schema,
runtime scoping, settings, conversion, tooling, compatibility, and cutover into
one issue and PR was not.

One atomic production release could still have been assembled from bounded child
issues and stacked PRs targeting an integration branch. Nothing required every
reviewer to absorb 161 files at once.

### The design interview had no complexity budget

Individually reasonable answers accumulated into a large contract. Reversible
implementation choices received the same attention as irreversible data and
product decisions. No checkpoint translated the accumulated requirements into
an expected file count, code size, test churn, or elapsed-time range.

Once the design was approved, removing implementation would have broken agreed
behavior. The correct intervention point was before design freeze: show the
aggregate cost and choose a smaller present-day contract.

### Single-use context encouraged the wrong kind of machinery

Taking the only production environment offline, rehearsing a current copy, and
restoring on failure were appropriate. A conventional atomic Django data
migration with narrow preflight checks would probably have been simpler than a
1,191-line migration that validated an external manifest and reconstructed every
historical configuration source.

Having one environment reduces the need for general machinery. It does not make
bespoke machinery cheaper. The likely better sequence was: materialize the few
external settings into database rows, run a read-only preflight, back up, stop
production, run a conventional migration, audit, and start.

### Compatibility feedback arrived too late

The full suite was intentionally deferred until Task 10. Its first run then
reported 233 failures and 216 errors, mostly stale fixtures after central models
gained required ownership. A broad gate immediately after the non-null schema
change would have localized that work and avoided a separate 298-line repair
plan late in the issue.

### Verification volume missed the actual operational boundary

The rehearsal proved migration and application behavior but did not start the
worker with the copied django-q schedule and observe a scheduler interval. On
the first production start, a legacy every-minute conversion schedule survived.
Bootstrap ran migrations but did not replace the schedule, so the worker invoked
the compatibility conversion function repeatedly and changed the derived cache.

The response was correct: stop immediately, restore the exact backup, migrate
again offline, replace the schedule before workers started, and observe the new
daily recovery through its first run. The lesson is that coverage should follow
operational risk, not merely maximize assertions.

## A better delivery structure

The final production invariant and one offline deployment should remain owned by
one parent cutover issue. Implementation should be divided into reviewable child
units:

1. final schema, data migration, preflight, and ownership audit;
2. settings and preference split;
3. request/query/form/API authorization boundary;
4. the smallest required currency-conversion behavior;
5. necessary operator and fixture tooling;
6. compatibility, full reconciliation, and production rehearsal.

Their PRs can target an integration branch rather than `main`. Each slice remains
reviewable and testable, while no intermediate state becomes a production
release. The final integration PR should introduce no surprise feature work; it
only proves the assembled release and its cutover.

## Timeless planning guidance

### Separate four boundaries explicitly

An issue boundary, review/PR boundary, migration boundary, and deployment boundary
solve different problems. Choose each deliberately. “Must deploy together” does
not mean “must design, implement, and review together.”

### Budget complexity before freezing scope

Before approving a large design, estimate affected subsystems, files, runtime
code, migration size, test churn, operational steps, and elapsed-time range.
These are forecasts, not commitments. Their purpose is to reveal when many small
decisions have created a different-sized project.

Set stop-and-replan triggers. Examples include crossing three independent
subsystems, requiring repository-wide fixture changes, introducing a state
machine, or exceeding a review unit that one person can understand in one sitting.

### Spend questions on irreversible decisions

Interview deeply about data loss, authorization, externally visible behavior,
compatibility promises, and irreversible operations. Give reversible internals a
recommended default and record them as assumptions. They can be changed when
implementation evidence appears.

### Classify scope by time horizon

Label requirements as cutover-critical, required by the current product, or
future hardening. Future multi-user, hosted, generalized import, or reusable
recovery behavior should not enter a single-user cutover without a separate,
explicit cost decision.

### Prefer conventional migrations by default

Use ordinary schema/data migrations when the transformation is derivable from
database state, can run transactionally, and should accompany the schema
everywhere. Add read-only preflight and post-migration audit commands when useful.

Use bespoke operator machinery only when the operation genuinely depends on
external systems, unavoidable human judgment, or data volumes that cannot fit the
normal migration model. “Only once” is not by itself a reason to generalize.

### Test risks, then remove overlap

Protect destructive transformations, authorization boundaries, concurrency, and
recovery paths. Run a broad gate soon after a central schema contract changes.
Once the behavior matrix is covered, remove assertions that repeat the same fact
through another endpoint or layer without defending a distinct failure mode.

### Rehearse the running system

A production rehearsal includes background workers, schedules, queues, caches,
health checks, and at least one relevant polling interval—not only migrations and
HTTP requests. Recheck key data invariants after asynchronous components run.

## Planning checklist for large changes

- What must be atomic in production, and what merely needs coordinated release?
- What are the independently understandable review units?
- Which decisions are irreversible or externally visible?
- What is the smallest current-user outcome?
- Which requirements are future hardening?
- What size and elapsed-time range does the accumulated design imply?
- What threshold will trigger decomposition or replanning?
- When will the first broad compatibility test run?
- Does rehearsal execute every stateful background component?
- Is recovery proven with the actual backup artifact?
- Can a reviewer explain each PR without reading the entire parent project?

## Follow-through

#826 and #827 remain separate UI work and should preserve their bounded scopes.
Future overhaul work should use the four-boundary distinction and complexity
budget above. The retained pre-#630 backup requires the documented cutover steps
if it is ever restored; current production and fresh installations cannot inherit
the legacy schedule that caused the first attempt.
