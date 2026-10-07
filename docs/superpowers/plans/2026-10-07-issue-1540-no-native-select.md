# Plan: no native select (#1540)

Spec: `docs/superpowers/specs/2026-10-07-issue-1540-no-native-select-design.md`.

1. **Suite-wide check** — `tests/html_answers.py` (done as probe),
   import in `tests/conftest.py`; `tests/test_html_answers.py`. Remove
   `PanelCheckingClient` and `FLOATING_PANEL` from
   `tests/test_paths_return_200.py`; remove
   `test_form_pages_render_no_native_select` and
   `test_list_and_builder_pages_render_no_native_select` from
   `tests/test_html_validity.py` (drop now-unused imports, e.g.
   `end_entry_access`).
2. **Swap rule** — `games/forms.py` `_holds_a_plain_select`:
   `type(field.widget) is forms.ChoiceField.widget`, keeping the
   model/multiple exclusion (ModelChoiceField inherits `widget = Select`).
   django-stubs types it `Any`: runtime-only.
3. **UnsetWidget** — drop `forms.Select` branch in `_join_of` and the
   `choices` setter's `forms.Select`. Replace
   `test_a_native_select_gets_its_choices_and_shape` with a refusal test.
4. **native_control_class** — drop select branch; `SELECT_CLASS =
   f"{_SELECT_LOOK} {SHAPE_CLASSES['full']}".strip()`.
5. **SettingWidget.MODEL** — remove from `timetracker/settings_registry.py`
   (enum member, `model_queryset`, `QuerysetFactory`, both validation
   rules, `empty_display` comment), `games/settings_forms.py`
   (`_model_label`, both branches), tests (`synthetic_model_setting` and
   its two tests; two registry tests). Grep docs/configuration.md.
5b. **Builders** — drop `Select`/`Option`/`Optgroup` from
   `common/components/elements.py`, `primitives.py`, `__init__.py`; kit
   page uses `Element("select"/"option", …)`.
6. **Comments** — `ts/elements/filter-group.ts` lines ~1131, ~1141.
7. **CLAUDE.md** — fixed-choices paragraph: drop "but a MODEL setting,
   which `settingControlOf` refuses"; Testing section: name the check.
8. `make format lint-fix format-check vale typecheck`, `make check`.
