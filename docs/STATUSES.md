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

**Abandoned is not Dormant.** Since #1033 a clock also counts a condition for
every unfinished run — Playing, Dormant or Never played — from the last day the
game was played against the viewer's `DORMANT_AFTER_DAYS`. A status is stated; a
condition is counted, and the clock reads no status: an abandoned game whose run
is unfinished is counted Dormant like any other. Neither word moves the other.
`docs/vocabulary.md` records all three pairs.

The status lives on `PlayerGame`, one row per library per game, so two libraries
can hold different statuses for one catalog game. It is the only place a status
is stated or read; `Game` holds no status column. `shelved` is settable
everywhere the other five are, because no letter has to hold it any more.

**Setting game status:**
- Users explicitly set game status via the UI (the status dropdown on the game
  page and the games list, the game form, finish/drop purchase buttons)
- Code states a status as a command (`record_facts()` in
  `games/writes/playergame.py`), which appends an event and lets the projector
  write the row.
- Refunding a purchase always marks its games as abandoned
- The events are the record. `games/reads/playergame_history.py` replays a
  library's status events into the History section of the game page, so the
  history is scoped to one library. `GameStatusChange` keeps its old rows,
  which the baseline backfill reads, but nothing writes or reads it otherwise;
  #771 takes the table

---

## Copy-Level Status Concepts

The backlog figures on the stats page count **copies**: live `LibraryEntry`
rows on a `full` Edition. Each figure is one `LibraryEntryFilter` in
`games/reads/copy_figures.py`, and the link beside it carries the same filter.
A copy reaches its game's status through `player_game`. See
[Every purchase read on the projections](superpowers/specs/2026-10-01-issue-735-purchase-reads-design.md).

### Finished

A copy's game is **finished** when:

```
PlayerGame.status in DONE_STATUSES OR a Playthrough states a completion in scope
```

`DONE_STATUSES` is `("completed", "retired")`. It lives in `games/models.py`
beside `PlayerGameStatus`. For a year, only a completion in that year counts;
all-time, a done status counts too.

### Dropped

A copy is **dropped** when its game is not finished, and:

```
PlayerGame.status == "abandoned" OR the copy's access ended with way "refunded"
```

A refund of a `game` purchase ends its copy with way `refunded`, so a refund
reaches the figure through the copy.

---

## Unfinished vs. Dropped

### Unfinished

A copy is **unfinished** when:
1. It is Owned, and its access has not ended
2. It was acquired in scope (both bounds inside the year; all-time takes every copy)
3. Its game is not finished and not abandoned
4. Its game does not state `excluded_from_unfinished`

The percent divides by the Owned, held copies acquired in scope.

### Dropped

A copy is **dropped** when:
1. It is Owned, and acquired in scope
2. Its game is not finished
3. Its game is abandoned, or the copy ended by refund
4. Its game does not state `excluded_from_dropped`

The percent divides by the Owned copies acquired in scope.

### Backlog decrease

Owned copies whose game was finished: for a year, acquired before it, at a
done status, with a completion in it; all-time, at a done status or with any
completion.

### Summary Table

| Category | Counts | Key Condition |
|----------|--------|---------------|
| **Unfinished** | Owned, held | NOT finished, NOT abandoned |
| **Dropped** | Owned | NOT finished, AND (abandoned OR ended by refund) |
| **Excluded from unfinished** | — | the game states `excluded_from_unfinished` |
| **Excluded from dropped** | — | the game states `excluded_from_dropped` |

A season pass, battle pass or upgrade rides its base copy and holds no backlog
place of its own. A DLC is its own Game, with its own copy and status.

---

## Query Patterns

A status is on the library's own row, so every query naming one takes the
library.

### Getting the copies behind a figure

```python
copies_matching(library, unfinished_copies(year))
```

### Getting the games at a status

```python
Game.objects.tracked_by(library, tracked__status=PlayerGameStatus.ABANDONED)
```

`tracked_by()` passes extra conditions into the one `filter()` call that opens
the join, so a second condition does not read the row twice.

---

## Edge Cases

### Unplayed games
- A copy of an unplayed game (`status="unplayed"`) is **unfinished**, not dropped
- A copy ended by refund counts as **dropped** whatever the status

### Several copies of one game
- Each copy counts once; two copies of one game count twice
- Both read the same game status, so they are finished or dropped together

### Runs that state no completion
- A run whose completion nobody recorded does NOT count as finished
- This represents a game that was started but not completed
- A completion nobody dated DOES count: the act is the marker, not the day

### Retired games

> **Retired counts as finished.** Retired means done with a game that has no
> ending, so it belongs with the completed ones and `DONE_STATUSES` holds both.
> A retired game leaves the backlog, adds to the all-time backlog decrease, and
> is not dropped. It joins a year's finished list only through a
> completed run, because that list is dated by the run's `completed_lower` and a
> retired game with none has no date to show. Until #678 C it counted for nothing: not finished, not in the
> backlog, not dropped.

### Shelved games
- A shelved game is unfinished and not final, so it stays in the backlog
- `unfinished` excludes only the two done statuses and `abandoned`, which is
  already what the words ask for
