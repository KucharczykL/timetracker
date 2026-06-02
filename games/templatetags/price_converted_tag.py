from django import template
from django.utils.safestring import mark_safe

from common.components import PriceConverted

register = template.Library()


@register.simple_tag
def python_price_converted(slot: str = "") -> str:
    return PriceConverted(children=[mark_safe(slot)] if slot else [])
