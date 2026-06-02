from django import template
from django.utils.safestring import mark_safe

from common.components import Modal

register = template.Library()


class ModalNode(template.Node):
    def __init__(self, modal_id, nodelist):
        self.modal_id = template.Variable(modal_id)
        self.nodelist = nodelist

    def render(self, context):
        modal_id = self.modal_id.resolve(context)
        content = self.nodelist.render(context)
        return str(
            Modal(modal_id=modal_id, children=[mark_safe(content)])
        )


@register.tag("python_modal")
def do_modal(parser, token):
    bits = token.split_contents()
    tag_name = bits[0]
    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            f"{tag_name} requires exactly one argument: the modal ID"
        )
    modal_id = bits[1]
    nodelist = parser.parse(("endpython_modal",))
    parser.delete_first_token()
    return ModalNode(modal_id, nodelist)
