# A form keeps the device its row holds

Issue #1303.

## Rule

A form shows the device its row, or its source session, names. The
device can be removed. A save that does not change the device keeps it.

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
  device renders with its name. A removed device reads "Name (removed)".
- A posted key outside the queryset is refused with `DEVICE_GONE`.
- A held key that is not this library's device is drift. The form logs
  an ERROR on `games`, because a save clears it.

Two forms call it:

- `SessionForm`, with the session's `device_id` on an edit and none on
  an add.
- `HistoricalPlaytimeForm`, with the record's or the source session's
  `device_id`.

## Command side

`restate_session` states no device that did not change. `DescribeSession`
also compares before it resolves, so a restated removed device is
`Unchanged`. A different removed device goes through `library_device`,
which refuses it. The form refuses it first.

A record's restatement and a reclassification keep a held device through
`library_device_row`.

## Platforms

A Purchase names no platform. A Release names one, and the catalog form
keeps a removed stored platform through `platforms_or_stored`.

## Tests

`tests/test_session_held_device.py`:

- An edit of a session whose device is removed renders the device as the
  held value. A note change keeps the device and writes only the note
  event.
- An edit that empties the box clears the device.
- A new session refuses a removed device with `DEVICE_GONE`.
- An edit refuses a removed device that the row does not hold.
- A held device of another library is logged.
