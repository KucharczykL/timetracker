# Player’s Journal design

Date: 2026-08-09
Issue: https://github.com/KucharczykL/timetracker/issues/37

> **Architecture note:** The approved visual references and interaction shape in
> this document remain valid. Domain details involving statuses, PlayEvents,
> bundles, associations, and live source queries are superseded by
> [Player history architecture design](2026-08-09-player-history-architecture-design.md).
> Reconcile this document with that foundation before Journal implementation.

## Problem

`Session.note` is editable and filterable but is not rendered on the sessions
list or game detail. It is therefore only readable by opening the edit form.
For games played over many sessions, a table cell or tooltip cannot convey the
player’s progress through the game.

The Player’s Journal is a compact daily digest of recorded play activity. It
surfaces notes as prose while retaining the surrounding context: sessions,
play events, status changes, and purchases.

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
   that game has a session, play event, or status change on the day. It is
   present even when no session was recorded, such as a day on which five games
   are marked Abandoned.
2. **Purchase-day entries**, one per `Purchase`, so a multi-game bundle is not
   falsely duplicated across every game it contains.

The full Game Journal is the same journal history filtered to one game. A
`See all N notes` link opens that game journal positioned at the selected day.

### Game-day entry

The game header contains, when present:

- `GameLink`;
- a summary of that day’s sessions: count, total duration, and number of
  distinct non-null devices;
- status and play-event facts, using the rules below.

The narrative area contains session-note excerpts and any qualifying play-event
note. It has a **shared four rendered-line budget** for the entire game/day
group. Complete notes remain complete when they fit; only true overflow is
clipped. The `See all N notes` link appears only when the budget clips content.
`N` counts every non-empty narrative note for that group: `Session.note` plus
the attached `PlayEvent.note`, if any.

Empty narrative content leaves no blank placeholder or link.

### Status and play-event facts

`Game.Status` labels are authoritative: Unplayed, Played, Finished, Retired,
and Abandoned. In particular, the implementation must display **Finished**,
not “Completed.”

- A matching same-game, same-calendar-day `PlayEvent.started` plus
  `GameStatusChange` to Played is rendered once as `GameStatus(Played)`.
- A matching `PlayEvent.ended` plus status change to Finished is rendered once
  as `GameStatus(Finished)`.
- The matching PlayEvent is not given a second “Started” or “Finished” state
  label. Its `days_to_finish` and its note remain visible as narrative support.
- A PlayEvent without a matching status change remains a neutral Started or
  Finished fact; it must not be coloured as a status.
- A finish PlayEvent with `days_to_finish` renders a narrative bullet in this
  form: `Finished in 12 days with a note: “…”`. The number is omitted when the
  model’s generated value is zero. A same-day playthrough is `1 day`, per the
  existing generated-field behaviour.
- A standalone `GameStatusChange` renders with the existing `GameStatus` dot
  and label. It never receives an invented progress colour.

`PlayEvent.started` and `.ended` are `DateField`s, not timestamped events. The
daily layout intentionally does not imply an exact intra-day order for them.

### Purchases

Purchases are enabled by default in the Player’s Journal. Add a per-user
setting, **Show purchases in Player’s Journal**, default `True`.

When enabled, each purchase appears on `Purchase.date_purchased` as a separate
`JournalPurchaseDayEntry`, including its own purchase details and all linked
games. The Game Journal may show purchases that include its game. When the
setting is disabled, only Player’s Journal purchase entries are hidden; no
purchase data or game-level purchase history changes.

## Data and date rules

The view builds typed journal data before rendering; components never query
models. The query layer gathers and merges the existing models:

| Source | Journal day | Content |
| --- | --- | --- |
| `Session` | request-local date of `timestamp_start` | session summary and non-empty note |
| `GameStatusChange` | request-local date of `timestamp` | status fact |
| `PlayEvent` | `started` and/or `ended` date | start/finish fact, days-to-finish, optional note |
| `Purchase` | `date_purchased` | one purchase entry, never cloned per game |

For a `PlayEvent` with both dates, the start fact belongs to `started` and the
finish fact (including the note and days-to-finish) belongs to `ended`. A
note-only PlayEvent with neither date falls back to its `created_at` local day,
so existing records such as a “wishlist” note are not silently lost.

`GameStatusChange.timestamp` is nullable. Dated changes participate in the
daily Player’s Journal. Undated manual history remains visible in an **Undated
activity** section at the bottom of the corresponding Game Journal; it is not
placed arbitrarily in the global daily timeline.

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
    │       ├── Play-event summary item
    │       └── See-all-notes link
    └── JournalPurchaseDayEntry
        └── timeline marker (private layout detail)
```

`JournalTimeline` is deliberately domain-specific, rather than a generic
`Timeline`. A timeline marker is owned by its entry; it is not a reusable
public component. The dot means “this game/purchase has journal activity on
this day,” not “a session happened.”

Use typed `JournalDayData`, `JournalGameDayEntryData`, and
`JournalPurchaseDayEntryData` view-data structures as the seam between query
and presentation.

## Responsive layout and colour

Desktop uses a two-column day layout: `JournalDate` on the left, with the
timeline and game/purchase entries on the right.

Mobile stacks the date above its entries. The selected stacked header shows
the game name first, then session metadata, then a status fact; it avoids a
dense wrapped metadata line.

No Journal-specific colour palette is introduced:

- game links, prose, summaries, dividers, and the see-all link use current
  neutral/link treatments;
- only `GameStatus` uses the established colours: gray (Unplayed), orange
  (Played), green (Finished), red (Abandoned), purple (Retired);
- PlayEvent facts with no status change remain neutral.

## Error handling and empty states

- A day with no visible entries is not rendered.
- A game-day entry with no notes has no empty prose area or see-all link.
- Missing device values are excluded from the distinct-device count and never
  require a sentinel record.
- A malformed/undated history record is retained in Game Journal’s Undated
  activity rather than silently discarded or given a fabricated date.
- The purchase preference hides only purchase timeline entries and does not
  affect filters, stats, or any database data.

## Verification

Automated coverage should pin:

1. day and game grouping, session count, duration, and distinct-device
   aggregation;
2. status-only days, including five separate abandoned games;
3. duplicate suppression for matching Started/Played and Finished/Finished
   source records;
4. date-only PlayEvent placement, generated same-day `days_to_finish`, and
   PlayEvent note rendering/counting;
5. empty, short, and overflowing narrative previews, including the exact
   visibility and target of `See all N notes`;
6. multi-game purchase rendering as one Player’s Journal entry and the
   default-enabled preference toggle;
7. desktop and mobile rendered structure, including stacked mobile game
   headers;
8. request timezone handling and undated status-history fallback.

Before delivery, run the repository gate: `make check`.

## Deferred scope

Session checkpoints are deliberately deferred. No new checkpoint model, form,
or timestamp-within-session feature is part of this work.
