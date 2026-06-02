from django import template

from common.components import _popover_html

register = template.Library()


@register.simple_tag
def python_popover(
    popover_content: str = "",
    wrapped_content: str = "",
    wrapped_classes: str = "",
    id: str = "",
    slot: str = "",
) -> str:
    """Template tag that generates popover HTML natively.

    Called from the cotton/popover.html shim template.
    Delegates HTML generation to _popover_html().
    """
    return _popover_html(
        id=id,
        popover_content=popover_content,
        wrapped_content=wrapped_content,
        wrapped_classes=wrapped_classes,
        slot=slot,
    )
