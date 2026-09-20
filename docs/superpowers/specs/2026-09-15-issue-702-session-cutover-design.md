# Switch Session writes and every read surface

Issue: [#702](https://github.com/KucharczykL/timetracker/issues/702).
Wave review: [Session delivery wave](2026-09-12-session-wave-design.md).
Member 3 of stack #1072, after #700 and #1047, before #704.

## Purpose

Every session write is a command. Every session read reads
`PlayerSession`. The legacy `Session` table stays for the conversion,
the census, the legacy playtime source, the removal registry and the
fixture commands, and `tests/test_session_import_guard.py` refuses an
import anywhere else. #772 drops the table and empties the guard.

## Writes

`games/writes/playersession.py` holds the request-free half. It follows
`games/writes/playthrough.py`. `record_session` dispatches
`CreateSession`. `restate_session` dispatches `CorrectSessionTiming`,
then `DescribeSession` for the facts that differ, then
`MoveSessionToPlaythrough` when the run changed, under one
`correlation_id`. Each dispatch goes through `answered("session")` and
absorbs `Unchanged`. Finish is `EndSession(now, browser zone)`. Reset is
`CorrectSessionTiming` with the row's `day_zone` and the browser's start
zone, and refuses a row that is not running. Remove is `RemoveSession`
behind the confirm page. Clone starts a Timed session now on the game's
latest live ordinary run, in the library's calendar zone. The bucket
takes no new session. `mark_as_played` stays a companion dispatch under
its own `correlation_id`.

`SessionForm` is a plain `Form`. It derives the mode from what is
filled: a start alone is Timed, a day and a duration is Duration-only,
a start, an end and a duration is Corrected. A start beside a duration
with no end, and a day beside an instant, are refused with a sentence
that names the shapes that work. `day_zone` is `calendar_day_zone(library)`.
The run is picked after the game through `<playthrough-select>`, which
refills from `GET /api/playthrough/?game=` and hides when the game holds
one run. A session on a game nothing tracks is refused on the run.

`PATCH /api/session/{id}` takes a body with `extra="forbid"`: `timing`
is a correction, `note`, `device_id` and `emulated` a description,
`playthrough_id` a move. A named key is the act. A device outside the
library answers 404.

`POST /api/session/` records one: the run, one whole timing statement,
and the three described facts. It answers 201 and the row, and an
`Idempotency-Key` header absorbs a repeat.

## Reads

`library_sessions(library)` is the one scope. `PlayerSessionFilter`
speaks projection words under model key `playersession`; a key no
field answers is refused. `GameFilter`'s session aggregates cross
`player_games__playthroughs__sessions`, and `aggregate_to_q` always
scopes its subquery through the context. A comparison operand reaches
the game through `ProjectionModel.comparison_through`, which
`games.E011` checks. Playtime `SOURCE` is the projection;
`game_playtime_between` is a parity member. Statistics scope a year on
`effective_day`, order first and last play by `sort_instant`, and read
superlatives from `effective_duration`, so a Corrected row enters at
its override. The navbar pages resumes by `(sort_instant, id)`. The
dormancy clock asks when the run was last played, so a run whose play
sits in the bucket reads Never played until the sessions are moved.

## Out

A restore route is #695. Preset
migration is #767. The legacy table is #772. The bulk move and the
organizer are #714, #715 and #716.
