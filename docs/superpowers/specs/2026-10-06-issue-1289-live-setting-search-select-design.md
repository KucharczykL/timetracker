# Live settings save a setting held in a SearchSelect

Issue #1289, part of #481 (workstream 1). Needs #1288 (none) and #1301
(fixed-choice widget), both merged.

## Decisions

1. **Every SELECT setting becomes a `SearchSelect`** (user's call). All ten
   `SettingWidget.SELECT` definitions, on the personal page and the admin page,
   THEME included. `RegistrySettingsForm._build_field` builds the field with
   `ChoiceSearchSelectWidget`. The `("", empty_label)` choice is the none row:
   "Use site default (X)" on the personal page, "Use configured default" on the
   admin page. This settles #1292 for settings; it does not decide other forms.
2. **One reader per control kind.** A new module, `ts/setting-control.ts`,
   gives a `SettingControl` over either a native control (input, select,
   textarea) or a `<search-select>`. `live-setting-fields.ts` and
   `theme-setting.ts` read every control through it. No `instanceof` branch
   stays in either element.
3. **A SearchSelect adapter forwards the widget's attrs.** Today
   `_SearchSelectAdapter._render` reads only the `attrs` argument and keeps
   its `id`. It now merges `{**self.attrs, **attrs}` first, because the
   settings kit stamps `data-setting-key`, `data-setting-source`,
   `data-live-setting-control`, `data-reload-after-save` and
   `aria-describedby` on `widget.attrs`. Django puts `disabled` for a locked
   field into the `attrs` argument. The adapter now forwards:
   - every `data-*` attr onto the `<search-select>` element,
   - `disabled`, `aria-describedby` and `aria-invalid` onto the search input
     (the documented way to disable a SearchSelect).
   Other attrs stay dropped, as today. `SearchSelect()` takes them as
   `host_data` (a mapping) and `disabled` / `described_by` / `invalid`.
   The element's init sets `aria-describedby` to its status span; it now
   appends the span's id to a rendered value instead of replacing it.
4. The library default device (`LibraryPreferencesForm`, a
   `ModelChoiceField`) stays native. It is workstream 2 of #481; the reader
   makes it a widget swap. Filed as a follow-up.

## The reader

```text
settingControlOf(element) -> SettingControl | null
changedSettingControl(event, root) -> SettingControl | null
```

A `SettingControl` states:

| Member | Native | SearchSelect |
|---|---|---|
| `element` | the control | the `<search-select>` |
| `changeEvent` | `change` | `search-select:change` |
| `read()` | as `settingPayloadValue` | held value; none → `null`; nothing picked → `undefined` |
| `snapshot()` | `{value, checked?}` | `{value, label, none}` |
| `restore(state)` | sets value/checked | holds value or none, **emits no change** |
| `write(value)` | sets `.value` | holds the option with that value, or none for `null`/`""` |
| `resolvedSnapshot(attempt, resolved)` | today's three rules: select keeps a `null` attempt, checkbox takes the boolean, else the resolved value | `null` keeps the attempt (none); else holds the resolved value |
| `equals(left, right)` | value and checked | value and none |
| `editable()` | not disabled, not readOnly | search input not disabled |
| `setDisabled`, `setBusy` | on the control | on the search input |

The native reader keeps its kind branches inside itself: the library default
device and the settings kit preview still render native selects. The
elements hold no `instanceof`.

`read() === undefined` means "nothing to save": the first keystroke into a
held value sends `values: []` with `none: false` (#1288), and that is not a
reset. The element saves nothing for it.

`changedSettingControl` maps an event to its control. A native `change`
counts only when its **target** carries `data-live-setting-control`. The
search box inside a `<search-select>` fires a native `change` on blur; its
target is the box, which carries no marker, so it is ignored. The
`search-select:change` event counts when its target is a marked
`<search-select>`.

## Live save

- Pick → `PATCH {value: "<option>"}`.
- None row or × → `PATCH {value: null}`. The box keeps showing the none row's
  label, "Use site default (X)". This matches today's blank-select rule in
  `resolvedSnapshot`: a `null` attempt keeps the attempt's own state, because
  the effective value may equal another option.
- Non-null answer → hold the resolved value with its option label (the server
  can only answer a value the choices offer).
- Failure → `restore` the last committed snapshot, silently, and toast as
  today. The coalescing and the in-flight queue are unchanged.

## Two SearchSelect rules

Both live in `search-select.ts`, so no consumer repeats them.

- **A pick that changes nothing emits nothing.** A native select fires no
  `change` when the value stays. A form-mode `<search-select>` now does the
  same: a pick of the held option, a pick of a pill already held, and the
  none row while none is held emit no `search-select:change`. Filter-mode
  pills keep their own events. Audit of every listener: the preset panel
  clears its selection after each pick, so a re-pick is never of a held
  row; the filter builder's field picker, the comparison operands, the time
  zone row and the dependency refetch all treat a same-value event as a
  no-op or are better without it. Without this rule, a re-pick on a
  `reload_after_save` setting reloads the page and a theme re-pick starts a
  save that disables the focused box.
- **`revert_on_leave`, opt-in.** A first keystroke drops a held value or
  none to nothing picked (#1288). With the prop, when focus leaves the
  `<search-select>` (`relatedTarget` outside it, so Tab to the × stays) and
  nothing is picked, the element holds again what it held before the drop,
  silently. The drop's event was not a commit, so no consumer acted on it;
  the revert returns to the state consumers last acted on. Without the prop
  (every ordinary form), typed text stays until a pick or a submit, as
  today. `SearchSelect(revert_on_leave=True)`, carried by
  `ChoiceSearchSelectWidget(revert_on_leave=True)`; every settings SELECT
  field sets it.

With the first rule, the in-flight case needs no extra logic: pick A (in
flight), then back to O, is a change and queues O. With the second, an
abandoned edit during a save reverts to A, which the settle path's
reconcile still matches.

`<search-select>` gains two public silent methods beside `setSelected`:
`holdValue(value)`, which finds the option row's label itself (a value no row
offers holds none, or nothing where there is no none row), and `holdNone()`.
Each sets the hidden input, the box text and the × as a pick does, and
emits no change. The reader uses them;
`resolved.value` is a number for the two int settings, so it passes
`String(value)`.

The reader module imports `elements/search-select.js`, so the element is
defined before `<theme-setting>` or `<live-setting-fields>` reads it.

The time zone picker renders about 600 inline rows per page, as the select
rendered 600 options. Client filtering is enough at that size; a server
search stays a later choice.

## Theme

`<theme-setting>` reads its control through `settingControlOf`. It listens on
`control.changeEvent`, stops it from reaching `<live-setting-fields>` as
today, ignores `undefined`, and sends `value` or `null` to the coordinator.
Its render writes the coordinator's state with `write`, `setDisabled` and
`setBusy`. Re-picks and abandoned edits need nothing here: the picker handles both.
The theme control carries no
`data-live-setting-control`, so `<live-setting-fields>` never sees it.

## Tests

- vitest `ts/setting-control.test.ts`: both kinds; none → `null`; keystroke →
  `undefined`; `restore` emits no `search-select:change`; blur `change` of the
  search box maps to no control.
- vitest `live-setting-fields.test.ts`: a SearchSelect saves on pick, saves
  `null` on none, sends nothing on a keystroke, restores on failure.
- vitest `theme-setting.test.ts`: over a SearchSelect.
- pytest: the adapter forwards `data-*` to the host and `disabled` /
  `aria-describedby` to the input; settings pages render a `<search-select>`
  per SELECT setting with its none row; a locked admin field renders a
  disabled search input.
- vitest (search-select): a re-pick of the held option, of a held pill and
  of the none row while none is held emit nothing; `revert_on_leave`
  restores a value and none on a leave, silently; Tab to the × does not
  revert; without the prop the text stays.
- vitest (live-setting-fields): a re-pick sends no PATCH; pick A in flight
  then O queues O. `aria-describedby` keeps the rendered
  id beside the status id.
- Existing tests that pin native markup move to the picker:
  `tests/test_settings_page.py` (`<select name=…>`, `<option … selected>`,
  the none label as an `<option>`), `tests/test_admin_settings_page.py`
  (`_opening_control_tag` regex, `<option value="25" selected>`),
  `ts/elements/theme-setting.test.ts`. The kit preview tests keep native
  forms.
- e2e (acceptance): on the personal page pick a display time zone, reload,
  see it; reset with ×, see `Use site default (…)`, and the stored value is
  `NULL`. Existing e2e that call `select_option` on a settings select move to
  the picker: `e2e/test_settings_page_e2e.py`, `e2e/test_theme_e2e.py`
  (`select_option("")` becomes the none row),
  `e2e/test_admin_settings_page_e2e.py`. After × and a reload, the admin
  page shows the resolved value, as today; no test asserts the none label
  there.

## Follow-up issues to file

- Library default device picker becomes a SearchSelect over the reader
  (#481 workstream 2).
