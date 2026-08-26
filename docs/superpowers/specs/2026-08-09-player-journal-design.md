# Player’s Journal design

Date: 2026-08-09
Issue: https://github.com/KucharczykL/timetracker/issues/37

> **Architecture foundation:** This document is reconciled with the
> [Timetracker overhaul design](2026-08-09-timetracker-overhaul-design.md).
> Its event-sourced player history, PlayerGame statuses, Playthroughs,
> single-item Purchases, temporal precision, and Journal projections are the
> domain source of truth. The visual references below remain layout references;
> superseded words in the original user wireframe are not requirements.

## Problem

`Session.note` is editable and filterable but is not rendered on the sessions
list or game detail. It is therefore only readable by opening the edit form.
For games played over many sessions, a table cell or tooltip cannot convey the
player’s progress through the game.

The Player’s Journal is a compact daily digest of recorded play activity. It
surfaces notes as prose while retaining the surrounding context: sessions,
playthrough lifecycle facts, status changes, exact-day historical playtime, and
purchases.

## Approved visual references

- User wireframe: [user-wireframe.png](assets/2026-08-09-player-journal/user-wireframe.png)
- Approved desktop/responsive direction: [desktop-and-responsive-mockup.html](assets/2026-08-09-player-journal/desktop-and-responsive-mockup.html)
- Mobile exploration; **Stacked header (A)** is selected:
  [mobile-layout-options.html](assets/2026-08-09-player-journal/mobile-layout-options.html)

The wireframe's colours are not a design reference. The approved mockup uses
the app's existing neutral palette, existing `GameStatus` dot colours, and
normal game-link treatment.

## Information architecture

### Player’s Journal

The main journal is ordered by day, newest first. A day has two kinds of
entries:

1. **Game-day entries**, grouped secondarily by game. A group is present when
   that game has a Session or day-precision playthrough, status, or Historical
   Playtime fact. It is present even when no Session was recorded, such as a day
   on which five games are marked Abandoned.
2. **Purchase-day entries**, one per single-item `Purchase`.

The full Game Journal contains the same daily history filtered to one game plus
an **Approximate history** section for month/year/decade/range/unknown facts. A
`See all N notes` link targets the canonical Game Journal URL with
`?day=YYYY-MM-DD#day-YYYY-MM-DD`. The server resolves which seven-day page
contains that Game/day key before rendering it. A stale day key that no longer
exists opens the newest page with a visible “That journal day has changed”
notice rather than silently landing on an unrelated anchor.
Approximate history never appears in the global Player's Journal.

### Game-day entry

The game header contains, when present:

- `GameLink`;
- a summary of that day’s sessions: count, total duration, and number of
  distinct non-null devices; running Sessions are included in the count with an
  in-progress qualifier but excluded from total finalized duration;
- status and playthrough facts, using the rules below.

The narrative area contains Session-note excerpts and qualifying playthrough or
Historical Playtime notes. Its preview uses deterministic server-side limits:
at most four note items and at most 240 Unicode code points after whitespace
normalization, shared across those items. Notes are considered in the entry's
stable timeline order. A note remains complete when it fits the remaining
character budget; the final
visible note is clipped with an ellipsis when it does not. Thus four notes of 30
characters each display completely on every viewport. The `See all N notes`
link appears when either limit omits or clips content. `N` counts every non-empty
narrative note for that group. Layout may wrap the retained content but performs
no additional clipping or client-side measurement.

Empty narrative content leaves no blank placeholder or link.

### Status and playthrough facts

`PlayerGame` status labels are authoritative: Unplayed, Played, Completed,
Retired, Shelved, and Abandoned. The Journal delegates their dot colours and
labels to the shared `GameStatus` component.

- Correlated `PlaythroughStarted` and status change to Played render once as
  `GameStatus(Played)`.
- Correlated `PlaythroughCompleted` and status change to Completed render once
  as `GameStatus(Completed)`.
- The matched lifecycle event receives no second Started/Completed heading. Its
  duration-to-completion and note remain visible as narrative support.
- An uncorrelated PlaythroughStarted or PlaythroughCompleted remains a neutral
  lifecycle fact and is not coloured as a PlayerGame status.
- A day-precision completion with a duration and note renders the approved
  narrative form: `Finished in 12 days with a note: “…”`. “Finished” is prose;
  the authoritative status label remains Completed. The duration is omitted
  when it is unknown. A same-day playthrough displays `1 day`.
- A standalone PlayerGame status change renders with the shared `GameStatus`
  dot and label. It never receives an invented progress colour.

Day-precision lifecycle facts do not imply an exact intra-day order. Correlation
identity—not same game/day coincidence—is the only basis for collapsing facts.

### Purchases

Purchases are enabled by default in the Player’s Journal. Add a per-library
preference, **Show purchases in Player’s Journal**, default `True`, on the
conventional one-to-one `PlayerLibraryPreferences` record. It does not add a
LIBRARY layer to the USER/SITE/INFRA settings registry.

When enabled, each purchase whose precision-aware effective purchase date has
day precision appears as a separate `JournalPurchaseDayEntry`, including its
item and associated Game/Release when
present. The Game Journal may show purchases associated with its Game. When the
setting is disabled, only Player’s Journal purchase entries are hidden; no
purchase data or game-level purchase history changes.

## Data and date rules

The Journal is a read projection, never another writable source of truth.
Synchronous projectors maintain `JournalDayProjection` and
`JournalFactProjection` alongside the current Session, status, lifecycle,
Historical Playtime, and purchase projections. Each visible day-precision source
fact produces a materialized Journal fact containing its library, local date,
Game/purchase group, kind, source identity, stable ordering keys, summary, and
narrative data. A day projection exists only while at least one structurally
visible fact references it and stores separate purchase-fact and non-purchase-
fact counts. Corrections, deletion, restoration, timezone changes, and
correlated commands update these models. Event-driven changes occur in the same
transaction as their events. A display-timezone preference change rebuilds
shadow Journal projections and swaps them active only after validation; exact
timestamps regroup while day-precision calendar facts retain their written day.
The setting UI reports **Updating journal dates…** while the old projection
remains readable. Ordinary writes continue during the rebuild and pause only for
the final atomic swap. Failure keeps the old Journal timezone active, displays a
retryable error, and never exposes a partially regrouped timeline.

A Player Journal page selects seven `JournalDayProjection` keys, newest first,
using both counts when purchases are shown and `non_purchase_fact_count > 0`
when they are hidden, then loads the eligible facts for those days in bounded
queries. Purchase-only dates therefore consume no page slot while hidden, and
changing the preference rewrites no Journal facts. It never discovers a page by
UNIONing heterogeneous source projections during the request. Game Journal does
not use the library-wide day rows: it obtains distinct populated days from the
indexed `JournalFactProjection` filtered by Game, then loads that Game's facts.
The view builds typed journal data before rendering; components never query
models.

| Read-model fact | Player Journal day | Content |
| --- | --- | --- |
| Completed timed/corrected Session | configured display-timezone date of exact `timestamp_start` | finalized session summary and non-empty note |
| Running timed Session | configured display-timezone date of exact `timestamp_start` | count/device and note; “In progress,” with no finalized-duration contribution |
| Duration-only Session | written effective calendar day, without timezone conversion | entered duration, optional day part/device, and non-empty note |
| PlayerGame status fact | effective date, only at day precision | status fact |
| Playthrough lifecycle fact | effective date, only at day precision | start/completion fact, duration-to-completion, optional note |
| Historical Playtime projection | effective date, only at day precision | duration, provenance, optional note; never counted as a Session |
| Purchase fact | effective purchase date, only at day precision | one single-item purchase entry |

Running timed Sessions appear from their start command and remain grouped on
their start day if they cross midnight. Their changing wall-clock elapsed time
is shown only by the existing running-session controls; the Journal summary does
not continuously rewrite or count it as finalized duration. Finishing the
Session replaces the in-progress Journal fact in the same transaction.

No fact falls back from unknown `effective_time` to `recorded_at`. Month-,
year-, decade-, range-, and unknown-date facts go to the corresponding Game
Journal's **Approximate history** section. Known temporal bounds sort newest
first by upper bound descending, then lower bound descending, then more specific
precision using the fixed day > month > year > decade > range rank, then
`recorded_at` and event UUIDv7. Thus 2000s sorts before 2004–2006, which sorts
before 2005 because their upper bounds are 2009, 2006, and 2005. Unknown facts
follow in descending `recorded_at` and UUIDv7 order. The section has independent
fact-count pagination with 25 facts by default and does not consume the daily
timeline's seven-populated-day page budget.

Legacy PlayEvents become Playthrough lifecycle facts during migration. Their
notes and known dates retain the same meaning; an undated note remains an
unknown-date fact rather than being assigned its migration or creation day.
Non-null legacy `GameStatusChange.timestamp` values are effective transition
times and enter the daily Journal using the library owner's configured display
timezone; null values remain unknown. A legacy lifecycle/status pair shares a
correlation ID only when the same Game, compatible meaning, and effective day
form exactly one unambiguous match. Ambiguous or unmatched facts stay separate
and are reported by migration rather than guessed together.

Within one day, exact timestamps sort first by local instant. Non-clock facts
follow in Morning, Afternoon, Evening, Night, then Unknown order. `recorded_at`
and event UUIDv7 break all remaining ties. Game grouping preserves that stable
order inside each group, and the same keys are used for pagination.

## Components

```text
JournalTimeline
└── JournalDay
    ├── JournalDate
    ├── JournalGameDayEntry
    │   ├── timeline marker (private layout detail)
    │   ├── JournalGameHeader
    │   │   ├── GameLink
    │   │   ├── SessionSummary
    │   │   └── GameStatus (existing)
    │   └── JournalNarrativePreview
    │       ├── Session-note items
    │       ├── Playthrough summary item
    │       ├── Historical-playtime item
    │       └── See-all-notes link
    └── JournalPurchaseDayEntry
        └── timeline marker (private layout detail)

GameJournal
├── JournalTimeline
└── ApproximateHistory
    └── ApproximateHistoryFact
```

`JournalTimeline` is deliberately domain-specific, rather than a generic
`Timeline`. A timeline marker is owned by its entry; it is not a reusable
public component. The dot means “this game/purchase has journal activity on
this day,” not “a session happened.”

Use typed `JournalDayData`, `JournalGameDayEntryData`,
`JournalPurchaseDayEntryData`, and `ApproximateHistoryFactData` view-data
structures as the seam between query and presentation.

## Responsive layout and colour

Desktop uses a two-column day layout: `JournalDate` on the left, with the
timeline and game/purchase entries on the right.

Mobile stacks the date above its entries. The selected stacked header shows
the game name first, then session metadata, then a status fact; it avoids a
dense wrapped metadata line.

In the Game Journal, `ApproximateHistory` follows the daily timeline under its
own heading. It does not continue the day timeline's vertical rule or reuse its
day markers, because those would imply false day precision. Desktop places the
honest temporal label (for example `2000s, approximate`) beside the fact; mobile
stacks that label above the fact. Both use the same neutral typography and
spacing as Journal narrative items.

No Journal-specific colour palette is introduced:

- game links, prose, summaries, dividers, and the see-all link use current
  neutral/link treatments;
- only the shared `GameStatus` component owns status colours; the Journal does
  not duplicate or override its mapping;
- playthrough lifecycle facts with no status change remain neutral.

## Error handling and empty states

- A day with no visible entries is not rendered.
- A game-day entry with no notes has no empty prose area or see-all link.
- Missing device values are excluded from the distinct-device count and never
  require a sentinel record.
- An imprecise or undated history record is retained in Game Journal's
  Approximate history rather than silently discarded or given a fabricated
  date.
- The purchase preference hides only purchase timeline entries and does not
  affect filters or stats and does not rewrite Journal facts/day counts.

## Verification

Automated coverage should pin:

1. day and game grouping for completed timed, corrected, duration-only, and
   running Sessions, including finalized-duration and distinct-device rules;
2. status-only days, including five separate abandoned games;
3. correlation-only duplicate suppression for PlaythroughStarted/Played and
   PlaythroughCompleted/Completed facts, including unambiguous legacy pairing
   and preservation of ambiguous pairs;
4. day-precision Playthrough placement, same-day completion duration, and
   playthrough note rendering/counting;
5. empty, short, four-by-30-character, note-count-overflow, and shared-character-
   overflow previews, including deterministic clipping and the exact visibility
   and target of `See all N notes` without client measurement;
6. single-item purchase rendering and the default-enabled per-library preference
   toggle, including seven full non-purchase days when purchase-only days are
   hidden;
7. desktop and mobile rendered structure, including stacked mobile game
   headers;
8. configured-display-timezone grouping, visible rebuild state, atomic swap,
   and failure retaining the previous active Journal timezone;
9. exclusion of every non-day temporal precision from Player's Journal;
10. month/year/decade/range/unknown Game Journal placement, ordering, and
    independent pagination;
11. replay parity after corrections, deletion, and restoration, including exact
    purchase/non-purchase counts and removal of empty materialized days;
12. stable within-day and approximate-bound ordering and pagination with tied
    facts;
13. seven-populated-day query bounds and the overhaul's 100,000-fact/200 ms p95
    Journal benchmark;
14. day-addressable Game Journal page resolution, exact anchor target, and stale-
    day fallback.

Before delivery, run the repository gate: `make check`.

## Deferred scope

Session checkpoints are deliberately deferred. No new checkpoint model, form,
or timestamp-within-session feature is part of this work.
