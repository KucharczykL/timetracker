# One test support for both suites

Issue #994.

## Rule

`e2e/` keeps no copy of a helper or fixture that `tests/` holds. Two copies
of one helper drift. A browser module imports the `tests/` helper by its bare
name.

## Path

`pythonpath = ["tests"]` in `[tool.pytest.ini_options]` puts `tests/` at the
front of `sys.path` before a conftest loads. This applies to every run: `pytest
tests/`, `pytest e2e/`, and the bare `pytest` of `make test`. No conftest
changes `sys.path`.

`e2e/` is a package and `tests/` is not. For a package, pytest puts its parent
on `sys.path`, not the package. So a bare name never finds an `e2e/` module:
`import graphs` in a browser module finds `tests/graphs.py`. Do not add a helper
module to `e2e/`. The bare name does not reach it.

`tests/` comes before the standard library and every installed package, also
for the app code a browser test runs. A helper with the name of such a module
replaces it. `tests/test_shared_test_support.py` refuses that name.

## Shared fixtures

A fixture that both suites use lives in a `tests/` module. Both conftests
import it under `# noqa: F401`:

| Fixture | Module |
| --- | --- |
| `chunk_queue`, `held_batches`, `failing_batches` | `tests/bulk_batches.py` |
| `_process_clock_off_the_calendar` | `tests/calendar_days.py` |
| `unknown_icon_names_fail` | `tests/icon_names.py` |
| `_reset_settings_caches` | `tests/settings_caches.py` |
| `_track_created_games` | `tests/tracked_games.py` |

Pytest orders the autouse fixtures of one conftest by name. Three of the
fixtures keep their leading underscore, so the order did not change when they
moved. Each suite has a test that the five fixtures apply.

A root `conftest.py` is not used. mypy reads it and `tests/conftest.py` as the
same module, `conftest`, and stops. `explicit_package_bases` would make the
second one `tests.conftest`, but then the bare `from graphs import` lines find
no module. With `tests/` also in `mypy_path`, every helper is found twice.

A fixture that one suite alone uses stays in that suite's conftest.

## The default graph

`default_graph` in `tests/graphs.py` is the one way a test states a Game with
one default Edition that holds one default Release. Call it directly. No
fixture wraps it.

`default_graph` saves a new game. It does not save a game that is already
saved, for example one that `create_tracked_game` made.

A helper that states another shape is not a copy. Examples are several
Releases, a second Edition, or a graph that keeps existing rows.
