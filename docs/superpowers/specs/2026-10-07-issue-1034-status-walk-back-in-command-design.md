# An act and its status share one dispatch

Issue #1034. Part of #601.

## Rule

An act implies a status for its game. A start implies Played. A
completion implies Completed. `status_implied_over(held, implied)` in
`games/models.py` decides if the implied status is stated. It is two
equality rules, not an order:

- Played is stated only where the game holds Unplayed.
- Completed is stated wherever the game does not hold Completed.
  Retired, Shelved and Abandoned do not stop it.

`played_is_offered` calls the same rule. It is a render hint only: the
form deletes the Played box where the hint says no. The command decides.

## Carriers

The command that records the act appends `playergame.status_changed` in
the same dispatch, under the same lock. The status event is always last,
because `created_aggregate_id` reads the first event. An `Unchanged` act
states no status. A replay replays both.

`with_implied_status` in `games/commands/playthrough.py` appends the
event. `implied_status_change` in `games/commands/playergame.py` builds
it, dated on the library's calendar.

| Command | Field | Implies |
|---|---|---|
| `StartPlaythrough` | `implies_status` | Played |
| `CompletePlaythrough` | `implies_status` | Completed |
| `CreatePlaythrough` | `implies_played`, `implies_completed` | Completed over Played |
| `CreateSession` | `implies_played` | Played |
| `MovePlaythroughToGame` | none | the run's endpoints, on the target |

No carrier field in the table has a default. A creation states one
status at most, and only for an act it states. A move states its status
always. A newly tracked target holds Unplayed.

The implied status is `ImpliedStatus`: Played or Completed. A carrier
reads the held status through `HeldGame`, a `StatusHolder`. A stored word
that no `PlayerGameStatus` names is `RowUnreadable`.

A session edit states no act. `restate_session(implies_played=True)`
dispatches `RecordPlayerGameFacts(implied_status=PLAYED)` last, under the
edit's correlation. That field obeys the same rule. Construction refuses
it beside `status`. A removed game takes no implied status. A bulk Edit
does not state it.

## Callers

- `RunDraft` carries both boxes. A correction carries no box.
- `record_session` and `restate_session` take `implies_played`.
- The batch start and completion pass `True`.
- The API, resume and the benchmark pass `False`.
- `MovedRun.stated_status` reads the move's status event.

An act and its status land or fail together. An act needs no second
dispatch and no `-status` key. Batch Undo still finds the batch's status by
`correlation_id`. It does not put back a status that a later move
stated.

## Follow-up

- #1563: batch Undo voids and restores the status in one dispatch.

## Fingerprint

`FINGERPRINT_VERSION` is 6. A key recorded under version 5 replays
unchecked. `tests/test_endpoint_fingerprints.py` records each carrier and
`RecordPlayerGameFacts`.
