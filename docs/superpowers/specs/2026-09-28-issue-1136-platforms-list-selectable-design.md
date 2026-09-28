# Select platforms and remove them in bulk

Issue: [#1136](https://github.com/KucharczykL/timetracker/issues/1136).
Precedent: [the Devices list](2026-09-24-issue-1135-devices-list-selectable-design.md).
Runner: [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md).

## Result

The person can select rows on the Platforms list. The tray has one act,
Remove. The ⋯ menu of each row has Edit and Remove. The Actions column
is gone.

## Why a platform needs a new Undo source

The Undo of a batch finds its act and its rows in the events of the
batch. A platform has no events. The charter keeps "shared platform
definitions" and "custom catalog records" as conventional data. A
device crossed the boundary (#1274) because it has an ownership
lifecycle. A platform has no lifecycle.

A Platform aggregate is also not possible without a split. One table
holds shared platforms (`library IS NULL`) and private platforms. Game,
Release, ExternalReference and Purchase are conventional rows with a
foreign key to it. A conventional row must not have a foreign key to a
projection row.

Thus the removal stamp states the batch.

## The column

`Platform.removed_in_batch` is a nullable UUID. It holds the correlation
id of the batch that last removed the row. The migration adds it with
no backfill.

- `remove(instance, *, batch=None)` in `games/removal.py` writes the
  column in the same `UPDATE` as `removed_at`. A removal outside a batch
  writes NULL. Thus an earlier batch does not claim a row that a later
  act removed.
- `restore()` does not change the column. The row still names the batch
  that last removed it.
- `remove()` with `batch` on a model without the column raises
  `TypeError`.

Only Platform has the column. Another conventional list that gets a
bulk act adds it with one migration.

## The runner

`BulkAction` replaces `inverse_aggregate` and `inverse_model` with one
value, `undo_rows`:

- `EventRows(aggregate, model)` — the Undo reads
  `batch_aggregate_ids`. Every act before this issue uses it.
  `__post_init__` keeps its two checks on it.
- `StampedRows(model)` — the Undo reads
  `model.objects.filter(library=library, removed_in_batch=batch)`.
  `__post_init__` refuses a model without `removed_in_batch`.

`_act_of` reads the events first. If the batch has no events, it asks
each `StampedRows` act for a row of the library with that batch. It
answers 404 if no row has it. A batch that the person restored by hand
still has its rows, thus its Undo runs and each row is "already so".

## The writes

`games/writes/platform.py` has two functions for the runner:

- `remove_platform_in_batch` makes one conditional `UPDATE`. A live row
  becomes removed: moved. A row that already has this batch: moved,
  because a posted chunk can come again. A row removed by another act:
  unchanged.
- `restore_platform_from_batch` clears `removed_at` on a row of this
  batch: moved. A live row: unchanged. If a live platform of the library
  has the same name and group, it refuses with 409 and a sentence.

The per-row `restore_platform` route uses the same refusal. Today it
answers 500, because `restore_and_return` catches only `CommandFailed`
and the partial unique constraint refuses the row.

A chunk of an Undo that comes again counts its rows as "already so",
not moved. The stamp cannot tell a restore by this Undo from a restore
by hand. Only the tally is wrong; the rows are correct.

## The act

`REMOVE_PLATFORM` in `games/bulk_removal.py` has these values:

- name `platform.remove`, subject "platform", colour red;
- titles "Remove this platform" and "Remove {count} platforms";
- `undo_rows=StampedRows(Platform)`, fallback `games:list_platforms`.

The scope is the read of the list, `Platform.objects.for_library`,
with the filter of the statement. Thus a shared platform is never in
the scope. A key that the library does not have is lost, with the
sentence `PLATFORM_GONE`.

## The confirmation

The preview shows Platform, Group, Games and Purchases.
`games/reads/platform_departures.py` counts the live games and the live
purchases of the library that name the platform, with one subquery
each. The page for one row shows the same numbers. Today that page
counts removed rows too.

## The row menu

`platform_row_menu` in `games/views/platform_menu.py` has two items:

1. Edit, a link to `edit_platform`.
2. Remove, a link to the confirmation for one row.

The label of the trigger is "`<name>` (`<group>`) actions", or
"`<name>` actions" when the group is empty. Two platforms can have the
same name in different groups.

## The view

`list_platforms` removes the Actions column and sets `menu_slot: True`.
Each row has a key and a menu. The table declares `selection` with the
tray act. The column picker goes into the menu slot. Only Name cannot
be hidden.

## Not in this issue

- A bulk act that changes the group or the icon.
- A picker that accepts a removed platform (#979).
- `removed_in_batch` on the other removable models.

## Proof

- `tests/test_bulk_platform_removal.py`: remove and Undo; a chunk that
  comes again; Undo after a restore by hand; a later removal for one
  row takes the row out of the earlier Undo; the name collision on the
  batch and on the route; `_act_of` for a stamped batch and for an
  unknown batch; the refused declaration; a shared platform outside the
  scope.
- `e2e/test_bulk_platform_removal_e2e.py` removes two platforms and
  undoes the batch.
- `make render-pages` shows the selection markup, the menu slot and no
  Actions column on the Platforms list. Each different file has a
  cause.
- The full `make check` passes.
