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

`e2e/` is a package and `tests/` is not. So `import graphs` in a browser module
finds `tests/graphs.py`. Do not add a helper module to `e2e/` with the name of
a `tests/` module. The bare name finds the `tests/` module, and the `e2e/`
module then drifts unread.

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

The three autouse fixtures keep their leading underscore. Pytest orders the
autouse fixtures of one conftest by name. The names keep that order.

A root `conftest.py` is not used. mypy reads it and `tests/conftest.py` as the
same module, `conftest`, and stops. A fix to the module bases breaks the bare
imports.

A fixture that one suite alone uses stays in that suite's conftest.

## The default graph

`default_graph` in `tests/graphs.py` is the one way a test states a Game with
one default Edition that holds one default Release. Call it directly. No
fixture wraps it.

`default_graph` saves the game. A game that `create_tracked_game` made saves
again: one `UPDATE`, and its `post_save` has `created=False`, so the tracking
hook does nothing.

A helper that states another shape is not a copy. Examples are several
Releases, a second Edition, or a graph that keeps existing rows.

## Second stack member

`authenticated_page` has 40 definitions in `e2e/`, in 13 variants. The
second member of this stack puts the shared login in one place.
