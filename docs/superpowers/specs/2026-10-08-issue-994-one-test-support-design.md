# One test support for both suites

Issue #994.

## Rule

`e2e/` keeps no copy of a helper or fixture that `tests/` holds. Two copies
drift. A browser module imports the `tests/` helper by its bare name.

## Path

`pythonpath = ["tests"]` puts `tests/` first on `sys.path` before a conftest
loads, in every run. No conftest changes `sys.path`.

`e2e/` is a package, so pytest puts its parent on the path, not `e2e/`. A bare
name never finds an `e2e/` module. Do not add a helper module to `e2e/`.

`tests/` comes before the standard library and every installed package, also
for app code. `tests/test_shared_test_support.py` refuses a helper name that
another module holds.

## Shared fixtures

A fixture that both suites use lives in a `tests/` module. Both conftests
import it under `# noqa: F401`:

| Fixture | Module |
| --- | --- |
| `chunk_queue`, `held_batches`, `failing_batches` | `tests/bulk_batches.py` |
| `_process_clock_off_the_calendar` | `tests/calendar_days.py` |
| `_fast_password_hashing` | `tests/password_hashing.py` |
| `unknown_icon_names_fail` | `tests/icon_names.py` |
| `_reset_settings_caches` | `tests/settings_caches.py` |
| `_track_created_games` | `tests/tracked_games.py` |

Pytest orders the autouse fixtures of one conftest by name, so a rename
can change their order. Each suite has a
test that the shared fixtures apply. Tests hash passwords with MD5: the
default hasher costs 0.1 s for each user.

There is no root `conftest.py`. mypy reads it and `tests/conftest.py` as one
module, `conftest`, and stops.

## The default graph

`default_graph` in `tests/graphs.py` is the one way a test states a Game with
one default Edition and one default Release. No fixture wraps it. It saves the
game only when the game is new.

## One login

A browser test signs in through `log_in(page, live_server,
credentials=E2E_LOGIN)` in `e2e/helpers.py`, or through `authenticated_page`
in `e2e/conftest.py`, which calls it. `create_login_user(credentials)` makes
another user from the same `Credentials`.

`log_in` checks the credentials with `authenticate`, makes a session on the
server, and puts its cookie into the browser context. It loads no page. The
page stays where it was, so the test goes to the page it reads. A login form
costs three page loads a test; the cookie took the suite from 63 s to 50 s.
It waits for nothing a script draws, so a context with JavaScript off can use
it. Bad credentials fail at once.

A module that does setup before the login keeps its own `authenticated_page`:
it does the setup, then calls `log_in`, and returns a `Page`. A test that
needs the user asks for `e2e_user`. A module that shows every list column
marks its tests with `usefixtures("every_column_user")`.

`log_in` resolves no URL, so a synthetic harness that swaps `ROOT_URLCONF`
can sign in before or after the swap.

Only a test whose subject is the login page fills the form.
