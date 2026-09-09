# Offer a status change beside a lifecycle act

A run states an act. The person who records it usually means a status too. This
design offers that status beside the act. Nothing is inferred. Each status event
is one a person asked for.

## The status a run offers

A game completed once is Completed. A second run does not walk that back.

| The person states | The status |
|---|---|
| A first start on an Unplayed game | Played |
| A completion | Completed |
| A start on a Played or stronger game | Unchanged |

`Played` is offered only where the status is `Unplayed`. On each other status
the box does not render. A game the library does not track yet has no status,
so both boxes render.

`Completed` is offered wherever the submit states a completion. Where the status
is Completed already, `RecordPlayerGameFacts` answers `Unchanged`.

Retired, Shelved and Abandoned are never offered beside an act. Each is a
judgement no run implies. The status selector states them directly.

## The two boxes

The run form carries two fields.

| Field | Label | Renders when |
|---|---|---|
| `also_mark_played` | Also mark this game Played | The status is `Unplayed` |
| `also_mark_completed` | Also mark this game Completed | Always |

Each box is checked when it renders. Each acts only where the draft states the
matching act. A note-only edit states no status. A box the form did not render
states nothing, whatever the posted body holds. The form decides twice: once at
render, and once at clean time against the game the submit names.

## The per-run acts

Each run row offers the act its state allows, ahead of Edit and Remove.

| The run states | The action |
|---|---|
| No start | Start |
| A start, no completion | Complete |
| Both | None |

Each action states today. A different day belongs in the edit form, which holds
each precision the grammar knows. Each action is a POST route that redirects to
its origin, so each is `ORIGIN_AWARE`. Neither confirms: the correction commands
reverse both.

## One human act, two dispatches

Each surface appends its lifecycle event and its status event under one
`correlation_id`. It uses two dispatches, because `run_in_transaction` refuses
to nest.

A refused status after a recorded run leaves the run recorded. The refusal
toasts. The person presses again, or states the status in the selector. No
screen shows a half state.

No reader groups events by `correlation_id` yet. The Journal will read that
grouping.

## Out of scope

The status selector is untouched. No activity signal renders. #1033 owns the
Playing and Dormant reads.
