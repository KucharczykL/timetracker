# The browser suite states nothing the unit suite states

Issue #994. Found by the review of #992.

## Problem

`e2e/` restates helpers that `tests/` already holds. Two copies of one helper
drift, and one already has:

- `state_default_graph` in `e2e/test_game_form_catalog_e2e.py` copies
  `default_graph` in `tests/graphs.py`. Its docstring says `tests/` is not on
  the browser suite's path. That is false: `e2e/conftest.py` appends `tests/`
  to `sys.path`, and six browser modules import `graphs.default_graph`.
- Four browser modules state the same one-Edition-one-Release graph inline,
  five times: `test_purchase_tray_e2e.py`, `test_library_tab_e2e.py`,
  `test_library_section_e2e.py`, and `test_form_dialog_e2e.py` (twice).
  `tests/test_anonymize_sample.py` states it inline once more.
- `e2e/devices.py` is a stale copy of `tests/devices.py`. It lacks
  `end_device_access`. No module imports it: a bare `import devices` in a
  browser module resolves to `tests/devices.py` (measured, below).
- `e2e/tracked_games.py` is a byte-identical copy of `tests/tracked_games.py`.
  Three browser modules import it as `e2e.tracked_games`; nineteen import
  the bare name, which resolves to `tests/`.
- `e2e/conftest.py` restates three autouse fixtures of `tests/conftest.py`:
  `_process_clock_off_the_calendar`, `_reset_settings_caches` and
  `_track_created_games`. The last one says so in its docstring: "the suites
  share no conftest".
- `tests/conftest.py` offers `stated_graph`, a fixture that returns
  `default_graph` and does nothing else. Fifty-six unit modules ask for it;
  others import `default_graph`. One helper has two spellings, and the browser
  suite cannot reach the fixture one. That gap is what produced
  `state_default_graph`.

## Path facts (measured)

`e2e/` holds an `__init__.py`; `tests/` does not. Under pytest's default
`prepend` import mode, pytest puts the repository root on `sys.path` for
`e2e/` (the first directory upward without `__init__.py`). `e2e/conftest.py`
appends `tests/` to the end of `sys.path`. A probe test in `e2e/` printed, for
`import devices`, `import tracked_games`, `import graphs`: `tests/devices.py`,
`tests/tracked_games.py`, `tests/graphs.py`; and for `import
e2e.tracked_games`: `e2e/tracked_games.py`.

`make test` runs bare `pytest` from the root, which collects `e2e/` first.
Prepend then skips `tests/` for `tests/conftest.py`, because the append put it
on the path already. So in the whole-suite run the unit helpers sit behind
site-packages, and an installed module of the same name would shadow one. None
does today. The comment in `e2e/conftest.py`, "pytest puts each suite's own
directory on the path", is false for `e2e/`.

## Decisions

1. **One helper, one spelling.** `tests/graphs.py::default_graph` is the only
   way a test states the default graph. `state_default_graph` goes. Every
   inline copy of the shape above calls `default_graph` instead. A helper that
   states a different shape (several Releases, a second Edition, a kept row)
   stays: it is not a copy.

   The copies differ from `default_graph` only where nothing persists. The
   browser copies call `create_tracked_game` first; `default_graph` then calls
   `game.save()` again, one `UPDATE`, whose `post_save` carries
   `created=False`, so the tracking hook does nothing. Their keys are
   `"edition"` and `"release"`; a key only labels a row inside one statement.
   The anonymizer test runs under `untracked_games` and creates its game with
   `Game.objects.create`; `default_graph(Game(...))` saves it the same way.

   These stay, because each states another shape: `_held_game` in
   `e2e/test_session_release_e2e.py` (several Releases), `_default_releases`
   in `tests/test_projection_replay_gate.py` (a count, no save),
   `second_release` and `prerelease_release` in `tests/entries.py`, the named
   Edition in `tests/test_reference_presentation.py`, `_state` in
   `tests/test_edition_kind.py` (restates a kept graph), and the second
   Release in `tests/test_entry_forms.py`. The two `live_releases` helpers in
   `e2e/test_game_form_catalog_e2e.py` and `tests/test_state_catalog_graph.py`
   are one-line reads local to their modules; they stay.
2. **`stated_graph` is retired.** Its 135 calls, in 56 modules, call an
   imported `default_graph`; its 132 fixture parameters go, which changes the
   signature of local fixtures such as `graph(owned_library, stated_graph)`.
   The fixture's docstring, which says why the shape is the default, moves to
   `default_graph`. A fixture that only returns a function adds a spelling and
   hides the helper from the browser suite.
3. **`tests/` holds every helper both suites use.** `e2e/devices.py` and
   `e2e/tracked_games.py` are removed. The three `e2e.tracked_games` imports
   become `tracked_games`.
4. **`tests/` is on the path by configuration.** `pythonpath = ["tests"]`
   under `[tool.pytest.ini_options]` puts it at the front of `sys.path` before
   any conftest loads, in every run. The `sys.path.append` line in
   `e2e/conftest.py` and its false comment go.
5. **What both suites share is one root `conftest.py`.** Pytest loads a
   conftest for every directory under it, so a fixture there reaches both
   suites, defined once. A probe confirmed a root `conftest.py` beside
   `tests/conftest.py` (both bare `conftest` modules) loads without a name
   clash. The root conftest holds:
   - `_process_clock_off_the_calendar`, `_reset_settings_caches` and
     `_track_created_games`, moved from both suite conftests;
   - the imports of `chunk_queue`, `held_batches`, `failing_batches` and
     `unknown_icon_names_fail`, moved from both suite conftests.

   The fixture names keep their leading underscore, so the specs and comments
   that name them stay true. The root conftest's autouse fixtures run before a
   suite conftest's, so `_no_process_statement_limit` now runs after the
   three; none reads another's state. `_track_created_games` keeps reading
   the `untracked_games` marker off `request.keywords`.

   `_reset_settings_caches` keeps both suites' reasons in its docstring:
   `TestCase` rollback fires no `SiteSetting` commit signal, a flush under
   `transaction=True` fires none either, and per-test `ENV_FILE`/`INI_FILE`
   fixtures must not bleed.

   The alternative, a fixture in a `tests/` module imported into both
   conftests under `# noqa: F401`, is how `chunk_queue` is shared today. It
   is rejected: each new shared fixture needs two imports, and forgetting one
   is the drift this issue removes.
6. **No new guard.** Removing the twins removes the trap. A static test that
   refuses a browser module copying a helper cannot tell a copy from a
   different shape.

Fixtures only one suite needs stay in that suite's conftest:
`_no_process_statement_limit`, `html_answers_checked` and the logger
captures in `tests/`, the browser and user fixtures in `e2e/`.

## Docs

- CLAUDE.md drops "(and its `e2e/` twin)" after `tests/tracked_games.py`.
- The #770 spec says `create_tracked_game` lives in both suites "because the
  suites share no conftest"; it is amended to say it lives in
  `tests/tracked_games.py`, which both suites import.
- The #678 spec says one autouse fixture in each conftest connects the
  tracking hook; it is amended to name the one fixture in the root conftest.
- The `_track_created_games` docstring drops "A twin of tests/conftest.py".
- `tests/tracked_games.py`'s module docstring still holds: the hook is not
  moved there.

## Verification

`make lint-fix` sorts the new `from graphs import default_graph` lines;
`make format` does not. Then full `make check`, including `e2e/`, under the
shared `heavy-tests.lock`. Every changed file is a test, a test helper or a
doc, so the suites passing is the whole check.

## Follow-up issues to file

- `authenticated_page` is defined in 40 browser modules, in 13 variants
  (viewport, user setup, extra fixtures). The 22 identical copies belong in
  `e2e/conftest.py`; the variants want a shared login helper. It is internal
  to `e2e/`, so not this issue's.
