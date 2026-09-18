# Reclassify a session as historical playtime

A library can write a duration into a session row. Sometimes that number is not
a sitting. It is a total that the library remembers or reads from a launcher.
This act moves such a row to a historical playtime record.

The code is in `games/commands/session_reclassification.py`.

## The act

`ReclassifySessionAsHistoricalPlaytime` takes a session and a statement. It
answers two events: `library.historicalplaytime.created` and
`library.playersession.reclassified`.

One command answers both events. Two dispatches are two transactions. If the
second transaction fails, the record and the session both state the same hours,
and the totals count them twice.

`statement_from_session` reads the statement that a session already holds. It
reads `effective_duration` and `effective_day`, because those are the columns
that the read layer counts. A Corrected row thus states its override, not its
elapsed time. Provenance is the one item that no session holds, so the caller
states it.

The command refuses a running Timed row. It refuses a playthrough of a
different game. It refuses a device that is not live, unless the session
already holds that device. A library that stops the use of a device removes it,
and the rows recorded on that device must still convert.

## The undo

`UndoSessionReclassification` removes the record and restores the session. It
answers `Unchanged` when the session is live and the record is removed. It
appends each event only when that event is still necessary.

## Storage

`PlayerSession.reclassified_into` refers to the record. The mark is
`removed_at`, which the reclassification sets. The act adds a reference. It
does not add a second mark, because each scope that hides a removed session
reads the one mark.

The reference stays after a restore. Because of it, the two rows refuse to be
live at the same time: `RestoreSession` refuses while the record is live, and
`RestoreHistoricalPlaytime` refuses while the session is live. Each refusal is
after the command's own `Unchanged`.

The payload holds the record as a bare key. The record does not exist when the
command builds the payload. One lock covers both events, so the same act mints
the key and states it.

## Screens

A written-down session row shows **Was an estimate**. It opens the historical
playtime form, seeded from the session.

The session list shows a link to the written-down rows of eight hours or
longer. A confirmation page lists each of those rows and converts them in one
request. Each row has its own idempotency key. A refused row does not stop the
other rows.

The link needs `is at least` on a leaf number field. `Modifier.for_numbers` is
the one location for the operators that a number or a date permits.

## What moves

Each playtime total stays the same. A record that states one day is inside each
period that the session was inside.

The session figures change: the count, the distinct days, the longest session,
the highest average, and the first play. A run whose only session converts
reads `Never played`.
