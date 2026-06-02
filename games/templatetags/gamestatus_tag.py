from django import template
from django.utils.safestring import mark_safe

from common.components import GameStatus

register = template.Library()


@register.simple_tag
def python_gamestatus(status: str = "u", display: str = "", class_: str = "", slot: str = "") -> str:
    children = [mark_safe(slot)] if slot else []
    return GameStatus(children=children, status=status, display=display, class_=class_)
