# Archive and restore a tracked game

Issue [#675](https://github.com/KucharczykL/timetracker/issues/675). The code is
in `games/models.py`, `games/events/dispatch.py`, the three `playergame`
modules, and the default pinned in `tests/test_projection_model.py`. #671 gives
the row, #672 gives `amend()`, and #673 and #674 give the shape this repeats.

A library archives a game it tracks, and later restores it. The charter states
the pair: a player's tracked Game is archived through `PlayerGameArchived` and
restored through `PlayerGameRestored`, and one library never archives a shared
Game for another library.

## The column

`PlayerGame.archived_at` is a `DateTimeField` that is null, is not editable, and
starts at `None`. A null column says the library keeps the game live.

The column holds a time and not a flag. The archive event states when, and a
flag would send every later reader to the events for a fact the projection can
hold. The charter's operator list takes a library, a type and a UUID, thus it
asks for no time; the time is for the person who reads one row and asks when it
left the list.

The default is a constant and the field has no database default, thus
`games.checks` E001 to E007 stay clear. `PINNED_DEFAULTS` gains the entry that
makes a change a reviewed diff.

`project()` names its columns in `update_fields`, and the creation handler does
not name this one, thus a second run keeps an archive a later event set.

The row is already library-scoped, thus one library's archive says nothing about
another. `unique_library_player_game` counts the archived row, which is what
gives a restore the same row with the status, the mastery and the exclusion it
had.

The migration adds the column and needs no data step: no event archives a game.

## Why the column is named `archived_at`

The name follows CLAUDE.md's one-act-one-verb rule. The event type is
`library.playergame.archived`, the command is `ArchivePlayerGame`, and the
column is `archived_at`. The charter names the act once, and the three sites
repeat that one word.

The name is free because #937 took it back. `Game`, `Platform` and `Device` held
an `archived_at` for retention's policy, which is a different act: an event
names the row under a `REQUIRED` kind, thus a delete keeps the row and takes
everything else. The sessions, the play events, the purchase counts and the
`SET_NULL`s all occur. That row is a gutted husk that stays for the events that
name it, so #937 renamed the column `tombstoned_at` and the outcome
`Retirement.TOMBSTONED`.

An archived `PlayerGame` is the opposite. The row keeps every fact, because a
restore returns the game the library had.

The two meet on one row. `tombstone_or_delete` collects with
`fail_on_restricted=False`, thus a retired catalog game keeps the projection
rows that point at it;
`tests/test_retention.py::test_a_tracked_game_is_tombstoned_and_keeps_its_projection_row`
pins that state. After this issue, `player_game.archived_at` and
`player_game.game.tombstoned_at` are two columns of one row, they are set
independently, and they state different things. Two names is what lets #678
read one and not the other.

## The two events

The types are `library.playergame.archived` and `library.playergame.restored`,
their aggregate id is the `PlayerGame` identity, and both payloads are empty.

Archiving and restoring are two facts, as the exclusion is one. #674 records a
direction in the payload because one word states both directions of one fact.
Here the type is the fact, thus Audit History reads the name and no payload
holds a flag that disagrees with it.

An empty payload is strict: `extra="forbid"` refuses every key, so a later fact
takes a later type and not a key nobody declared.

Neither payload states the time. The event carries `recorded_at`, as the
creation event does for `tracked_at`, thus a replay writes what was recorded.

## The handlers

`_archived` calls `amend()` with `archived_at=event.recorded_at`, and `_restored`
calls it with `archived_at=None`: one `UPDATE` on the primary key of the created
row. An absent row raises `ProjectionRowMissing`.

## The commands

`ArchivePlayerGame(game_id)` and `RestorePlayerGame(game_id)` run behind the
stream-head lock and give one event each. `CommandName.PLAYERGAME_ARCHIVE` is
`library.playergame.archive` and `CommandName.PLAYERGAME_RESTORE` is
`library.playergame.restore`.

`_tracked_game()` rejects a game the library does not track. An archived row
rejected an archive and a live row rejected a restore.
[#906](https://github.com/KucharczykL/timetracker/issues/906) settled that:
both now return `Unchanged`, a success that records no event.

The idempotency key must name the request and not the pair. `idempotent_append`
reads the key before `build()` runs, thus a repeat key replays the first record
and appends no event. A caller that makes one key from the command and the game
archives, restores, and then archives again with no second event, and reads a
success. #677 gives the first caller and takes this requirement.

## A restore reads the projection only

Neither command asks whether the catalog game is tombstoned. `TrackGame` asks,
because it makes a row; these two find one.

The case occurs. A delete of a tracked game tombstones the catalog row and keeps
the projection row, thus a library can hold an archived game whose catalog row
is a husk. A restore returns it.

That is the outcome to want. The row exists, `RESTRICT` keeps the catalog row
alive for it, and a refusal would leave the library a game it can neither see
nor recover. A test pins it.

## The one edit outside the new code

`TrackGame` rejects a game that has a row, and its message states that the
library already tracks the game. An archived game has a row and the library
lists nothing, thus the message names the restore instead. The text changes and
the behaviour does not.

`SetPlayerGameStatus`, `SetPlayerGameMastered` and
`SetPlayerGameExcludedFromUnfinished` stay as they are. An archived row keeps
its facts, so a restore returns the game the library archived. Whether an
archived game accepts a status is a question for the dropdown that shows one,
which is #677.

## Verification and reversibility

The gate is the full `make check`, over tests for the pinned default, two
registered specs that refuse an extra key, one `UPDATE` per amended row, a
creation event that replays without clearing a later archive, an archive and a
restore and an archive that replay to one state, a `CHECK` rebuild without
drift, the four rejections, a restore of a game whose catalog row is tombstoned,
and the amended `TrackGame` message.

A revert is the commits and a migration back to
`0031_playergame_excluded_from_unfinished`; no recorded event is lost, because
none exists until #677.

## Out of scope

No view, form or API calls either command, and no read consumes the column, thus
no filter, saved preset, statistic or API changes here. #676 backfills no
archive event, because the catalog states no archived game. #677 switches the
writes; #678 moves the reads and states what an archived game means to each
list.
