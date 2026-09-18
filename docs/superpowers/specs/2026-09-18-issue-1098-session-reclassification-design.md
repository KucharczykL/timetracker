# Reclassify a session as historical playtime

A library can write a duration into a session row. Sometimes that number is not
a sitting. It is a total that the library remembers or reads from a launcher.
This act moves such a row to a historical playtime record.

The code is in `games/commands/session_reclassification.py`.

## The act

`ReclassifySessionAsHistoricalPlaytime` takes a session and a statement. It
answers two events: `library.historicalplaytime.created` and
`library.playersession.reclassified`.

One command answers both events. Two dispatches are two transactions, and a
failure between them lets the totals count the same hours twice.

`statement_from_session` reads the statement that a session already holds. It
reads `effective_duration` and `effective_day`, because those are the columns
that the read layer counts. Provenance is the one item that no session holds,
so the caller states it.

The command refuses a running Timed row, and a playthrough of a different game.
It refuses a device that is not live, unless the session already holds that
device: a library that stops the use of a device removes it, and those rows
must still convert.

It refuses a session that a live record already came from. Without that refusal
the same hours reach two records.

The statement names its own playthroughs. They are not read from the session,
so a session in the imported-history bucket converts when the statement names
one of the game's ordinary runs. The bucket itself takes no stated playtime and
is refused, with a sentence that names the remedy.

## The undo

`UndoSessionReclassification` removes the record and restores the session. It
finds the record by a query, not by a column on the session.

It answers `Unchanged` before each refusal, as every other lifecycle command
does. It is `Unchanged` in exactly one state: no record from the session is
live **and** the session is live. That is the end state the undo asks for, so a
second press changes nothing. A session that a plain removal took, and that no
live record came from, is refused rather than restored: this route undoes one
act, and a general restore of any removed session is `RestoreSession`'s. The
route says which of the two happened, because `Unchanged` raises nothing and a
restore message printed over it would report a restore that did not occur.

It refuses when a live record from the session was restated after the act,
which `HistoricalPlaytime.restated_at` marks. An undo puts things back.
Removing a record that a person has since edited is a surprise, not a reversal,
so the person removes it themselves. **The refusal is of the whole command, not
of one leg.** Refusing only the leg that removes the record would restore the
session beside a live record, which is the double count the invariant forbids.
A record the person already removed holds no mark to refuse on and does not
block the session's return.

The marker is a column because nothing else can answer the question. The
projector overwrites every stated column on a restatement, so the row cannot be
compared against what the act created, and no command reads the event history.
A statement rebuilt from the session would be wrong in any case: a session in
the bucket states a different run on purpose.

It refuses under a removed game and a removed playthrough, as `RestoreSession`
does. A restored session under a removed parent is a row no scope can reach.

Past those refusals, it appends each event only where that event is still to
happen: a record already removed takes no second removal.

## Storage

`HistoricalPlaytime.reclassified_from` refers to the session, and
`HistoricalPlaytime.restated_at` marks a record a person changed after the act.
The session keeps `removed_at` and gains no column.

`library.playersession.reclassified` stays, and it projects `removed_at` alone.
The event is what says why the mark is there, which a plain removal does not.
The act's own reference belongs to the row the act created, not beside the
mark.

This reverses what two committed documents say, and both are amended with it.
The naming rule in `docs/event-retention.md` argues for the reference beside
the mark on the session; the paragraph that does so is rewritten to the rule
below it. The `HistoricalPlaytime` contract lists the row's columns, says the
created and restated payloads share one statement whole, counts the audited
foreign keys, and enumerates what a restore refuses; each of those four is
restated there.

The branch already carries a migration for a column on the session. That
migration is not on the main branch, so it is rewritten rather than reversed by
a second one. A working copy that applied it migrates back to `0010` first.

The record holds the reference, because one session can become more than one
record over time. A column on the session holds only the most recent link, so a
second act makes the earlier record unreachable, and a guard that reads that
column goes blind to it. The record's own reference cannot be overwritten.

A session and every record made from it are one fact. **At most one of them is
live.** Three commands keep that invariant, each after its own `Unchanged`:

- `ReclassifySessionAsHistoricalPlaytime` refuses while a record from the
  session is live.
- `RestoreSession` refuses while a record from the session is live.
- `RestoreHistoricalPlaytime` refuses while the session is live, **and while
  another record from the same session is live**. The second half is what a
  pairwise rule misses: a session converted twice leaves two records, and
  restoring the earlier one must not put two live records on one session's
  hours.

Every one of those queries is scoped to the library. A record of another
library naming this session is drift, which the ownership audit reports; no
command reads outside its own scope to find it.

The created event carries the session as a bare key. It is not part of the
statement, which `created` and `restated` share, so a restatement neither
states it nor clears it, and an event already recorded without it stays valid.
One lock covers both events.

## Screens

A written-down session row shows a history icon. Its tooltip says that the row
was an estimate and what the act does. It opens the historical playtime form,
seeded from that session.

The form offers the game's ordinary runs, never the bucket. A session in the
bucket is seeded with a run the form does not offer, so nothing is selected and
the person states which run the hours belong to. The field is required, so an
unanswered form is a field error that names the field, rather than a command
refusal that names neither the field nor the bucket.

The form and the bulk act state one duration for one session. The form's
inputs show whole minutes, so it keeps the seconds the session holds when those
minutes are unchanged. It does this for a record today and must do it for a
session.

The Library page has a Playtime section. It says in plain words what a
written-down session is, what the move does, and how many sessions wait. One
control opens the session list narrowed to those rows. One opens a
confirmation page.

The confirmation page lists each row and converts them in one request. It
parses each posted key and drops what it cannot read. A key that names a live
row of this library which the review does not name is refused, not converted,
with a sentence saying the row's time was measured rather than written down:
this act converts what the review offers and nothing else, though the command
itself admits a finished measured row. It reports how many of the keys **the
person sent** were recorded, so a row that another act removed in the meantime
is counted as lost, and it says what each refusal was. A refusal does not stop
the other rows. A defect stops the request and answers
with the defect's own status, because a defect is not a refusal and no retry of
it can succeed. The boundary answers a defect as a
`CommandFailed` like any other, so the loop tells the two apart by status code,
not by type. The page that answers a defect states how many rows were recorded
before it, and offers no button to try again: each row is its own transaction,
so the rows before the defect are recorded and a second submit would act on a
different set. The confirmation page has no such variant today and gains one;
its ordinary shape always renders the confirm button.

Each refused row is written to the log with its key, its library and the
request's correlation id. The page states sentences, not keys, so the log is
the only record of which row each sentence was about.

The confirmation page offers no Undo. Issue #1123 owns that.

## Greater-or-equal

`Modifier.for_numbers` gains `GREATER_THAN_OR_EQUAL` and `LESS_THAN_OR_EQUAL`.
Every handler that serves a number field compiles both.

`Modifier.for_dates` does not offer them, and no handler that serves a date
criterion compiles them. This restores what a date leaf accepted before this
change; the two members reached dates only because `for_dates` returns
`for_numbers`.

A date criterion has no control for choosing a comparison. Its widget is a
start box and an end box, and the comparison follows from which boxes hold a
date. A member the widget cannot emit is one a person can only reach by writing
`?filter=` JSON, and neither widget carries it back: the quick bar renders `on
or before` into the start box and reads a filled start box back as `after`,
while the nested builder's date leaf leaves both boxes blank for a member it
does not know and prunes the leaf.

This forecloses one thing, and the foreclosure is deliberate. A start box alone
compiles to `after`, which excludes the start day, while a start and an end
compile to a range that includes it. `GREATER_THAN_OR_EQUAL` is the honest
spelling for that box. Issue #1124 owns the repair, which is a change to what
the widget emits and to how both sides hydrate it, not to this act.

A field comparison between two date columns is a different leaf with its own
modifier control, and it keeps both members.

## What moves

Each playtime total stays the same. A record that states one day is inside each
period that the session was inside.

Two rendered figures read the tracked half alone and do fall by the session's
hours: the playthrough page's range sum, which takes only sittings on purpose,
and the game list's filtered-playtime column, which counts the sessions a
filter matched. Neither is a total.

The session figures can change: the count, the distinct days, the longest
session, the highest average, the busiest game, and the first and last play.
