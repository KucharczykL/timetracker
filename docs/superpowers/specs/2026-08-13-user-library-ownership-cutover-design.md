# User library ownership and production cutover design

Status: approved design from the #629-#638 review and design interview.

Companion specification: [Library page, component kit, and navigation](2026-08-13-library-page-and-navigation-design.md).

## Context

The existing application combines account preferences, private game data, and
globally scoped catalogue data. That works for the current single-user
installation, but it does not provide a clean portable boundary for
backup/restore or safe hosted multi-user operation.

The original OWN plan split this change across ten narrowly scoped issues,
including a temporary legacy library and a library-claim operation. Production
has one known database, one User, and one global collection of private data. It
can be rehearsed on a copy and taken offline for the cutover. The temporary
claim architecture would therefore be machinery for a state that only exists
during this one migration.

This design introduces a durable `UserLibrary` boundary while collapsing the
actual cutover into one coordinated migration. It preserves the useful
separation between the identity foundation and the disruptive cutover without
requiring the application to support half-migrated runtime states.

## Goals

- Give portable game data a stable identity that survives backup and restore.
- Separate account preferences from library-owned data and preferences.
- Scope all supported reads, writes, filters, statistics, and background work
  so hosted users cannot see or change another user's private data.
- Preserve current production data and effective settings through a rehearsed,
  offline migration with explicit reconciliation.
- Support exactly one attached library per User today without adding an active
  library selector or transfer workflow.
- Keep the application structure evolvable if a real multi-library requirement
  is designed later.
- Replace the every-minute price-conversion poll with prompt, atomic,
  per-library conversion and bounded recovery.

## Non-goals

- Library transfer between accounts.
- User-facing creation or selection of additional libraries.
- Supporting arbitrary hand-edited database relationships.
- A reusable legacy-library, claim, compatibility, or rollback framework.
- Database triggers or composite foreign keys for cross-library integrity.
- A final Purchase valuation/event-sourcing model; #728 owns that work.
- Individual Game, Platform, or Device lifecycle redesign.
- Backup/restore implementation or self-service account deletion.
- IGDB catalogue separation.

## Terminology and boundary

The model is named `UserLibrary`, not `PlayerLibrary` or bare `Library`. User is
already the application's account/domain term; “Player” remains valid in the
user-facing “Player's Journal” feature name but is not introduced as a second
identity concept.

There is one `UserLibrary` for each User and one User for each `UserLibrary`.
Application code may use `request.user.library`. There is no selected or active
library stored in a session, thread-local, process global, or request setting.
Services and forms receive the resolved library explicitly.

The one-to-one relationship is an intentional current product rule. A future
multi-library feature may change that relationship, but explicit library
parameters throughout the application keep that change local and deliberate.

## Delivery shape and dependencies

The implementation order is:

1. #639 establishes the repository-wide UUIDv7 convention.
2. #629 adds the unused identity foundation and automatic provisioning.
3. #630 performs the coordinated offline ownership, preference, currency, and
   scoping cutover.

#629 is independently deployable and leaves existing global behavior intact. It
creates a UserLibrary only when a new User is created; it does not backfill the
existing production User. #630 adds UserLibraryPreferences, extends final User
provisioning to all three required companion records, and creates the known
production library with the approved identity and timestamp. #630 is one
deployment/cutover, not a chain of live compatibility releases. The component
and Library-page work in the companion specification follows the cutover.

## Data model

### `UserLibrary`

- Immutable UUIDv7 primary key, using the convention supplied by #639.
- Required one-to-one `user` relationship with cascade deletion.
- `created_at` is set for new records at creation time but can be supplied
  explicitly by migrations and restore. It is not an `auto_now_add` value that
  forcibly substitutes restore time.
- No display name and no `updated_at`.

Backup/restore preserves both the UUID and `created_at`. The production
library receives a newly generated UUIDv7 during cutover and uses the timestamp
of the repository's first commit, `6ae46c5d3481298926e673e93956c934a4a032a7`
(`2022-12-31T14:18:27+01:00`), as its creation time.

### `UserLibraryPreferences`

- The required one-to-one `library` relationship is also the primary key; no
  unrelated surrogate identifier is added.
- Initial preference: optional `default_device`, restricted to the same
  library.
- `updated_at` changes only when a preference value actually changes. A no-op
  save does not change it.
- No `created_at`.

Backup/restore preserves library preferences and their `updated_at` values.
#750 later adds the Player's Journal purchase-visibility preference here.

### Direct and derived ownership

| Model | Ownership rule |
| --- | --- |
| Game | Required direct `library` |
| Purchase | Required direct `library` |
| Device | Required direct `library` |
| FilterPreset | Required direct `library`, replacing its User relationship |
| Platform | Nullable `library`: null is shared, non-null is private |
| Session | Derived through required `game`; no `library` column |
| PlayEvent | Derived through required `game`; no `library` column |
| GameStatusChange | Derived through required `game`; no `library` column |

Purchase retains direct ownership because its many-to-many Game relationship
does not provide one simple parent edge and because purchase reporting is a
first-class library operation.

`Session.game` becomes required. Production's Game-is-null list was checked
and contains zero records. The migration also checks that no saved Session
filter relies on Game being null or non-null. A violation aborts and is
investigated; it is not silently rewritten.

### Platform visibility and uniqueness

A Platform with `library=NULL` is shared, operator-managed catalogue data. A
Platform with a library is private customization. Normal users may select
shared Platforms but may create, edit, browse for management, and delete only
their own private Platforms.

An exact fixture of built-in `(name, group)` pairs determines which existing
production rows become shared. Every unmatched Platform becomes private. There
is no fuzzy migration classification.

Shared duplicates and duplicates within one private library are rejected after
trimming surrounding whitespace and comparing `(name, group)`
case-insensitively. A private `steam` therefore cannot shadow shared `Steam`.
Different libraries may create the same private pair. This is a
Platform-specific rule, not a general normalization framework.

Game uniqueness becomes library-scoped while preserving the application's
current exact, case-sensitive matching. Private custom games remain library
specific after the later IGDB catalogue split.

## Automatic provisioning and structural readiness

Every User created through the supported ordinary ORM path immediately gets:

- one `UserLibrary`;
- one `UserPreferences`; and
- one `UserLibraryPreferences`.

An idempotent User `post_save` receiver owns this provisioning. Raw fixture and
bulk User creation bypass signals and are explicitly unsupported.

At web and background-worker startup/readiness, a cheap structural check
requires every User to have both UserPreferences and UserLibrary, and every
UserLibrary to have UserLibraryPreferences. If this invariant is broken, the
application logs the problem and refuses to serve or process normal work. It
does not repair data silently.

Repair-capable management commands remain runnable and perform their own
preconditions. A separate explicit, read-only ownership audit performs the
expensive relationship and cross-library checks and exits nonzero on any
violation.

## Application scoping

Authenticated views resolve `request.user.library` and pass it explicitly.
Small queryset helpers make ownership intent visible:

- `.for_library(library)` for directly owned records;
- `.visible_to(library)` for shared plus library-private Platforms.

Default managers remain unscoped so migrations, audits, and operator tooling
can deliberately inspect the complete database. Normal page/API lookup,
search, autocomplete, forms, services, filters, statistics, and tasks must use
an explicit library.

Identifiers belonging to another library are treated as nonexistent and
return 404. Staff and superusers receive no bypass in ordinary application
paths. Cross-library relationships are rejected at supported form, service,
and API boundaries and proven by tests. Manual database edits are outside the
supported contract, so triggers and composite-key machinery are omitted.

Commands that touch private data require exactly one `--user` or `--library`
scope. A site-wide command must opt in explicitly with `--all-libraries`.

FilterPreset becomes library-owned and portable. Presets stay in their current
filter/list management surfaces rather than gaining a Library-page panel.
Future schema changes retain unresolved presets and surface them as disabled or
erroneous; they do not silently discard or rewrite them.

Deleting a Device that is the library default clears `default_device`. The
application does not guess a replacement.

## Preference split

`UserPreferences` retains account/presentation choices:

- theme;
- display timezone;
- date and number formatting;
- Session timezone presentation;
- default landing page;
- page size;
- Default purchase currency; and
- Display currency.

`UserLibraryPreferences` contains only settings that travel with game data,
initially the default Device. “Devices and their settings are library-level”
does not move unrelated presentation preferences into the library.

The old `DEFAULT_DEVICE` site/User setting is removed completely. There is no
site fallback after cutover: a library either has its own optional default
Device or has no default.

Library is added to the Default landing page choices. An unset choice keeps
the current Sessions fallback.

### Currency settings

The exact setting names are:

- `DEFAULT_PURCHASE_CURRENCY`: “Default purchase currency — preselected when
  adding a purchase.”
- `DEFAULT_DISPLAY_CURRENCY`: “Display currency — converted totals/stats.”

Both use the normal site-default then optional User-override hierarchy.
Purchase currency affects only the default in future entry forms. A Purchase
must always be saved with an explicit `price_currency`; the model rejects a
missing value rather than reading a hidden global fallback. Changing the
setting never rewrites original purchases.

Display currency determines the current per-library converted values and
reporting totals. Changing a site default invalidates only libraries whose
users inherit it; explicit User overrides are unaffected. A no-op setting save
does not request conversion.

### Settings migration

Before deploying the old release's final preflight, record the effective old
currency and effective default Device (personal override first, then site
default). Production configuration is then updated explicitly for the new
keys.

During cutover:

- the old site `DEFAULT_CURRENCY` initializes both new site defaults;
- an existing personal `DEFAULT_CURRENCY` becomes the personal Default
  purchase currency only;
- the personal Display currency starts unset and inherits the old site value;
- the effective old default Device becomes the production library's optional
  default Device; and
- obsolete setting rows are removed.

Post-cutover verification requires both new effective currency values to equal
the recorded old behavior and the library default Device to equal the recorded
choice. There is no runtime alias for old names and no permanent rejection code
for them. A follow-up issue adds focused warnings for unknown `[timetracker]`
configuration keys and stale unknown SiteSetting rows, not arbitrary process
environment variables.

## Atomic conversion bridge

The existing per-Purchase converted amount/currency remains a transitional
cache. #630 introduces one small, purpose-built `PurchaseConversionState` per
library with enough state to identify:

- the latest requested version and target currency;
- the last completely published version and currency; and
- whether the latest request is pending/running or failed, including retry
  timing needed by the UI.

It is not a generic background-operation framework. #728 must replace and
remove it when proper Purchase valuations are introduced.

Relevant original-price/currency edits, new Purchases, and effective Display
currency changes increment the library's requested version in the same
transaction as the triggering change and enqueue conversion after commit.
Rapid requests may create several cheap queue entries, but each job reads the
latest version. A job exits if that version is already published; intermediate
choices are never published.

The worker fetches all required rates and calculates the complete candidate
set before opening the publication transaction. It then locks the conversion
state, verifies that its requested version and target are still current, and
updates all affected Purchase cache values plus the published state in one
transaction. A newer mutation makes the old job discard its candidate result.
Readers therefore see the previous complete currency set or the new complete
set, never mixed currencies.

The existing every-minute sweep is removed. Normal changes trigger conversion
immediately. A failure schedules one retry approximately 15 minutes later. A
daily sweep is recovery only: it finds anything still stale or failed after a
missed trigger or unsuccessful retry.

The previous complete values remain available during conversion or failure and
are always labelled with their actual published currency. Totals are not
hidden or relabelled as the requested currency before publication.

### Conversion notification behavior

The existing toast implementation gains only two generic capabilities:

- a toast may have no dismissal timer; and
- a stable toast identifier permits replacement or removal.

Conversion-specific code owns state lookup, retry language, and browser-tab
dismissal. No notification database model is introduced.

While conversion is active, every authenticated page can reconstruct one
persistent informational toast from server state:

> Prices are being converted. Totals will update when conversion is complete.

Explicit dismissal is remembered in browser session storage for the current
tab and operation phase, so it remains dismissed across navigation in that tab.
Another tab or device may show the still-relevant state. A tab that has
observed active conversion performs a bounded lightweight status check while
work is running; after a failure it waits until the supplied retry time before
checking the retry. Dismissal does not stop completion detection.

Completion removes the persistent notice and produces the existing normal
five-second success toast:

> Prices converted. Totals are now up to date.

The success toast appears even if the running notice was dismissed. A tab that
never observed that operation does not replay historical success messages.

Failure replaces the running state with a persistent cross-navigation error:

> Prices couldn't be converted. Existing totals are still available. We'll
> retry automatically.

A failure remains dismissible per tab. The retry is a new phase and may show
the running notice again. A later user-triggered conversion has a new version
and is not suppressed by dismissal of an earlier operation.

### Backup and restore

Backups preserve original Purchase amounts/currencies and the last complete
converted values with their published currency. This tiny cache makes a
restored library immediately useful and can always be recalculated later.

User/account preferences, including personal currency choices and presentation
settings, are not part of the portable library backup. A restore uses the
preferences of the account to which the library is restored.

Backups omit `PurchaseConversionState`, queued jobs, retry state, and toast
dismissal. After restore, preserved values are used as-is when their currency
matches the restoring User's effective Display currency. A mismatch keeps the
complete preserved values visible in their actual currency and requests a new
conversion.

## Production cutover

The only supported legacy database is the inspected production shape: exactly
one User and the current global private data. The application is offline for
the operation. The cutover is rehearsed against a fresh copy first, then run
against production with a fresh restorable backup.

This is an ordinary Django data migration with explicit preconditions, not a
temporary library/claim workflow. Before mutation it verifies:

- exactly one User and the expected required preference/configuration state;
- zero Sessions with a null Game;
- no saved filter relying on nullable Session Game;
- the exact built-in Platform classification fixture is unambiguous;
- uniqueness changes can succeed;
- every relationship can resolve to the single production library; and
- recorded effective currency/default-Device values match deployment input.

Any mismatch aborts before guessing. The operator inspects and fixes the data,
then reruns. The website is not kept online in a half-migrated compatibility
mode.

Preflight also requires the current converted Purchase cache to form one
complete set in the recorded old reporting currency. If it is stale, the
operator runs the existing explicit conversion and rechecks before migration;
the data migration does not perform network calls. The bridge can then seed its
published state from a known-complete set.

The migration creates the UserLibrary and UserLibraryPreferences, assigns
direct ownership, classifies Platforms, migrates settings, makes Session Game
required, installs constraints, and removes obsolete setting state. It prints
a human-readable before/after reconciliation including the new library UUID.

Reconciliation covers:

- all direct owner assignments;
- shared/private Platform classification and Game uniqueness;
- Purchase-Game, Purchase-Platform, and related-Game links;
- required Session Game and optional same-library Device;
- PlayEvent and GameStatusChange derivation through Game;
- presets and every required preference record;
- original/converted values and effective currencies;
- row and link counts; and
- aggregate, playtime, statistics, page, API, and filter parity.

The migration is expected to move forward by correcting discovered issues. A
restored pre-migration backup is the recovery path for a genuinely
unrecoverable failure; no ongoing rollback framework is built.

## Deletion and operator tooling

Deleting a User cascades through UserLibrary, UserLibraryPreferences, and all
private library data. A guarded operator command is included now. It is
non-interactive, performs a dry run by default, and requires matching explicit
arguments to destroy data:

```text
--user USERNAME --confirm USERNAME
```

The dry run prints the complete deletion scope and a conspicuous warning.
Self-service deletion UI is deferred to #801 and depends on #796 backup/restore.

The read-only ownership audit requires exactly one explicit scope and exits
nonzero on violations. It never repairs data.

The sample-data loader requires `--user`, creates the User before private
records, reuses shared Platforms by exact identity, and never invents an owner.

## Verification

Isolation tests are added with each affected code path inside #630, not delayed
to a final test-only issue. A two-User/two-library fixture proves that pages,
APIs, forms, selectors, searches, filters, presets, statistics, background
conversion, and detail routes neither disclose nor mutate the other library.
Shared Platforms remain visible to both.

Focused tests cover provisioning idempotency, startup refusal, audit exit
status, cascade deletion, command guards, required Session Game, scoped
uniqueness, explicit Purchase currency, conversion coalescing, stale-job
rejection, atomic publication, retry/daily recovery, toast state transitions,
backup-cache decisions, and migration precondition failures.

The standard full `make check` gate runs for #629 and #630. On Windows it uses
the repository's normal parallel worker default through the managed hidden
process required by `AGENTS.md`.

## Explicit handoffs

- #728 replaces and removes `PurchaseConversionState` and the transitional
  per-Purchase conversion cache while preserving per-user effective Display
  currency, coalescing, atomic publication, backup/restore behavior, and the
  approved toast contract.
- #750 adds Player's Journal purchase visibility to
  UserLibraryPreferences.
- #796 implements backup/restore and preserves library UUID, `created_at`,
  library preferences (including preference `updated_at`), private records,
  presets, and the last complete converted cache.
- #801 implements self-service deletion after backup/restore exists.
- #481 later migrates the Library default-Device field from the current
  dropdown implementation to SearchSelect.
- New follow-ups cover Purchase price certainty and unknown configuration/site
  setting warnings.
