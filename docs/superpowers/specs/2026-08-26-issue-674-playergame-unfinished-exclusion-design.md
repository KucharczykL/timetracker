# Exclude from unfinished behind commands and events

Issue [#674](https://github.com/KucharczykL/timetracker/issues/674). The code is
in `games/models.py`, `games/events/dispatch.py`, the three `playergame`
modules, and the default pinned in `tests/test_projection_model.py`. #671 gives
the row, #672 gives `amend()`, and #673 gives the shape this repeats.

A library states that a game it tracks stays out of unfinished lists. The
charter makes this an advanced preference and not a status: nothing infers it
from genre, catalog data, or a change of status.

## The column

`PlayerGame.excluded_from_unfinished` is a `BooleanField` that starts at
`False`. No event states it at creation, so it takes a constant default, as
`status` and `mastered` do. A literal clears `games.checks` E004 to E007, and
`PINNED_DEFAULTS` gains the entry that makes a change a reviewed diff.

`project()` names its columns in `update_fields`, and the creation handler does
not name this one, thus a second run keeps a value a later event set.

The migration adds the column with its default and needs no data step: no event
states the exclusion.

## The event

The type is `library.playergame.excluded_from_unfinished_changed`, its aggregate
id is the `PlayerGame` identity, and its payload has one key,
`excluded_from_unfinished`.

One event states one fact, because Audit History shows each change. The payload
states the value, thus one type serves both directions and a replay writes what
was recorded. The value is a `bool`, which strict validation reads back as
itself; only an enum field needs a `Literal`.

The column, payload key and event name hold one word, so one grep finds every
part. #675's archive and restore are two facts and take two types.

## The handler

`_excluded_from_unfinished_changed` calls `amend()`: one `UPDATE` on the primary
key of the created row. An absent row raises `ProjectionRowMissing`.

## The command

`SetPlayerGameExcludedFromUnfinished(game_id, excluded_from_unfinished)` runs
behind the stream-head lock and gives one event.
`CommandName.PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED` is
`library.playergame.set_excluded_from_unfinished`.

`_tracked_game()` rejects a game the library does not track. An unchanged value
rejected too; [#906](https://github.com/KucharczykL/timetracker/issues/906)
settled that, and it now returns `Unchanged`, a success that records no event.

## The hand-off from Purchase.infinite

`Purchase.infinite` stays the one field the unfinished and dropped statistics
read (`games/views/stats_data.py`). The charter moves that fact at the Purchase
cutover: a game with one or more infinite purchases receives the exclusion
there, with the preflight list of mixed-purchase games.

#676 thus backfills no exclusion event. The catalog states nothing to back one
with, and `False` is what a rebuild must reproduce for every row until a user
sets it.

## Verification and reversibility

The gate is the full `make check`, over tests for the pinned default, a strict
payload, one `UPDATE` per amended row, a replay and a `CHECK` rebuild without
drift, and the three rejections. A revert is the commits and a migration back to
`0030_playergame_mastered`; no recorded event is lost, because none exists until
#677.

## Out of scope

No view, form or API calls the command, and no read consumes the column, thus no
filter, saved preset, statistic or API changes here. #677 switches the writes;
#678 moves the reads.
