# A session or a record names its Release

Issue [#1354](https://github.com/KucharczykL/timetracker/issues/1354).
Wave: [Access and Purchases](2026-09-28-access-and-purchases-wave-design.md).

## The fact

A session or a historical playtime record may state the Release it was
played on. The fact is optional. Null is "not stated", and nothing
infers it: not the game, the device, the resumed session or another
record. A demo session is a session that names a Release on a
`prerelease` Edition.

## The rule

`held_releases(library)` in `games/reads/releases.py` is the one
reader of "the library holds a copy": the Releases that some entry of
`library_entries(library)` names (five marks; an ended copy counts).
The picker and the command both read it.

A stated Release passes these checks, under the dispatch lock, in
this order:

1. The Release is visible to the library (`visible_row` over
   `Release.objects.all()`), else `RowNotHeld` (404). A Release the
   catalog removed (its own mark, its Edition's or its Game's) is
   refused here with `CommandRejected`: "That release was removed.
   Restore it before choosing it."
2. The Release is a Release of the row's game (the session's run's
   game; the record's player game, as the statement states it), else
   `CommandRejected`: "Pick a release of this game."
3. The Release is in `held_releases`, else `CommandRejected`: "You
   have no copy of that release in your library. Add it first, or
   choose another."

Rule 2 always runs. Rules 1 and 3 are skipped for the *held* value, the
Release the row already names, the way a held removed device stays
(`library_device_row`). Thus `RemoveEntry`, an end of access, a
removed Release and a restatement that keeps the Release leave every
session and record alone. A record restated onto another game's runs
that repeats its Release fails rule 2.

The payload types the key as `ReleaseReference`, an `Annotated`
`Reference` whose validator refuses any kind but `catalog.release`,
since `check_kinds_registered` checks registration only. The alias is
an `Annotated`, which `_without_qualifiers` strips, so the arity scan
still reads `Reference | None`; a `NewType` would raise
`ReferenceFieldUnsupported`.

The ownership audit reports a row whose Release is of another game
than its own (rule 2), reading only rows with `release__isnull=False`:
a negated lookup across a null foreign key passes the null rows.

## Events

- `playersession.created` already carries `release`, retyped
  `ReleaseReference | None`; `CreateSession` now fills it, and
  `PlayerSessions._created` names `release_id`, since `project()`
  refuses an unnamed column without a default.
- New `library.playersession.release_changed`, payload
  `{release: Reference | None}`. `DescribeSession` gains
  `release: StatedRelease | None` (bare `None` unstated), the
  `StatedDevice` pattern, and counts it in its "states no fact"
  refusal.
- The record statement payload widens `release: None` to
  `release: ReleaseReference | None`. Recorded events hold `None` and stay
  valid. `HistoricalPlaytimeStatement` gains `release_id: uuid.UUID |
  None = None`. `columns_for_statement` and `_held_columns` gain
  `release_id`, so a restatement that changes only the Release is no
  `Unchanged`.
- `historicalplaytime.moved` gains `release: NotRequired[None]`. The
  key is present exactly when the move cleared a Release the record
  named; absent, the move cleared nothing. The projector clears the
  column only where the key is present, so no replay rule lives in the
  projector alone.
- `FINGERPRINT_VERSION` goes to 4: `CreateSession`, `DescribeSession`
  and the statement gain a field.

## Moves to another game

A Release belongs to one game, so a move to another game clears it.
It never refuses.

- `MoveSessionToPlaythrough` to a run at another game appends
  `playersession.release_changed(None)` before `moved` when the session
  names a Release.
- `MovePlaythroughToGame` appends the same event for every session of
  the run, removed ones included, that names a Release. Each record's
  `moved` carries `release: None` where the record names one.
- `MovedRun` counts the Releases cleared, read from the move's events:
  the sessions' `release_changed` and the records' `moved` that carry
  the key, removed rows included. `_move` reads the payloads, not only
  the event types. `MovedRun` gains `cleared_releases: int = 0`. Edit
  playthrough's info toast names the count beside the placeholder
  swaps.

The single-session Edit page and the session PATCH state a Release
after the move, in a `DescribeSession` of its own under the same
correlation id. The move clears the old game's Release first, so a
Release of the target game passes rule 2. The PATCH today describes
before it moves; the Release joins neither that description nor its
order. An edit that changes the device and the Release at one game is
thus two description dispatches; that is intended.

No bulk act moves a session to another game (`refuse_another_game`),
so no bulk Undo meets a cleared Release.

## Resume

`clone_session` states no Release. Device and emulated are the
person's setup; a Release is where a sitting was played.

## Reclassification

`ReclassifySessionAsHistoricalPlaytime` seeds the record form from the
session. The session's Release is the held value, so it carries without
a check; a changed one obeys the rule.

## Projection

`PlayerSession.release` and `HistoricalPlaytime.release`: nullable
foreign key to `Release`, `RESTRICT`, `related_name="+"`. Both are
registered in `AUDITED_PROJECTION_REFERENCES`. The reference kind is
`catalog.release` (`REQUIRED`), as the entry's.

## Outside dates (the before-start clause)

`outside_playthrough_dates` never matches a session that names a
Release on a `prerelease` Edition, on both halves. A session with no
Release counts as before. #1358 inherits the clause when it splits out
Before start. `outside_interval_handler` gains an `unless: Q` argument:
True compiles `outside & ~unless`, False the plain negation, so a demo
session answers False ("not outside"). `organization_counts` and the
quick facet read the same predicate.

## Surfaces

- **Session form**: a `Release` picker after Playthrough. Its
  `params` name the game field. It lists the game's Releases that the
  library holds a live copy on. A row whose every live copy is ended
  carries the latest end's way as a hint. No create row. The empty row reads "Not stated". The
  field's choices add the held value, so an edit keeps a Release whose
  copy is gone, as the record form keeps a held device. The form
  refuses a Release of another game than the one chosen.
- **Record form** (and the reclassification form): the same picker
  after Playthroughs, its game fixed.
- **Bulk Edit (sessions)**: a Release field mirroring the playthrough
  field. When the selection holds one game the picker searches that
  game; a selection over several games drops the field with the
  playthrough field. A row at another game is refused per row. ⊘
  states "No release", so this picker carries no `none_label`
  (`UnsetFieldsForm` refuses both). The Undo restates the earlier value from
  `release_changed` or `created` in a `DescribeSession` of its own,
  after the other facts, so a Release whose copy is gone since refuses
  that fact alone.
- **Search**: `GET /api/releases/search` stays Add to library's,
  over every visible Release. `GET /api/releases/held?game_id=&q=`,
  the session and record pickers' options over `held_releases`. `GET /api/releases/played?q=`, the filter
  fields' options: the Releases the library's live sessions or records
  name, so a Release whose copies are all gone stays findable. Its
  label leads with the game's name.
- **Filters**: `PlayerSessionFilter` and `HistoricalPlaytimeFilter`
  gain `release` (set over `release_id`, null "not stated") and
  `edition_kind` (choice over `release__edition__kind`, null where no
  Release is stated). Builder only; no quick facet.
- **API**: `SessionOut`, `SessionIn`, the session PATCH and
  `HistoricalPlaytimeOut` carry `release_id`, a bare key as
  `playthrough_id` is. A PATCH naming
  `release_id: null` clears it.

## Docstrings

`PlayerSessionCreatedPayload` says `release` "is reserved and always
None"; that sentence goes.

## Out of scope

- A Release column on the Playtime lists.
- Quick facets for the two filter fields.
- #1361's toggle, which reads `edition_kind` through this column.

## Follow-up issues to file

- A Release column on the Sessions and Historical lists.
- Quick facets for `edition_kind` on the Playtime lists.
