import hashlib

from django import template

register = template.Library()


@register.simple_tag
def randomid(seed: str = "") -> str:
    content_hash = hashlib.sha1(seed.encode()).hexdigest()
    if seed:
        return content_hash[: max(0, 10 - len(seed))] + seed
    return content_hash[:10]
