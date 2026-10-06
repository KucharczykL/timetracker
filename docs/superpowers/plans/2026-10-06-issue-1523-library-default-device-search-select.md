# Plan: Library default device in a SearchSelect (#1523)

Spec: `docs/superpowers/specs/2026-10-06-issue-1523-library-default-device-search-select-design.md`.

## Task 1 — `held` on the device search route

- `games/api.py` `search_devices`: `held: bool = False`; when true filter
  `access_end_recorded_at__isnull=True` before both orderings.
- Test (`tests/test_library_preferences.py` or beside other device-search
  tests): ended device absent with `held=1`, present without.

## Task 2 — `SearchSelectWidget.revert_on_leave`

- `games/forms.py` `SearchSelectWidget.__init__`: keyword, passed to
  `_SearchSelectAdapter`.
- Test in `tests/test_search_select.py`: renders `revert-on-leave="true"`.

## Task 3 — the form and the view

- `games/forms.py`: drop `DeviceChoiceField`; `LibraryPreferencesForm`
  takes `library`, `default_device`; field `ModelChoiceField(queryset=
  Device.objects.for_library(library), required=False)`; widget built in
  `__init__` with `DEVICE_SEARCH_URL`, `params={"held": {"value": "1"}}`,
  `partial(device_options, library=library)`, `none_label="No device"`,
  `revert_on_leave=True`. `empty_label` irrelevant now.
- `games/views/library.py`: pass `library=`.
- Replace `tests/test_library_form_isolation.py::
  test_library_preferences_default_device_is_a_scoped_model_choice`.
- Replace `tests/test_library_preferences.py::
  test_the_settings_page_shows_an_ended_default_and_offers_held_devices`:
  `<search-select name="default_device"` present, held hidden input value
  is the ended pk, box value "Deck", help text present.
- `tests/test_library_page_isolation.py:118`: count 25 → measure.

## Task 4 — the picker remembers what it held

- `ts/elements/search-select.ts`: `remembered: Map<string,
  SearchSelectOption>` (single-select only). Seed at init beside
  `_searchSelectLabel = search.value` (line ~1001) from the held input
  lacking `data-search-select-none`. `selectOption` single branch records.
  `_searchSelectOffers`: row or remembered. `_searchSelectHoldValue`:
  `option = offeredRow ? optionFromRow(row) : remembered.get(value)`;
  already-held check uses `option !== undefined`. `_searchSelectSetOptions`
  clears the map. Update the `offers` docstring (~1808).
- vitest `ts/elements/search-select.settle.test.ts`: mount with
  `search-url`, stub `fetch`; × with panel closed then `holdValue`
  restores; none input seeds nothing; `setOptions` forgets.
- vitest `ts/elements/live-setting-fields.test.ts`: pick, type, answer
  lands, committed stays the pick (check existing harness there).

## Task 5 — e2e

- New `e2e/test_library_default_device_e2e.py` (or extend an existing
  Library-page e2e): user with devices Deck (stored default), Phone.
  1. pick Phone → PATCH `/api/library/default-device` body `{"value":
     "<id>"}` 200, reload holds it.
  2. × → `{"value": null}`, box "No device", DB null.
  3. none row → `null` (from a held device).
  4. `page.route` 422 on the PATCH; type "Ph" (drops Deck row), pick
     Phone → box restores "Deck", hidden input Deck's id.
- Gotcha: nothing touches the picker before the response; restore runs
  only while snapshot equals the attempt's.

## Gotchas

- `make ts` after TS edits before e2e.
- Combobox refetches on every open.
- Gate commands wrapped in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
