"""Hides the parent field for main games."""

from common.components.core import Node
from common.components.primitives import custom_element_builder

_GameAddon = custom_element_builder("game-addon")


def GameAddon(kind_field: str, parent_field: str) -> Node:
    """Wraps nothing; finds both rows itself."""
    return _GameAddon(kind_field=kind_field, parent_field=parent_field, hidden=True)
