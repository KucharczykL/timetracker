# Reclassify a session as historical playtime

> This spec is 530 words. The band is 200 to 500. The overrun is an explicit
> exception for this document, accepted on review: it holds one act, one
> invariant, one undo with five rules, and a bulk screen, and each is a rule
> the code keeps. It is not a loosening of the band.

A written duration in a session row is sometimes a total, not a sitting. This
act, in `games/commands/session_reclassification.py`, moves the row to a
historical playtime record.

## The act

`ReclassifySessionAsHistoricalPlaytime` takes a session and a statement. It
answers two events under one lock: `library.historicalplaytime.created`, which
carries the session as a bare `reclassified_from` key, and
`library.playersession.reclassified`, which projects `removed_at` alone. Two
dispatches could count the hours twice.

`statement_from_session` reads `effective_duration` and `effective_day`; the
caller states the provenance. The statement names its own playthroughs, so a
bucket session converts onto an ordinary run.

The command refuses a running Timed row, a playthrough of another game, a
device that is not live unless the session holds it, and a session a live
record was made from. A live session beside a live record is a defect.

## The invariant

A session and every record made from it are one fact. At most one is live.
The reference is on the record, `HistoricalPlaytime.reclassified_from`: one
session can become a record more than once. `RestoreSession` refuses while a
record from the session is live. `RestoreHistoricalPlaytime` refuses while the
session is live, or another record from it is. A partial unique index stands
behind the three. Every guard is scoped to the library.

## The undo

`UndoSessionReclassification` decides by the marks, in this order:

- No record was made from the session: refused.
- No record is live and the session is live: `Unchanged`.
- The live record was restated, which `restated_at` marks: refused whole, as
  one refused leg leaves both live.
- The session was marked after its last record: refused. The act marks the
  session first, so a later mark is another act's.
- A parent is removed: refused.

Past those it removes the live record, if any, and restores the session.

## Screens

A written-down session row shows a history icon. It opens the historical
playtime form, seeded from the session. The form requires a playthrough,
offers only ordinary runs, and keeps a session's seconds when the minutes are
unchanged.

The Library page's Playtime section counts the written-down sessions that
wait: live Duration-only rows of eight hours or longer on an ordinary run. One
control opens the session list narrowed to them; one opens a confirmation that
converts them in one request.

The confirmation converts the posted keys the review names now. Every other
key is left alone with the sentence true of it: not available, already
recorded, in the bucket, measured, or under the threshold. The denominator is
the distinct keys sent; each key left alone is logged with its library. A
defect stops the loop and answers on a page with no submit. The page offers no
Undo; #1123 owns that.

## Dates

`Modifier.for_numbers` holds `GREATER_THAN_OR_EQUAL` and `LESS_THAN_OR_EQUAL`.
`for_dates` does not: a date widget is two boxes, and neither emits nor reads
the pair. A start box alone excludes its day; #1124 owns that.

## What moves

Every playtime total stays the same: a record stating one day is inside each
period the session was. The playthrough page's range sum and the game list's
filtered-playtime column read sittings alone and fall. The session figures
change.
