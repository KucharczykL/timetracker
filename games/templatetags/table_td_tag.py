from django import template
from django.utils.safestring import mark_safe

from common.components import TableTd

register = template.Library()


@register.simple_tag
def python_table_td(slot: str = "") -> str:
    children = [mark_safe(slot)] if slot else []
    return TableTd(children=children)
