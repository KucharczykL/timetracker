# Issue #994 plan: one test support for both suites

Spec: `docs/superpowers/specs/2026-10-08-issue-994-one-test-support-design.md`.
Inline, in order. Each task ends green on its focused run.

## Task 1: `tests/` on the path by configuration

- `pyproject.toml` `[tool.pytest.ini_options]`: add `pythonpath = ["tests"]`.
- `e2e/conftest.py`: drop `sys.path.append` and its comment; gather the
  `tests/` helper imports at the top of the file in isort order (the late
  `icon_names` import at :179 joins them).
- Probe (scratch test in `e2e/`, removed after): bare `import graphs`
  resolves to `tests/graphs.py`, and `tests` is `sys.path[0]`-near, in a
  `pytest e2e/x.py` run and in a `pytest tests/x.py e2e/x.py` run.
- Gotcha: mypy runs `mypy .`, which already finds `tests/` helpers as top
  level modules; nothing to change there.

## Task 2: root `conftest.py`

- New `conftest.py` at the repository root:
  - autouse `_process_clock_off_the_calendar`, `_reset_settings_caches`
    (merged docstring, both reasons), `_track_created_games` (body as in
    `tests/conftest.py`, docstring without the twin sentence);
  - `from bulk_batches import chunk_queue, failing_batches, held_batches  # noqa: F401`,
    `from icon_names import unknown_icon_names_fail  # noqa: F401`.
- Remove the moved fixtures and imports from `tests/conftest.py` and
  `e2e/conftest.py`; `make lint-fix` drops imports left unused (`Game`,
  `uuid`, `post_save`, `timezone`, `config_module`, `settings_resolver`).
- Check `tests/test_calendar_days.py` and `e2e/test_process_clock_e2e.py`
  still pass (they observe the clock fixture).
- Check an `untracked_games` module still runs untracked
  (`tests/test_anonymize_sample.py`).

## Task 3: one default graph

- `tests/graphs.py`: `default_graph` docstring takes the reason from the
  `stated_graph` fixture docstring.
- `tests/conftest.py`: remove `stated_graph` and the `default_graph` import.
- 56 unit modules: AST-driven rewrite script in the scratchpad —
  - remove `stated_graph` from every function's parameters (tests and local
    fixtures);
  - rename calls `stated_graph(` → `default_graph(`;
  - add `from graphs import default_graph` where absent
    (`tests/test_library_api_isolation.py` already has it).
  Review the diff by hand; then `make lint-fix` + `make format`.
- `tests/test_anonymize_sample.py:480`: inline graph → `default_graph(Game(
  library=owner.library, name="Tunic"), owner.library)`; drop now-unused
  imports.
- `e2e/test_game_form_catalog_e2e.py`: delete `state_default_graph`; callers
  use `default_graph` (its return is a `DefaultGraph`, not the written graph:
  adapt call sites reading `.editions[0]`).
- `e2e/test_purchase_tray_e2e.py`, `test_library_tab_e2e.py`,
  `test_library_section_e2e.py`, `test_form_dialog_e2e.py` (two helpers):
  replace inline `state_catalog_graph` with
  `default_graph(create_tracked_game(...), library, platform=...).release`
  or `.game`; drop the `Release.objects.get` re-reads.

## Task 4: no e2e twins

- `git rm e2e/devices.py e2e/tracked_games.py`.
- `e2e/test_filter_builder_e2e.py`, `test_picker_sheet_e2e.py`,
  `test_quick_filter_e2e.py`: `from e2e.tracked_games import` →
  `from tracked_games import`.

## Task 5: docs

- CLAUDE.md: drop "(and its `e2e/` twin)".
- #770 spec lines 29–35: helper lives in `tests/tracked_games.py`, both
  suites import it; the hook is in the root conftest.
- #678 spec :265: one autouse fixture in the root `conftest.py`.
- `tests/test_anonymize_sample.py:88` comment still names
  `_track_created_games`: true, keep.

## Task 6: gate

- `make format`, `make lint-fix`, `make format-check`, `make vale`.
- Iterate: `make check-fast` under the lock; focused e2e runs for the touched
  browser modules.
- Final: full `make check` under the lock, read by exit code.

## Follow-up issue to file

- `authenticated_page`: 40 copies in `e2e/`, 13 variants.
