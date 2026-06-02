from django import template
from django.utils.safestring import mark_safe

from common.components import ButtonGroup

register = template.Library()


@register.simple_tag(takes_context=True)
def python_button_group(context, buttons=None):
    """Template tag that delegates button group rendering to ButtonGroup().

    Supports two modes:
    - buttons list passed: renders button links via ButtonGroup()
    - no buttons (slot only): passes through children (showcase usage)
    """
    if buttons is not None:
        return ButtonGroup(buttons)
    # Slot mode: render children directly (for <c-button-group> with direct children)
    slot = context.get("slot", "")
    return mark_safe(slot) if slot else ""
