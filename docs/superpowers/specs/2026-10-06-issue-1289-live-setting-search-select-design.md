# Live settings in a SearchSelect

Issue #1289, part of #481.

## Controls

Every `SettingWidget.SELECT` setting renders a `<search-select>` on the
personal page and on the site page. `RegistrySettingsForm._build_field`
builds it with `ChoiceSearchSelectWidget(revert_on_leave=True)`. The
`("", empty_label)` choice is the none row: "Use site default (X)" on the
personal page, "Use configured default" on the site page.

The form adapter merges `self.attrs` with the `attrs` argument. It puts
every `data-*` attribute on the `<search-select>` element. It puts
`disabled`, `aria-describedby` and `aria-invalid` on the search box. It
drops other attributes. The element appends its status id to a rendered
`aria-describedby`; it does not replace it.

## The reader

`ts/setting-control.ts` gives one `SettingControl` for a native input,
select or textarea, and for a `<search-select>`. `<live-setting-fields>`
and `<theme-setting>` read every control through it. Neither element
tests the control kind.

| Member | Native | SearchSelect |
|---|---|---|
| `changeEvent` | `change` | `search-select:change` |
| `read()` | the payload value; empty is `null` | held value; none is `null`; nothing picked is `undefined` |
| `restore`, `write` | set the value | `holdValue` or `holdNone`, silent |
| `setDisabled`, `setBusy` | the control | the search box |

`read()` returns `undefined` after a first keystroke drops the held value.
The element saves nothing for it.

`changedSettingControl(event)` returns a control only when the event
target carries `data-live-setting-control`. The search box fires a
native `change` on blur. Its target carries no marker, so no save starts.

`settingControlOf` upgrades a `<search-select>` before it reads it. A
parent element can connect before its child upgrades.

## Live save

- A pick sends the value.
- The none row or × sends `null`. The box keeps the none label.
- A success holds the resolved value. A failure restores the last
  committed state, silently, and shows a toast.

## SearchSelect rules

- A form-mode pick that changes nothing emits no `search-select:change`.
  This applies to the held option, a held pill, and the none row while
  none is held. Filter-mode pills always emit.
- `revert_on_leave` is opt-in. When focus leaves the element with nothing
  picked, the element holds again what the first keystroke dropped. It
  emits no change. Focus that moves to the × stays inside the element.
- `holdValue(value)` holds the row that offers `value`. An unoffered
  value holds none, or nothing where no none row exists. `holdNone()`
  holds none. Neither emits a change.

## Theme

`<theme-setting>` listens on its control's `changeEvent` and stops it.
It sends the read value to the theme coordinator and ignores
`undefined`. It renders the coordinator state with `write`,
`setDisabled` and `setBusy`.

## Follow-up

- #1523: the library default device uses a SearchSelect.
