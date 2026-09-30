"""Hides the parent field for main games."""

from common.components.core import Node
from common.components.custom_elements import FormFieldName
from common.components.primitives import custom_element_builder

_GameAddon = custom_element_builder("game-addon")


def GameAddon(kind_field: FormFieldName, parent_field: FormFieldName) -> Node:
    """Wraps nothing; finds its fields itself."""
    return _GameAddon(kind_field=kind_field, parent_field=parent_field, hidden=True)
