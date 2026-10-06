# A form keeps the device its row holds

Issue #1303.

## Rule

An edit form shows the device its row names. The device can be removed.
A save that does not change the device keeps it.

A removed device is never a new choice. The form offers it only as the
value the row already holds. Device search reads live devices alone.

## Shape

`device_field(form, library=..., held=...)` in `games/forms.py` sets the
`device` field of a form. It sits beside `release_field`, which does the
same for a Release.

- The queryset is the library's live devices.
- When `held` names a device, the queryset also contains that device,
  removed or not.
- The picker resolves posted keys against the same queryset, so the held
  device renders with its name.

Two forms call it:

- `SessionForm`, with the session's `device_id` on an edit and none on
  an add.
- `HistoricalPlaytimeForm`, with the record's or the source session's
  `device_id`.

## Command side

`DescribeSession` compares the stated device with the row before it
resolves it. A restated removed device is `Unchanged`, so the save writes
no device event. A different removed device goes through `library_device`,
which refuses it. The form refuses it first: another row's removed device
is not in the queryset.

## Platforms

A Purchase names no platform. A Release names one, and the catalog form
already keeps a removed stored platform through `platforms_or_stored`.

## Tests

`tests/test_session_held_device.py`:

- An edit of a session whose device is removed shows the device, saves a
  note change, and keeps the device. No device event is written.
- A new session refuses a removed device.
- An edit refuses a removed device that the row does not hold.
