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

The browser suite signs in through one helper. Today 67 browser modules
restate the steps: open the login page, fill both fields, press Login, wait
for `/tracker`. The copies are 40 `authenticated_page` fixtures in 13 shapes,
four local `_login`/`_log_in` shapes in 30 modules, `_login_and_open`, four
`LOGIN` tuples, other fixtures (`signed_in`, `library_page`, `touch_page`,
`tokyo_page`, `pre_upgrade_page`, `superuser_page`) and inline steps in test
bodies.

### The helper

`e2e/helpers.py` holds `Credentials(NamedTuple)` (`username`, `password`),
`E2E_LOGIN = Credentials("tester", "secret123")` and `log_in(page,
live_server, credentials=E2E_LOGIN)`. It opens the login page, fills both
fields, presses Enter in the password field and waits for `/tracker`.
`e2e_user` takes its credentials from `E2E_LOGIN`.

`log_in` presses Enter, not the Login button. A click leaves Playwright's
virtual mouse on the button. The next page then gets `pointerenter` on the
element under that point, and a tooltip can open on load. The touch fixtures
tap for that reason today. Enter moves no pointer in any context, so one
helper serves the mouse and the touch contexts.

`log_in` calls `reverse("login")` when it runs. It waits for nothing that a
script draws, so a context with JavaScript off can use it. A synthetic
harness that swaps `ROOT_URLCONF` logs in before the swap, in a fixture or in
an undecorated test, or extends the base patterns, as
`test_filter_count_e2e.py` does. A module that swaps in an autouse fixture,
as `test_selectable_table_e2e.py` does, cannot take `authenticated_page`.

### The fixture

`e2e/conftest.py` holds `authenticated_page(live_server, page, e2e_user)`,
which calls `log_in` and returns the page. The identical copies go, and so do
the overrides that only rename it (`test_date_picker_e2e.py`,
`test_global_error_handler_e2e.py`).

A module that must do something before the login keeps its own
`authenticated_page`: it does its setup, then calls `log_in`. The order stays
as it is. Examples: a viewport, a setting, `show_every_column`, and a
dependency that must exist before the first page loads. The `errors` fixture
of the form-dialog, picker-sheet and dialog-create modules listens for
console errors from the login on, and `world` in
`test_return_to_origin_e2e.py` seeds rows; those overrides keep them.

An override returns a `Page`, as the conftest fixture does. Fourteen tests
unpack a tuple today. The date picker and date-time tests ask for `e2e_user`
beside `authenticated_page`. The settings page tests ask for a new module
fixture, `preferred_device`, that depends on `e2e_user` and holds the
device; the override depends on it and keeps creating the 51 games, so the
games and the device exist before the login.

### Other users

A module that made its own "tester" with `create_user` uses `e2e_user`
instead, so no two fixtures make one user. The `pinned_column` and
`responsive_table` modules split the user setup out of `_login` into a
fixture that both their pages use, the JavaScript page and the one without,
so `show_every_column` still runs before `log_in`.

A login as another user passes its own `Credentials`: the superuser
pages, the font-fallback test, and the theme tests (`password="pw"`).

### What keeps its own steps

A test whose subject is the login page keeps its steps: the anonymous-theme
and logout tests fill a page they already opened and probed, and the sign-in
inside a form dialog fills the dialog. These read `E2E_LOGIN` where they named the
test user.

### Not changed

The login stays a form login. Cookie login (`force_login` and the session
cookie) was the other choice. It saves one page load a test, but the page
then starts at `about:blank`, and the login form is the path a person takes.
With one helper, a change to it is one edit.
