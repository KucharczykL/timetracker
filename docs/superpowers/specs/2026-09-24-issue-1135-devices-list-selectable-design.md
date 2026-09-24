# Select devices and remove them in bulk

Issue: [#1135](https://github.com/KucharczykL/timetracker/issues/1135).
After [#1274](2026-09-24-issue-1274-device-aggregate-design.md), which
gives a device removal an event for the Undo to read.
Precedent: [the Games list](2026-09-22-issue-1134-games-list-selectable-design.md).

The Devices list is a selectable table. The tray offers one act, Remove.
The row's ⋯ menu offers Edit and Remove. The Actions column is gone.

## The act

`REMOVE_DEVICE` in `games/bulk_removal.py`: name `device.remove`, label
"Remove", titles "Remove this device" and "Remove these devices", confirm
label "Remove", subject "device", colour red, fallback
`games:list_devices`, `inverse_aggregate="device"`,
`inverse_model=Device`.

- `device_scope` is the list's own read, `Device.objects.for_library`,
  narrowed by the statement's filter through `narrowed` and
  `parse_device_filter`.
- `device_resolution` reads the same base, ordered by name and key, and
  refuses no key it finds. A key it does not find is lost under
  `DEVICE_GONE`: "One of the devices is no longer available, so it was
  left as it is."
- `run` is `remove_device` from `games/writes/device.py`, `inverse` is
  `restore_device` over the removed row that `_removed_row` reads through
  the plain manager. Both carry `{"bulk": {"action": "device.remove"}}`.
  A device a person restored between the batch and the Undo answers
  `Unchanged`, counted already so.

## The confirmation

The preview columns are Device, Type and Sessions, the last right-aligned.
Sessions is the count of live sessions naming the device, the figure the
per-row confirmation states ("N session(s) still name it"), as a
correlated subquery over `library_sessions` in
`games/reads/device_departures.py`, annotated by `device_resolution`. A
join count would multiply, so it is not one. A removed device keeps its
sessions naming it; the count says how many will name a removed device.
Historical playtime records naming the device are not counted, as the
per-row confirmation counts none: the two confirmations of one act say
the same thing.

## The row menu

`device_row_menu` in `games/views/device_menu.py`, beside `game_menu.py`
and for its reason (reading `games.bulk_actions` from
`common/components/` closes a cycle):

1. Edit, a link to `edit_device` with the origin.
2. Remove, a link to the per-row confirmation, labelled
   `REMOVE_DEVICE.label`, `danger=True`.

The trigger's label is "`<name>` (`<type>`) actions", since nothing refuses two
devices of one name, and its id `device-menu-<key>`.
Remove keeps two entries, the menu's and the tray's, as on every list
before it (#1209 weighs this).

## The view

`list_devices` deletes the Actions column from `DEVICE_COLUMNS`, states
`menu_slot: True`, builds each row with
`make_row(*cells, key=str(device.pk), menu=device_row_menu(device, origin))`,
and declares `selection` with the filter, the CSRF token and
`tray_actions(REMOVE_DEVICE.name, origin=origin)`. The column picker moves
into the menu slot by itself. Only Name is `hideable=False`.

The table leaves `tests/test_column_priority_contract.py`, which skips a
table with no Actions header.

## Not in this issue

- A bulk act that changes a device's type, the set-one-value shape of
  #1211.
- Sold and lost (#1275).
- A per-row summary below `md` (#1241).

## Proof

`make render-pages` before and after. Each differing file is a Devices
list page, and each difference is the selection markup, the menu slot or
the removed Actions column.

`tests/test_bulk_removal.py`'s parametrised cases take the fifth act;
`tests/test_bulk_device_removal.py` covers resolution, the Sessions
count, the Undo of a batch, and a token posted twice. An e2e case selects
two devices, removes them through the tray, and undoes the batch.
