# Select platforms, then edit or remove them in bulk

Issue: [#1136](https://github.com/KucharczykL/timetracker/issues/1136).
Precedents: [the Devices list](2026-09-24-issue-1135-devices-list-selectable-design.md),
[Edit many games](2026-09-28-issue-1270-bulk-game-edit-design.md).
Runner: [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md).

## Result

The Platforms list is selectable. The tray has Edit… and Remove. Edit…
sets the group, the icon, or both. The ⋯ menu of each row has Edit and
Remove.

## Why a ledger

An Undo must find its act, its rows and the values before the batch. A
platform writes no event: the charter keeps custom catalog records
conventional. A projection is not possible, because Game, Release,
ExternalReference and Purchase have a foreign key to Platform, and one
table holds shared and private platforms.

`BatchChange` records one field that a batch changed on a conventional
row: `library`, `batch`, `act`, `model_label`, `row_id`, `field`,
`earlier`, `stated`. It is unique on (batch, model, row, field). An
event-backed act never writes it. `games/batch_ledger.py` records and
reads it; an instant is stored as full ISO text.

`BulkAction.undo_rows` is `EventRows(model)` or `LedgerRows(model)`.
`_act_of` reads the events, then the ledger's act.

## The writes

`games/writes/platform.py` locks the row and records in the same
transaction.

- Remove: a row that this batch recorded, or a removed row, is
  unchanged.
- Edit: a field that this batch recorded, or that holds the statement,
  is not written.
- Undo, one inverse for both acts: each recorded field that does not
  hold its earlier value gets it back, also over a later change, which
  is logged. This is the rule of the Games, session and Remove Undos.
  An edit's Undo refuses a removed platform. The Undo records its own
  writes, so a repeated post skips them.

A write refuses at 409 where the name and group would match a live
private platform of the library or a live shared one. A name
constraint from a concurrent insert gives the same answer; another
`IntegrityError` is a defect.

## What the Edit acts share

`games/bulk_edit.py` holds the "Keep:" placeholder, the decode of a
carried statement, the guard of a missing choice, the form refusal,
and the Undo's restate and overwrite log. It imports no act, because
the act table imports every act. `FactChange` is in
`games/reads/fact_change.py`. The session Edit is
`games/bulk_session_edit.py`.

## The acts

Both read the live private rows of the list with the statement's
filter.

- Remove previews the games, releases and purchases that name each
  platform (`games/reads/platform_departures.py`); the per-row
  confirmation shows the same numbers.
- Edit previews Platform, Group and Icon. Group is a text box with the
  groups the library sees as a `<datalist>`, and ⊘ for no group.

## The icon picker

`PLATFORM_ICONS` names each icon a platform may take. `IconPicker` is a
`<drop-down>` whose trigger shows the icon and its name, and whose
panel is a grid of native radios, one tile an icon, named for screen
readers and on hover. The `choice-grid` behavior focuses the checked
tile on open, reflects the arrow keys' choice on the trigger, and
closes on a click, Enter or Space. The bulk Edit leads with a Keep
tile; the Platform form starts on the platform's icon and keeps an
older slug pickable.

## Not in this issue

- A picker that accepts a removed platform (#979).
- The ledger for other removable models.
