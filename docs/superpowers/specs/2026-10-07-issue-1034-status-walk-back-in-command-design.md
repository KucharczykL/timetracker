# An act states its status in its own dispatch

Issue #1034. Part of #601. Follows #683 and #1313.

## Problem

An act implies a status for its game. A start implies Played. A completion
implies Completed. Played is correct only where the game is Unplayed. On any
other status, Played walks the status back.

Today the act and its status are two dispatches. The status rule is read
outside the lock, in four places:

1. `implied_by_start` in `games/writes/implied_status.py`, for `state_start`
   (the batch start, which the row's ⋯ item also posts) and for
   `implied_status(run)` (the move).
2. `PlaythroughForm.clean` in `games/forms.py`.
3. `_record_companion_status` in `games/views/playthrough.py`.
4. `_record_played` in `games/views/session.py`, which reads the row itself.

Each read can go stale before its dispatch. A second dispatch can be refused
after the act committed, which leaves an act without its status and needs
`StatusRefused`, `MovedThenFailed`'s status half, and a second idempotency
key (`<key>-status`).

## Design

The command that records the act appends `playergame.status_changed` in the
same dispatch, under the same lock. The row is read there, so the answer
cannot go stale.

### The rule

Two equality rules, not an order. `status_implied_over(held, implied)` in
`games/models.py`, beside `PlayerGameStatus`, answers whether an implied
status is stated:

- Played: only where `held` is Unplayed.
- Completed: wherever `held` is not Completed. Retired, Shelved and
  Abandoned do not stop it, as today.

`implied_status_change(context, tracked, implied)` in
`games/commands/playergame.py` turns a true answer into the status event.
Its `effective_time` is the calendar day (`_stated_now`). A removed
`PlayerGame` gets no implied status.

`played_is_offered` stays as the form's render hint, and it calls
`status_implied_over`. The box is still deleted where the hint says no.

### The carriers

Each command field below has no default, so every caller decides.
`CreatePlaythrough` and `CreateSession` become `kw_only=True`, because
their other fields have defaults. `EndpointStatement.first` gets its own
protocol, `FirstActCommand`, which takes `implies_status`; corrections keep
`EndpointCommand`.

| Command | Field | Implies |
|---|---|---|
| `StartPlaythrough` | `implies_status: bool` | Played |
| `CompletePlaythrough` | `implies_status: bool` | Completed |
| `CreatePlaythrough` | `implies_played`, `implies_completed: bool` | Completed over Played |
| `CreateSession` | `implies_played: bool` | Played |
| `MovePlaythroughToGame` | none: a move always carries its status | the run's endpoints, on the target |

A carrier appends the status event only where its act appends, and
appends it **last**: `created_aggregate_id` reads a dispatch's first event
as the created row. An `Unchanged` act states no status. A replay replays
both.

A creation with both acts and both boxes appends Completed alone. History
then shows Unplayed to Completed, without the Played step between.
`MoveSessionToPlaythrough` implies no status, as today.

A move reads the target's held status under the lock. A newly tracked
target holds Unplayed.

### Callers

- `RunDraft` carries the two boxes, `implies_played` and
  `implies_completed`, both without a default and before `game_id`. `_state_endpoint` passes the box to the
  first act, never to a correction. The API's draft passes `False` to both,
  as today. A move through the API still carries its own status.
- The batch start and completion pass `True`.
- `state_start`, `state_completion` and `_move` dispatch once each. Their
  `StatusAnswer` is `None` where nothing was appended, else read from
  `dispatched_events(result)`: `StatusStated` or `None`. `dispatched_events`
  raises on an `Unchanged` outcome, so the outcome is read first. `StatusRefused` goes entirely, with the "could not be marked"
  toast, the API's refused-status log and `_report_a_refused_status`. A
  refusal now refuses the act as well.
- `_record_companion_status`, `record_completed`, `implied_by_start`,
  `state_implied_status`, `_state_the_moved_status` and
  `PlaythroughForm.clean`'s gate go. `clean` keeps its `setdefault`: the
  render hint deletes the field, and the draft reads the key. The forward
  `-status` key goes; batch Undo's stays until the follow-up.
- `SessionDraft` (a `NamedTuple`) carries `implies_played`, without a
  default. The session form sets it from
  `mark_as_played`. Resume (`clone_session`), `POST /api/session/`, the
  benchmark workload and the test builders pass `False`, as today.
- A session edit states no act, so it dispatches `RecordPlayerGameFacts(
  implied_status=PLAYED)`. That field uses the same rule, counts as a fact
  for the "states no fact" guard, and is refused beside `status`.
  `record_facts` and `record_facts_for_request` take it.
  `test_the_fact_lists_agree` excludes it: a bulk Edit states facts, not
  implied statuses.

### Undo

Batch Undo finds the status by the batch's `correlation_id`
(`games/reads/fact_change.py`). That still holds inside one dispatch. Undo
itself still voids and restores in two dispatches; see the follow-up.

## Fingerprint

The new fields enter the digests of five commands, and of
`RecordPlayerGameFacts`. `FINGERPRINT_VERSION` goes from 5 to 6.
`tests/test_endpoint_fingerprints.py` is recorded again, and gains a
`RecordPlayerGameFacts` entry.
A key recorded under version 5 replays unchecked. A replayed act no
longer retries its status: a version-5 act whose `-status` dispatch never
landed keeps no status. The single library has no batch in flight across a
deploy, so this is accepted.

## Tests

- The rule over the whole status table, for Played and Completed.
- Each carrier: true appends the status where the rule says so; false never
  does; an `Unchanged` act appends no status; a replay states nothing new.
- A start over a Completed game keeps it Completed, through the batch,
  through the form, and through a move.
- A session create and edit over a Completed game keep it Completed.
- A `<key>` recorded under version 5 replays.
- The tests that pin `also_mark_played` cleaning to False are rewritten to
  assert the status after the POST.
- Tests of the second dispatch go: the `-status` key, a refused status
  carried back, and the monkeypatches of `games.writes.implied_status`.
- Every direct construction of the five commands states the new field.
- The `_record_played` tests (`tests/test_playergame_status_word_setters.py`,
  `tests/test_playergame_view_cutover.py`) assert the row after the POST.
- A start and a session create now read the calendar inside the act's
  dispatch. A test library without a `LibraryCalendar` row fails there.

## Follow-up issues to file

- Batch Undo of a start or a completion: void and restore the status in one
  dispatch.
