# Library default device in a SearchSelect

Issue #1523, part of #481. After #1289.

## Control

`LibraryPreferencesForm.default_device` is a `ModelChoiceField` over the
library's live devices (`Device.objects.for_library(library)`). The form
builds its widget in `__init__`, because the resolver needs the library:

- `SearchSelectWidget(search_url=DEVICE_SEARCH_URL,
  params={"held": {"value": "1"}})`.
- `options_resolver=partial(device_options, library=library)`.
- `none_label="No device"`.
- `revert_on_leave=True`.
- No create row and no dialog +.

The form takes `library` and `default_device`; the Library view passes
both. It no longer narrows the
queryset to held devices: the widget renders no choices, and nothing binds
the form. The search route narrows what a person can pick.

`DeviceChoiceField` goes. Its `label_from_instance` fed only the native
`<option>` text.

## The search route

`GET /api/devices/search` takes `held: bool = False`. When true, it
returns only devices whose access has not ended
(`access_end_recorded_at__isnull=True`). Without it the route is
unchanged: session and record pickers still offer ended devices, hinted.

Reason: `PATCH /api/library/default-device` refuses an ended device with
422. A picker that offers one invites a refusal.

## The held value

The box shows the held device's name, as every device picker does. The
held box shows no hint. An ended default therefore reads as its name; the
help text under the field ("Lost, so new sessions name no device. Choose
another.") states the end. The help text renders on the server, so it
stays until reload after a pick. A search never offers the ended device.

## A picker remembers what it held

`holdValue(value)` and `offers(value)` read only the rows in the panel.
On a picker with a `search_url` the rows are the last answer, and × drops
them. The stored value is therefore often not a row. A failed save then
restores "No device" while the server keeps the device.

The same gap poisons a success. Pick D, type before the answer lands:
the keystroke drops the held input, the next search answer no longer
keeps D's row, and `resolvedSnapshot` finds no row offering D. The
committed state becomes none while the server holds D.

A single-select `<search-select>` remembers each option it holds, keyed
by value, the last label winning:

- At init, the server-rendered held input (not the none input) with the
  box text as its label. A multi-select seeds nothing.
- Each option `selectOption` holds after.

`holdValue` holds a remembered option when no row offers the value;
`offers` answers true for one. An already-held value answers true with no
rewrite, offered or remembered, so an open panel stays open.
`_searchSelectSetOptions` forgets every remembered option: on an inline
picker the rows are authoritative, and it drops a held value no new row
offers. A dependency change keeps the memory; a remembered value is still
a value the field held.

`revert_on_leave` restores the label the first keystroke dropped. With
the memory, `<live-setting-fields>`' own leave restore would restore the
value too; the prop keeps the restore inside the element.

## `SearchSelectWidget.revert_on_leave`

`SearchSelectWidget` takes `revert_on_leave: bool = False` and passes it to
the adapter, as `ChoiceSearchSelectWidget` does. The component refuses it
on a multi-select or panel picker.

## Save

The server half is unchanged. `<live-setting-fields>` reads the picker
through `ts/setting-control.ts`: a pick sends the id, the none row or ×
sends `null`, and the box shows "No device".

## Tests

- Route: `held=1` omits an ended device; no `held` keeps it.
- Form (replaces the queryset test in `tests/test_library_form_isolation.py`):
  the widget is a `SearchSelectWidget` with `revert_on_leave`, the none
  label, the `held` param, and a library-scoped queryset.
- Library page (replaces the `<option>` test in
  `tests/test_library_preferences.py`): an ended stored default renders as
  the held value with its name; the help text names the end.
- `tests/test_library_page_isolation.py` pins the page's query count; the
  native select's option query goes, so the count drops by one.
- vitest (search-url mount, `fetch` stubbed): after × drops the rows,
  `holdValue` of the rendered option holds it and `offers` answers true;
  the none input seeds nothing; `setOptions` forgets.
- vitest (`live-setting-fields`): pick, type, answer lands; the committed
  state stays the pick.
- e2e on the Library page: a pick saves the id; × saves `null` and shows
  "No device"; the none row saves `null`. A refused save (`page.route`
  answers 422) after a typed query dropped the stored device's row
  restores the stored device.

## Follow-up issues to file

None.
