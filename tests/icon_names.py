"""A test that draws an unknown icon fails."""

import logging

import pytest

from common.components.primitives import _warn_unknown_icon, icon_logger


class Recorder(logging.Handler):
    """Keeps each record it hears."""

    def __init__(self, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture(autouse=True)
def unknown_icon_names_fail(request):
    """Every test starts warning afresh, and fails on one."""
    _warn_unknown_icon.cache_clear()
    recorder = Recorder()
    icon_logger.addHandler(recorder)
    yield
    icon_logger.removeHandler(recorder)
    if recorder.messages and not request.node.get_closest_marker("draws_unknown_icon"):
        pytest.fail("\n".join(recorder.messages), pytrace=False)
