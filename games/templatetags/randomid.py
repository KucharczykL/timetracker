import random
import string

from django import template

register = template.Library()


@register.simple_tag
def randomid(seed: str = "") -> str:
    return str(hash(seed + "".join(random.choices(string.ascii_lowercase, k=10))))
