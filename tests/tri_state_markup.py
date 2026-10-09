"""Reads the held state off a rendered tri-state checkbox."""

import re


def held_word(markup: str, name: str) -> str:
    """The held word on box ``name``."""
    tag = re.search(rf'<tri-state-checkbox\b[^>]*\bname="{name}"[^>]*>', markup)
    assert tag is not None
    held = re.search(r'\bheld="(\w+)"', tag.group(0))
    assert held is not None
    return held.group(1)
