# Reclassify a session as historical playtime

A library can write a duration into a session row. Sometimes that number is a
total, not a sitting. This act moves such a row to a historical playtime
record. The code is in `games/commands/session_reclassification.py`.

## The act

`ReclassifySessionAsHistoricalPlaytime` takes a session and a statement. It
answers two events under one lock: `library.historicalplaytime.created`, which
carries the session as a bare `reclassified_from` key, and
`library.playersession.reclassified`, which projects `removed_at` alone. Two
dispatches would be two transactions, and a failure between them lets the
totals count the same hours twice.

`statement_from_session` reads `effective_duration` and `effective_day`, the
columns the read layer counts; the caller states the provenance. The statement
names its own playthroughs, so a bucket session converts onto an ordinary run.

The command refuses a running Timed row, a playthrough of another game, a
device that is not live unless the session holds it, and a session a live
record was made from, each in its own words. Both live is drift, answered as a
defect.

## The invariant

A session and every record made from it are one fact; at most one is live.
The reference lives on the record, `HistoricalPlaytime.reclassified_from`: one
session can become a record more than once, and a column on the session would
hold only the latest link. `RestoreSession` refuses while a record from the
session is live; `RestoreHistoricalPlaytime` while the session is, or another
record from it. A partial unique index stands behind the three. Every guard is
scoped to the library and resolves the row it names.

## The undo

`UndoSessionReclassification` decides by the marks, in order: no record ever
made from the session, refused; none live and the session live, `Unchanged`;
the live record restated since, which `restated_at` marks, refused whole, since
refusing one leg would leave both live; the session marked after its last
record was, refused, since the act marks the session before its record can be
and a later mark is another act's; a removed parent, refused. Past those it
removes the live record, if one, and restores the session. The route says which
happened, because `Unchanged` raises nothing.

## Screens

A written-down session row shows a history icon that opens the historical
playtime form, seeded from the session. The form requires a playthrough, offers
the game's ordinary runs, never the bucket, and keeps a session's seconds when
the minutes are unchanged, as it does a record's.

The Library page's Playtime section says what a written-down session is and
how many wait: live Duration-only rows of eight hours or longer on an ordinary
run. One control opens the session list narrowed to them; one opens a
confirmation that converts them in one request.

The confirmation converts the posted keys the review names now. Every other
key is left alone with the sentence true of it: not available, already
recorded, in the bucket, measured, or under the threshold. The denominator is
the distinct keys sent; every key left alone is logged with its library and
correlation id, since the page prints sentences, not keys. A defect stops the
loop and answers with its own status on a page with no submit: the rows before
it are recorded, and no sentence can say what to state instead. The page
offers no Undo; #1123 owns that.

## Dates

`Modifier.for_numbers` holds `GREATER_THAN_OR_EQUAL` and `LESS_THAN_OR_EQUAL`;
`for_dates` does not, and no date handler compiles them: a date widget is two
boxes, and neither emits nor carries back the pair. A start box alone compiles
to `after`, which excludes its day; #1124 owns that.

## What moves

Every playtime total stays the same: a record stating one day is inside each
period the session was. The playthrough page's range sum and the game list's
filtered-playtime column read sittings alone and fall. The session figures
change: count, distinct days, longest, highest average, busiest game, first and
last play.
