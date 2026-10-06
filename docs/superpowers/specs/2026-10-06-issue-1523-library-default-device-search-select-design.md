# Library default device in a SearchSelect

Issue #1523, part of #481.

## Control

`LibraryPreferencesForm` takes `library` and `default_device`.
Its `default_device` field is a `ModelChoiceField` over
`Device.objects.for_library(library)`. The form builds the widget in
`__init__`, because the resolver needs the library:

- `SearchSelectWidget` over `DEVICE_SEARCH_URL`.
- `params` is `{"held": {"value": "1"}}`.
- `options_resolver` is `device_options` bound to the library.
- `none_label` is "No device".
- `revert_on_leave` is true.
- The picker has no create row and no dialog +.

`SearchSelectWidget` takes `revert_on_leave` and gives it to the adapter.

## Search route

`GET /api/devices/search` takes `held`. When `held` is true, the route
omits a device whose access ended. Session and record pickers do not send
`held`. They show an ended device with its hint.

`PATCH /api/library/default-device` refuses an ended device with 422. The
picker therefore does not offer one.

## Held value

The box shows the held device's name. It shows no hint. The help text
under the field states an ended default. The server renders the help
text, so it stays until the page reloads.

## Memory of held options

On a picker with a `search_url`, the rows are the last search answer.
× removes them. A typed query replaces them. The stored value is
therefore often not a row.

A single-select `<search-select>` remembers each option that it holds,
keyed by value. The last label is kept.

- At init, the rendered held input gives the first option. Its label is
  the box text. The none input gives no option.
- `selectOption` records each option that it holds.
- A multi-select remembers nothing.

`holdValue` holds a remembered option when no row offers the value.
`offers` answers true for a remembered option. `setOptions` forgets every
remembered option, because inline rows are the complete set. A dependency
change keeps the memory.

`<live-setting-fields>` reads the picker through `ts/setting-control.ts`.
The memory gives it two results:

- A refused save restores the stored device, not "No device".
- A save that resolves after a typed query keeps the saved device as the
  committed state.

## Save

The server half does not change. A pick sends the device id. The none row
or × sends `null`, and the box shows "No device".

## Tests

- `held=1` omits an ended device. A request without `held` includes it.
- The form widget states the search URL, `held`, the none label and
  `revert_on_leave`. The resolver reads one library.
- The Library page holds an ended default by name. The help text names the
  end.
- vitest: after ×, `holdValue` holds the rendered option. The none input
  gives no option. `setOptions` forgets.
- vitest: a save that resolves after a typed query keeps the pick as the
  committed state.
- e2e: a pick saves the id. × and the none row save `null`. A refused
  save after a typed query restores the stored device.
