"""Hides a Game form's parent while its kind is main."""

from common.components.core import Node
from common.components.primitives import custom_element_builder

_GameAddon = custom_element_builder("game-addon")


def GameAddon(kind_field: str, parent_field: str) -> Node:
    """Wraps nothing: it finds both rows in its form."""
    return _GameAddon(kind_field=kind_field, parent_field=parent_field, hidden=True)
