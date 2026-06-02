from django import template

from common.components import TableRow

register = template.Library()


@register.simple_tag
def python_table_row(data=None) -> str:
    return TableRow(data=data)
