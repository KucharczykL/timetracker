"""Exercises the production static-hashing path that the e2e suite can't.

e2e runs on the DEBUG runserver where static files are unhashed and served
as-is, so it never touches ``HashedStaticStorage``. These tests run
``collectstatic`` under that storage against a throwaway ``STATIC_ROOT`` and
assert the two things the deploy relies on:

- filenames are content-hashed (so a changed asset gets a new URL), and
- the relative ESM ``import`` specifiers inside compiled dist modules are
  rewritten to those hashed filenames — otherwise a hashed module would import
  a stale, separately-cached dependency (the failure this change prevents).

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
from django.test import Client, override_settings
from django.urls import reverse

VENDORED_JS_DIR = Path(settings.BASE_DIR) / "games" / "static" / "js"
DIST_DIR = VENDORED_JS_DIR / "dist"

# A bare `pytest` doesn't build dist (it's gitignored); `make test`/`make check`
# do via the `ts` prereq. Skip rather than fail when the artifacts are absent.
# Scoped per-test so the vendored-JS check below (which needs no build) always runs.
needs_dist = pytest.mark.skipif(
    not (DIST_DIR / "elements" / "quick-filter-bar.js").exists(),
    reason="compiled dist not built (run `make ts`)",
)

# Django's HashedFilesMixin inserts a 12-hex-char content-hash fragment into a
# name (`props.js` -> `props.<hash>.js`).
_HASHED_FRAGMENT = re.compile(r"\.[0-9a-f]{12}\.")
# Any relative specifier (`./x`, `../y/z.js`, with or without extension) reached
# via `import`/`from`/`import(`. Deliberately a *superset* of Django's rewrite
# matcher: every relative import in a dist module must come out hashed, so a form
# Django fails to rewrite (extensionless, query/fragment, no semicolon) is caught
# here rather than silently resolving to a stale, unhashed sibling.
_RELATIVE_IMPORT = re.compile(
    r"""(?:from|import)\s*\(?\s*["'](?P<spec>\.\.?/[^"']+)["']"""
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


@needs_dist
def test_asset_urls_are_hashed(tmp_path):
    with _collect(tmp_path):
        call_command("collectstatic", "--no-input", verbosity=0)
        for name in (
            "js/dist/toast.js",
            "js/dist/theme-bootstrap.js",
            "base.css",
            "js/flowbite.min.js",
        ):
            url = static(name)
            assert _HASHED_FRAGMENT.search(url), f"{name} not hashed: {url}"


@needs_dist
def test_production_document_loads_hashed_bootstrap_before_hashed_css(tmp_path, db):
    with _collect(tmp_path):
        call_command("collectstatic", "--no-input", verbosity=0)
        html = Client().get(reverse("login")).content.decode()
        bootstrap = static("js/dist/theme-bootstrap.js")
        stylesheet = static("base.css")

        assert _HASHED_FRAGMENT.search(bootstrap)
        assert _HASHED_FRAGMENT.search(stylesheet)
        assert html.index(f'src="{bootstrap}"') < html.index(f'href="{stylesheet}"')
        assert html.rfind("<script", 0, html.index(f'src="{bootstrap}"')) == html.index(
            "<script"
        )


@needs_dist
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
            assert _HASHED_FRAGMENT.search(spec), f"unrewritten import: {spec}"


@needs_dist
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
                if not _HASHED_FRAGMENT.search(spec):
                    offenders.append(f"{stored}: {spec}")
        assert not offenders, "unrewritten relative imports:\n" + "\n".join(offenders)


def test_no_vendored_js_has_dangling_sourcemap():
    """A `//# sourceMappingURL=x.map` whose `.map` isn't shipped fails
    collectstatic under the hashed storage (Django tries to rewrite the ref).
    Guards the flowbite fix from silently regressing. Needs no dist build.
    (The dead-comment fix in session-timestamp-buttons.ts needs no guard: tsc
    strips comments, so a reintroduced source comment never reaches dist.)"""
    offenders: list[str] = []
    for js in VENDORED_JS_DIR.glob("*.js"):
        for match in re.finditer(r"sourceMappingURL=(\S+)", js.read_text()):
            reference = match.group(1)
            if not (js.parent / reference).exists():
                offenders.append(f"{js.name} -> {reference}")
    assert not offenders, (
        "dangling sourceMappingURL (ship the .map or strip it): " + ", ".join(offenders)
    )


def test_caddy_immutable_policy_matches_only_hashed_static_names():
    caddyfile = (Path(settings.BASE_DIR) / "Caddyfile").read_text()
    matcher = re.search(r"path_regexp\s+hashed\s+(\S+)", caddyfile)

    assert matcher is not None
    pattern = re.compile(matcher.group(1))
    assert pattern.search("/js/dist/theme-bootstrap.0123456789ab.js")
    assert pattern.search("/base.abcdef012345.css")
    assert not pattern.search("/js/dist/theme-bootstrap.js")
    assert not pattern.search("/base.abcdef01234g.css")
    assert (
        'header @hashed Cache-Control "public, max-age=31536000, immutable"'
        in caddyfile
    )
