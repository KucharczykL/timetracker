# Issue #390 final review fix report

## Scope and baseline

- Branch: `feat/issue-390-admin-settings`
- Starting commit: `f0040b144552` (`test: isolate admin settings currency fallback`)
- Findings addressed:
  1. Distinguish personal and site `DEFAULT_CURRENCY` help on rendered pages.
  2. Prove `/admin/` raises `Resolver404` under `DEBUG=true`.
  3. Replace stale FX-to-CZK guidance with resolved site `DEFAULT_CURRENCY`.

## TDD evidence

### Exact `/admin/` absence assertion

RED command:

```console
$ direnv exec . uv run --frozen pytest tests/test_admin_removed.py::test_debug_urls_exclude_admin_and_retain_debug_toolbar -q
F                                                                        [100%]
=================================== FAILURES ===================================
____________ test_debug_urls_exclude_admin_and_retain_debug_toolbar ____________

    def test_debug_urls_exclude_admin_and_retain_debug_toolbar():
        configuration = _debug_configuration()

>       assert configuration["admin_route_raises_resolver404"] is True
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'admin_route_raises_resolver404'

tests/test_admin_removed.py:63: KeyError
=========================== short test summary info ============================
FAILED tests/test_admin_removed.py::test_debug_urls_exclude_admin_and_retain_debug_toolbar
1 failed in 0.46s
```

GREEN command:

```console
$ direnv exec . uv run --frozen pytest tests/test_admin_removed.py::test_debug_urls_exclude_admin_and_retain_debug_toolbar -q
.                                                                        [100%]
1 passed in 0.46s
```

The subprocess now records `True` only from `except Resolver404`; a successful
unnamespaced resolution takes the `else` branch and records `False`.

### Personal/site currency help

RED command:

```console
$ direnv exec . uv run --frozen pytest tests/test_settings_page.py::test_settings_page_explains_personal_currency_scope tests/test_admin_settings_page.py::test_admin_settings_page_explains_site_currency_scope -q
FF                                                                       [100%]
=================================== FAILURES ===================================
_____________ test_settings_page_explains_personal_currency_scope ______________

auth_client = <django.test.client.Client object at 0x7c905d1e4f50>

    def test_settings_page_explains_personal_currency_scope(auth_client):
        html = auth_client.get(reverse("games:settings")).content.decode()

>       assert (
            "A personal value affects only your purchase entry; purchases saved "
            "without user context and FX/reporting continue to use the site value."
            in html
        )
E       assert 'A personal value affects only your purchase entry; purchases saved without user context and FX/reporting continue to use the site value.' in '<!DOCTYPE html><html lang="en-us" data-date-time-presentation="{&quot;version&quot;:1,&quot;locale&quot;:&quot;en-us&...                  </button>\n                </div>\n            </div>\n        </template>\n    </div></body></html>'

tests/test_settings_page.py:72: AssertionError
____________ test_admin_settings_page_explains_site_currency_scope _____________

superuser_client = <django.test.client.Client object at 0x7c905ce00770>
clean_site_setting_sources = None

    def test_admin_settings_page_explains_site_currency_scope(
        superuser_client,
        clean_site_setting_sources,
    ):
        html = superuser_client.get(reverse("games:admin_settings")).content.decode()

>       assert (
            "Used for purchase entry by users without a personal value, purchases "
            "saved without user context, and the FX/reporting target."
            in html
        )
E       assert 'Used for purchase entry by users without a personal value, purchases saved without user context, and the FX/reporting target.' in '<!DOCTYPE html><html lang="en-us" data-date-time-presentation="{&quot;version&quot;:1,&quot;locale&quot;:&quot;en-us&...                  </button>\n                </div>\n            </div>\n        </template>\n    </div></body></html>'

tests/test_admin_settings_page.py:202: AssertionError
=========================== short test summary info ============================
FAILED tests/test_settings_page.py::test_settings_page_explains_personal_currency_scope
FAILED tests/test_admin_settings_page.py::test_admin_settings_page_explains_site_currency_scope
2 failed in 0.95s
```

GREEN command:

```console
$ direnv exec . uv run --frozen pytest tests/test_settings_page.py::test_settings_page_explains_personal_currency_scope tests/test_admin_settings_page.py::test_admin_settings_page_explains_site_currency_scope -q
..                                                                       [100%]
2 passed in 0.88s
```

## Verification evidence

Required focused suite, rerun after formatting:

```console
$ direnv exec . uv run --frozen pytest tests/test_settings_page.py tests/test_admin_settings_page.py tests/test_settings_registry.py tests/test_admin_removed.py -q
........................................................................ [ 90%]
........                                                                 [100%]
80 passed in 4.48s
```

Ruff lint:

```console
$ direnv exec . uv run --frozen ruff check games/views/settings.py timetracker/settings_registry.py tests/test_settings_page.py tests/test_admin_settings_page.py tests/test_admin_removed.py
All checks passed!
```

Ruff formatting:

```console
$ direnv exec . uv run --frozen ruff format tests/test_settings_page.py tests/test_admin_settings_page.py
2 files reformatted
$ direnv exec . uv run --frozen ruff format --check games/views/settings.py timetracker/settings_registry.py tests/test_settings_page.py tests/test_admin_settings_page.py tests/test_admin_removed.py
5 files already formatted
```

Whitespace check:

```console
$ git diff --check
```

Exit status: `0`; no output.

Full repository gate:

```console
$ direnv exec . make check
uv run --frozen ruff check
All checks passed!
uv run --frozen ruff format --check
221 files already formatted
uv run --frozen mypy .
Success: no issues found in 223 source files
pnpm exec tsc --noEmit -p tsconfig.check.json
uv run --frozen python manage.py gen_icons --check
common/components/icons_generated.py is up to date.
pnpm exec tsc
pnpm test:ts
 Test Files  41 passed (41)
      Tests  649 passed (649)
uv run --frozen --with pytest-django pytest
======================= 2157 passed in 241.65s (0:04:01) =======================
```

## Files changed

- `CLAUDE.md`
- `games/views/settings.py`
- `timetracker/settings_registry.py`
- `tests/test_settings_page.py`
- `tests/test_admin_settings_page.py`
- `tests/test_admin_removed.py`
- `.superpowers/sdd/issue-390/final-fix-report.md`

## Self-review

- Personal help says the override affects only that user's purchase entry and
  explicitly leaves context-free saves and FX/reporting on the site value.
- Site help covers inheriting users, context-free saves, and the FX/reporting
  target. Each rendered-page test asserts its own copy and rejects the other.
- The context-specific personal text is a view-level override; no registry
  schema or setting concept was added.
- The `/admin/` check can no longer treat an unnamespaced successful match as
  route absence: only `Resolver404` sets the asserted flag.
- `CLAUDE.md` now matches the runtime site-currency resolver contract.
- Diff review found no unrelated source changes. Pre-existing untracked review
  artifacts were preserved and excluded from the commit.

## Concerns

None.
