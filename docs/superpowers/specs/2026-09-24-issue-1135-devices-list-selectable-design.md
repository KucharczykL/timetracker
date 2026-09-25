# Select devices and remove them in bulk

Issue: [#1135](https://github.com/KucharczykL/timetracker/issues/1135).
It needs [the Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md),
because the Undo of a batch reads the events of the batch.
Precedent: [the Games list](2026-09-22-issue-1134-games-list-selectable-design.md).

## Result

The person can select rows on the Devices list. The tray has one act,
Remove. The ⋯ menu of each row has Edit and Remove. The Actions column
is gone.

## The act

`REMOVE_DEVICE` in `games/bulk_removal.py` has these values:

- name `device.remove`, subject "device", colour red;
- titles "Remove this device" and "Remove these devices";
- `inverse_aggregate="device"` and `inverse_model=Device`.

The scope is the read of the list, `Device.objects.for_library`, with the
filter of the statement. A key that the library does not have is lost,
with the sentence `DEVICE_GONE`. The run sends `RemoveDevice`. The Undo
sends `RestoreDevice`. A device that is already live gives `Unchanged`.

## The confirmation

The preview shows Device, Type and Sessions. Sessions is the number of
live sessions that name the device. `games/reads/device_departures.py`
counts them with a subquery. The page for one row shows the same number.
The count does not include historical playtime records.

## The row menu

`device_row_menu` in `games/views/device_menu.py` has two items:

1. Edit, a link to `edit_device`.
2. Remove, a link to the confirmation for one row.

The label of the trigger is "`<name>` (`<type>`) actions". Two devices
can have the same name, thus the type is necessary.

## The view

`list_devices` removes the Actions column and sets `menu_slot: True`.
Each row has a key and a menu. The table declares `selection`. The
column picker goes into the menu slot. Only Name cannot be hidden.

## Not in this issue

- A bulk act that changes the type of a device.
- "Sold" and "lost" (#1275).

## Proof

- `make render-pages` shows the selection markup, the menu slot and no
  Actions column on the Devices list.
- `tests/test_bulk_device_removal.py` and an e2e test remove two devices
  and undo the batch.
