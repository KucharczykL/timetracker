# Issue #994, member 2 plan: one login

Spec: `docs/superpowers/specs/2026-10-08-issue-994-one-test-support-design.md`,
section "One login". Inline.

## Task 1: helper and fixture

- `e2e/helpers.py`: `Credentials(NamedTuple)`, `E2E_LOGIN`, `log_in(page,
  live_server, credentials=E2E_LOGIN)` — goto `reverse("login")`, fill
  `input[name="username"]`/`input[name="password"]`, `press` Enter in the
  password field, `wait_for_url(f"{live_server.url}/tracker**")`.
- `e2e/conftest.py`: `e2e_user` reads `E2E_LOGIN`; new `authenticated_page`.

## Task 2: mechanical sweep (AST script in the scratchpad, reviewed by hand)

- Delete the 22 identical `authenticated_page` copies.
- Delete the four local helper shapes; every call → `log_in(page,
  live_server[, Credentials(...)])`. `_login(…, django_user_model)` in
  pinned_column/responsive_table: split user setup into a module fixture.
- `LOGIN` tuples go; `_log_in` → `log_in`; `test_form_dialog_e2e.py:277-292`
  reads `E2E_LOGIN`.
- Drop now-unused `reverse`/`Page` imports via `make lint-fix`.

## Task 3: by hand

- Overrides with setup: mobile lists, column_picker, date_preset_zone,
  truncated_text, return_to_origin (`world`), form_dialog/picker_sheet/
  dialog_create (`errors`) → setup, then `log_in`.
- Renaming overrides deleted: date_picker, global_error_handler.
- Tuples: date_picker, datetime_field → tests take `e2e_user`;
  settings_page → `preferred_device` fixture, override keeps the 51 games.
- Other fixtures: `signed_in` ×2, `library_page`, `touch_page` ×4 (drop the
  tap comment, Enter covers it), `tokyo_page`, `pre_upgrade_page` ×2,
  `superuser_page` ×2 (`Credentials("settings-admin", …)` etc.),
  `_login_and_open` (keeps its goto).
- Inline: compact_button, session_finish, session_reset, truncated_text
  font fallback, datetime_field contexts, theme (`password="pw"`; the three
  anonymous/logout tests keep their steps).

## Task 4: verify

- `grep` for `reverse("login")`/`reverse('login')` in `e2e/`: only `helpers.py`
  and the tests whose subject is the login page remain.
- `make format`, `make lint-fix`, `make lint`, `make typecheck`, `make vale`.
- `make test-e2e` under the lock; then docs sweep (delete this plan, trim the
  spec section), full `make check` once on the user's word.
