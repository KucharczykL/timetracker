import contextlib
import logging

import pytest


@pytest.fixture
def capture_games_logger(caplog):
    """Context manager that wires ``caplog`` to the ``games`` logger.

    The ``games`` logger sets ``propagate=False`` in settings
    (``timetracker/settings.py``), so caplog's root handler never sees its
    records. This attaches caplog's handler to the ``games`` logger directly for
    the duration of the block. Use as ``with capture_games_logger(): ...`` and
    then assert against ``caplog.records``.
    """

    @contextlib.contextmanager
    def _capture():
        games_logger = logging.getLogger("games")
        games_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger="games")
        try:
            yield caplog
        finally:
            games_logger.removeHandler(caplog.handler)

    return _capture
