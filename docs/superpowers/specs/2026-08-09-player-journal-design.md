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
`See all N notes` link opens that game journal positioned at the selected day.
Approximate history never appears in the global Player's Journal.

### Game-day entry

The game header contains, when present:

- `GameLink`;
- a summary of that day’s sessions: count, total duration, and number of
  distinct non-null devices;
- status and playthrough facts, using the rules below.

The narrative area contains Session-note excerpts and qualifying playthrough or
Historical Playtime notes. It has a **shared four rendered-line budget** for the
entire game/day group. Complete notes remain complete when they fit; only true
overflow is clipped. The `See all N notes` link appears only when the budget
clips content. `N` counts every non-empty narrative note for that group.

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
setting, **Show purchases in Player’s Journal**, default `True`.

When enabled, each purchase appears on `Purchase.date_purchased` as a separate
`JournalPurchaseDayEntry`, including its item and associated Game/Release when
present. The Game Journal may show purchases associated with its Game. When the
setting is disabled, only Player’s Journal purchase entries are hidden; no
purchase data or game-level purchase history changes.

## Data and date rules

The Journal is a read projection, never another writable source of truth.
Synchronous event projectors maintain the status/lifecycle/purchase facts needed
for Journal queries, while current Session and Historical Playtime projections
provide their summaries and notes. Corrections, deletion, restoration, and
correlated commands update these read models in the same transaction as their
events. The view builds typed journal data before rendering; components never
query models.

| Read-model fact | Player Journal day | Content |
| --- | --- | --- |
| Session projection | request-local date of exact `timestamp_start` | session summary and non-empty note |
| PlayerGame status fact | effective date, only at day precision | status fact |
| Playthrough lifecycle fact | effective date, only at day precision | start/completion fact, duration-to-completion, optional note |
| Historical Playtime projection | effective date, only at day precision | duration, provenance, optional note; never counted as a Session |
| Purchase fact | effective purchase date, only at day precision | one single-item purchase entry |

No fact falls back from unknown `effective_time` to `recorded_at`. Month-,
year-, decade-, range-, and unknown-date facts go to the corresponding Game
Journal's **Approximate history** section. Known temporal bounds sort newest
first; unknown facts follow in stable `recorded_at` order. The section has
independent fact-count pagination with 25 facts by default and does not consume
the daily timeline's seven-populated-day page budget.

Legacy PlayEvents become Playthrough lifecycle facts during migration. Their
notes and known dates retain the same meaning; an undated note remains an
unknown-date fact rather than being assigned its migration or creation day.

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
  affect filters, stats, or any database data.

## Verification

Automated coverage should pin:

1. day and game grouping, session count, duration, and distinct-device
   aggregation;
2. status-only days, including five separate abandoned games;
3. correlation-only duplicate suppression for PlaythroughStarted/Played and
   PlaythroughCompleted/Completed facts;
4. day-precision Playthrough placement, same-day completion duration, and
   playthrough note rendering/counting;
5. empty, short, and overflowing narrative previews, including the exact
   visibility and target of `See all N notes`;
6. single-item purchase rendering and the default-enabled per-library
   preference toggle;
7. desktop and mobile rendered structure, including stacked mobile game
   headers;
8. request timezone handling;
9. exclusion of every non-day temporal precision from Player's Journal;
10. month/year/decade/range/unknown Game Journal placement, ordering, and
    independent pagination;
11. replay parity after corrections, deletion, and restoration.

Before delivery, run the repository gate: `make check`.

## Deferred scope

Session checkpoints are deliberately deferred. No new checkpoint model, form,
or timestamp-within-session feature is part of this work.
