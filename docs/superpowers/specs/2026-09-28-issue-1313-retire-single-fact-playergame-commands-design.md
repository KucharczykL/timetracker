# One command states status and mastery

Issue [#1313](https://github.com/KucharczykL/timetracker/issues/1313). The code
is in `games/commands/playergame.py` and `games/events/dispatch.py`.

`RecordPlayerGameFacts` is the one command that appends
`library.playergame.status_changed` and `library.playergame.mastered_changed`.
Every caller reaches it through `record_facts` in `games/writes/playergame.py`.

## Retired commands

`SetPlayerGameStatus` and `SetPlayerGameMastered` are removed, with their
`CommandName` members `PLAYERGAME_SET_STATUS` and `PLAYERGAME_SET_MASTERED`.
No production code dispatched them.

Two single-fact commands were the alternative. They are refused: the game form
states both facts at each save, and two commands would need two idempotency
keys, so one save could commit half. One command also gives one place to a rule
about status, such as the walk-back rule of #1034.

## Idempotency records

A `LibraryIdempotencyRecord` keeps a SHA-256 digest of the canonical input, not
the command name. Nothing reads a name back. A key issued under a retired name
replays by key and digest, as before.

## Retired names

A retired name is never used again. A new command with a retired name and equal
fields would give an equal digest, and an old key would replay as the new
command.

`RETIRED_COMMAND_NAMES` in `games/events/dispatch.py` holds
`library.playergame.set_status` and `library.playergame.set_mastered`.
`Command.__init_subclass__` refuses a command whose name is in the set, before
the registry check. That check covers each vocabulary, including the ones tests
declare. A second test keeps each `CommandName` member out of the set, because a
member that no command claims does not reach `__init_subclass__`.

A name is removed from `CommandName` and added to the set. It is not renamed
and not reused.

## Tests

The status and mastery tests of `tests/test_playergame_command.py` were twins.
Four tests take a `fact` parameter with the cases `status` and `mastery`, and
dispatch `RecordPlayerGameFacts` through `dispatch`. `record_facts` is not
used there, because it tracks an untracked game and a refusal test would pass
for the wrong reason. Each case gives its event type, payload and row attribute
as data.

Tests that the `RecordPlayerGameFacts` tests already cover are deleted: the day
a status states, a fact for an untracked game, and a fact that already holds.

`tests/test_projection_replay_gate.py` dispatches `RecordPlayerGameFacts` with
the other fact `None`. The keys and the order do not change, and a `False`
mastery is still stated. The gate asserts the set of event types, so it proves
that both events are still appended.

## Out of scope

The walk-back rule stays in #1034. `SetPlayerGameExcludedFromUnfinished` has a
production caller and stays. Earlier specs keep the old names as history.
