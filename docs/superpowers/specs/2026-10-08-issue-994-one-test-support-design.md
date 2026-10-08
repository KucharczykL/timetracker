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

## One login

A browser test signs in through one helper. Only a test whose subject is
the login page restates the login steps.

`e2e/helpers.py` holds `Credentials(NamedTuple)` (`username`, `password`),
`E2E_LOGIN`, `create_login_user(credentials, *, superuser=False)` and
`log_in(page, live_server, credentials=E2E_LOGIN)`. `log_in` opens the login
page, fills both fields and presses Enter in the password field. When the
page then is not `/tracker`, it fails at once with the form's text.
`e2e_user` takes its credentials from `E2E_LOGIN`.

`log_in` presses Enter, not the Login button. A click leaves Playwright's
virtual mouse on the button. The next page then gets `pointerenter` on the
element under that point, and a tooltip can open on load. Enter moves no
pointer, so one helper serves the mouse and the touch contexts.

`log_in` waits for nothing that a script draws, so a context with JavaScript
off can use it. It calls `reverse("login")` when it runs. A synthetic harness
that swaps `ROOT_URLCONF` logs in before the swap, or extends the base
patterns. A module that sets `ROOT_URLCONF` in an autouse fixture cannot take
`authenticated_page`: the autouse fixture runs first, and `reverse("login")`
then fails.

`e2e/conftest.py` holds `authenticated_page(live_server, page, e2e_user)`. It
calls `log_in` and returns the page. A module that must do something before
the login keeps its own `authenticated_page`: it does its setup, then calls
`log_in`. An override returns a `Page`. A test that needs the user or another
row asks for that fixture beside `authenticated_page`.

A test that needs the default user asks for `e2e_user`; no test looks it up
by name. Another user is made with `create_login_user` from the same
`Credentials` that `log_in` then takes. A module that shows every list column
marks its tests with `usefixtures("every_column_user")`, so the choice does
not hang on a fixture override.

A test whose subject is the login page keeps its own steps: the
anonymous-theme and logout tests, and the sign-in inside a form dialog.

The login stays a form login. Cookie login (`force_login` and the session
cookie) saves one page load a test, but the page then starts at
`about:blank`, and the login form is the path a person takes.
