# Plan: the release row's platform picker (#1222)

Spec: `docs/superpowers/specs/2026-10-06-issue-1222-release-platform-picker-design.md`.

## Task 1 — option helpers and constants (`games/forms.py`, `games/api.py`, `games/filters.py`)

- `PLATFORM_SEARCH_URL`, `PLATFORM_CREATE_URL` beside the device constants.
- `platform_option(platform) -> SearchSelectOption`, `" (removed)"` when
  `removed_at`.
- `stored_or_visible_platforms(library, stored_id) -> QuerySet[Platform, Platform]`
  (in `games/forms.py` or `games/reads/releases.py`).
- `platform_options(values, *, library, stored)`.
- `NEW_PLATFORM = DialogCreate(reverse_lazy("games:add_platform"), "New platform")`.
- `create_platform` answers `CreatedRow(**platform_option(...))` shape
  (value, label only — check `CreatedRow` fields).
- filters literals → constant.
- Tests: `platform_option` labels; API create unchanged
  (`tests/test_row_creation_api.py`).

## Task 2 — `ReleaseRowForm` (`games/catalog_form.py`)

- `instance` kwarg; queryset visible-or-stored; widget per spec, resolver
  bound in `__init__`.
- `_release_form(..., instance=)`; `_blocks_from_storage` and
  `_blocks_from_post` pass it; drop the `row.instance =` lines.
- `platform_names()` resolves every row's `value()` in one query.
- Drop the stale field comment.
- Tests (`tests/test_catalog_graph_form.py`,
  `tests/test_library_form_isolation.py`): invert plain-select test; edit
  unspecified test; foreign-bound row shows no foreign name; removed
  stored platform renders `(removed)` and validates; posted
  `not-a-platform` still refuses (`test_game_form_page.py:257`).

## Task 3 — `add_platform` in a dialog (`games/views/platform.py`)

- `_platform_form_page`: on write with `platform is None`, return
  `CreatedRedirect(return_url(...), option=platform_option(record))`.
- Test: dialog-mode POST (`X-Form-Dialog: 1`) answers `created` with the
  option; plain POST still redirects. Find the existing game test for
  `CreatedRedirect` and mirror it.

## Task 4 — `heldLabel()` and the editor (`ts/elements/search-select.ts`, `ts/elements/catalog-editor.ts`)

- `SearchSelectElement.heldLabel(): string | null` — read the container
  directly; none input → none label; one held value → `_searchSelectLabel`
  or null if empty; else null.
- Editor: import `SearchSelectElement`; `FOLLOWED.platform.control =
  'search-select[name$="-platform"]'`; `shown()` handles input and picker
  (upgrade, instanceof, heldLabel); `null` → skip the row silently;
  listen `search-select:change`.
- vitest (`ts/elements/catalog-editor.test.ts`, maybe
  `search-select.*.test.ts` for heldLabel): fixtures with a real picker
  shell; pick renames; none names Unspecified; keystroke keeps.
- `make ts`.

## Task 5 — guards and e2e

- `tests/test_html_validity.py`: no `<select>` at all.
- `e2e/test_game_form_catalog_e2e.py`: `choose_platform(card, platform)`
  by key; rewrite `test_a_restored_value_is_named_on_arrival` (run it,
  decide by evidence); new create-row case on a cloned row; new + dialog
  case.

## Task 6 — docs

- CLAUDE.md native-select clause; #1292 spec line 68; `game.py` imports
  `UNSPECIFIED_PLATFORM`.

## Gotchas

- `make lint-fix` sorts imports.
- e2e never beside `make dev`.
- Tests POSTing through a dispatching view need `transaction=True`.
