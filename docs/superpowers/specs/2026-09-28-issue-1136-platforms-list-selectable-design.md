# Select platforms and remove them in bulk

Issue: [#1136](https://github.com/KucharczykL/timetracker/issues/1136).
Precedent: [the Devices list](2026-09-24-issue-1135-devices-list-selectable-design.md).
Runner: [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md).

## Result

The person can select rows on the Platforms list. The tray has one act,
Remove. The ⋯ menu of each row has Edit and Remove.

## Why the stamp names the batch

The Undo of a batch must find its act and its rows. A platform writes
no event: the charter keeps custom catalog records as conventional
data. A projection is also not possible, because Game, Release,
ExternalReference and Purchase have a foreign key to Platform, and one
table holds shared and private platforms. Thus the removal stamp names
the batch.

## The column

`Platform.removed_in_batch` holds the correlation id of the batch that
last removed the row.

- `remove(row, batch=…)` writes it with `removed_at`. A removal outside
  a batch writes NULL, thus an earlier batch does not claim the row.
- `restore()` keeps it. An Undo after a restore by hand finds the rows
  and answers "already so".
- A model without the column refuses `batch` with `TypeError`.

## The runner

`BulkAction.undo_rows` tells the Undo where to read rows:

- `EventRows(aggregate, model)` reads the events of the batch.
- `StampedRows(model)` reads the rows whose stamp names the batch.

A declaration with a `StampedRows` model that has no column is
refused. `_act_of` reads the events first. For a batch without events,
it finds the `StampedRows` act that has a row of the batch, or answers
404.

## The writes

`games/writes/platform.py` locks the row and acts only on the state it
expects:

- Remove: a live row becomes removed with this batch. A live row that
  names this batch stays live: a person restored it, and a chunk that
  comes again must not remove it a second time.
- Restore from the batch: a removed row of this batch becomes live.
  Other rows stay as they are.

A restore refuses with 409 and a sentence when a live private platform
of the library, or a live shared platform, has the same name and
group. An `IntegrityError` from a concurrent insert gives the same
answer in a savepoint, thus the batch continues. The per-row restore
route uses the same refusal.

A chunk of an Undo that comes again counts its rows as "already so",
because the stamp cannot tell this Undo from a restore by hand.

## The act and the page

`REMOVE_PLATFORM` (`platform.remove`) reads the private, live rows of
the list with the filter of the statement. A key that the library does
not have is lost with `PLATFORM_GONE`. The preview shows Platform,
Group, Games, Releases and Purchases; `games/reads/platform_departures.py`
counts the live rows that name each platform, and the per-row
confirmation shows the same numbers.

`platform_row_menu` has Edit and Remove. Its label is
"`<name>` (`<group>`) actions", or "`<name>` actions" without a group.
The list has no Actions column; the column picker is in the menu slot.

## Not in this issue

- A bulk act that changes the group or the icon.
- A picker that accepts a removed platform (#979).
- `removed_in_batch` on the other removable models.
