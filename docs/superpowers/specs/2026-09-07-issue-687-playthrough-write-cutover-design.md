# Switch lifecycle writes to Playthrough commands

Issue [#687](https://github.com/KucharczykL/timetracker/issues/687). The model
is [the PlayerGame write path](2026-08-28-issue-677-playergame-write-cutover-design.md).

Every request path that records a run states Playthrough commands. No request
writes `games_playevent`. The legacy table is still read, so a run stated here
reaches no screen until #1012 through #1015.

## The act rule

A legacy row means a completed run. Each write states both acts. An act takes
the day the person gave, at day precision, and is stated with no day where the
person gave none.

## The write path

`games/writes/playthrough.py` takes an actor and raises.
`games/views/playthrough_writes.py` takes a request and toasts. Both wrap
`answered("playthrough")`. One request states one correlation id.

A write reads the game's live ordinary runs first, through
`games/reads/playthrough_runs.py`. Exactly one run that states no act receives
the acts and the note. Every other shape creates a run. #679 states such a run
when a library tracks a game, and a first write fills it in.

`CreatePlaythrough` states a whole run in one build: the creation, the note,
the start, the completion. One build, because a creation that commits before a
failed start leaves a run `RemovePlaythrough` refuses to remove.

A run that already exists takes three statements: `DescribePlaythrough` for a
different note, then the start, then the completion. An unstated endpoint takes
`StartPlaythrough` or `CompletePlaythrough`; a stated one takes a correction,
carrying the endpoint's own note beside the day. Each command answers
`Unchanged` for state the run holds, so a second submit finishes a submit that
failed midway.

No command withdraws a stated act, so the write path refuses a reversed pair
before it states anything. A race that chose the wrong command reads the run
again. `PlayerGameNotTracked` calls `track_game` and runs the whole branch
again, because `TrackGame` states a run of its own. One retry each.

## Removal

The remove view is one `confirm_and_apply` call that states
`RemovePlaythrough`, and writes no `removed_at` on the legacy row. The command
refuses the last live ordinary run of a tracked game. A person who wants that
run gone removes the game.

## The bridge to a legacy row

`games/reads/playthrough_provenance.py` maps a legacy row id to its run, from
`source_metadata.play_event_id` on the conversion's creation events. The map is
partial: a default run names no row. A test holds its four callers to four, and
a row that maps to no run is refused. #771 takes the module with the table.

## Surfaces

| surface | behaviour |
|---|---|
| add view, add-for-game, `POST /api/playthrough` | adopt, else `CreatePlaythrough`; the API answers 204 |
| edit view, `PATCH /api/playthrough/{id}` | the three difference statements |
| remove view, `DELETE /api/playthrough/{id}` | `RemovePlaythrough` |
| `GET /api/playthrough`, and by id | the legacy row, until #1015 |

The form is a plain `Form`, and a posted change of game is a field error. Game
detail states no run inline; #1024 owns stating a count.

## Names

Every identifier that does not derive from the model's own name reads
`playthrough`: the view module, five routes and their paths, the form, the API
prefix and its schemas, `parse_playthrough_filter`, the `playthrough_count` and
`playthrough_filter` criterion keys, the sorts, and the `playthroughs` mode
key. `PlayEventFilter`, the singular key `playevent` and
`related_name="playevents"` wear the model's own name and wait for #771.

Migration `0046_playthrough_preset_mode` carries the `AlterField` the mode key
forces, and rewrites the saved presets: the mode, and the two criterion keys at
any depth.

## Refusals

Five reach a person: a reversed pair of endpoints; the removal of a game's last
live ordinary run; a changed game on an edit; an act under a removed game or
run; an act on a legacy row that maps to no run. Each answers as a toast, as
the confirmation page, or as a 409.

## Rollback

The write path appends events only. Reversal is the projection rebuild
[#667](2026-08-25-issue-667-shadow-rebuild-design.md) provides. The preset
migration reverses by the inverse rewrite.
