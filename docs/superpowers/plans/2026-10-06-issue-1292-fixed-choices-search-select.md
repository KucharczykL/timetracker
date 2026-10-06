# Plan: fixed choices leave the native select (#1292)

Spec: `docs/superpowers/specs/2026-10-06-issue-1292-fixed-choices-search-select-design.md`.
Inline, TDD. Iterate with focused `make test ARGS=…` and `make check-fast`
under the shared lock; full `make check` once at the end.

## Task 1 — `SearchSelect(required=)`

- `common/components/search_select.py`: `SearchSelect()` and the shell
  take `required: bool = False`; write `aria-required="true"` on the
  `[data-search-select-search]` box when set.
- `games/forms.py` `_SearchSelectAdapter._render`: forward
  `required=self.is_required`.
- Tests (`tests/test_search_select.py`): `required=True` writes
  `aria-required` on the box; default writes none. A required
  `ChoiceSearchSelectWidget` field renders it through `FormFields`.
- Gotcha: existing required `SearchSelectWidget` fields (session game,
  run) gain the attribute too. Intended; check snapshot tests.

## Task 2 — the swap in `apply_primitive_widget_classes`

- `games/forms.py`: after the `BooleanField` branch, when
  `isinstance(field, forms.ChoiceField)` and not
  `isinstance(field, (forms.ModelChoiceField, forms.MultipleChoiceField))`
  and `type(field.widget) is forms.Select`: build
  `ChoiceSearchSelectWidget(attrs=field.widget.attrs, revert_on_leave=True,
  clearable=…)` and `host_choices(field, widget)`; `continue`.
- `clearable`: the choices hold `""` and the field is optional. Compute
  after `host_choices` from `widget.offers_none(name)`-equivalent. Name a
  helper rather than inline (`_offers_empty(field)`), since `offers_none`
  takes a posted name only for its error text.
- Update `PrimitiveWidgetsMixin` docstring.
- Tests (`tests/test_settings_forms.py`, rewrite
  `test_stamping_applies_the_shared_control_classes_by_widget_type`; new
  tests beside it):
  - `ChoiceField`/`TypedChoiceField` with default widget → picker,
    `is_required` kept, `revert_on_leave` true.
  - × only with a `""` choice on an optional field.
  - later `field.choices = …` reaches the widget.
  - `ModelChoiceField`, `MultipleChoiceField`, `NullBooleanField`,
    `UnsetWidget(forms.Select())`, `RadioListWidget` untouched.
  - a non-`data-*` attr on the old widget raises at render.

## Task 3 — field-level fallout

- `games/entry_forms.py` `EntryEndForm.__init__`: `self.initial.setdefault("way", EndWay.UNSTATED.value)`.
- `games/bulk_access_end.py`: drop `_NO_WAY_CHOSEN` and its insert.
- Re-pin tests: `tests/test_playergame_game_views.py:153`,
  `tests/test_playergame_view_cutover.py:116`,
  `tests/test_game_form_addons.py:275`, `tests/test_edition_kind.py:113`,
  `tests/test_device_views.py:188`, `tests/test_bulk_entry_end.py:153`,
  `tests/test_settings_ui_kit.py:157,401`,
  `tests/test_settings_ui_kit_preview.py:92,136`. Pin the held hidden
  input (`name=… value=…` inside `data-search-select-pills`) instead of
  `<option selected>`.
- New: `EntryEndForm` unbound holds `unstated`; each converted form
  renders `search-select[name=…]` and no `<select` (one parametrized test
  over the nine forms).

## Task 4 — `<game-addon>`

- `ts/elements/game-addon.ts`: find `search-select[name=kindField]`; read
  the held value from its pills' hidden input; listen for
  `search-select:change` on that element; act only when
  `detail.values.length > 0`. Error text names `search-select`.
- `ts/elements/game-addon.test.ts`: rebuild fixtures over a
  `<search-select>` markup (server shape: pills with hidden input);
  dispatch `search-select:change` details directly. Cases: pick dlc shows,
  pick main hides and clears parent, a values-empty change moves nothing,
  a change from the parent picker moves nothing.

## Task 5 — temporal shape

- `common/components/temporal_field.py`: `_kind_select` splits.
  `_segments_can_hold(data)` → `Input(type="hidden", name=…, id_=input_id,
  data_temporal_input="kind", value=kind)`; else `SearchSelect` over
  `TEMPORAL_DRAFT_KIND_LABELS` plus a refused shape row,
  `clearable=False`, `revert_on_leave=True`, `required`, `id=input_id`,
  `clear_description_id=field_label_id(input_id)`. The data must reach
  `_kind_select` (pass `holds: bool`).
- Rewrite the module docstring; `docs/temporal.md` shape-select line.
- `games/forms.py` `TemporalWidget.component_media`: add
  `dist/elements/search-select.js`, `dist/elements/drop-down.js`.
- Tests `tests/test_temporal_form_field.py:222-240, 286, 404`: wrapped
  case renders the hidden kind; bare case renders a picker holding the
  kind, echoing a refused one once.
- Gotcha: `SearchSelect` import inside `temporal_field.py` — check for an
  import cycle (`games.forms` imports this module; `search_select` is in
  `common`, so fine).

## Task 6 — setting-control native select arm

- `ts/setting-control.ts`: remove `HTMLSelectElement` from the
  `NativeElement` union, `resolvedSnapshot` blank branch, `editable()`,
  `settingControlOf`.
- Vitest fixtures: `ts/setting-control.test.ts:39-50`,
  `ts/elements/live-setting-fields.test.ts` (fixtures 19/40/45, reads),
  `ts/elements/theme-setting.test.ts` `mount()`. Reuse `mountPicker`
  from `setting-control.test.ts`.
- Gotcha: `live-setting-fields.ts` may branch on select too; grep.

## Task 7 — e2e

- Rewrite `select_option` uses with `pick_choice` / `held_choice`
  (`e2e/helpers.py`): `test_game_form_catalog_e2e.py` (597-648),
  `test_dialog_create_e2e.py:85`, `test_library_tab_e2e.py:160,187`,
  `test_library_section_e2e.py:111`, `test_device_access_end_e2e.py:31,58`
  (`""` picks the Held none row), `test_settings_ui_kit_e2e.py:226,703`.
- New: two cloned editions' kind pickers have distinct
  `aria-controls`; both kinds save. A typed letter in Kind then leaving
  keeps DLC and the parent row. A refused temporal value renders the
  shape picker; picking a shape and saving round-trips.

## Task 8 — docs sweep, gate, PR

- CLAUDE.md: `temporal_field.py` line (hidden kind when wrapped), the
  forms bullet (fixed choices render the picker by default),
  `SearchSelect` `required`.
- Delete this plan; spec timeless.
- `make format`, `make lint-fix`, `make format-check`, `make vale`; full
  `make check` under the lock; draft PR closing #1292; comment on #481
  with the decision and amended inventory.
