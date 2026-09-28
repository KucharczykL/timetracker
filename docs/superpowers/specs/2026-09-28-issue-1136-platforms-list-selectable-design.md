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
`model_label`, `row_id`, `field`, `earlier` and `stated` (JSON through
`DjangoJSONEncoder`; each field has one decoder), `created_at`. It is
unique on (`batch`, `model_label`, `row_id`, `field`) and indexed on
(`library`, `batch`). A purge of the library removes it. Only
conventional rows write it; an event-backed act never does, so nothing
is recorded twice. The ledger replaces the earlier removal stamp
(`removed_in_batch`), and its migration replaces that stamp's, which no
deployment ran.

`games/batch_ledger.py` records one change, reads the rows of a batch
for one model, reads the act of a batch, and reads the changes of one
row as `FactChange` values.

`BulkAction.undo_rows` is `EventRows(model)` or `LedgerRows(model)`.
`EventRows` derives its aggregate from the model and refuses a model
that no event type speaks about. `_act_of` reads the events first, then
the act of the ledger's first row of the batch; a name the table does
not declare answers `UNKNOWN_ACT`, as for events. A batch in neither
answers 404.

## The writes

`games/writes/platform.py` locks the row and writes its ledger rows in
the same transaction.

- Remove: a ledger row of this batch for the row means a repeated post:
  unchanged. A removed row: unchanged. Else `remove()`, and the ledger
  records `removed_at`.
- Edit: a field that this batch recorded is not written again. Each
  stated field that differs is written with `update()` and recorded. A
  row with no difference is unchanged.
- Undo, one inverse for both acts: for each recorded field, a row that
  holds the earlier value stays as it is. Else the earlier value is
  written back, also over a later change, which is logged. This is the
  rule of the Games and session Edit Undos and of the Remove Undos; the
  playthrough acts, which refuse a change since, are the exception.
  `removed_at` goes back through `restore()` whenever the row is
  removed. The Undo of an edit refuses a platform that is removed now,
  after the unchanged check, with `PLATFORM_REMOVED`, as the Games Edit
  refuses a removed game.
- The Undo records its own writes in the ledger under its own batch and
  the act name `<act>.undo`, which no table declares. Thus a repeated
  post of an Undo chunk skips the fields that it wrote, and an Undo
  offers no Undo.

A write refuses with 409 and a sentence where the name and group would
be the same as those of a live private platform of the library or a
live shared platform: an edit of the group, a restore, and the Undo of
an edit. A name constraint from a concurrent insert gives the same
answer; any other `IntegrityError` rises as a defect.

## What every Edit act shares

The session Edit moves to `games/bulk_session_edit.py`, beside
`bulk_game_edit.py` and `bulk_platform_edit.py`. `games/bulk_edit.py`
then holds what they share, and imports nothing that the foot of
`games/bulk_actions.py` imports:

- `keeping`, the "Keep: X" and "Keep: mixed" placeholder, generic in
  the row;
- the decode of a carried statement (JSON, an object, no unknown key)
  and `STATEMENT_UNREADABLE`;
- the guard of a run that has no settled choice (`RowUnreadable`);
- `form_refusal`, a form's first error led by its label, for the Games
  and platform Edits; the session Edit keeps its bare sentences;
- `restated` and `log_overwrite`, for the Games and platform Undos; the
  session Undo gives every earlier value to `DescribeSession`, which
  compares them.

`FactChange` moves to `games/reads/fact_change.py`, so a read does not
depend on a bulk module. `RowOutcome.either` replaces the session
Edit's `_either`. Each act keeps its own settle, its checks and its
sentences.

## The acts

`platform.remove` and `platform.edit` read the private, live rows of the
list with the filter of the statement. A key that the library does not
have is lost with `PLATFORM_GONE`.

- Remove previews Platform, Group, Games, Releases and Purchases;
  `games/reads/platform_departures.py` counts the live rows that name
  each platform, and the per-row confirmation shows the same numbers.
- Edit previews Platform, Group and Icon. `PlatformEditStatement`
  states the group (a value or none), the icon, or both; one at least.
  Group is a `DatalistTextInput`, a text box with a `<datalist>` of the
  distinct groups of the live platforms the library sees (its own and
  the shared ones), inside an `UnsetWidget`, whose ⊘ states no group. Icon is a
  `ChoiceSearchSelectWidget` over `PLATFORM_ICONS`, a declared tuple of platform icon slugs; a test holds each to a snippet.

The tray shows Edit…, then Remove. `platform_row_menu` has Edit and
Remove, labelled "`<name>` (`<group>`) actions", or "`<name>` actions"
without a group. The list has no Actions column; the column picker is
in the menu slot.

## Not in this issue

- The single-row Platform form keeps its text box for the icon.
- A picker that accepts a removed platform (#979).
- A ledger for the other removable models.
