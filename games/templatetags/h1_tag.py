from django import template
from django.utils.safestring import mark_safe

from common.components import H1

register = template.Library()


@register.simple_tag
def python_h1(badge: str = "", slot: str = "") -> str:
    children = [mark_safe(slot)] if slot else []
    return H1(children=children, badge=badge)
