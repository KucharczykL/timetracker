# Sessions before their playthrough's start

Issue #1358.

## Two questions

A session proves that its run started. A session dated before the run's start
is a contradiction. One of these is true:

- The session belongs to an earlier run that nobody recorded.
- The session's day is wrong.
- The run's start is wrong.

A completion states that the main objective was completed. It does not state
that the run ended. Play after the completion is post-game play on the same
run. That row is correct.

## The fields

`PlayerSessionFilter` has two `BoolCriterion` fields:

| Field | Label | True selects |
|---|---|---|
| `before_playthrough_start` | Before start | `effective_day < playthrough__started_lower` |
| `after_playthrough_completion` | After completion | `effective_day > playthrough__completed_upper` |

Both use `beyond_bound_handler` in `common/criteria.py`. False is the plain
negation. Django guards a negated column comparison with `IS NOT NULL`, so a
run without that bound answers False. An open start has no lower bound and
flags nothing. A bound is the widest day the endpoint permits.

Both fields pass `unless=PRERELEASE_PLAY`. Demo play is not the run's play.
Thus the count does not change with `SHOW_PRERELEASE_PLAY`.

A session read in a zone east of the run's zone can flag by one day. This is
accepted. A wider bound would hide a real one-day contradiction.

The old key `outside_playthrough_dates` is refused, not renamed. It maps onto
two keys with a different meaning.

Both fields are quick facets.

## The Library page

The Playtime section counts Before start only. The card links to the session
list with `sort=playthrough`, so the rows of one game sit together.

A paragraph after the card gives three remedies, in this order:

1. Earlier attempt: select one game's sessions, choose Edit, and create a new
   playthrough. Bulk Edit moves one game at a time.
2. Wrong session day: correct the session.
3. Wrong start: correct the start on the game's page.

No new bulk act exists. Nothing in a row tells which cause applies.

A demo session that names no Release counts. Its remedy is bulk Edit's Release
field. The field offers only Releases the library holds a copy of.

"Nothing to review" shows only when no card shows.

## Out of scope

- A per-run mark that post-game play was reviewed.
- A tolerance of N days.
- A link from a session's Playthrough cell to its run.
