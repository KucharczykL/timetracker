# Live settings in a SearchSelect

Issue #1289, part of #481.

## Controls

Every `SettingWidget.SELECT` setting renders a `<search-select>` on the
personal page and on the site page. `RegistrySettingsForm._build_field`
builds it with `ChoiceSearchSelectWidget(revert_on_leave=True)`. The
`("", empty_label)` choice is the none row: "Use site default (X)" on the
personal page, "Use configured default" on the site page.

The form adapter merges `self.attrs` with the `attrs` argument. It puts
`data-*` on the `<search-select>` element, and `id`, `disabled`,
`aria-describedby` and `aria-invalid` on the search box. It refuses any
other attribute. The element appends its status id to a rendered
`aria-describedby`.

## The reader

`ts/setting-control.ts` gives one `SettingControl` for a native control
and for a `<search-select>`. `<live-setting-fields>` and
`<theme-setting>` read every control through it.

| Member | Native | SearchSelect |
|---|---|---|
| `changeEvent` | `change` | `search-select:change` |
| `read()` | the payload value; empty is `null` | held value; none is `null`; nothing picked is `undefined` |
| `restore`, `write` | set the value | `holdValue` or `holdNone`, silent |
| `setDisabled`, `setBusy` | the control | the search box |

After a first keystroke drops the held value, `read()` returns
`undefined` and nothing saves.

`changedSettingControl(event)` returns a control only when the event
target carries `data-live-setting-control` and the event type is the
control's `changeEvent`. The search box's blur `change` therefore starts
no save.

`settingControlOf` upgrades a `<search-select>` before it reads it,
because a parent can connect first. It refuses a multi-select picker. A
control refuses the other kind's snapshot.

## Live save

- A pick sends the value.
- The none row or × sends `null`. The box keeps the none label.
- A success holds the resolved value. A resolved value that no row
  offers holds none and logs an error.
- A failure shows a toast. It restores the last committed state,
  silently, unless a newer edit shows.
- When focus leaves a control with no save pending, the element restores
  the committed state if the control shows another.

## SearchSelect rules

- A form-mode pick that changes nothing emits no `search-select:change`.
  This applies to the held option, a held pill, and the none row while
  none is held. Filter-mode pills always emit.
- `revert_on_leave` is opt-in, single-select and field-hosted only. When
  focus leaves the element with nothing picked, the element holds again
  what the first keystroke dropped. It emits no change. Focus that moves
  to the × stays inside the element.
- `holdValue(value)` holds the row that offers `value`; else it holds
  none, or nothing, and answers false. `holdNone()` holds none.
  `offers(value)` tests a row. A hold of the held state does nothing, so
  an open panel stays open. Each throws before the element initialises
  and emits no change.

## Theme

`<theme-setting>` listens on its control's `changeEvent` and stops it.
It sends the read value to the theme coordinator and ignores
`undefined`. It renders the coordinator state with `write`,
`setDisabled` and `setBusy`.

## Follow-up

- #1523: the library default device uses a SearchSelect.
