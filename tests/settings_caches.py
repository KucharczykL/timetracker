"""Settings caches, reset around each test."""

import pytest

from timetracker import config as config_module
from timetracker import settings_resolver


@pytest.fixture(autouse=True)
def _reset_settings_caches():
    """Reset the resolver around each test.

    No rollback or flush fires the ``SiteSetting`` commit signal, so a
    discarded row would leak through the resolver's snapshot. Also
    resets the env/ini caches that ``ENV_FILE``/``INI_FILE`` fixtures fill.
    """
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield
    config_module.reset_caches()
    settings_resolver.clear_cache()
