# Game & Purchase Status Definitions

## Game Statuses

A status is one of the six words of `PlayerGameStatus`:

| Status | Value | Description |
|--------|-------|-------------|
| **Unplayed** | `unplayed` | Tracked, never played |
| **Played** | `played` | Being played, no verdict yet |
| **Completed** | `completed` | You beat what you were playing it for — your objective, not the game's |
| **Retired** | `retired` | Done with a game that has no ending |
| **Shelved** | `shelved` | Stopped, and might be picked up again |
| **Abandoned** | `abandoned` | Stopped, and staying that way |

Two axes decide which word applies: whether the player is done, and, for a game
they are not done with, whether stopping was final. **Completed** and **Retired**
are both done — the second is for a game that offers nothing to complete.
**Shelved** and **Abandoned** are both unfinished — the second is final.

The status lives on `PlayerGame`, one row per library per game, so two libraries
can hold different statuses for one catalog game. It is the only place a status
is stated or read: since #678 D2 nothing maintains the five-letter `Game.status`
column, which #770 drops. `shelved` is settable everywhere the other five are,
because no letter has to hold it any more.

**Setting game status:**
- Users explicitly set game status via the UI (the status dropdown on the game
  page and the games list, the game form, finish/drop purchase buttons)
- Code states a status as a command (`record_facts()` in
  `games/writes/playergame.py`), which appends an event and lets the projector
  write the row. Do not assign `Game.status` directly.
- Refunding a purchase always marks its games as abandoned
- The events are the record. `games/reads/playergame_history.py` replays a
  library's status events into the History section of the game page, so the
  history is scoped to one library. `GameStatusChange` keeps its old rows,
  which the baseline backfill reads, but nothing writes or reads it otherwise;
  #771 takes the table

---

## Purchase-Level Status Concepts

These concepts determine whether a purchase appears in the "unfinished" or "dropped" lists in stats views.

### Finished

A purchase is considered **finished** when:

```
PlayerGame.status in DONE_STATUSES OR Purchase.games.* has a PlayEvent with an ended date
```

`DONE_STATUSES` is `("completed", "retired")`. It lives in `games/models.py`
beside `PlayerGameStatus`, and both `games/views/stats_data.py` and
`games/views/stats_links.py` read that one name, so a stats link cannot select a
different set than the number it links from.

Either signal indicates the player is done with the game:
- **Explicit**: The row says `completed` or `retired`
- **Implicit**: A PlayEvent exists with `ended` date set (data-driven)

This uses **OR** logic during a transition period. Later, these signals should be kept in sync so only one source of truth is needed.

### Dropped

A purchase is considered **dropped** when it is not finished, and:

```
PlayerGame.status == "abandoned" OR Purchase.date_refunded IS NOT NULL
```

Either signal indicates the user no longer has an active interest in the game:
- **Explicit**: The row says `abandoned`
- **Implicit**: User refunded the purchase (which automatically sets games to abandoned)

Note: Refunding a purchase always marks its games as abandoned. There is no
option to refund without abandoning. So a purchase that is both refunded and
retired should not arise; if one does, it counts as finished, not dropped.

---

## Unfinished vs. Dropped

The stats views categorize purchases into **unfinished** and **dropped** lists.

### Unfinished

A purchase is **unfinished** when:
1. It was purchased in the relevant time period (this year for yearly stats, all time for all-time stats)
2. It was NOT refunded (only counts toward unfinished/backlog)
3. It is NOT finished (per the finished definition above)
4. It is NOT dropped (per the dropped definition above)
5. It is NOT infinite (subscription, etc.)
6. It IS a game or DLC (not season passes or battle passes)

**Unfinished = Active backlog** — games the user may still play.

### Dropped

A purchase is **dropped** when:
1. It was purchased in the relevant time period
2. It is NOT finished (per the finished definition above)
3. It matches at least one dropped signal (per the dropped definition above)
4. It is NOT infinite
5. It IS a game or DLC

**Dropped = Terminal state** — games the user has given up on or refunded.

### Summary Table

| Category | Includes Refunded? | Key Condition |
|----------|-------------------|---------------|
| **Unfinished** | No | NOT finished, NOT dropped |
| **Dropped** | Yes | NOT finished, AND (abandoned OR refunded) |
| **Refunded** | Yes | `date_refunded IS NOT NULL` |
| **Infinite** | Yes | `infinite = True` |

---

## Query Patterns

A status is on the library's own row, so every query naming one takes the
library. There are two shapes.

### Getting finished purchases

```python
Purchase.objects.for_library(library).finished(library)
```

### Getting the games at a status

```python
Game.objects.tracked_by(library, tracked__status=PlayerGameStatus.ABANDONED)
```

`tracked_by()` passes extra conditions into the one `filter()` call that opens
the join, so a second condition does not read the row twice.

---

## Transition State

The system uses **OR logic** for both finished and dropped to catch any mismatch between explicit user actions and data signals:

- **Finished**: `status in DONE_STATUSES OR PlayEvent.ended`
- **Dropped**: `status == "abandoned" OR date_refunded`

This bridges the gap between the old model (where `date_finished` and `date_dropped` were on the Purchase model) and the new model (where the `PlayerGame` status and `PlayEvent` are the sources of truth).

**Future:** These signals should be kept in sync. For example:
- Stating `completed` should create a PlayEvent with `ended` date
- When the sync is reliable, the OR can be simplified to a single check

Note: Refunding a purchase always automatically sets its games' status to Abandoned. This is not optional — there is no way to refund without abandoning.

---

## Edge Cases

### Unplayed games
- Unplayed games (`status="unplayed"`) are considered **unfinished**, not dropped
- They appear in the unfinished/backlog list since they are still games the user may play
- Unplayed games that are refunded DO count as **dropped** (refund signal overrides)

### Multiple games per purchase
- A purchase can have multiple games via `Purchase.games` (many-to-many)
- A purchase is finished if ANY of its games is finished
- A purchase is dropped if ANY of its games is abandoned OR the purchase itself is refunded

### PlayEvents without ended date
- A PlayEvent with `started` but no `ended` does NOT count as finished
- This represents a game that was started but not completed

### Retired games

> **Retired counts as finished.** Retired means done with a game that has no
> ending, so it belongs with the completed ones and `DONE_STATUSES` holds both.
> A retired game leaves the backlog, adds to the all-time backlog decrease, and
> is not dropped. It joins a year's finished list only through a play event,
> because that list is dated by the play event and a retired game with none has
> no date to show. Until #678 C it counted for nothing: not finished, not in the
> backlog, not dropped.

### Shelved games
- A shelved game is unfinished and not final, so it stays in the backlog
- `unfinished` excludes only the two done statuses and `abandoned`, which is
  already what the words ask for
