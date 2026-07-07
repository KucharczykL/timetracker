"""Static-files storage backends.

``HashedStaticStorage`` content-hashes every collected static file so a changed
asset gets a new URL — cache-forever, never stale after a deploy. Enabling
``support_js_module_import_aggregation`` additionally rewrites the relative ESM
``import``/``export … from``/``import()`` specifiers inside the compiled dist
modules to their hashed targets at ``collectstatic`` time, so hashing the
filenames does not break inter-module imports.

Safe for this codebase: there are no dynamic ``import()`` calls, and every
specifier is a static relative ``.js`` path present in the manifest — so the
rewrite covers the whole dist module graph and ``collectstatic`` fails loudly
if an import ever fails to resolve.
"""

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class HashedStaticStorage(ManifestStaticFilesStorage):
    support_js_module_import_aggregation = True
