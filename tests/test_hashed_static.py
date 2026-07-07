"""Exercises the production static-hashing path that the e2e suite can't.

e2e runs on the DEBUG runserver where static files are unhashed and served
as-is, so it never touches ``HashedStaticStorage``. These tests run
``collectstatic`` under that storage against a throwaway ``STATIC_ROOT`` and
assert the two things the deploy relies on:

- filenames are content-hashed (so a changed asset gets a new URL), and
- the relative ESM ``import`` specifiers inside compiled dist modules are
  rewritten to those hashed filenames — otherwise a hashed module would import
  a stale, separately-cached dependency (the bug this whole change fixes).

``DEBUG=False`` is forced because ``ManifestStaticFilesStorage.url()`` returns
the *unhashed* name in DEBUG, which the test suite otherwise runs with.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management import call_command
from django.templatetags.static import static
from django.test import override_settings

DIST_DIR = Path(settings.BASE_DIR) / "games" / "static" / "js" / "dist"

# A bare `pytest` doesn't build dist (it's gitignored); `make test`/`make check`
# do via the `ts` prereq. Skip rather than fail when the artifacts are absent.
pytestmark = pytest.mark.skipif(
    not (DIST_DIR / "elements" / "quick-filter-bar.js").exists(),
    reason="compiled dist not built (run `make ts`)",
)

# Django's HashedFilesMixin appends a 12-hex-char md5 fragment before the suffix.
_HASHED_SUFFIX = re.compile(r"\.[0-9a-f]{12}\.js$")
# Relative ESM specifiers (`./x.js`, `../y/z.js`) inside a module — the ones
# that must come out rewritten to their hashed targets.
_RELATIVE_IMPORT = re.compile(
    r"""(?:from|import)\s*\(?\s*["'](?P<spec>\.\.?/[^"']*\.js)["']"""
)


def _collect(static_root: Path):
    """collectstatic into ``static_root`` under HashedStaticStorage, DEBUG off."""
    hashed = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "common.storage.HashedStaticStorage"},
    }
    # override_settings fires setting_changed, which rebuilds the storages
    # handler and the staticfiles_storage proxy for both entry and exit.
    return override_settings(DEBUG=False, STORAGES=hashed, STATIC_ROOT=str(static_root))


def test_asset_urls_are_hashed(tmp_path):
    with _collect(tmp_path):
        call_command("collectstatic", "--no-input", verbosity=0)
        for name in ("js/dist/toast.js", "base.css", "js/flowbite.min.js"):
            url = static(name)
            assert re.search(r"\.[0-9a-f]{12}\.", url), f"{name} not hashed: {url}"


def test_dist_module_imports_are_rewritten_to_hashed(tmp_path):
    with _collect(tmp_path):
        call_command("collectstatic", "--no-input", verbosity=0)
        stored = staticfiles_storage.stored_name("js/dist/elements/quick-filter-bar.js")
        body = (tmp_path / stored).read_text()
        specifiers = [m.group("spec") for m in _RELATIVE_IMPORT.finditer(body)]
        assert specifiers, "expected relative imports in quick-filter-bar module"
        # e.g. `../generated/props.js` must have become `../generated/props.<hash>.js`
        assert any("generated/props" in spec for spec in specifiers)
        for spec in specifiers:
            assert _HASHED_SUFFIX.search(spec), f"unrewritten import: {spec}"


def test_no_hashed_dist_module_keeps_an_unhashed_import(tmp_path):
    """Completeness: catches any tsc import form Django's regex fails to rewrite,
    which would silently resolve to a stale, unhashed dependency."""
    with _collect(tmp_path):
        call_command("collectstatic", "--no-input", verbosity=0)
        offenders: list[str] = []
        for logical, stored in staticfiles_storage.hashed_files.items():
            if not (logical.startswith("js/dist/") and logical.endswith(".js")):
                continue
            body = (tmp_path / stored).read_text()
            for match in _RELATIVE_IMPORT.finditer(body):
                spec = match.group("spec")
                if not _HASHED_SUFFIX.search(spec):
                    offenders.append(f"{stored}: {spec}")
        assert not offenders, "unrewritten relative imports:\n" + "\n".join(offenders)
