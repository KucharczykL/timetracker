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
before it states anything. The two endpoints are then stated one at a time, so
in between the run holds one new day beside one old one, and the wrong order
reverses that pair. `_statement_order` picks the order that does not: the
completion first for a run moved wholly later, the start first otherwise. Only
one of the two orders can reverse, because both would need the draft itself
reversed, and that was refused already.

The choice between a first statement and a correction is read before dispatch
takes its lock, so a racer who states the endpoint first turns it stale. That
refusal rises rather than being retried: reading the run again and correcting
instead would overwrite the day the racer stated and answer this person
success.

`PlayerGameNotTracked` is the one retry. The write path raises it itself when
no `PlayerGame` row stands, rather than leaving the absent row to the command:
a game tracked between the read and the dispatch would let a creation through,
leaving the new run beside the empty one that tracking just made. The caller
calls `track_game` and runs the whole branch again, because `TrackGame` states
a run of its own, and answers `RecordedRun(tracked_the_game=True)` so the
request-shaped caller tells the person their library now tracks the game.
Dispatch refuses to nest, so no transaction spans the two: a refusal after
tracking leaves the game tracked with no run stated, and stating it again
finishes it.

## Removal

The remove view is one `confirm_and_apply` call that states
`RemovePlaythrough`, and writes no `removed_at` on the legacy row. The command
refuses the last live ordinary run of a tracked game. A person who wants that
run gone removes the game.

## The bridge to a legacy row

`games/reads/playthrough_provenance.py` maps a legacy row id to its run, from
`source_metadata.play_event_id` on the conversion's creation events. The map is
partial: a default run names no row. A test holds its two reading modules to
two, and a row that maps to no run is refused. #771 takes the module with the
table.

`run_for_row` answers a `ConvertedRun`, which tells the two ways to hold no run
apart. No creation event names the row is ordinary — the conversion skipped a
game the library no longer tracks — and says so. An event that names a run this
library cannot read is drift, from a lagging projection, a rebuild mid-swap, or
the ownership `audit_library_ownership` reports; it is logged at error and
answered in its own words. A doubled conversion is logged the same way, and the
first run wins.

The two request paths state whole days, so both seed themselves from the run
through `restatable_days` in `games/reads/playthrough_endpoints.py`, never from
the legacy row: nothing writes that row any more, so a second edit seeded off
it would put the frozen day back over what the first edit stated. The read
answers nothing where either endpoint states a value a day cannot hold — a
month, a decade, a range, a qualified day — and both surfaces refuse rather
than flatten it. #1015 owns the screen that states the richer value.

## Surfaces

| surface | behaviour |
|---|---|
| add view, add-for-game, `POST /api/playthrough` | adopt, else `CreatePlaythrough`; the API answers 204 |
| edit view, `PATCH /api/playthrough/{id}` | the three difference statements |
| remove view, `DELETE /api/playthrough/{id}` | `RemovePlaythrough` |
| `GET /api/playthrough`, and by id | the legacy row, until #1015 |

The form is a plain `Form`, and a posted change of game is a field error. Its
note carries no length cap: the 255 came from the legacy column, and
`Playthrough.note` is a `TextField`. Game detail states no run inline; #1024
owns stating a count.

## Names

Every identifier that does not derive from the model's own name reads
`playthrough`: the view module, five routes and their paths, the form, the API
prefix and its schemas, `parse_playthrough_filter`, the `playthrough_count` and
`playthrough_filter` criterion keys, the sorts, and the `playthroughs` mode
key. `PlayEventFilter`, the singular key `playevent` and
`related_name="playevents"` wear the model's own name and wait for #771.

Migration `0046_playthrough_preset_mode` carries the `AlterField` the mode key
forces, and rewrites the saved presets: the mode, and the two criterion keys at
any depth. It prints how many of how many it rewrote, so an operator can tell a
run that touched nothing from one against the wrong database.

A `?filter=` blob outlives the rename that broke it, and no migration reaches a
bookmark or a mailed link. `OperatorFilter.renamed_fields` maps an old
criterion key forward at the top of `from_json`, logging a warning; without it
the renamed criterion is dropped and the page answers with more rows than it
was asked for. `GameFilter` names both keys. A blob holding both spellings
keeps the current one. #771 takes the table away.

## Refusals

Six reach a person: a reversed pair of endpoints; the removal of a game's last
live ordinary run; a changed game on an edit; an act under a removed game or
run; an act on a legacy row that maps to no run; and an edit of a run stating a
date this day-shaped form cannot hold. Each answers as a toast, as the
confirmation page, or as a 409.

## Rollback

The write path appends events only. Reversal is the projection rebuild
[#667](2026-08-25-issue-667-shadow-rebuild-design.md) provides. The preset
migration reverses by the inverse rewrite.
