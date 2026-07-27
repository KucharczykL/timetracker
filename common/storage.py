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

    # Django rewrites in repeated passes and gives up after
    # max_post_process_passes (5 by default). A module can only take its final
    # hash once every module it imports has one, so a chain of N imports costs
    # up to N passes plus one that changes nothing — and the dist graph is 9
    # deep (filter-summary → filter-group → filter-widgets → date-range-picker
    # → … → csrf.js). What it actually costs depends on the order collectstatic
    # happens to walk the tree: reach a dependency first and its dependents
    # settle in the same pass. That order is the filesystem's, so the default
    # cap sat right at the edge — the same image collected fine on one machine
    # and died with "Max post-process passes exceeded" on another. Passes stop
    # as soon as a pass changes nothing, so the headroom is free.
    max_post_process_passes = 15
