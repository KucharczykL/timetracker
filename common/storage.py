"""Static-files storage backends.

``HashedStaticStorage`` content-hashes every collected static file so a changed
asset gets a new URL — cache-forever, never stale after a deploy. Enabling
``support_js_module_import_aggregation`` additionally rewrites relative ESM
import specifiers inside the compiled dist modules to their hashed targets at
``collectstatic`` time, so hashing the filenames does not break inter-module
imports.

Django's rewrite handles ``import``/``export … from``/dynamic ``import()``; this
codebase emits only the static ``import``/``export … from`` forms, every
specifier a relative ``.js`` path present in the manifest. So the rewrite covers
the whole dist module graph, and ``collectstatic`` fails loudly if an import
ever fails to resolve.
"""

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class HashedStaticStorage(ManifestStaticFilesStorage):
    support_js_module_import_aggregation = True
