# A session or a record names its Release

Issue [#1354](https://github.com/KucharczykL/timetracker/issues/1354).
Wave: [Access and Purchases](2026-09-28-access-and-purchases-wave-design.md).

## The fact

A session or a historical playtime record may name the Release it was
played on. The fact is optional. Null is "not stated". Nothing infers
it: not the game, the device, a resumed session or another record. A
demo session is a session that names a Release on a `prerelease`
Edition.

## The rule

`held_releases(library)` (`games/reads/releases.py`) is the one reader
of "the library holds a copy": the Releases that `library_entries`
names. An ended copy counts. A removed copy does not.

`stated_release` (`games/commands/scope.py`) checks a Release under the
dispatch lock:

1. The library sees the Release, else `RowNotHeld`.
2. No mark removes the Release, else `RELEASE_REMOVED`.
3. The Release is of the row's game, else `RELEASE_OF_ANOTHER_GAME`.
4. A live copy names the Release, else `NO_COPY_OF_RELEASE`.

Check 3 always runs. Checks 2 and 4 skip the held value, the Release
the row names already. Thus a removed copy or a removed Release leaves
the row alone. The entry commands share the first three sentences.

The ownership audit (`release_game_violations`) reports an entry,
session or record whose Release is of another game. It reads only rows
that name a Release, because a negated lookup passes a null.

## Events

- `playersession.created` and the record statement carry
  `release: ReleaseReference | None`. `ReleaseReference` refuses every
  kind but `catalog.release`.
- `playersession.release_changed` states the Release or none.
  `DescribeSession` states it through `StatedRelease`.
- `historicalplaytime.moved` holds `release: None` only when the move
  cleared a Release. The projector clears the column only then.

## Moves

A move to another game clears the Release. It never refuses.
`MoveSessionToPlaythrough` appends `release_changed(None)` before
`moved`. `MovePlaythroughToGame` clears every session of the run,
removed ones included, and every record. `MovedRun.cleared_releases`
counts them, and the Edit playthrough toast says the count.

The Edit session page and the session PATCH state the Release after
the move, in a dispatch of its own.

## Surfaces

- The session form, the record form and the reclassification form
  show a Release picker after the playthrough. It lists the game's
  held Releases from `GET /api/releases/held`. A Release whose every
  copy ended shows the way it ended. The row's own Release stays a
  choice.
- Bulk Edit states a Release for a selection at one game. ⊘ states
  none. The Undo restates the Release in a dispatch of its own, so a
  gone copy refuses that fact alone.
- `PlayerSessionFilter` and `HistoricalPlaytimeFilter` take `release`
  and `edition_kind`. `GET /api/releases/played` feeds the `release`
  field.
- `outside_playthrough_dates` never matches a demo session. A session
  that names no Release still matches.
- The session API and the record API carry `release_id`.
- Resume states no Release.
