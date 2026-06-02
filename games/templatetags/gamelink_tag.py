from django import template
from django.utils.safestring import mark_safe

from common.components import GameLink

register = template.Library()


@register.simple_tag
def python_gamelink(game_id: int, name: str = "", slot: str = "") -> str:
    children = [mark_safe(slot)] if slot else []
    return GameLink(game_id=game_id, name=name, children=children)
