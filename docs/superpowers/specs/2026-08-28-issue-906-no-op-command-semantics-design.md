# A command that changes nothing

Issue [#906](https://github.com/KucharczykL/timetracker/issues/906). The code is
in `games/events/vocabulary.py`, `games/events/idempotency.py`,
`games/events/dispatch.py`, `games/commands/playergame.py` and
`games/models.py`. #664 gives the boundary that owns the outcome, #675 gives the
first reversible pair, and #677 gives the first caller that can ask twice.

A player sets a game to completed when the library already completes it. Nothing
must be recorded, and the player must not read a failure. #664 left the meaning
of that dispatch open, because no real command existed to settle it. Six exist
now, and each one says so in its own refusal message.

## The rule

A `build` asks two questions, in this order.

1. Does the state the caller asks for already hold? The command returns
   `Unchanged`. To do nothing is to reach that state.
2. Can that state be reached from here? A no raises `CommandRejected`.

`CommandRejected` keeps the meaning #664 gave it: a precondition that nothing
satisfies, such as an end for a session that never started. The rule is decided
inside each `build`. No command declares a kind, and the dispatcher reads no
flag.

## What a build returns

`Unchanged` is a frozen dataclass beside `NewEvent` in `vocabulary.py`. The two
members of a `build` return live in one module, and that module is a leaf that
`idempotency.py` and `dispatch.py` already import, thus no import cycle occurs.
`dispatch.py` re-exports it, thus a command author has one import site.

```python
@dataclass(frozen=True, slots=True)
class Unchanged:
    """The state the caller asks for already holds."""

    reason: str
```

`Command.build` returns `Sequence[NewEvent] | Unchanged`. mypy reads the union,
thus a caller that forgets the second member is a type error.

## What a dispatch returns

`CommandResult.replayed` becomes an outcome of three members, and the two
sequence integers become one named range that is absent when nothing was
recorded.

```python
class CommandOutcome(StrEnum):
    APPENDED = "appended"
    REPLAYED = "replayed"
    UNCHANGED = "unchanged"


class SequenceRange(NamedTuple):
    first: int
    last: int
```

`CommandResult` carries `stream_id`, `outcome`, `sequences`, `reason` and
`correlation_id`. `sequences` is `SequenceRange | None`, and it is `None`
exactly when the outcome is `UNCHANGED`. A boolean pair would describe four
states where three exist.

`reason` is `str | None`. It holds a sentence only for a `build` that ran and
returned `Unchanged`, thus it is absent for an appended outcome, for a replayed
one, and for a no-op whose key was already claimed.

`AppendResult` and `ReplayedAppend` keep their two flat integers. The named
range is a type of the dispatch boundary, and to fit it underneath is work this
issue does not own.

## The append is untouched

`LockedStream.append` still raises `ValueError` for an empty sequence. #662
chose that to mark a programming error, and the choice holds: a `build` that
forgets to return its events is still a bug rather than a reported success. The
sentinel is what buys that guard, and it is why an empty list expresses nothing.

## A no-op claims its key

`idempotent_append` gains a third return, `UnchangedAppend`, beside
`ReplayedAppend`. It carries `stream_id` and a `reason` of `str | None`. It
writes a `LibraryIdempotencyRecord` whose sequence range is absent, and it
appends no event and advances no head.

A record with no range closes a silent lost update. Without it the key stays
unclaimed, and this occurs:

1. Request K sets the status to completed. The library already completes the
   game, thus the dispatch changes nothing and records nothing.
2. Another writer sets the status to played.
3. K is delivered a second time. Its `build` now finds played, thus it appends,
   and step 2 is undone with no sign to either writer.

Both conditions are needed and neither is exotic. A repeated delivery is an
ordinary browser retry, and a second writer is a second tab. The result is wrong
and quiet.

With the record, the second delivery of K reads the key before `build` runs and
returns `UNCHANGED` with no range, whatever the state has since become.

`LibraryIdempotencyRecord.first_sequence` and `last_sequence` become nullable.
The two check constraints are replaced by one that admits both columns absent,
or both present and ordered. No data step is needed: every existing row carries
a range. Only `idempotency.py` reads the two columns, thus the change reaches no
other reader.

`reason` is absent on a replayed no-op. The key is read before `build` runs, and
to run it against a state that has moved is the bug above. Nothing user-facing
may depend on the reason for that cause; see below.

## Why the record gains nothing else

`LibraryIdempotencyRecord` is a pointer. It states which events a key produced,
and it exists only because one key produces many event rows, thus the events
table cannot hold the uniqueness. An absent range keeps it a pointer that points
at nothing.

A reason column would make it something else: a row that holds a typed fact
about what happened, with no replay, no type registry and no place in the
stream's order. That is a second event log with none of the first one's
properties, and the repository already holds the first one.

The fact has two proper homes and neither is here.

- The event stream. To append a "nothing changed" event needs no migration,
  because an event is recorded. It also writes a permanent row for every
  redundant pick a player makes, and every rebuild pays for all of them. The
  stream holds what a library did, not what it was asked.
- [#740](https://github.com/KucharczykL/timetracker/issues/740), which is
  already scoped as "command **and** event audit-history records". A request
  that ran and changed nothing is a command fact, thus #740 owns it.

The record therefore stays as it is: a key, a fingerprint and a range that may
be absent. Nothing is added to it.

`Unchanged.reason` stays inside the application. It carries the sentence each
refusal carries today, which serves a log line and lets a test name which of the
six branches fired. #677 states its own wording from what it asked for and what
it reads, thus no screen depends on a reason that a replay cannot supply.

## The commands

Six of the eight refusals in `games/commands/playergame.py` become `Unchanged`,
and three stay. The six are the ones whose message reads "Whether a repeat
should instead succeed as a no-op is EV-23 (#906)"; that sentence is deleted
wherever it appears.

| Command                                | Condition                     | After                                  |
| -------------------------------------- | ----------------------------- | -------------------------------------- |
| `TrackGame`                            | tracks the game, live row     | unchanged                              |
| `TrackGame`                            | tracks the game, archived row | rejected, "restored, not tracked again" |
| `TrackGame`                            | no catalog game it can see    | rejected                               |
| `SetPlayerGameStatus`                  | status already equal          | unchanged                              |
| `SetPlayerGameMastered`                | flag already equal            | unchanged                              |
| `SetPlayerGameExcludedFromUnfinished`  | flag already equal            | unchanged                              |
| `ArchivePlayerGame`                    | already archived              | unchanged                              |
| `RestorePlayerGame`                    | not archived                  | unchanged                              |
| `_tracked_game`                        | the library tracks no such game | rejected                             |

`TrackGame` takes the rule without an exception. A live row means the library
tracks the game, thus to do nothing reaches what was asked. A caller that must
tell an addition from a repeat reads the outcome, which is what the three
members are for. An archived row is a rejection, because "tracked and live" does
not hold and nothing reaches it by doing nothing.

## Verification

- Each of the six branches returns `UNCHANGED`, appends no `LibraryEvent`,
  leaves `LibraryEventStreamHead.current_sequence` where it was, and leaves the
  `PlayerGame` row equal field for field.
- `sequences` is `None` if and only if the outcome is `UNCHANGED`, across all
  three outcomes.
- `reason` names which branch refused. A first no-op carries the sentence, and
  the same key delivered again carries `None`.
- A `LibraryIdempotencyRecord` is written for a no-op, with both sequence
  columns absent.
- The lost update is closed: a no-op under key K, then an interleaved write,
  then K again, returns `UNCHANGED` and appends nothing.
- The constraint admits both columns absent and refuses one of the two.
- The guard survives: a test double whose `build` returns `[]` still raises
  `ValueError`.
- The reversible pair, which #675 recorded and #677 inherits: archive, restore
  and archive under three distinct keys append three events, and the same key
  twice replays and appends one.
- The five `pytest.raises(CommandRejected, match="#906")` assertions in
  `tests/test_playergame_command.py` become outcome assertions.
- The full `make check` gate passes.

## To be removed by #740

The nullable range is a patch. #740 replaces
`LibraryIdempotencyRecord` with a record of the request itself, where an outcome
of nothing is an ordinary row rather than an absent range.

Three markers carry the debt.

1. A comment on the two nullable fields and on the replacement constraint in
   `games/models.py`, naming #740.
2. This section.
3. A comment on #740, so whoever takes it inherits the debt rather than finds
   it.

## Out of scope

- How #677 renders `UNCHANGED`. A quiet success is the likely answer, and it is
  #677's to make.
- Recording a rejection. A rejected command rolls its transaction back, thus to
  record one needs a write outside that transaction. #740 owns it.
- `AppendResult` and `ReplayedAppend` adopting `SequenceRange`.
