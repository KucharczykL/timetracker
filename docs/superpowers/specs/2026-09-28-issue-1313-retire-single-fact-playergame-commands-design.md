# One command states status and mastery

Issue [#1313](https://github.com/KucharczykL/timetracker/issues/1313). The code
is in `games/commands/playergame.py` and `games/events/dispatch.py`.

## The command

`RecordPlayerGameFacts` is the one command that appends
`library.playergame.status_changed` and `library.playergame.mastered_changed`.
Each caller reaches it through `record_facts` in `games/writes/playergame.py`.

The command states a status, a mastery, or both. The game form states both
facts at each save. One command gives one idempotency key to one save, so a
save cannot commit half. A rule about status has one place: the `build()`
method of this command.

## Retired names

`library.playergame.set_status` and `library.playergame.set_mastered` are
retired. `CommandName` does not hold them.

A retired name is never used again. The idempotency fingerprint is a SHA-256
digest of the command name and its fields. A new command with a retired name
and equal fields gives an equal digest. An old key then replays as the new
command.

`RETIRED_COMMAND_NAMES` in `games/events/dispatch.py` holds the retired names.
`Command.__init_subclass__` refuses a command with a name in this set. The check
is after the vocabulary check, so the name has a value. The check is before the
registry check, so a refused class does not register. The check applies to each
vocabulary, also to the vocabularies that tests declare.

A member of `CommandName` that no command claims does not go through
`__init_subclass__`. A test in `tests/test_command_dispatch.py` therefore keeps
each `CommandName` value out of the set.

To retire a command, remove its member from `CommandName` and add its value to
`RETIRED_COMMAND_NAMES`. Do not rename a member.

## Idempotency records

A `LibraryIdempotencyRecord` keeps the digest, not the command name. No code
reads a command name back. A key replays by key and digest.

## Tests

`tests/test_playergame_command.py` has one set of fact tests. Each test has the
cases `status` and `mastery`. Each case states one fact and sets the other fact
to `None`. The tests examine these rules:

- A fact appends its event and projects it.
- A fact does not change the other columns of the row.
- A fact for an untracked game is refused. No event is appended.
- A fact for a game that another library tracks is refused.
- A fact that already holds is `Unchanged`. No event is appended.
- One idempotency key records one change.

The tests use `dispatch`. They do not use `record_facts`, because
`record_facts` tracks an untracked game. A refusal test through `record_facts`
passes for the wrong reason.

`tests/test_projection_replay_gate.py` states each fact through
`RecordPlayerGameFacts`. The gate asserts the set of event types, so it shows
that both events are appended.

## Limits

`SetPlayerGameExcludedFromUnfinished` states a different fact and stays. The
walk-back rule of #1034 goes into `RecordPlayerGameFacts.build()`.
