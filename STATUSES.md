# Game & Purchase Status Definitions

## Game Statuses

Games have a `status` field with the following values:

| Status | Code | Description |
|--------|------|-------------|
| **Unplayed** | `u` | Game was purchased but never played |
| **Played** | `p` | Game was played but not yet finished |
| **Finished** | `f` | Game has been completed |
| **Retired** | `r` | Game was intentionally retired (e.g., no longer accessible, collector's item) |
| **Abandoned** | `a` | Game was played but the user gave up on it |

**Setting game status:**
- Users explicitly set game status via the UI (finish/drop purchase buttons, status change form)
- Status changes are tracked in `GameStatusChange` model
- Refunding a purchase always marks its games as abandoned

---

## Purchase-Level Status Concepts

These concepts determine whether a purchase appears in the "unfinished" or "dropped" lists in stats views.

### Finished

A purchase is considered **finished** when:

```
Game.status == "f" OR Purchase.games.* has a PlayEvent with an ended date
```

Either signal indicates the game is complete:
- **Explicit**: User marked the game as finished (`Game.status = "f"`)
- **Implicit**: A PlayEvent exists with `ended` date set (data-driven)

This uses **OR** logic during a transition period. Later, these signals should be kept in sync so only one source of truth is needed.

### Dropped

A purchase is considered **dropped** when:

```
Game.status == "a" OR Purchase.date_refunded IS NOT NULL
```

Either signal indicates the user no longer has an active interest in the game:
- **Explicit**: User marked the game as abandoned (`Game.status = "a"`)
- **Implicit**: User refunded the purchase (which automatically sets games to abandoned)

Note: Refunding a purchase always marks its games as abandoned. There is no option to refund without abandoning.

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
| **Dropped** | Yes | Finished OR Abandoned/Retired |
| **Refunded** | Yes | `date_refunded IS NOT NULL` |
| **Infinite** | Yes | `infinite = True` |

---

## Query Patterns

### Checking if a game is finished

```python
game.finished()  # Returns True if status="f" or has PlayEvent with ended date
```

### Checking if a game is abandoned

```python
game.abandoned()  # Returns True if status="a"
```

### Getting finished purchases

```python
Purchase.objects.finished()  # All purchases where games are finished
```

### Getting dropped purchases

```python
Purchase.objects.dropped()  # All purchases that are abandoned or refunded
```

---

## Transition State

The system uses **OR logic** for both finished and dropped to catch any mismatch between explicit user actions and data signals:

- **Finished**: `status="f" OR PlayEvent.ended`
- **Dropped**: `status="a" OR date_refunded`

This bridges the gap between the old model (where `date_finished` and `date_dropped` were on the Purchase model) and the new model (where `Game.status` and `PlayEvent` are the sources of truth).

**Future:** These signals should be kept in sync. For example:
- Setting `Game.status = "f"` should create a PlayEvent with `ended` date
- When the sync is reliable, the OR can be simplified to a single check

Note: Refunding a purchase always automatically sets its games' status to Abandoned. This is not optional — there is no way to refund without abandoning.

---

## Edge Cases

### Unplayed games
- Unplayed games (`status="u"`) are considered **unfinished**, not dropped
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
- Retired games (`status="r"`) are considered **dropped**
- Retirement is for games the user intentionally removed from their collection (collector's items, no longer accessible, etc.)
