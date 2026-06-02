from django import template
from django.utils.safestring import mark_safe

from common.components import Button

register = template.Library()


@register.simple_tag
def python_button(
    color: str = "blue",
    size: str = "base",
    icon: str = "",
    type: str = "button",
    class_: str = "",
    hx_get: str = "",
    hx_target: str = "",
    hx_swap: str = "",
    title: str = "",
    onclick: str = "",
    data_target: str = "",
    data_type: str = "",
    name: str = "",
    slot: str = "",
) -> str:
    """Template tag that delegates to the Python Button() component."""

    extra_attrs: list[tuple[str, str]] = []
    if class_:
        extra_attrs.append(("class", class_))
    if data_target:
        extra_attrs.append(("data-target", data_target))
    if data_type:
        extra_attrs.append(("data-type", data_type))

    children = [mark_safe(slot)] if slot else []

    return Button(
        attributes=extra_attrs or None,
        children=children or None,
        size=size,
        icon=icon if isinstance(icon, bool) else str(icon).lower() == "true",
        color=color,
        type=type,
        hx_get=hx_get,
        hx_target=hx_target,
        hx_swap=hx_swap,
        title=title,
        onclick=onclick,
        name=name,
    )
