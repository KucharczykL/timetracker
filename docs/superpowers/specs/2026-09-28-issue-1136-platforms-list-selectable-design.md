# Select platforms, then edit or remove them in bulk

Issue: [#1136](https://github.com/KucharczykL/timetracker/issues/1136).
Precedents: [the Devices list](2026-09-24-issue-1135-devices-list-selectable-design.md),
[Edit many games](2026-09-28-issue-1270-bulk-game-edit-design.md).
Runner: [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md).

## Result

The person can select rows on the Platforms list. The tray has two acts,
Edit… and Remove. Edit… sets the group, the icon, or both. The ⋯ menu of
each row has Edit and Remove.

## Why a ledger

The Undo of a batch must find its act, its rows and, for an edit, the
values before the batch. A platform writes no event: the charter keeps
custom catalog records as conventional data. A projection is also not
possible, because Game, Release, ExternalReference and Purchase have a
foreign key to Platform, and one table holds shared and private
platforms. Thus a ledger records what a batch changed on a conventional
row.

## The ledger

`BatchChange` is a conventional table: `library`, `batch`, `act`,
`table` (the model label), `row_id`, `column`, `earlier` and `stated`
(JSON), `created_at`. It is unique on (`batch`, `table`, `row_id`,
`column`) and indexed on (`library`, `batch`). A purge of the library
removes it. Only conventional rows write it; an event-backed act never
does, so nothing is recorded twice.

`games/batch_ledger.py` records one change, reads the rows of a batch
for one model, reads the act of a batch, and reads the changes of one
row as `FactChange` values.

`BulkAction.undo_rows` is `EventRows(model)` or `LedgerRows(model)`.
`EventRows` derives its aggregate from the model and refuses a model
that no event type speaks about. `_act_of` reads the events first, then
the ledger. A batch in neither answers 404.

## The writes

`games/writes/platform.py` locks the row and writes its ledger rows in
the same transaction.

- Remove: a ledger row of this batch for the row means a repeated post:
  unchanged. A removed row: unchanged. Else `remove()`, and the ledger
  records `removed_at`.
- Edit: a column that this batch recorded is not written again. Each
  stated column that differs is written with `update()` and recorded. A
  row with no difference is unchanged.
- Undo, one inverse for both acts: for each recorded column, a row that
  holds the earlier value stays as it is. Else the earlier value is
  written back, also over a later change, which is logged. This is the
  rule of the event-backed Edit and Remove acts. `removed_at` goes back
  through `restore()`.

A write refuses with 409 and a sentence where the name and group would
be the same as those of a live private platform of the library or a
live shared platform: an edit of the group, a restore, and the Undo of
an edit. A name constraint from a concurrent insert gives the same
answer; any other `IntegrityError` rises as a defect.

## What every Edit act shares

`games/bulk_edit.py` holds what the Edit acts of sessions, games and
platforms share: `FactChange`, the Undo rule (`restated`,
`log_overwrite`), `keeping` for the "Keep: X" and "Keep: mixed"
placeholders, `settle_statement` (a carried statement, else the form's,
each error led by its label), `either`, and the shared sentences. The
session Edit moves to `games/bulk_session_edit.py`. Only the reading of
earlier values differs by source: session events, PlayerGame events, or
the ledger.

## The acts

`platform.remove` and `platform.edit` read the private, live rows of the
list with the filter of the statement. A key that the library does not
have is lost with `PLATFORM_GONE`.

- Remove previews Platform, Group, Games, Releases and Purchases;
  `games/reads/platform_departures.py` counts the live rows that name
  each platform, and the per-row confirmation shows the same numbers.
- Edit previews Platform, Group and Icon. `PlatformEditStatement`
  states the group (a value or none), the icon, or both; one at least.
  Group is a text box with the groups of the visible platforms as
  `<datalist>` suggestions, inside an `UnsetWidget`, whose ⊘ states no
  group. Icon is a `ChoiceSearchSelectWidget` over `PLATFORM_ICONS`, a
  declared tuple of platform icon slugs; a test holds each to a snippet.

The tray shows Edit…, then Remove. `platform_row_menu` has Edit and
Remove, labelled "`<name>` (`<group>`) actions", or "`<name>` actions"
without a group. The list has no Actions column; the column picker is
in the menu slot.

## Not in this issue

- The single-row Platform form keeps its text box for the icon.
- A picker that accepts a removed platform (#979).
- A ledger for the other removable models.
