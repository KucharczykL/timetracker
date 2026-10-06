# Plan: live settings save a SearchSelect (#1289)

Spec: `docs/superpowers/specs/2026-10-06-issue-1289-live-setting-search-select-design.md`.

## Task 1 — SearchSelect takes host data and input state

- `common/components/search_select.py` `SearchSelect()`: `host_data:
  Mapping[str, str] | None`, `disabled: bool`, `described_by: str | None`,
  `invalid: bool`. `host_data` keys must start `data-` (else `ValueError`).
- `games/forms.py` `_SearchSelectAdapter._render`: merge `{**self.attrs,
  **(attrs or {})}`; route `data-*` → `host_data`, `disabled`,
  `aria-describedby`, `aria-invalid` → input. Callers of `_render` pass
  `attrs` already.
- Tests (`tests/test_search_select_widget*.py` or nearest): forwarded attrs
  land; an unknown attr (`class`) still dropped.

## Task 2 — search-select element: holdValue, holdNone, describedby

- `ts/elements/search-select.ts`: internal `_searchSelectHoldValue(value)`
  (find `[data-search-select-option]` row by value, its `data-label`; no row
  → none where offered, else clear), `_searchSelectHoldNone()` (= `holdNone`).
  Public `holdValue(value)`, `holdNone()` on `SearchSelectElement`.
- Init appends the status id to an existing `aria-describedby`.
- Emit only on change: `selectOption` and `pickNone` compare held values and
  none before/after (form mode only); a no-op emits nothing.
- `revert-on-leave` prop (`SearchSelectProps`, regenerate types): remember
  the held state at the first-keystroke drop; on a `focusout` leaving the
  container with nothing picked, hold it again silently.
- Python: `SearchSelect(revert_on_leave=...)`,
  `ChoiceSearchSelectWidget(revert_on_leave=...)`.
- vitest beside existing `search-select.*.test.ts`.

## Task 3 — `ts/setting-control.ts`

- `SettingValue`, `ControlSnapshot`, `SettingControl` interface (spec table),
  `settingControlOf(element)`, `changedSettingControl(event)`.
- Native: moves `settingPayloadValue`, `snapshot`, `restore`,
  `resolvedSnapshot`, `snapshotsEqual` out of `live-setting-fields.ts`.
- SearchSelect: `read()` from hidden inputs (`[data-search-select-none]` →
  null; held → value; none → undefined).
- Imports `./elements/search-select.js`.
- `ts/setting-control.test.ts`.

## Task 4 — live-setting-fields over the reader

- Maps keyed by `HTMLElement` (`control.element`); listens on `change` and
  `search-select:change`; skips `read() === undefined`.
- Keep `settingPayloadValue` export path working (re-export or update test
  import).
- vitest cases from the spec.

## Task 5 — settings forms build the picker

- `games/settings_forms.py` `_build_field` SELECT: `widget=ChoiceSearchSelectWidget(revert_on_leave=True)`
  on both `TypedChoiceField` and `ChoiceField`.
- Update `tests/test_settings_page.py`, `tests/test_admin_settings_page.py`.
- New pytest: none row label per page; locked admin field → disabled input.

## Task 6 — theme-setting over the reader

- `ts/elements/theme-setting.ts`: `settingControlOf(querySelector("[data-setting-key]"))`;
  listen `control.changeEvent`, stopPropagation, skip `undefined`. `theme-setting.test.ts` over a SearchSelect.

## Task 7 — e2e

- Helper to pick a SearchSelect option by label and to press ×
  (look for an existing one in `e2e/` first).
- Move `e2e/test_settings_page_e2e.py`, `e2e/test_theme_e2e.py`,
  `e2e/test_admin_settings_page_e2e.py`.
- New acceptance test: personal page time zone pick → reload holds it; × →
  `Use site default (…)`, stored `NULL`.

## Gotchas

- Run `make ts` before e2e.
- `settingPayloadValue` is imported by `live-setting-fields.test.ts`.
- The search box's blur `change` must not reach a save.
- Follow-up issue: library default device picker (#481 workstream 2).
