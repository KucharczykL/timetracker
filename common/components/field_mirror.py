"""Copies one field into another until edited."""

from common.components.core import Node
from common.components.custom_elements import FormFieldName
from common.components.primitives import custom_element_builder

_FieldMirror = custom_element_builder("field-mirror")


def FieldMirror(source_field: FormFieldName, target_field: FormFieldName) -> Node:
    """Wraps nothing; finds its fields itself."""
    return _FieldMirror(
        source_field=source_field, target_field=target_field, hidden=True
    )
