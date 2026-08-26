# Mastered behind commands and events

Issue [#673](https://github.com/KucharczykL/timetracker/issues/673). The code is
in `games/models.py`, `games/events/dispatch.py`, the three `playergame`
modules, and the default pinned in `tests/test_projection_model.py`. #671 gives
the row; #672 gives `amend()` and the rule for a default.

A library states that it mastered a game it tracks. The charter keeps mastery a
separate, stronger fact, thus a flag and not a seventh `PlayerGameStatus` value.

## The column

`PlayerGame.mastered` is a `BooleanField` that starts at `False`. The creation
event states nothing about it, so it takes a constant default, as `status` does.
A literal clears `games.checks` E004 to E007, and `PINNED_DEFAULTS` gains the
entry that makes a change a reviewed diff.

`project()` names its columns in `update_fields`, and the creation handler does
not name this one, thus a second run keeps a value a later event set.

The migration adds the column with its default and needs no data step: no event
states mastery yet.

## The event

The type is `library.playergame.mastered_changed`, its aggregate id is the
`PlayerGame` identity, and its payload has one key, `mastered`.

One event states one fact, because Audit History shows each change. A flags
event holding this and #674's exclusion would need `total=False`, which makes an
empty payload valid. #674 repeats this shape; #675's archive and restore are
two facts.

The payload states the value, thus one type serves both directions and a replay
writes what was recorded.

`mastered` is a `bool`. `status` needs a `Literal` because strict validation
refuses a plain string for an enum field; a bool reads back as itself.

## The handler

`_mastered_changed` calls `amend()`: one `UPDATE` on the primary key of the
created row. An absent row raises `ProjectionRowMissing`.

## The command

`SetPlayerGameMastered(game_id, mastered)` runs behind the stream-head lock and
gives one event. `CommandName.PLAYERGAME_SET_MASTERED` is
`library.playergame.set_mastered`.

A game the library does not track rejects, as does an unchanged value.
[#906](https://github.com/KucharczykL/timetracker/issues/906) decides whether a
no-op must instead succeed.

`SetPlayerGameStatus._tracked()` becomes a module-level
`_tracked_game(context, game_id)` that both commands call. Its rejection says
"a recorded fact", not "a status".

## Notes for #676 and #677

The default covers a row that no event touched, and not the catalog's
`Game.mastered`: #676 must record a `mastered_changed` event for each game a
library mastered, or a rebuild loses the flag.

A form that saves several facts is one command emitting several events under one
lock, which the charter permits. #677 thus needs #906: a save with nothing
changed emits nothing, and an empty append raises.

## Verification and reversibility

The gate is the full `make check`, over tests for the pinned default, a strict
payload, one `UPDATE` per amended row, a replay and a `CHECK` rebuild without
drift, and one event for one key. A revert is the commits and a migration back
to `0029_playergame_status`; no recorded event is lost, because none exists
until #677.

## Out of scope

No view, form or API calls the command, thus `Game.mastered` stays the one flag
anything writes until #677; #678 moves the reads. #674 and #675 add the rest.
