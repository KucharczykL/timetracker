"""Reads refuse a missing library."""

from games.models import UserLibrary


class UnscopedRead(RuntimeError):
    """A library read given no library."""


def require_library(library: UserLibrary | None) -> UserLibrary:
    """The library, or a refusal."""
    if library is None:
        raise UnscopedRead("A library read was given no library; state one.")
    return library
