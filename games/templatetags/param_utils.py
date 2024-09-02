from typing import Any

from django import template
from django.http import QueryDict

register = template.Library()


@register.simple_tag(takes_context=True)
def param_replace(context: dict[Any, Any], **kwargs):
    """
    Return encoded URL parameters that are the same as the current
    request's parameters, only with the specified GET parameters added or changed.
    """
    d: QueryDict = context["request"].GET.copy()
    for k, v in kwargs.items():
        d[k] = v
    return d.urlencode()
